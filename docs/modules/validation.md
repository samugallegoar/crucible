# Module: validation

## What exists

Gate 4 statistics. Detail sections follow.

- `splits.py` — `WalkForwardSplitter`, `PurgedKFoldSplitter`, `CombinatorialPurgedCVSplitter`;
  `config.py` / `registry.py` — their configs and `build_splitter`.
- `trial_registry.py` — `DuckDBTrialRegistry`, `TrialRecord`. `dsr.py` — `deflated_sharpe_ratio`,
  `per_period_sharpe`. `pbo.py` — `probability_of_backtest_overfitting`.
- `sensitivity.py` — `sensitivity_surface_1d`, `sensitivity_surface_2d`.
- `monte_carlo.py` — `ReturnOrderShuffleTest`, `StartDateShiftTest`, `BlockBootstrapTest`.
- `null_tests.py` — `compare_to_null` (Monte Carlo), `compare_to_single_null`; `factor_regression.py` — `factor_regression`;
  `contamination.py` — `check_contamination`.
- `interfaces.py` — `Split` and the Protocols `Splitter`, `TrialRegistry`, `ResamplingTest`.

## Responsibility
Gate 4: walk-forward, purged/embargoed CV, CPCV, trial registry,
DSR/PBO, sensitivity surfaces, Monte Carlo, null tests, factor regression,
bootstrap CIs, contamination flagging.

## Interfaces (`crucible/validation/interfaces.py`)
- `Split(train, test, validate=())` — half-open `[start, end)` index range
  tuples; `train`/`test` may each hold more than one disjoint range (purged
  K-fold/CPCV place the test fold mid-timeline); `validate` is populated
  only by `WalkForwardSplitter` (three-way windows).
- `Splitter.splits(n_samples)` — deterministic generation; no RNG.
- `TrialRegistry.record_trial/trial_count` — per-family counting, ADR-0008.
  Implemented by `DuckDBTrialRegistry` (`trial_registry.py`).
- `ResamplingTest.run(returns, rng, n_iterations)` — named distribution
  statistics. Implemented by three classes in `monte_carlo.py`.

## Implementations (`crucible/validation/splits.py`)
- `WalkForwardSplitter(train_size, test_size, anchored, validate_size=0, purge=0)` —
  anchored (expanding) or rolling (fixed-width) train window; advance
  between folds is fixed at `test_size` (non-overlapping OOS coverage).
  `purge` drops that many samples from the end of the train (and validate)
  window: set it to the label horizon, or a forward-looking label leaks the
  next window into training (ADR-0070; `test_unpurged_forward_labels_manufacture_an_edge_on_pure_noise`
  shows an unpurged 20-bar label giving a correlation above 0.6 on pure noise).
- `PurgedKFoldSplitter(n_splits, purge=0, embargo=0)` and
  `CombinatorialPurgedCVSplitter(n_groups, n_test_groups, purge=0,
  embargo=0)` share group-partition and purge/embargo arithmetic — plain
  K-fold is CPCV with one test group per split. `purge` trims train at
  both edges of a test boundary (label-overlap leakage); `embargo` trims
  an additional, one-directional amount only at the start of a train
  group immediately following a test group (serial-correlation leakage,
  `docs/GLOSSARY.md`). Convention pinned in ADR-0013.
- All three raise `ConfigurationError` for invalid parameters or for any
  configuration that would yield zero splits or an empty-train fold
  (pessimism rule — a silent 0-fold validation run is worse than a loud
  refusal).
- `_assert_disjoint` runs before every yielded `Split` (I11,
  `docs/INVARIANTS.md`): train/validate/test are pairwise disjoint,
  enforced at runtime, not only by property test.

## Implementations (`crucible/validation/trial_registry.py`)
- `DuckDBTrialRegistry(path)` — one DuckDB file per artifact store
  (`<artifacts_root>/trial_registry.duckdb`), table
  `trials(family, experiment_id, sharpe, mode, start_ns, end_ns)` with
  `PRIMARY KEY (family, experiment_id)`. `record_trial` upserts with
  `ON CONFLICT DO NOTHING`: recording the same `experiment_id` twice
  under the same family does not double-count (it's a re-run of the same
  evaluation, not a new one). Storage choice, idempotency, and
  scenario-fan-out scoping (only the base run of `run_with_scenarios`
  counts — the variants are a robustness check, not a parameter search)
  pinned in ADR-0014.
- Wired into `experiments/runner.py::run_experiment`: `manifest.json`'s
  `trial_count` and the report header's `trial_count` cell carry the
  registry's real, persistent count. `record_trial`'s optional `sharpe`
  (per-period, ADR-0015) is also persisted for DSR; `mode`/`start_ns`/
  `end_ns` (also optional) are persisted for contamination flagging
  (ADR-0021). A run executed with `record_trial=False` never inserts a
  row, so it never contributes to any of these.
- `overlapping_optimization_trials(family, start_ns, end_ns) ->
  Sequence[str]` — `experiment_id`s of every `mode="optimization"` trial
  in `family` whose recorded window overlaps the query window (half-open
  interval overlap, raw date range, no purge/embargo adjustment — the
  conservative default, ADR-0021). Feeds `contamination.py` below.
- `all_trials(family) -> list[TrialRecord]` (ADR-0038)
  — every recorded trial, ordered by `experiment_id` (DuckDB gives no
  ordering guarantee without an explicit `ORDER BY`). The result-registry
  query surface; `crucible compare FAMILY` is its
  only caller today, sorting by Sharpe and joining in each trial's DSR
  from its own `manifest.json` when still on disk.
- **Multiprocessing note (ADR-0038)**: DuckDB allows only one process to
  hold `trial_registry.duckdb` at a time (fails fast otherwise). This
  registry is therefore only ever touched from `experiments/
  runner.py::_finalize_experiment`, which `run_experiment_parallel` calls
  serially in the parent process — worker processes never construct a
  `DuckDBTrialRegistry` at all.

## Implementations (`crucible/validation/dsr.py`, `pbo.py`)
- `deflated_sharpe_ratio(returns, trial_sharpes) -> DsrResult` — PSR
  (Bailey & López de Prado 2012) evaluated against the expected-max-Sharpe
  benchmark a family's trial count would produce by chance (2014 paper);
  operates entirely on per-period figures, never annualized. `trial_sharpes`
  comes from `TrialRegistry.trial_sharpes(family)`. `N<=1` -> benchmark
  0.0 (no deflation without a search to deflate against); a non-positive
  PSR denominator raises `CrucibleError` rather than returning a bad
  number, and so do non-finite returns and a zero-variance series (its
  Sharpe ratio is undefined; ADR-0070 replaced the earlier "Sharpe 0,
  DSR = PSR(0)" convention). `N` is the raw count of recorded trials in
  the family, not an effective number of independent trials, and the PSR
  variance assumes i.i.d. returns; DSR is not the probability that the
  strategy is profitable. Wired into `run_experiment`: `manifest.json`'s `dsr`/
  `dsr_benchmark_sharpe`/`dsr_error` and the report's statistical-validity
  block carry the real value (or an explicit "not computable" reason).
  Convention and formula choices pinned in ADR-0015.
- `probability_of_backtest_overfitting(returns, splitter) -> PboResult` —
  CSCV (Bailey, Borwein, López de Prado & Zhu 2015), implemented by
  reusing `CombinatorialPurgedCVSplitter` configured symmetrically
  (`n_test_groups == n_groups // 2`, purge=embargo=0) rather than a
  separate splitter class. Rank convention (ADR-0070): out-of-sample rank
  1 = worst, a split is overfit when `2 * rank <= N + 1` (logit <= 0,
  computed on the integer rank, so no logarithm and no infinite logit).
  Ties are resolved by expectation under uniform random tie-breaking, both
  among in-sample co-winners and in the out-of-sample ranking, so a panel
  of identical trials scores about 0.5, not 1.0; `n_tied_splits` counts the
  splits that depended on a tie. Refuses NaN/infinite returns, a partition
  shorter than two observations, and a constant non-zero row (undefined
  Sharpe); a flat all-zero row scores Sharpe 0. Selection uses only each
  split's in-sample columns. Tested against an exhaustive
  tie-break-enumeration reference (`tests/unit/test_pbo.py`).
  **Not wired into `run_experiment`**: PBO needs
  a trials × periods returns panel, which a single run doesn't have — see
  Known gaps and ADR-0015.

## Implementations (`crucible/validation/sensitivity.py`)
- `sensitivity_surface_1d(param_values, metric_values, chosen_index) ->
  SensitivitySurface1D` / `sensitivity_surface_2d(...)` — the "plateau vs
  spike" diagnostic: the relative drop from the chosen
  point's metric to the average of its immediate neighbors (2 in 1D, 4
  grid-adjacent in 2D). `> spike_threshold` (default `0.25`, a pragmatic,
  not literature-derived default) classifies `"spike"`, else `"plateau"`.
  Requires evenly-spaced, bracketing sweep points. Orchestration —
  `experiments/sensitivity.py::sweep_1d` — drives real `run_experiment`
  calls across a strategy parameter's values and **does** record every
  swept point as a trial, unlike scenario fan-out (contrast with
  ADR-0014's opposite call; both pinned in ADR-0016).

## Implementations (`crucible/validation/monte_carlo.py`)
- `ReturnOrderShuffleTest` / `StartDateShiftTest` / `BlockBootstrapTest` —
  `ResamplingTest`s for the trade-reshuffle/start-shift/block-bootstrap
  trio, interpreted at the return-series level (no access to
  trades/dates from the Protocol's signature — ADR-0017). Shuffle and
  shift are both permutations of the same returns, so per-period Sharpe
  is mathematically identical across their iterations
  (`sharpe_invariant_to_permutation`, a single value, not a distribution)
  while drawdown genuinely varies (`p_drawdown_worse_than_threshold`,
  `median_max_drawdown`, `worst_max_drawdown`). Block bootstrap resamples
  with replacement, so both drawdown and Sharpe (`median_sharpe`,
  `p_sharpe_lt_0`) are real distributions. Wired into `run_experiment`
  (1,000 iterations each, `analytics.metrics.N_BOOTSTRAP`'s convention):
  `manifest.json["monte_carlo"]` and a new report section. Execution/
  parameter perturbation Monte Carlo needed re-simulation, so it lives in
  `experiments/perturbation.py` instead (ADR-0018) — not auto-wired into
  every report the way this trio is, since it needs the caller to choose
  which field to perturb.

## Implementations (`crucible/validation/null_tests.py`)
- `compare_to_null(real_value, null_values) -> NullTestResult` — pure
  statistics, no engine access: a one-sided Monte Carlo test with
  `p_value = (k + 1) / (B + 1)`, `k` the valid null values `>=` the real
  one (ties count against the strategy), `B` the valid (non-NaN) null
  values; it is never 0, and `n_exceedances`, `n_valid`, `n_invalid` and
  `monte_carlo_se = sqrt(p (1 - p) / B)` are reported with it (ADR-0070;
  the earlier `mean(null >= real)` reported 0 on zero exceedances).
  Calibrated: under exchangeability `P(p <= 0.05) = 0.05` exactly for
  `B = 19` (checked over 4,000 replications in `tests/unit/test_null_tests.py`).
  `compare_to_single_null(real_value, null_value)` is the sign-flip's
  single deterministic comparison: `p_value` is `None` (one value is not a
  distribution), `null_matched_or_beat_real` says which side it fell.
  Refuses an empty or all-NaN `null_values` and a non-finite real value
  (`ConfigurationError`). Neither corrects for multiple testing. The re-simulation
  that produces `null_values` — reading real bars, transforming them,
  re-running `run_experiment` against the transformed data — lives in
  `experiments/null_tests.py`, one layer up (this module never runs the
  engine, matching the `experiments` → `validation` dependency direction).

## Implementations (`crucible/validation/factor_regression.py`)
- `factor_regression(returns, factors) -> FactorRegressionResult` — OLS of
  per-period returns on an explicit `factors: Mapping[str, Sequence[float]]`
  of already-aligned factor return series. Returns
  `alpha`/`alpha_t_stat` (per-period, no p-value — no t-distribution CDF
  without a new dependency), `loadings` (per-factor beta), `r_squared`,
  `n_obs`. Refuses (`ConfigurationError`) an empty factor mapping,
  mismatched-length factor series, too few observations, or a singular
  design matrix; refuses (`CrucibleError`) a numerically perfect/degenerate
  fit via a relative residual-variance tolerance (an exact-zero check is
  unreachable in float64 — ADR-0020). Factor files are supplied on the command line (`crucible validate --factors`, ADR-0020/0022); the
  module itself is pure statistics and reads no files.

## Implementations (`crucible/validation/contamination.py`)
- `check_contamination(family, mode, start_ns, end_ns, registry) ->
  ContaminationResult` (`contaminated`, `overlapping_trials`, `reason`) —
  Only an `evaluation`-mode run can be flagged; an
  `optimization` run is never contaminated regardless of overlap.
  `reason` is always a populated string, contaminated or not (explicit "why", never a bare flag).
  Wired into `run_experiment`: `manifest.json`'s `contamination` / `contamination_reason` /
  `contamination_overlapping_trials` and the report header's `contamination_flags` cell carry the
  result (ADR-0021).

## Config (`crucible/validation/config.py`, `registry.py`)
- `WalkForwardConfig` / `PurgedKFoldConfig` / `CombinatorialPurgedCVConfig`
  — discriminated union `SplitterConfig`; `build_splitter(config)` in
  `registry.py` dispatches to the matching class.
- **Known gap**: unlike `execution/`, these config models live inside `validation/` itself rather
  than in `experiments/config.py`'s discriminated union, because nothing in the `experiments` layer
  consumes them (the `validate` command takes a factor file, not a splitter).

## Extension points
New resampling/null tests implement `ResamplingTest`; new split schemes
implement `Splitter`. All stochastic components take an explicit
`numpy.random.Generator` (none of the three splitters are stochastic).

## Known gaps
- Factor regression is available through `crucible validate --factors`; it is not part of the default
  run report.
- `overlapping_optimization_trials` is a raw date-range overlap check; it
  doesn't know about a splitter's purge/embargo windows, so it can flag
  (or fail to distinguish the severity of) an overlap a purge convention
  would have already partially mitigated — deliberately the stricter,
  conservative default (ADR-0021), not an oversight.
- Null tests cover shuffled/sign-flipped/synthetic-GBM data
  only (ADR-0019; the intraday-only and overnight-only shuffles of
  ADR-0070 exist as transforms in `data.transforms` but are not wired into
  an orchestration function or the CLI); "time-shifted signals" (a fourth variant) needs
  strategy-level signal-delay machinery, not a data transform, and is
  not implemented.
- `experiments.null_tests`'s temp data stores
  (`<artifacts_root>/_null_test_stores/`) aren't cleaned up after the
  test — one directory per null-test iteration, alongside `sweep_1d`'s and
  perturbation's "full artifacts per run" disk cost.
- `experiments.perturbation.perturb_execution` only perturbs scalar
  shorthand execution fields (`slippage_bps`-style); model-slot fields
  (spread/latency/participation) aren't supported (ADR-0018).
- `sweep_1d` writes full artifacts for every swept run (like scenario
  fan-out); a wide sweep is proportionally disk/time-heavy.
- No command exposes sensitivity sweeps directly; `crucible optimize` is the 1-D sweep.
- PBO needs a multi-trial returns panel, so it is reported by `crucible optimize` (ADR-0015, ADR-0022)
  and not for a single run.
- Splitters are calendar-agnostic (`n_samples` is an abstract index count,
  not calendar time) by design; mapping years to bar counts is the caller's job.
- `CombinatorialPurgedCVSplitter` doesn't expose which groups were chosen
  as test per split beyond the raw index ranges. Group membership is cheaply re-derivable (group
  boundaries are a deterministic function of `n_samples`/`n_groups`) but is not first-class metadata.
- Acceptance: a known-overfit strategy shows PBO > 0.5 and DSR ≈ 0, while a genuine synthetic edge
  survives (`tests/integration/test_phase3_acceptance.py`).
- PBO's tie rule makes a degenerate panel (every split tied) report the probability of a random
  pick (about 0.5), which describes the selection procedure, not the strategies; read it with
  `n_tied_splits`. The CLI JSON carries it.
- DSR's `N` is the number of trials recorded in the family; the registry cannot know about trials
  run elsewhere, so the correction is a lower bound on the true search (the one-step result says
  so in `validation.trial_count_scope`, ADR-0070). No effective-independent-trials estimate.
