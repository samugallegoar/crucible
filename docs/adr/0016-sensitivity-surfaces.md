# ADR-0016: Sensitivity surface diagnostic and trial-counting for sweeps

- **Status**: accepted
- **Date**: 2026-09-18

## Context

The original requirements ask for "1D/2D sweeps around chosen params with plateau-vs-spike
diagnostics" (R4.4) with no formula specified — "plateau vs. spike" is a
description of an intent, not a named statistic from the literature the
way DSR/PBO are. Separately, sweeping a strategy parameter necessarily
runs the strategy multiple times with different parameter values through
`run_experiment`, the same entry point ordinary runs and scenario fan-out
use — and ADR-0014 already had to decide, for scenario fan-out, whether
its repeated `run_experiment` calls count as trials. A sweep raises the
same question with a different answer.

## Decision

**The diagnostic is a relative drop-ratio, not a curvature formula.**
`crucible/validation/sensitivity.py` computes, at the chosen parameter
value, the average metric of its immediate neighbors in the sweep (two
in 1D, four grid-adjacent in 2D — no diagonals), then:

```
drop_ratio = (chosen_metric - neighbor_avg) / abs(chosen_metric)
```

classified `"spike"` if `drop_ratio > spike_threshold` (default `0.25`)
else `"plateau"`. This is mathematically a monotonic transform of the
discrete second derivative (central-difference curvature) at the chosen
point, but stated directly in "how much performance is lost by picking a
neighboring value instead" rather than as a normalized curvature — easier
to explain to the person reading the report, and it doesn't need a step-size
normalization since it's already a ratio. `spike_threshold` is an
explicitly pragmatic default: the original requirements name no target value, and none of the
Bailey/López de Prado papers this codebase otherwise follows define one
either — it needs tuning against known-good and known-overfit examples
once Phase 3's acceptance harness (priority 10) exists, not treated as a
calibrated constant today.

Sweep points must be evenly spaced and the chosen value's neighbors must
exist on every side (validated, `ConfigurationError` otherwise) — the
diagnostic is specifically about the immediate neighborhood of the chosen
point, so a sweep that doesn't bracket it can't answer the question.

**Sweep points ARE recorded as trials — the opposite of ADR-0014's call
for scenario fan-out.** `crucible/experiments/sensitivity.py::sweep_1d`
calls `run_experiment` with its default `record_trial=True` for every
swept value. The distinguishing test from ADR-0014 still applies, it just
comes out the other way: scenario fan-out varies *execution assumptions*
(not a parameter of the strategy's alpha) to measure cost sensitivity on
one already-chosen trial; a sensitivity sweep varies the *strategy
parameter itself* — exactly ADR-0008's "parameter evaluation." Trying five
lookback values and reporting the best-looking one is precisely the kind
of search DSR's trial count exists to catch; undercounting it here would
let a sensitivity sweep quietly launder a parameter search as a
"diagnostic."

## Alternatives considered

- **Discrete-Laplacian curvature normalized by step size**: rejected as
  the primary output — mathematically fine, but harder to explain and no
  more informative than the ratio form once you're already dividing by
  `abs(chosen_metric)`; the ratio form was chosen for legibility.
- **Don't count sweep points as trials** (treat sensitivity analysis as
  "just a diagnostic," mirroring scenario fan-out): rejected — see
  Decision. This would be the *less* conservative choice (fewer counted
  trials, less DSR deflation) for something that is, mechanically, a
  parameter search; AGENTS.md §1.4 favors the reading that costs more.
- **A single combined 1D/N-D implementation**: rejected — the original requirements ask for
  1D/2D specifically; a fully general N-dimensional sweep is complexity
  with no requested consumer yet (YAGNI).

## Consequences

A `spike_threshold` that later proves miscalibrated is a one-line default
change, not a rearchitecture — every caller can already override it.
`sweep_1d` writes full artifacts for every swept run (same as scenario
fan-out); a wide sweep is proportionally disk- and time-heavy, not yet
addressed (tracked as a known gap alongside scenario fan-out's same
property). No CLI command exposes sweeps yet — that arrives with priority
9's `optimize`/`validate` CLI, same as PBO's still-unwired state.
