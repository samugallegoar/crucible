# ADR-0032: Borrow cost and margin financing accrual (Phase 5, priority 2)

- **Status**: accepted
- **Date**: 2026-09-19

## Context

ADR-0031 (Phase 5 priority 1) added margin *governance* for shorts —
`MarginRequirementLimit`/`MarginCallLimit` decide whether a short can be
opened or must be closed, but neither charges anything for *holding*
one. The original requirements's Phase 5 scope also names "Borrow availability/cost" and
"financing rates" explicitly, and `core.types.TransactionType` has
carried unused `BORROW`/`FINANCING` members since the Phase 0 scaffold,
anticipating exactly this work.

Two real, distinct carrying costs needed a home: a stock-loan fee on a
short position (you're borrowing shares; the lender charges for that),
and interest on a negative (margin/debit) cash balance (you're borrowing
money; the broker charges for that). Both are periodic, proportional to
elapsed time and to how much is borrowed — structurally the same
mechanism with a different balance to charge against — so this priority
designs and builds them together rather than twice.

## Decision

**A single accrual method on `BacktestEngine`, not a new pluggable
model.** `_accrue_financing(ts)` runs at the top of every `_mark()`
call (before the mark's own snapshot/invariant check, so an accrued fee
this instant is reflected in *this* mark's equity — consistent with how
a fill posted this same bar is already reflected by the time `_mark()`
runs). It computes `elapsed_ns` since the last accrual (initialized to
the run's `start`), and for each of the two costs, only if its rate is
non-zero:
- **Borrow cost**: for every symbol with a short position (`qty < 0`),
  `fee = |qty| · mark · short_borrow_rate · elapsed_ns / YEAR_NS`,
  posted as a `TransactionType.BORROW` transaction in that symbol's
  currency.
- **Margin financing**: for every currency with negative cash,
  `fee = |cash| · margin_financing_rate · elapsed_ns / YEAR_NS`, posted
  as a `TransactionType.FINANCING` transaction. Re-folds the ledger
  after the borrow-cost loop so a borrow fee posted moments earlier in
  the *same* accrual call already counts toward the cash balance being
  charged interest on — the two costs compose correctly within one call
  rather than needing a strict ordering guarantee from the caller.

This was **not** built as a new pluggable `FinancingModel` Protocol
(the shape `ExecutionSetup`/`RiskEngine` use) because both costs are
simple, single-formula computations with no realistic near-term need
for multiple competing implementations — unlike execution models (five
realism levels) or risk limits (open-ended, composable list), there is
one accrual formula each here, parameterized by a rate. Two new
`BacktestEngine.__init__` parameters (`short_borrow_rate`,
`margin_financing_rate`, both `float`, default `0.0`) follow the exact
precedent `settlement_lag_days` set in ADR-0028: a simple, optional,
config-driven parameter rather than a new component class, chosen when
the behavior is one formula, not a family of interchangeable ones. If a
future need for multiple borrow-cost models emerges (e.g.
per-symbol/hard-to-borrow rate schedules), promoting this to a Protocol
behind the same call site is a contained change.

**Actual/365 day-count convention, fixed, not configurable.** `_YEAR_NS
= 365 * DAY_NS` is a module constant. Real financing conventions vary
(Actual/360, 30/360, Actual/Actual), and `ExperimentConfig` already has
a *different*, legitimately distinct "days per year" — `periods_per_year`
(default 252, trading days, used for annualizing returns/Sharpe). Reusing
`periods_per_year` for interest accrual would silently conflate two
different conventions that happen to share a name shape; a fixed,
documented Actual/365 constant avoids that confusion and avoids a third
config knob for a modeling detail with one well-known default. A
configurable day-count convention is a reasonable, contained future
addition if ever needed.

**End-of-period balance, not intraday time-weighting.** A charge for
the period `(last_accrual_ts, ts]` uses the position/balance **as of
`ts`** (the end of that period), not a time-weighted average across it.
Concretely: if a short opens via a fill that posts in the *same* bar as
the mark being charged, that mark's accrual charges a full period's fee
against the now-open short, even though the short existed for only an
instant before the charge. This matches how many real broker systems
actually work (end-of-day balance snapshots drive daily interest/borrow
postings, not intraday time-weighting) and is the simpler, honestly
documented choice — the alternative (weighting by how long a position
was actually open within the period) would need to track sub-period
position changes, a materially bigger feature for a marginal accuracy
gain this priority's scope didn't justify.

**Multiplication before division**, computed as `notional · rate ·
elapsed_ns / YEAR_NS` in that exact order (not `notional · rate ·
(elapsed_ns / YEAR_NS)`). `elapsed_ns / YEAR_NS` alone is a
non-terminating decimal in base 10 (`1/365` has no exact representation)
and forces Decimal's default context to round to 28 significant digits
before the subsequent multiplications — introducing rounding noise this
priority's own test caught immediately (`-9.000000000000000000000000001`
instead of exactly `-9`). Deferring the division to the very last step
means the *product* often divides out exactly (a whole number of
elapsed days against an Actual/365 rate chosen for clean math, as in
this priority's tests) instead of losing precision on an intermediate
result nothing needed as its own value.

**Neither cost counts toward `fees_paid`.** `InMemoryLedger.fold`'s
`fees_paid` aggregation only sums `TransactionType.FEE` (broker
commissions); `BORROW`/`FINANCING` are separate, distinct transaction
types by design (the original requirements' own type list already distinguishes them) and
stay out of that aggregate — `fees_paid` means "commissions," not "every
cost," and conflating carrying costs into it would make that field mean
something different for a Phase 5 run than it already means for every
Phase 1-4 run and every existing test that asserts against it.

## Alternatives considered

- **A `FinancingModel` Protocol + registry**, mirroring execution/risk:
  rejected for now — see Decision; promotable later behind the same
  call site if multiple implementations are ever needed.
- **Intraday time-weighted accrual**: rejected — materially more
  complexity (tracking position/balance changes *within* a period, not
  just at its boundary) for a refinement real broker systems mostly
  don't bother with either; documented as the simpler, honest choice.
- **Reusing `periods_per_year` for the day-count convention**: rejected
  — conflates two different, legitimately distinct conventions (trading
  days for return annualization vs. calendar days for interest accrual)
  that happen to sound similar; a separate fixed constant is clearer
  than a shared config field with two different meanings depending on
  context.
- **Folding borrow/financing into `fees_paid`**: rejected — would
  silently change what an existing, tested field means; the original requirements' own
  `TransactionType` list already treats these as distinct categories.

## Consequences

`BacktestEngine.__init__` gained `short_borrow_rate: float = 0.0` and
`margin_financing_rate: float = 0.0` (both validated `>= 0`; default
`0.0` for both is zero behavior change — `_accrue_financing`'s two
loops never run). New `_accrue_financing`/module constant `_YEAR_NS`.
`ExperimentConfig` gained matching top-level fields (same placement
precedent as `settlement_lag_days`, ADR-0028); wired into
`assemble_engine`.

Tests: `tests/integration/test_financing.py` (new, 3 — hand-computed:
a short held 3 marks accrues exactly $10/day borrow cost on a $10000
notional at a 36.5% rate chosen for clean Actual/365 math; a margin
debit balance accrues exactly $9 financing in one period on a $9000
balance at the same rate; a zero-rate run accrues nothing at all).

**Golden fixture regenerated, intentionally**: the two new
`ExperimentConfig` fields (default `0.0`) serialize into every
`config.yaml`, shifting its hash and therefore `experiment_id`. Verified
file-by-file that `ledger.parquet`, `orders.parquet`, `fills.parquet`,
`trades.parquet`, `equity.parquet`, `metrics.json` all stayed
byte-identical before regenerating with `--regen-golden`, same
verification procedure as every prior config-field addition this
session (ADR-0028, ADR-0030).

Known gaps carried forward: no per-symbol/hard-to-borrow rate schedule
(one flat `short_borrow_rate` for every short in the book); no interest
earned on a positive cash balance (only debit/negative balances are
charged — a "financing rate," not a full cash-sweep interest model);
day-count convention is fixed at Actual/365, not configurable; accrual
is end-of-period-balance-based, not intraday time-weighted (both
documented above as deliberate scope boundaries, not oversights).
The original requirements's third named Phase 5 acceptance target, "a futures roll," is
still entirely unaddressed.
