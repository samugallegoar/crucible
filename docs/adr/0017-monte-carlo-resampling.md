# ADR-0017: Monte Carlo resampling scope, and the shuffle/shift invariant

- **Status**: accepted
- **Date**: 2026-09-18

## Context

The original requirements group five techniques under one "Monte Carlo" bullet:
"trade-order reshuffle, start-date shift, block/stationary bootstrap of
returns, execution perturbation (slippage/latency/liquidity), parameter
perturbation." §9 lists "Monte Carlo distributions" as report-body
content. The existing `ResamplingTest` Protocol (`validation/interfaces.py`,
written in an earlier phase) takes only a `returns: Sequence[float]`
array — no way to re-run the engine. Three of the original requirements' five techniques fit
that signature; two structurally don't, the same split priority 4
(sensitivity surfaces, ADR-0016) already hit between "resample existing
output" and "re-simulate with different inputs."

## Decision

**Scope this pass to the three return-only techniques**: return-order
shuffle, start-date shift, block bootstrap — implemented as
`ResamplingTest`s in `crucible/validation/monte_carlo.py`, matching the
Protocol's existing signature exactly. "Execution perturbation" and
"parameter perturbation" need to re-run `run_experiment` with randomly
perturbed configs (structurally identical to `sensitivity.sweep_1d`, but
sampling randomly rather than a fixed grid) — a distinct, comparably-sized
piece of design and implementation work, not started here (see Known gaps
below and `docs/modules/validation.md`).

**"Trade-order reshuffle" and "start-date shift" are interpreted at the
return-series level, not the literal trade/calendar level.** The
Protocol's signature is the reason: `run(returns, rng, n_iterations)` has
no access to the trade log or the underlying price data, only an already-
computed return series. So:
- *Return-order shuffle* permutes the per-period return series' order
  (not individual trades' P&L sequencing specifically) — `ReturnOrderShuffleTest`.
- *Start-date shift* circularly rotates the already-computed return
  series to a random start point, rather than re-simulating from a
  different actual calendar date — `StartDateShiftTest`.

Both remain legitimate, standard resampling techniques answering a
closely related question ("how much does the specific sequencing/framing
of this exact history drive the headline numbers?") — just not the most
literal reading of the original requirements' phrasing, which this ADR makes explicit
rather than leaving as a silent reinterpretation.

**A provable invariant shapes both tests' output.** Both operate by
*permuting* the same fixed multiset of returns (a full shuffle and a
cyclic rotation are both permutations). Sample mean and variance don't
depend on order, so per-period Sharpe is mathematically identical across
every iteration of either test — only the drawdown *path* varies, because
drawdown genuinely is order-dependent. Each test's output therefore
reports a single `sharpe_invariant_to_permutation` value (not a
median/distribution, which would misleadingly imply variation that
cannot occur) alongside genuine drawdown distribution statistics
(`p_drawdown_worse_than_threshold`, `median_max_drawdown`,
`worst_max_drawdown`). `BlockBootstrapTest` resamples *with replacement*
— composition genuinely changes between iterations — so it reports real
distributions for both drawdown and Sharpe (`median_sharpe`,
`p_sharpe_lt_0`).

**Wired into every report, like DSR.** `run_experiment` runs all three
tests (1,000 iterations each, matching `analytics.metrics.N_BOOTSTRAP`'s
existing convention) using the same seeded `rng` stream `compute_metrics`
already advances — deterministic given the run's seed, no separate
generator. Results land in `manifest.json["monte_carlo"]` and a new report
section, matching the original requirements's "Monte Carlo distributions" body content.
`render_report`'s new `monte_carlo` parameter is optional (unlike the
mandatory `validation_summary`) so `_cmd_report` re-rendering an
older manifest without this field degrades to "not computed for this
run" instead of erroring.

## Alternatives considered

- **Extend the `ResamplingTest` Protocol to accept trades/dates** so
  "trade-order reshuffle" and "start-date shift" could be implemented
  literally: rejected for this pass — a real interface change to an
  already-shipped Protocol, and the return-series interpretation already
  answers a closely related question without one. Revisit if the
  return-level version proves insufficient once real usage exists.
- **Implement execution/parameter perturbation now too**: rejected — see
  Decision; distinct, re-simulation-based work deserving its own design
  pass (mirroring `sweep_1d`'s scope from ADR-0016), not folded in here
  just because the original requirements list them in the same bullet.
- **Report shuffle/shift Sharpe as a degenerate one-point "distribution"**
  (median == the single value, CI == a point): rejected — naming it
  `sharpe_invariant_to_permutation` instead of `median_sharpe` tells the
  reader directly that no variation is possible here, rather than
  implying a distribution was computed when it wasn't.

## Consequences

Every run now performs 3,000 additional resampling iterations
(3 tests × 1,000) using already-computed returns — measured impact on
the momentum example's integration test suite: a few seconds, not
minutes. `N_MONTE_CARLO_ITERATIONS` is a module-level constant in
`runner.py`, not yet config-exposed (same precedent as
`analytics.metrics.N_BOOTSTRAP`). Execution/parameter perturbation Monte
Carlo remains a known gap until its own design pass.
