# ADR-0035: Vectorized engine — weight semantics, shift discipline, and the event-driven agreement test

- **Status**: accepted
- **Date**: 2026-09-19

## Context

Phase 6 asks for "a vectorized Level 0/1 engine with shift
discipline and poison test" whose results "agree with the event-driven
engine within documented tolerance on the example strategy." Three things
had to be pinned that the original requirements leave open:

1. What does a `SignalFunction`'s `score` column actually mean (a raw
   z-score to be ranked, a target weight, something else), and how does the
   engine turn it into a position?
2. What, concretely, is "shift discipline" as an *engine-enforced*
   mechanism, given the vectorized path has no per-event `as_of` checkpoint
   the way `StorePITAccessor` does (ADR-0004)?
3. What tolerance is "documented," and against which example strategy —
   and is that tolerance a real, understood quantity or a number picked to
   make one test pass?

These affect results (a "how do we score a strategy" question), so per
AGENTS.md §10 they're decided here rather than silently in code.

## Decision

**1. `score` is a target weight, used as-is.** No normalization, no
ranking, no leverage clipping — a signal function that wants to express
"go 100% long" returns `1.0`; "40% short" returns `-0.4`. This keeps the
engine's own job minimal (lag, then multiply by return) and matches the
`SignalFunction` docstring's framing ("full price history in, per-symbol
scores out... the engine lags the output before it becomes a position").
A signal wanting cross-sectional ranking, vol targeting, or gross-leverage
normalization does that arithmetic itself before returning `score` — no
different from how an event-driven `Strategy` calls a
`PortfolioConstructor` itself (ADR-0029) rather than the engine doing it.

**2. Shift discipline is one unconditional operation the engine performs
on every run, regardless of the signal function's own code:**
`weight = score.shift(lag_bars).over(symbol)`, `lag_bars >= 1`, refused
otherwise (no opt-out, `vectorized/interfaces.py`'s existing docstring).
This is deliberately *not* a validation that inspects the signal
function's internals — there is no way to statically prove a black-box
polars pipeline never used a future row. Instead, exactly like the
event-driven engine's own pessimism-by-construction pattern (e.g. "fills
clamp into `[low, high]`" is enforced by the fill code, not asserted after
the fact), the *only* path from `score` to `weight` runs through a hard
`shift`. A signal function cannot make position `t` depend on data at `t`
or later, no matter what it computes internally, because position `t`
literally never reads `score` at index `t` — it reads `score` at index
`t - lag_bars`. The poison test (`tests/lookahead/
test_vectorized_poisoned_future.py`) is the *evidence* this holds, not the
mechanism; the mechanism is the shift itself, engine-side, unconditional.

Net-of-cost return per bar is
`net_t = sum_symbol(weight_t * ret_t) - turnover_t * (slippage_bps +
commission_bps) / 10_000`, where `ret_t` is close-to-close simple return
and `turnover_t = sum_symbol(|weight_t - weight_{t-1}|)`. Equity compounds
`equity_t = equity_{t-1} * (1 + net_t)`. This turnover-bps cost is an
approximation of the event-driven engine's per-fill bps costs (which apply
to actual traded notional, not portfolio-fraction turnover) — documented
as a known, deliberate approximation below, not a bug.

**3. Level gating mirrors ADR-0010's own rule, reused, not reinvented.**
`VectorizedBacktestEngine.run` refuses `realism_level` outside
`{FRICTIONLESS, BASIC_FRICTION}`, and refuses nonzero
`slippage_bps`/`commission_bps` at `FRICTIONLESS` — the exact same
"configuring friction at Level 0 is refused" rule ADR-0010 already
established for the event-driven engine at Level 0. There is no config
slot for spread/latency/impact models, risk limits, multi-currency, or
futures multipliers at all (refuse by omission, not by rejecting a
populated field) — those stay exclusively the event-driven engine's
territory until a future priority decides otherwise.

**4. `VectorizedConfig`/`VectorizedResult` are types owned by
`crucible.vectorized`, not `crucible.experiments.config.ExperimentConfig`
reused directly.** The layered view places the vectorized path
*below* the experiments layer, parallel to the event-driven core — so the
dependency must run experiments → vectorized, matching how
`core/engine.py::BacktestEngine` already takes plain constructor-shaped
arguments rather than importing `ExperimentConfig` itself. A future
priority adds `crucible/experiments`-side glue
(`assemble_vectorized_engine(config: ExperimentConfig) -> ...`) that
translates and refuses out-of-scope fields, exactly mirroring
`experiments/runner.py::assemble_engine`.

**5. The agreement test uses `examples.trend_demo`
(`TrendFollower`), not `examples.momentum`.** Single symbol, binary
long/flat, `rebalance_every: 1`, zero slippage/commission in its shipped
config — the simplest possible strategy that still has genuine signal
content (AR(1) serial correlation, ADR-0024), which makes an exact,
hand-derivable correspondence between the two engines' timing conventions
possible (worked below), rather than an approximate cross-sectional
ranking match. `examples.momentum`'s multi-symbol top-k selection and
per-share integer rounding across 8 names would make any disagreement much
harder to attribute to a specific, named cause.

**Bar-by-bar correspondence (why the two engines should agree at all).**
`TrendFollower._rebalance` computes its signal from closes strictly before
the current bar (`event_time < current_event_time`), submits a market
order on that bar, which then fills (ADR-0010) at the *next* bar's open.
Because the data generator uses the no-overnight-gap convention
(`open[t] = close[t-1]`), a fill reported at bar `t+1` executes at exactly
`close_t` — i.e. it captures precisely `ret_{t+1} = close_{t+1}/close_t -
1`. Deriving the index algebra (full derivation kept in the module
docstring of `examples/trend_demo/vectorized_signal.py` and the commit
that introduced it): the event-driven position that captures `ret_{t+1}`
is decided from returns ending at `ret_{t-1}` — a **two-bar** lag from the
signal's last input to the return it captures. The vectorized engine only
ever contributes one mandatory lag, so `trend_follower_signal` supplies
the other bar itself, via its own internal `.shift(1)` on the rolling
mean — mirroring `TrendFollower`'s own exclusion of the current bar's
close. With both lags stacked, `weight_t` (engine-shifted) exactly equals
`TrendFollower`'s own decision for the position that captures `ret_t`.
This was verified two ways, not just asserted: algebraically here, and
empirically by `tests/integration/test_vectorized_agreement.py`, which
asserts the two engines' long/flat *decision sequences* are byte-for-byte
identical over the full ~500-bar run (not merely "close enough") —
that's the real evidence shift discipline reproduces the event-driven
engine's timing exactly, not a tolerance-masked coincidence.

**Tolerance: 2%, on final equity only, given the decision-sequence
match.** Measured divergence on this example is ~1.37%, entirely
attributable to `TrendFollower._rebalance`'s integer-share `ROUND_DOWN`
sizing — `Decimal` share truncation on ~500 daily rebalances, each losing
a fraction of a share's worth of notional against the then-current
(already slightly reduced) equity, so the effect compounds across the
run rather than washing out. The vectorized side has no share-rounding at
all (continuous weights), so this gap is one-directional and fully
explained; it is not a hidden timing or lookahead bug, which the exact
decision-sequence match independently rules out. 2% leaves comfortable
headroom above the measured ~1.37% while staying far below the order of
divergence a genuine bug (wrong lag, wrong price series, a real lookahead
leak) would produce.

## Alternatives considered

- **`score` as a raw signal to be cross-sectionally ranked/normalized by
  the engine** (top-k, vol-target, etc., like a `PortfolioConstructor`):
  rejected for Level 0/1 — that's exactly the kind of policy decision
  `PortfolioConstructor` already owns on the event-driven side (ADR-0029);
  duplicating it inside the vectorized engine would fork the "how do
  signals become sizes" decision across two engines instead of sharing it.
  A future priority may let vectorized signal functions call the same
  `portfolio.constructors` library directly (they're plain numpy/polars
  math, not engine-coupled) — no engine change needed for that.
- **Validating the signal function's internals for lookahead** (e.g.
  static analysis of the polars expression tree): far more complex, still
  incomplete (a signal function can call arbitrary Python), and redundant
  with the poison test, which empirically proves the same property for the
  actual computation that runs. Rejected as premature engineering for a
  guarantee the shift mechanism already provides structurally.
- **Matching event-driven costs exactly (bps-per-fill on traded notional)
  instead of turnover-bps**: would require the vectorized engine to track
  notional in dollars, which needs prices at the *decision* bar, not just
  weights — adds real complexity for a Level 0/1 fast-research path whose
  whole purpose is approximate speed. Turnover-bps is the standard
  vectorized-backtest convention and was accepted as a documented
  approximation instead; the agreement test's zero-cost config sidesteps
  needing the two cost models to match at all for Phase 6's acceptance
  criterion.
- **A tighter tolerance (e.g. 0.5%) forcing a "no-rounding" event-driven
  variant just for this test**: rejected — it would mean testing a
  strategy that isn't the one that actually ships in
  `examples/trend_demo/config.yaml`, weakening the acceptance
  demonstration's honesty. Documenting the real, measured, explained
  number is more valuable than a smaller number obtained by testing
  something slightly different.
- **Reusing `ExperimentConfig` directly as `VectorizedEngine.run`'s
  parameter**: rejected per the layered view — see Decision
  point 4.

## Consequences

- `crucible/vectorized/engine.py` (`VectorizedBacktestEngine`,
  `VectorizedConfig`, `VectorizedResult`) is the first real implementation
  in `crucible/vectorized/` (previously interfaces-only).
  `crucible/vectorized/interfaces.py`'s `VectorizedEngine.run` is now typed
  concretely instead of `object -> object`.
- `examples/trend_demo/vectorized_signal.py` is the first `SignalFunction`
  implementation and the vehicle for Phase 6's acceptance test; it is
  *not* a general-purpose reusable signal (its internal double-shift is
  specifically tuned to mirror `TrendFollower`'s own timing), so a future
  signal function should not copy its shift pattern without re-deriving
  the correspondence for its own event-driven counterpart, if it has one.
- Known gaps deliberately left for later Phase 6 priorities: no
  `crucible.experiments`-side glue yet (`assemble_vectorized_engine`,
  artifact writing, `crucible run --vectorized` CLI surface); no
  "promotion" command (rerun a vectorized experiment's config through the
  event-driven engine at Level ≥2); no multiprocessing sweep runner; no
  result-registry queries. All four are named explicitly in the original requirements's
  Phase 6 scope and remain open.
- The vectorized `equity` frame has no FX handling (single implicit
  currency) and no per-trade trade log (`trades.parquet` equivalent) —
  continuous weights don't have discrete "trades" the way integer-share
  fills do. Both are known gaps, not oversights; revisit if/when the
  vectorized path needs to support multi-currency signals or per-trade
  attribution.
- `compute_metrics`/`simple_returns` (`crucible.analytics.metrics`) accept
  `VectorizedResult.equity` unchanged (same `ts`/`equity` shape as the
  event-driven `equity.parquet`) — the "same metrics module" half of the original requirements's Phase 6 description is satisfied now, without needing to wait for
  the experiments-layer glue.
