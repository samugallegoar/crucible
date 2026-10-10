# ADR-0022: `optimize`/`validate` CLI shape

- **Status**: accepted
- **Date**: 2026-09-18

## Context

Phase 3's last priority (the original requirements priority 9, E5's `optimize`/`validate`
verbs) is the one place several already-implemented-but-unreachable
pieces finally get real input:

- PBO (`validation.pbo.probability_of_backtest_overfitting`, ADR-0015)
  has existed since priority 3 but needs a trials × periods returns
  panel no single run has ever assembled.
- Factor regression (`validation.factor_regression.factor_regression`,
  ADR-0020) has existed since priority 7 but needs user-supplied factor
  return series no config field has ever carried.

The original requirements's config schema is explicitly "illustrative" and describes a
`validation:` config block (`walk_forward`, `monte_carlo`, `null_tests`,
`factors`) that doesn't remotely match `ExperimentConfig`'s real,
already-built shape. Implementing that aspirational schema literally
would mean inventing a large YAML-driven sweep/validation DSL with no
existing convention to anchor it. This ADR instead builds the smallest
real, tested surface that actually closes priorities 9's two open debts
(PBO's panel, factor regression's data), using patterns already
established this phase (`sweep_1d`, `perturb_strategy_param`).

## Decision

**`crucible optimize CONFIG --param NAME --values "v1,v2,..." [--metric
sharpe] [--pbo-groups N]`** (`crucible/experiments/optimize.py::
optimize_1d`): runs `run_experiment` once per value (reusing
`experiments.sensitivity._derived_param_config`, the same internal-reuse
precedent `perturbation.py` already established for `_cast_like`/
`_derived_param_config`), every point counted as a trial exactly like
`sweep_1d` (ADR-0016's reasoning: a parameter search). After every run,
reads each trial's own return series back from its `equity.parquet`
(same `analytics.metrics.simple_returns` convention used everywhere else
this phase) and stacks them into the panel PBO needs, split via
`CombinatorialPurgedCVSplitter(n_groups=pbo_groups, n_test_groups=
pbo_groups // 2)` (CSCV's own symmetric convention, ADR-0015).

**`optimize` refuses a config whose `experiment.mode` isn't already
`optimization`** (`ConfigurationError`), rather than silently forcing it.
The config is this codebase's single source of truth for what a run
means everywhere else (frozen, hashed, `extra="forbid"`); a CLI verb that
quietly overrode `mode` would make the same YAML mean different things
depending which command ran it, and forces someone re-deriving a
manifest's provenance to check *which command* wrote it, not just what
it says.

**`crucible validate CONFIG [--factors PATH.csv]`**
(`crucible/experiments/validate.py::validate_run`): DSR, Monte Carlo, and
contamination flagging are already unconditional in `run_experiment`
itself (priorities 3, 5, 8) — `validate` adds exactly the one thing that
needed external input: if `--factors` is given, it regresses the run's
own returns on the supplied factor series and merges the result into the
run's `manifest.json` and re-renders its report. `validate` does not
restrict `experiment.mode` — factor regression is meaningful regardless
of whether the run is being searched over or evaluated once.

**Factor CSV convention**: one column per factor (header names the
factor), one row per period, **row-aligned to the run's own return
series** — no date column, no reindexing. This is the simplest shape that
needs no date-parsing/calendar-alignment machinery; `factor_regression`
already refuses (`ConfigurationError`) a length mismatch, so a
misaligned file fails loudly rather than silently regressing against the
wrong periods.

**`rebuild_report(out_dir, *, factor_regression=None)`** moved from
`_cmd_report`'s inline body into `experiments/runner.py` as a shared
function. Both `crucible report` (re-rendering an existing run
unmodified) and `validate_run` (re-rendering after merging in a factor
regression) need the identical "load manifest/metrics/equity/trades,
rebuild the header, re-render" sequence; duplicating it a second time for
`validate_run` was the trigger to extract it once both callers existed
(CLAUDE.md: prefer editing/reusing over duplicating once a second call
site appears).

**`render_report`/`ReportRenderer.render` gain an optional
`factor_regression: Mapping[str, object] | None` parameter**, following
`monte_carlo`'s existing precedent (ADR-0017): optional, plain-data
(never importing `validation` types into `analytics`, keeping the original requirements
§4.1 layering `analytics` sits below `validation`/`experiments`), so a
report without one still renders and says so explicitly rather than
silently omitting the section.

**`DEFAULT_PBO_GROUPS = 6`** (even, satisfies CSCV's symmetric-split
requirement `n_test_groups = n_groups // 2`): a pragmatic, not
literature-derived default — same status as `spike_threshold`/
`N_MONTE_CARLO_ITERATIONS` elsewhere in this codebase. Literature (Bailey
et al. 2015) commonly uses larger group counts (10-16) for CSCV on
larger panels; 6 is chosen as a safe default for the momentum example's
~500-period panel and small trial counts this phase's tests use, not a
general recommendation.

**`optimize_1d` requires every trial's return series to have identical
length** (`ConfigurationError` otherwise) — a purely defensive check:
since only a strategy parameter varies (not the date range or calendar),
every trial's equity curve should already have identical length; this is
belt-and-suspenders pessimism (AGENTS.md §10), not a case observed to
actually occur.

## Alternatives considered

- **Implement the original requirements's full illustrative `validation:` config block**
  (`walk_forward`, `monte_carlo`, `null_tests`, `factors` as YAML,
  driving `optimize`/`validate` from config alone, no CLI flags):
  rejected as premature — it would require a new n-dimensional sweep
  specification, a new discriminated union for "which null tests to
  run," and a factor-file *reference* mechanism (path in YAML, resolved
  relative to the config) before any of them have a second real use case
  to generalize from. The CLI-flag surface built here is the concrete
  instance; promoting it into config is deferred until a second sweep
  shape (e.g. 2D) actually needs it.
- **Let `optimize` silently set `experiment.mode = optimization`** on
  whatever config it's given: rejected (see Decision) — breaks the
  config-is-truth invariant this codebase relies on everywhere else.
- **Store factor files as a path in `ExperimentConfig`** rather than a
  `--factors` CLI flag: rejected for now — `ExperimentConfig` is
  frozen/hashed, and a factor file's own content isn't yet tracked by a
  manifest hash the way datasets are (`DatasetManifest`); wiring that
  properly is a bigger change than this ADR's scope, and would need its
  own hash-provenance story to avoid a silent gap in `experiment_id`'s
  reproducibility guarantee.
- **Have `optimize_1d` write its own panel report artifact** (e.g. a
  `<family>_pbo_panel.json` file under `artifacts_root`): deferred, not
  rejected — `OptimizeResult` is returned to the caller (library function
  and CLI both print it) but nothing persists it yet. Flagged as a known
  gap; add if a future session needs to re-inspect a past optimize run's
  panel without re-running it.

## Consequences

Phase 3's the original requirements acceptance criteria (known-overfit strategy → PBO > 0.5,
DSR ≈ 0; genuine edge survives) are now reachable in principle — `crucible
optimize` on a large-enough parameter grid with a genuinely overfit
strategy is the first real path to a multi-trial panel this codebase has
had. Acceptance itself (priority 10) still needs a purpose-built
known-overfit example strategy, not built by this ADR. `OptimizeResult`'s
panel isn't persisted to disk (see Alternatives). `optimize`'s sweep is
1D only, matching `sweep_1d`'s own scope — a 2D sweep (mirroring
`sensitivity_surface_2d`) is a natural but unbuilt extension.
