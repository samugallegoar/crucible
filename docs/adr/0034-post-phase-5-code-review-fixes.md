# ADR-0034: Post-Phase-5 code review — fixes applied and gaps deferred

- **Status**: accepted
- **Date**: 2026-09-19

## Context

At the user's request, a full code review (`/code-review high`, forked
subagent) ran over every commit from Phase 4's start through Phase 5's
completion (`8c0ec51..HEAD`, 8 commits). It surfaced 10 findings; each
was independently re-verified against the current source (not taken on
trust) before any action. Two were small, contained, low-risk
correctness bugs — fixed immediately, with regression tests. Four more
are real, confirmed correctness gaps that need a genuine design
decision or a larger interface change to fix properly — documented here
and in the project notes rather than patched hastily under review
pressure. Two are performance/style observations, recorded for
awareness. Two more (registry-dispatch duplication across
`portfolio/registry.py`/`risk/registry.py`/`execution/registry.py`, and
a repeated 4-line "no mark yet, defer" guard across four risk limit
classes) were considered and explicitly **not** acted on: extracting a
shared helper for 3-4 call sites of a simple pattern is exactly the
premature abstraction CLAUDE.md's own working style warns against
("Three similar lines is better than a premature abstraction"), so
these are noted as reviewed-and-declined, not missed.

## Fixed (this ADR)

**`PortfolioSnapshot.realized_pnl` missing FX conversion**
(`crucible/accounting/snapshot.py`). The property summed each
position's `realized_pnl` (correctly scaled by futures multiplier since
ADR-0033) but never converted a non-base-currency amount to the run's
base currency — unlike its sibling `equity()`, a few lines above in the
same class, which has always called `convert_at_mid` for every
cash/position value. This bug **pre-dates Phase 5**: the property
existed with this shape since Phase 4's multi-currency work (ADR-0025)
and was carried forward unfixed when Phase 5 added multiplier scaling
on top of it. Fixed by adding the same `convert_at_mid` call `equity()`
already makes, converting each position's (multiplier-scaled) realized
PnL to `self._base` before summing. Regression test:
`tests/integration/test_multi_currency_accounting.py::
test_realized_pnl_converts_a_foreign_currency_gain_to_base` — a
10-share EURSTOCK round trip (buy @ 50, sell @ 60) realizing exactly
100 EUR, asserted to report as exactly 110 USD at a constant 1.10 mid
rate (100 would be the old, buggy value).

**Borrow cost accrual applying to short futures positions**
(`crucible/core/engine.py::_accrue_financing`). The short-borrow-cost
loop charged a stock-loan `BORROW` fee against *every* negative-qty
position with no exclusion for futures symbols, and did so without the
futures multiplier — a compounded error (wrong fee basis, wrong
economics) that would only ever trigger when a run configures both
`futures_specs` and `short_borrow_rate > 0` together, which is why
neither ADR-0032 nor ADR-0033's own test suites (each written before
the other existed as a combination to consider) caught it. Shorting a
future is entering a symmetric contract, not borrowing a security to
sell — there is nothing to charge a stock-loan fee against, so the fix
excludes any symbol present in `self._futures_specs` from this loop
entirely, rather than attempting to make the fee "correct" with
multiplier scaling. Regression test: `tests/integration
/test_financing.py::test_borrow_cost_never_applies_to_a_short_futures_position`
— a short futures position at constant price (isolating from MTM)
configured with a nonzero `short_borrow_rate`; cash and equity must stay
exactly at the initial amount, and no `BORROW` transaction may appear.

Both fixes verified: full suite green (432 passed, 2 new), `mypy
--strict` clean, `ruff` clean. Neither changed the momentum example's
golden fixture (pure logic fixes, no new config surface).

## Confirmed, deferred (not fixed by this ADR)

**Risk limits compare foreign-currency notional against base-currency
thresholds with no FX conversion** (`MaxOrderNotionalLimit`,
`MaxGrossExposureLimit`, `MarginRequirementLimit`, `MarginCallLimit`,
all in `crucible/risk/limits.py`). `portfolio.mark(symbol)` is
documented as being in the symbol's *own* currency
(`accounting/interfaces.py::PortfolioView.mark`); none of these four
limits convert it before comparing against a base-currency threshold or
`equity()` (which *is* correctly converted). `InsufficientCashLimit`
documents this exact class of gap explicitly as a known limitation
(ADR-0028); the other four do not, despite having the identical
underlying issue — two of them (`MarginRequirementLimit`/
`MarginCallLimit`) were added in this session's own Phase 5 work
without carrying the same documented caveat forward. **Not fixed here**
because a real fix needs `PortfolioView`/the `PreTradeLimit`/`MarkLimit`
Protocols to expose an FX-conversion capability to risk limits, which
none of them currently receive — a genuine interface change across the
risk module, not a local patch, and exactly the kind of design decision
AGENTS.md §10 says to resolve via its own ADR before writing code, not
retrofit under review pressure. Tracked in the project notes as a
priority for a dedicated future session.

**Dividend ex-date entitlement can include the same day's own fill**
(`crucible/core/engine.py::_handle_dividend`, Phase 4 priority 2 vintage).
`_load_events` enqueues every `BarEvent` before any
`CorporateActionEvent`; since both draw from the same monotonic
sequence counter, a bar and a dividend ex-date sharing a timestamp
always has the bar's sequence number lower, so the bar (and any fill it
produces) is processed first. `_handle_dividend`'s ex-date branch then
folds the ledger *after* that same-day fill has already been appended,
so entitlement reflects the post-trade position instead of the
pre-trade one — backwards from real ex-dividend convention. **Not fixed
here** because the obvious-looking fix (enqueue corporate actions before
bars) would break `DELISTING`'s correctness in the opposite direction:
delisting liquidation deliberately wants *today's* mark
(`self._marks[symbol]`, only current after today's bar has been
processed) as "the last mark, final close" (ADR-0010) — reordering
uniformly would make a same-day delisting liquidate at yesterday's
price instead. A correct fix needs to treat `CASH_DIVIDEND` and
`DELISTING` differently, which is a genuine design decision, not a
one-line reorder. Tracked in the project notes; no existing test
exercises a same-day trade on an ex-date bar in either direction.

**Margin risk limits don't apply the futures multiplier** — already an
explicitly documented known gap (ADR-0031's Consequences, ADR-0033's
Known gaps, `docs/modules/risk.md`, the project notes), re-confirmed by
this review as still real and still undocumented *as a refusal*: per
AGENTS.md §5 ("Refuse, don't warn"), a future session should make
`MarginRequirementLimit`/`MarginCallLimit` explicitly reject (raise a
clear `ConfigurationError`, not silently miscompute) when applied
against a futures-registered symbol, until the risk module can properly
receive `futures_specs` and scale correctly. This requires the same
kind of interface change as the FX-conversion gap above and is grouped
with it as one future priority: "risk limits need currency- and
instrument-aware notional, not just `PortfolioView.mark`."

## Noted, not acted on

**Six-plus ledger re-folds per mark** (`_mark()` calls
`_current_snapshot()`, then redoes the same fold/FX computation for
`MarkContext`, and each of `check_mark`'s four invariant checks
independently re-folds again, on top of `_accrue_financing`'s and
`_settle_futures_mtm`'s own per-symbol folds). This is real and grows
with run length, but it compounds an *already-documented, deliberate*
trade-off: `docs/modules/core.md` states plainly "Engine re-folds the
ledger at every mark (intentional until benchmarks, ADR-0003)." Phase
4/5's additions made that trade-off costlier without changing its
nature. No action taken — consistent with AGENTS.md §1's "never
optimize a code path that lacks a golden or property test" and ADR-0003's
own "measure first" stance; worth remembering if a future performance
pass ever profiles mark-time cost.

**Three independent inlined copies of `86_400 * 10**9`**
(`risk/limits.py::DAY_NS`, `engine.py::_YEAR_NS`, the
`settlement_lag_ns` computation), none derived from the existing
`NS_PER_S` constant `crucible/data/calendars.py` already builds on
correctly. Low practical risk (this is a fixed physical constant, not a
tunable that could plausibly change), but a fair, easy code-quality
improvement for whichever session next touches any of these three
sites — not urgent enough to justify an isolated commit on its own.

**Registry-dispatch duplication** (`portfolio/registry.py`,
`risk/registry.py`, `execution/registry.py` each hand-roll the same
"key → factory, else `ConfigurationError`" pattern) and **the repeated
"no mark yet, defer" guard** across four risk limit classes: reviewed
and declined. Extracting a shared helper for three-to-four call sites
of a simple, already-consistent pattern is the premature abstraction
CLAUDE.md's own conventions explicitly warn against. Revisit only if a
fourth/fifth registry or limit genuinely needs the pattern to change in
a way that would otherwise require editing multiple places identically.

## Consequences

`crucible/accounting/snapshot.py::PortfolioSnapshot.realized_pnl` and
`crucible/core/engine.py::BacktestEngine._accrue_financing` both
changed (additive fixes, no interface change, no config surface
change). Two new regression tests. the project notes gains a new,
prominent "confirmed gaps from code review" section pointing at this
ADR so a future session picks up exactly where this one left off,
instead of re-discovering these four deferred issues from scratch.

## Status update (2026-09-25)

The four deferred gaps above are closed: the risk limits' missing FX conversion
and the margin limits' missing futures multiplier by ADR-0045 (the limits use
`PortfolioView.notional`; the margin limits refuse futures symbols); the
dividend ex-date sequencing gap by ADR-0046; the attribution `qty*price`
re-derivation by ADR-0047. Nothing else in this ADR changes.
