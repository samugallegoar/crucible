# ADR-0018: Perturbation Monte Carlo, and why it splits ADR-0014/0016's rule

- **Status**: accepted
- **Date**: 2026-09-18

## Context

R4.5's other half — "execution perturbation (slippage/latency/liquidity),
parameter perturbation" — needs re-simulation: randomly draw a perturbed
execution assumption or strategy parameter, re-run `run_experiment`, and
report the resulting distribution (ADR-0017 already deferred this out of
the return-only `ResamplingTest` scope). Building the orchestrator raises
the same trial-counting question ADR-0014 (scenario fan-out) and
ADR-0016 (sensitivity sweeps) already answered — but this time in
**opposite directions for its own two halves**, which is the reason this
gets its own ADR rather than a one-line extension of either.

## Decision

**Execution perturbation does not count as trials — same reasoning as
ADR-0014.** Randomly perturbing `slippage_bps`/`commission_bps` (etc.)
within a range and re-running is mechanically scenario fan-out with a
random draw instead of four named points (optimistic/base/conservative/
extreme). It varies an execution assumption, not a parameter of the
strategy's alpha, so it is not ADR-0008's "parameter evaluation" — it is
the same cost-sensitivity re-examination of one already-chosen trial.
`perturb_execution` calls `run_experiment(..., record_trial=False)`.

**Parameter perturbation DOES count as trials — same reasoning as
ADR-0016.** Randomly perturbing a strategy parameter and re-running is
mechanically a sensitivity sweep with a random draw instead of an evenly-
spaced grid. It is a genuine parameter search; undercounting it would let
"Monte Carlo" quietly launder the exact search DSR's trial count exists
to catch. `perturb_strategy_param` calls `run_experiment` with its
default `record_trial=True`.

Both orchestrators (`crucible/experiments/perturbation.py`) share one
internal `_perturb_and_collect` loop — draw `n_iterations` uniform values
in `[low, high]`, derive a config per value, call `run_experiment`, and
aggregate each run's own already-computed `metrics["max_drawdown"]` and
the target `metric` (default `"sharpe"`) into the same
`p_drawdown_worse_than_threshold` / `median_*` / `p_*_lt_0` shape the
return-only Monte Carlo tests (ADR-0017) use — only the `record_trial`
flag passed through to `run_experiment`, and which config field the
derive callback touches, differ between the two.

Drawdown here comes from each perturbed run's own real, re-simulated
equity curve (`RunArtifacts.metrics["max_drawdown"]`), not reconstructed
from a returns array the way ADR-0017's resampling tests had to — a real
simulation already computed the real thing, so there's no reason to
approximate it.

**Not auto-wired into every `run_experiment` call.** Unlike DSR, trial
count, and the three resampling Monte Carlo tests — all computable from
data every run already has — perturbation needs the caller to say *which*
field to perturb and over *what range*. There is no sensible default to
assume automatically, so (like `sweep_1d` and PBO) this is a library
function for manual use or the future `optimize`/`validate` CLI
(priority 9), not part of the automatic per-run report.

## Alternatives considered

- **One answer for all of R4.5's perturbation half** (either "always
  counts" or "never counts"): rejected — the two halves are mechanically
  identical to two *already-answered* questions with *different* answers
  (ADR-0014 vs ADR-0016); forcing one answer onto both would silently
  contradict whichever precedent it disagrees with, for no reason other
  than they share a the original requirements bullet.
- **A single `perturb()` function parameterized by a config-field path
  covering both execution and strategy params**: rejected — the
  `record_trial` answer depends on *which kind* of field is being
  perturbed, so collapsing the distinction into one call signature would
  require the caller to separately supply the trial-counting answer
  anyway, defeating the point of encoding the ADR-0014/0016 reasoning in
  code rather than leaving it to every call site to get right.
- **Perturb execution model-slot fields (spread/latency/participation),
  not just the `slippage_bps`/`commission_bps` shorthand**: deferred, not
  rejected — the shorthand fields cover the Level 0/1 examples this
  session's tests use; model-slot perturbation is a real gap (see Known
  gaps) for Level 2-4 configs, not implemented this pass.

## Consequences

`crucible/experiments/perturbation.py` reuses `sensitivity.py`'s
`_cast_like`/`_derived_param_config` for the parameter-perturbation path
(both are internal to `crucible.experiments`, sharing the same "cast a
perturbed float back to the field's original numeric type" need).
Execution perturbation is currently limited to the shorthand
`slippage_bps`/`commission_bps` fields — perturbing a model-slot field
(e.g. `execution.spread.base_bps`) is a known gap, not yet supported.
