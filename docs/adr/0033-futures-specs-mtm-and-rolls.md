# ADR-0033: Futures contract specs, daily MTM settlement, and rolls (Phase 5, priority 3)

- **Status**: accepted
- **Date**: 2026-09-19

## Context

ADR-0031 (margin/shorts) and ADR-0032 (borrow cost/financing) closed
two of Phase 5's three named the original requirements acceptance golden tests ("a short,"
"a margin call"); "a futures roll" remained, and futures were otherwise
completely unaddressed — no contract specs, no instrument model, no
mention anywhere in the engine.

The prior session's handoff notes explicitly flagged the open design question
this ADR resolves: does a futures position reuse `PositionState`/
`TransactionRecord` at all, given futures economics are genuinely
different from equities' — no cash changes hands to open a position
(only a margin *requirement*, not modeled as a cash movement here); PnL
realizes to cash **every day** via mark-to-market (MTM) settlement,
never sitting "unrealized" in the position the way an equity's does;
and PnL per unit of quoted price movement is the contract's
**multiplier**, not 1.

## Decision

**Reuse `PositionState.apply` unchanged, for both futures and equities**
— but book *different cash* at fill time, and add a **new periodic
settlement operation** equities never need. This was the central design
insight, and the ADR spends most of its space justifying it because it
determines everything else:

`PositionState.apply(qty, price)`'s weighted-average-cost and
closing/realized-PnL math is generic and correct for *any* instrument
that has a quantity and a reference price — it doesn't know or care
whether "price" means "what I paid" (equity) or "the contract's last
settlement level" (futures). The only genuinely different thing about
futures is **what cash movement accompanies a change in that
quantity**, and **that a periodic event (not just a fill) can also
change the reference price and realize PnL**. Both of those are
handled entirely *outside* `apply()`, at the call sites, using a small
reusable primitive:

```python
def _futures_price_delta(self, symbol, delta_qty, price, ts) -> Decimal:
    """The realized-PnL delta apply() would book, on a throwaway clone."""
    position = self._ledger.fold(up_to=ts).positions.get(symbol)
    trial = copy(position) if position is not None else PositionState()
    before = trial.realized_pnl
    trial.apply(delta_qty, price)
    return trial.realized_pnl - before
```

This clones the *current* position, applies the hypothetical fill to
the clone, and reads off what `apply()`'s own formula says was
realized — reusing the exact sign/weighted-average logic rather than
re-deriving it. There is now only one place that math can be wrong.

**At fill time** (`_book_fill`), a futures symbol's cash amount is
`_futures_price_delta(...) × multiplier` instead of the equity
`-signed_qty × price`: zero for an opening/increasing fill (no realized
PnL, matching "no cash changes hands to open a position"), the
realized gain/loss × multiplier for a closing/reducing fill. Settlement
lag (ADR-0028) never applies to a futures fill — it's an equity
sale-proceeds concept with no futures analogue.

**At every mark** (`_settle_futures_mtm`, called from `_mark()`
alongside `_accrue_financing`), every held futures position's *entire*
unrealized move since the last settlement is realized to cash, via a
**synthetic close-then-reopen transaction pair** at the current mark:
one transaction with `qty = -position.qty` at `price = mark` (a full
close, realizing `(mark - avg_cost) × qty × multiplier` to cash via the
exact same `apply()` formula, replayed generically by `fold()` with **no
changes to `fold()` or `apply()` needed**), immediately followed by one
with `qty = +position.qty` at `price = mark` (a fresh reopen at the
current mark, zero cash — `apply()`'s same-direction branch on a
just-closed, empty position simply sets `avg_cost = mark`). Skipped
entirely (both transactions) when the realized delta is exactly zero —
appending only the reopen half without its matching close would be
misread by `apply()`'s same-direction branch as *adding* to a still-open
position, silently doubling it (caught by this priority's first test
run, before the fix).

**Why a *transaction pair*, not a live-state side effect**: `fold()` is
this engine's source of truth everywhere else — any cached snapshot
must equal a fresh fold from raw transactions (I3/I4). If MTM rebasing
were applied only as an in-memory side effect on the engine's live
`PositionState`, a fresh fold of the raw transaction list would
disagree with it (replaying only the *original* entry prices, with no
memory of intervening rebases). Representing each settlement as two
ordinary, fold-replayable transactions means the existing generic
position-apply logic reproduces the exact same state on any replay —
no invariant needed new code to check, because none of them had to
change.

**Equity's own formula needed a matching fix.** `PortfolioSnapshot.
equity()` (and `accounting.invariants.check_equity_identity`, which
independently recomputes the same identity from a fresh fold and must
match it exactly) previously computed every position's contribution as
`qty × mark` — correct for equities (you paid for that notional, so you
own it), **wrong** for futures (you paid nothing, so adding the full
notional would fabricate equity that isn't there). Both were changed to
contribute `(mark - avg_cost) × qty × multiplier` for a futures symbol
— its *unsettled* variation margin since the last mark, which is
exactly zero the instant after `_settle_futures_mtm` has run (the
position's entire economics are already in cash by then), and
correctly nonzero for anything reading equity *between* marks (e.g. a
pre-trade risk check mid-bar, after today's bar has updated `_marks`
but before today's `_mark()`/settlement has run). `PortfolioSnapshot.
realized_pnl` needed the same multiplier scaling, for the same reason:
`PositionState.realized_pnl` has no multiplier awareness (it's shared
with every equity position), so the one place that must apply it is the
aggregate that reports it.

**Multiply by hand, not inside `apply()`.** The multiplier scaling
happens at the *call sites* (fill cash, MTM settlement cash, equity,
realized_pnl) — never inside `PositionState`/`apply()` itself, and
`avg_cost`/`qty`/ledger `price` stay in **raw quoted-price units**
throughout. This keeps `ledger.parquet`'s `price` column showing the
actual quote (e.g. `4500`, not `225000`) for reporting/debugging
clarity, and keeps `PositionState` a single generic primitive shared by
every instrument type rather than forking it per-instrument.

**Rolls need no new mechanism at all.** Since each futures contract
month is its own tradeable `Symbol` (the universal real-world
convention — "ESZ25" and "ESH26" are different symbols with different
bar data), and the fill/MTM machinery above operates independently per
symbol, a roll is simply **two ordinary orders**: SELL (close) the
expiring symbol, BUY (open) the new one — both going through the exact
same `ctx.orders.submit` path every other order uses. No dedicated
`submit_roll` API, no new order type, no new engine method. This
priority's acceptance test demonstrates exactly that: a strategy
submits both orders together and the resulting ledger is hand-verified
to show the near contract closing (realizing its PnL) and the far
contract opening fresh, simultaneously.

## Alternatives considered

- **A parallel, futures-specific position/accounting type** (not
  reusing `PositionState`): rejected — the *only* genuinely
  futures-specific things are the cash-at-fill rule and the periodic
  settlement event, both of which live cleanly outside `PositionState`
  already; forking the whole position model would duplicate the
  weighted-average/closing math this codebase already has exactly
  right, doubling the surface area for a sign-convention bug.
- **Rebasing `avg_cost` as a live-state side effect** instead of a
  fold-replayable transaction pair: rejected — breaks the I3/I4
  fold-is-truth invariant this engine relies on everywhere; a fresh
  fold from raw transactions would silently disagree with the engine's
  own live tracking.
- **Scaling `price`/`avg_cost` internally by the multiplier** (so
  `PositionState.realized_pnl` comes out in dollars directly, no
  external scaling needed): rejected — would make `avg_cost` and the
  ledger's `price` column show a multiplier-inflated number instead of
  the real quoted price, actively confusing for reporting/debugging;
  scaling at the handful of call sites that need dollars is a smaller,
  more localized change than threading a scaled price through every
  internal computation.
- **A dedicated roll API** (`submit_roll(old, new, qty)` or a new
  composite order type like bracket/OCO): rejected — the two-ordinary-
  orders approach is already fully correct and requires zero new
  engine surface; a convenience wrapper could be added later purely as
  strategy-side sugar with no accounting implications, but wasn't
  needed to satisfy this priority's correctness bar.

## Consequences

New: `crucible/core/instruments.py::FuturesSpec` (one field,
`multiplier`, validated `> 0`). `BacktestEngine` gained
`futures_specs: Mapping[Symbol, FuturesSpec] | None = None` (empty
default, zero behavior change for every existing run), `_futures_price_delta`,
`_settle_futures_mtm` (called from `_mark()`). `_book_fill` branches on
whether the filled symbol has a `FuturesSpec`. `PortfolioSnapshot`
gained a `futures_specs` constructor parameter, threaded through both
of its construction sites in `engine.py`; `equity()` and `realized_pnl`
both updated. `accounting.invariants.MarkContext` gained a matching
`futures_specs` field; `check_equity_identity` updated to match
`equity()`'s formula exactly (a required change, not an optional one —
these two computations must never diverge). `experiments/config.py::
DataConfig.futures_multipliers: dict[str, Decimal]` (empty default);
wired into `assemble_engine`.

Tests: `tests/integration/test_futures.py` (new, 3, all hand-computed
per AGENTS.md §7 and cross-checked against the direct entry-to-exit
calculation, not just internal consistency): daily MTM settlement
across three marks telescopes to the same total as one lump-sum move
(explicitly verifying the no-op-skip fix does *not* double-count);
a fill that closes a futures position mid-holding realizes its PnL
immediately, composing correctly with an earlier MTM settlement on the
same position; **a roll** — closing the near contract and opening the
far one via two ordinary orders — hand-verified end to end. Together
with ADR-0031/0032's tests, this satisfies the original requirements's Phase 5 acceptance
criterion in full: hand-computed ledgers for a short, a margin call,
and a futures roll.

**Golden fixture regenerated, intentionally**: the new
`DataConfig.futures_multipliers` field (default `{}`) serializes into
every `config.yaml`, shifting its hash and `experiment_id`. Verified
file-by-file that every other artifact stayed byte-identical before
regenerating with `--regen-golden`, same procedure as every prior
config-field addition this session.

Known gaps carried forward: futures positions are **not** integrated
with the margin risk limits (`MarginRequirementLimit`/`MarginCallLimit`,
ADR-0031) — those check short *equity* notional specifically; a real
futures account requires initial/maintenance margin symmetrically on
both long and short positions, which this priority does not add (folds
into the existing "long-side margin" deferred item, now broadened to
"symmetric margin, including futures"). No futures-specific commission
model (per-contract fees) — the existing bps-of-notional commission
model applies unchanged, a documented mismatch with how futures
commissions actually work in practice. No tick-size rounding, no
position limits, no forced-close-at-expiry mechanism (a strategy that
doesn't roll before expiry is not automatically closed out — this
priority assumes strategies self-manage rolls). No physical-delivery
vs. cash-settlement distinction (irrelevant at the P&L level this
engine models, but real for certain contract types).
