# ADR-0026: Dividend timing mechanics (Phase 4 priority 2)

- **Status**: accepted
- **Date**: 2026-09-19

## Context

The original requirements: dividends are "received on longs, paid on shorts, on ex-date
with cash on pay-date." `CorporateActionType.CASH_DIVIDEND` has existed
as an enum member since Phase 0, and `CorporateActionEvent`'s docstring
already anticipated `value` carrying "dividend per share" — but no
handler existed; any non-`DELISTING` action raised
`"not implemented in Phase 2"`.

The core difficulty: entitlement (who gets paid, and how much) is
determined by the position held on the **ex-date**, but the cash moves
on a **later, distinct pay-date**. The engine's ledger is strictly
append-only and time-ordered (`InMemoryLedger.append` raises if a new
transaction's `ts` precedes the last appended one) — so a transaction
for a future pay-date cannot simply be appended early while other, later
transactions (or other dividends with earlier pay-dates than an
already-queued later one) might still need to slot in ahead of it in
time order.

## Decision

**A dividend is two events from one dataset row, both the same
`CorporateActionEvent` type, distinguished by which field is set.** The
dataset row (`CORPORATE_ACTION_SCHEMA`'s new nullable `pay_at` column,
required for `CASH_DIVIDEND`, unused/null for other actions) produces
one event at `effective_at` (the ex-date) with `pay_at` set and
`resolved_amount` unset. Its handler (`BacktestEngine._handle_dividend`)
resolves entitlement immediately from the **current** ledger fold
(`qty * per_share` — negative `qty`, i.e. a short, naturally produces a
negative amount, so "paid on shorts" needs no special-case branch) and
**pushes a second `CorporateActionEvent`** onto the engine's own event
queue, scheduled at `pay_at`, with `resolved_amount` set (and `pay_at`
unset). When that second event is popped in its natural time order, the
handler recognizes `resolved_amount is not None` and posts the ledger
transaction directly — no entitlement recomputation, since by pay-date
the position may have changed (sold, added to) and the ex-date snapshot
is what governs, exactly per the original requirements' own timing rule.

**Pushing a future-dated event onto the queue mid-run is safe and
idiomatic** — `DeterministicEventQueue` is a plain `(ts, seq)` heap;
insertion order never matters, only pop order, and popping enforces
non-decreasing `(ts, seq)` (I9). This sidesteps the ledger's
append-ordering constraint entirely: the *event* is scheduled now, the
*transaction* is appended only when the clock actually reaches pay-date,
so two dividends with pay-dates in "the wrong order relative to when
their ex-dates fired" (e.g. dividend A's ex-date is day1/pay-date day10,
dividend B's ex-date is day5/pay-date day7) still append in correct
final time order (day7 before day10) because each transaction is only
appended when its *own* pay-date arrives, not when its ex-date does.

**`pay_at` is a new nullable column, not a new dataset or a change to
`effective_at`'s meaning.** `effective_at` stays the ex-date for
`CASH_DIVIDEND` (consistent with its existing meaning for `DELISTING`);
`pay_at` is simply absent (null) for every action type that doesn't need
it. Every existing corporate-actions builder (`examples/momentum/
build_data.py`, `tests/integration/test_engine_end_to_end.py`) needed a
one-line addition (`"pay_at": [None]` with a `pl.Int64` override) since
`build_dataset` requires every schema column present — this is the same
kind of schema-widening `crucible/data/contracts.py` has done before
(FX_RATE_SCHEMA, ADR-0025) and is an accepted cost of the "engine
enforces the contract, not convention" prime directive (AGENTS.md §1.2):
a dividend row missing `pay_at` should be impossible to build, not merely
discouraged.

**A malformed dividend row (`pay_at` or `value` missing) refuses at
ex-date processing time with `DataQualityError`**, not later at
pay-date (there would be no way to even schedule the pay-date event
without a `pay_at`) and not earlier at engine construction (dividends
aren't validated upfront the way FX dataset presence is, ADR-0025 —
doing so would mean scanning the whole corporate-actions dataset at
construction; deferred as unnecessary until a real need for that
eagerness appears).

**Fixed a latent multi-currency reporting bug found while touching this
code**: `BacktestEngine._ledger_rows()`'s `currency` column was
hardcoded to `self._base` regardless of a transaction's actual currency
— harmless before ADR-0025 (everything *was* base currency), wrong
after it (a EUR-denominated fill would misreport `USD`). Fixed to read
the transaction's own (single) currency key.

## Alternatives considered

- **Pre-append the pay-date transaction early, dated in the future**:
  rejected — breaks `InMemoryLedger`'s append-ordering invariant when a
  later-queued dividend's pay-date precedes an earlier-queued one's (see
  Context); the event-queue approach has no such ordering hazard because
  nothing is appended until the clock naturally arrives.
- **A single event carrying both dates, resolved lazily by comparing
  `ctx.clock.now` against `pay_at` on repeated dispatch**: rejected —
  would require the engine to re-visit the same event multiple times or
  poll, which this engine's event-driven design has no mechanism for and
  shouldn't invent one for a single feature.
- **Two separate dataset rows** (one for the ex-date, one pre-computed
  for the pay-date) instead of one row producing two events: rejected —
  the pay-date amount depends on the *position held on the ex-date*,
  which isn't knowable at data-build time (it depends on what the
  strategy does during the backtest); it can only be resolved by the
  engine, at simulation time.

## Consequences

`CorporateActionEvent` gained two optional fields (`pay_at`,
`resolved_amount`) — every other action type (`DELISTING` today) simply
never sets either, no behavior change. `CORPORATE_ACTION_SCHEMA` gained
`pay_at`; this changed `examples/momentum`'s corporate-actions dataset's
content hash, which changed its `experiment_id` — the golden fixture's
*only* change is that id string; every actual simulation artifact stayed
byte-identical, regenerated and justified here per AGENTS.md §1.6/§7. No
dividend reinvestment, DRIP, or foreign-currency-dividend FX handling is
modeled yet (a dividend on a foreign-currency symbol pays in that
symbol's own currency via the existing `_currency_of` resolution from
ADR-0025 — this composes for free, verified only incidentally, not by a
dedicated test; add one if dividends and multi-currency are combined in
anger).
