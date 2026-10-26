# Module: experiments

## What exists

Reproducibility: configs, the runner, artifacts and the research orchestrators. Detail sections follow.

- `config.py` — the frozen pydantic `ExperimentConfig` tree, `load_config`, `config_hash`,
  `canonical_yaml` (fields in `docs/SCHEMAS.md`).
- `runner.py` — `run_experiment`, `run_experiment_parallel`, `run_with_scenarios`, `rebuild_report`,
  `assemble_engine`, `experiment_id`, `RunArtifacts`.
- `artifacts.py` — the artifact schemas (`LEDGER_SCHEMA`, `ORDER_SCHEMA`, `FILL_SCHEMA`,
  `EQUITY_SCHEMA`), `MANIFEST_FIELDS`, `SCHEMA_VERSION`, and the reader `load_experiment` /
  `compare_metrics` (`docs/USAGE.md`).
- `vectorized_runner.py` — `run_vectorized_experiment`, `run_vectorized_experiment_parallel`; `promotion.py` — `promote_config`,
  `PromotedSignalStrategy`.
- `optimize.py` (`optimize_1d`), `sensitivity.py` (`sweep_1d`), `perturbation.py`
  (`perturb_execution`, `perturb_strategy_param`), `null_tests.py` (`null_test_shuffle`,
  `null_test_sign_flip`, `null_test_synthetic_gbm`), `validate.py` (`validate_run`,
  `load_factors_csv`).
- `interfaces.py` — the Protocols `ArtifactStore` and `RunRegistry`, both stubs (see Known gaps).

## Responsibility
Reproducibility: frozen hashed configs, the runner, the filesystem artifact
store. An experiment = config hash + code commit (+ dirty) + data manifest
hashes + seed + env lock hash + realism level + trial family. Identical
inputs ⇒ identical experiment id ⇒ byte-identical artifacts (golden-tested).

## Implementations
- `config.py`: frozen Pydantic tree (`ExperimentConfig` = experiment header
  + data + strategy + execution + cash/window), all `extra="forbid"`;
  `load_config` (YAML), `config_hash` (canonical JSON SHA-256),
  `canonical_yaml` (deterministic artifact rendering). Dates are ISO
  strings; datetimes must carry a timezone. `DataConfig.futures_margins`
  (per-symbol `initial`/`maintenance` futures margin; each symbol needs a
  `futures_multipliers` entry; wired into `FuturesSpec`, ADR-0050).
  `DataConfig.symbol_currency`
  (per-symbol trading currency; unlisted symbols default to
  `base_currency`) and `fx_rates` (FX rate dataset id),
  ADR-0025 — both wired through `assemble_engine` into
  `BacktestEngine`'s `symbol_currency`/`fx_dataset`, and `fx_rates`'
  manifest hash joins `corporate_actions`/`universe` in `data_hashes`.
- `runner.py` checkpointing (ADR-0058): `checkpoint_experiment(config, path, *, stop_at,
  runtime, resume_from)` runs to the session boundary at or before `stop_at`, writes the
  checkpoint and returns `CheckpointWritten(path, boundary_ts)` (no experiment directory, report
  or trial); `run_experiment(..., resume_from=, checkpoint_path=, checkpoint_every_ns=)` resumes
  a saved run through the normal pipeline and/or atomically rewrites a checkpoint every interval
  of simulated time (`start + k * interval`, at most `MAX_CHECKPOINTS`); both share
  `_prepare_run` (quality gate, engine build, resume), which creates no directory, so any
  refusal leaves nothing behind. `config.parse_interval("4h")` parses the cadence.
- `runner.py`: `run_experiment(..., runtime="backtest"|"paper"|"live")` (ADR-0051):
  `_check_runtime` refuses a runtime that disagrees with `live.enabled`, `_build_engine`
  builds the engine for the runtime, paper/live never record a trial, and
  `manifest.json` gains `runtime`. Quality gate (refuses; skips need a
  logged reason recorded in the manifest) → engine → trades/metrics →
  artifacts: `config.yaml, manifest.json, ledger/orders/fills/trades/equity
  .parquet, metrics.json, equity.svg, report.html, logs/run.jsonl`.
  `experiment_id` = `EXP-` + hash of (config hash, data hashes).
- `walk_forward.py` (ADR-0081): `walk_forward(config, artifacts_root, *, param_name, values,
  train, test, step, metric, holdout, max_runs)` builds rolling folds with
  `validation.splits.WalkForwardSplitter` semantics (`fold_windows` is the pure, tested
  arithmetic), selects each fold's value on train with the ordinary `run_experiment`, evaluates
  it on test with `record_trial=False`, and writes `<artifacts>/walk_forward.json`. First
  increment: no concatenated out-of-fold series/DSR yet, and the per-fold selection is not
  deflated (both stated in the summary).
- `runner.py` annualization (2026-10 audit, M5): when the config leaves `periods_per_year`
  unset (`model_fields_set`), `_prepare_run` derives it from the bars' spacing and the
  calendar -- 252 sessions a year times the median bars per session, 365 for `24/7`
  (`crucible.data.calendars.periods_per_year_for`, the same rule the one-step product uses).
  An explicit value always wins. Before this, an intraday config that left the daily default
  annualized per-bar Sharpe by `1/sqrt(bars per session)` too little (hourly on XNYS: 0.81
  instead of 2.13 for the same series); the derivation costs one `event_time` column scan and
  only runs when the field is untouched. The vectorized runner applies the same rule.
- `runner.py` result identity (ADR-0079): the manifest records
  `crucible_version`, `commit`, `dirty` and `code_fingerprint` (HEAD +
  `git status` + the working-tree diff), all resolved from the checkout that
  contains the loaded package rather than the process cwd (a run from another
  directory used to record `commit="unknown"`). Before the trial registry and
  before any file, `_refuse_overwrite` compares the existing manifest's code
  identity with the current run's: the same fingerprint is an idempotent
  re-run, a different one raises `ExperimentError` unless `overwrite=True`
  (`crucible run --overwrite`), so a run of different code cannot silently
  replace the earlier numbers.
  Git commit/dirty captured via subprocess (unknown ⇒ treated dirty);
  env hash = SHA-256 of `uv.lock`. `trial_count` in the manifest/report
  header comes from `validation.trial_registry.DuckDBTrialRegistry`
  (`<artifacts_root>/trial_registry.duckdb`, ADR-0008/ADR-0014) — recorded
  once per distinct `experiment_id` per family, keyword-only
  `record_trial=False` reports without incrementing. `dsr`/
  `dsr_benchmark_sharpe`/`dsr_error` in the manifest and the report's
  statistical-validity block come from `validation.dsr.deflated_sharpe_ratio`
  (ADR-0015); `pbo` is always `null` — a single run has no multi-trial
  panel to compute it from. `monte_carlo` in the manifest/report comes
  from three `validation.monte_carlo.ResamplingTest`s
  (`N_MONTE_CARLO_ITERATIONS = 1,000` each), run on the same seeded `rng`
  `compute_metrics` already advanced (ADR-0017). `contamination`/
  `contamination_reason`/`contamination_overlapping_trials` in the
  manifest and the report header's `contamination_flags` cell come from
  `validation.contamination.check_contamination` (ADR-0021) — the trial
  registry call above also now passes `mode`/`start_ns`/`end_ns` so this
  check has what it needs. Also:
  `build_execution_setup` (config → models via the level-gated registry,
  one shared `MarketStats`), `assemble_engine` (shared by run and debug so
  replay = original run; optional `feed_factory` and
  `execution_backend_factory`), `ExperimentConfig.live`
  (`LiveConfig`: `enabled`, `venue: simulated`; default `None`, off; ADR-0043), and `run_with_scenarios` (R3.10: base + each
  scenario as separate experiments, only the base counted as a trial;
  `scenario_decay.json`/`.html` written into the base run's artifacts).
- `sensitivity.py`: `sweep_1d(config, param_name, values, artifacts_root)`
  — runs `run_experiment` once per swept value (every point recorded as a
  trial, per ADR-0016 — unlike scenario fan-out), reads a metric from
  each, and hands the series to `validation.sensitivity` for the
  plateau/spike diagnostic. Also exposes `_cast_like`/`_derived_param_config`,
  shared with `perturbation.py`.
- `perturbation.py`: `perturb_execution(config, field_name, low, high,
  n_iterations, ...)` and `perturb_strategy_param(...)` — Monte Carlo by
  re-simulation rather than resampling
  (`validation.monte_carlo`, ADR-0017). `perturb_execution` runs the base
  config once (counted as the one real trial) then perturbs a scalar
  execution field (`slippage_bps`-style only — model-slot fields are a
  known gap) without counting the perturbed runs as trials, mirroring
  scenario fan-out (ADR-0014). `perturb_strategy_param` counts every
  perturbed draw as a trial, mirroring sensitivity sweeps (ADR-0016). Both
  decisions contrasted and justified in ADR-0018.
- `null_tests.py`: `null_test_shuffle`/`null_test_sign_flip`/
  `null_test_synthetic_gbm(config, ...)` — the null tests.
  Reads the real bars via `ParquetDataStore`, transforms them with
  `data.transforms.{shuffle_bar_returns,sign_flip_returns,
  synthetic_gbm_like}`, writes each transformed variant into its own fresh
  temp store under `<artifacts_root>/_null_test_stores/<variant_id>`
  (`_run_on_transformed_bars`, copying the real corporate-actions/universe
  datasets across unchanged so the derived config is self-contained), and
  re-runs `run_experiment` with `record_trial=False` against it — the real
  `config.data.store` is only ever read, never written. None of the null
  runs count as trials (they never touch real market data, so they aren't
  a parameter evaluation in ADR-0008's sense); the one real run is subject
  to ordinary trial counting. Shuffle/GBM run `n_iterations` times with an
  explicit `rng` and compare a distribution; sign-flip is deterministic
  and runs exactly once. All three return
  `(validation.null_tests.NullTestResult, real_run, null_run(s))`. Design
  rationale (decompose/reconstruct bar transform, temp-store isolation,
  trial-counting, deferred time-shift scope) pinned in ADR-0019.
- `optimize.py`: `optimize_1d(config, param_name, values, artifacts_root,
  ...) -> (OptimizeResult, list[RunArtifacts])` — the `crucible optimize`
  CLI's library function (ADR-0022). Runs one trial
  per swept value (every point counted, ADR-0016), refuses unless
  `config.experiment.mode` is already `optimization`, then reads each
  trial's own returns back from its `equity.parquet` and assembles the
  trials × periods panel `validation.pbo.probability_of_backtest_overfitting`
  needs. `DEFAULT_PBO_GROUPS = 6` (untuned default).
  `OptimizeResult.best_dsr`/`best_experiment_id`: the winning trial's
  Deflated Sharpe, recomputed against the *full completed sweep's* trial
  history — each trial's own `manifest.json["dsr"]` only reflects the
  trial count as of *its own* recording time mid-sweep, which
  under-deflates a winner that wasn't the last trial run (bug found and
  fixed while building the overfit-detection acceptance test, ADR-0023).
- `validate.py`: `validate_run(config, artifacts_root, *, factors=None) ->
  ValidateResult` — the `crucible validate` CLI's library function. A
  plain `run_experiment` call when `factors` is omitted; when given
  (`load_factors_csv`: one column per factor, row-aligned to the run's own
  returns, no date column), regresses the run's returns on them
  (`validation.factor_regression`) and merges the result into the run's
  manifest/report via `runner.rebuild_report`.
- `runner.py::rebuild_report(out_dir, *, factor_regression=None)` —
  re-renders `report.html` from a finished run's on-disk artifacts,
  optionally merging a factor regression into `manifest.json` first.
  Shared by the `crucible report` CLI command and `validate_run` (a
  refactor out of `_cmd_report`'s former inline body once `validate_run`
  became its second caller, ADR-0022).
- `interfaces.py`: `ArtifactStore`/`RunRegistry` Protocols.
- `runner.py` (ADR-0038): `run_experiment` is now a
  two-line wrapper over `_run_experiment_compute` (quality gate, engine,
  metrics, Monte Carlo — touches only the read-only data store and this
  run's own artifact directory) then `_finalize_experiment` (trial
  registry, DSR, contamination, artifact writing — the only part that
  touches `trial_registry.duckdb`). `run_experiment_parallel(configs,
  artifacts_root, *, max_workers=None) -> list[RunArtifacts]` runs the
  first phase across a `ProcessPoolExecutor` (`pool.map`, which preserves
  `configs` order regardless of completion order) and finalizes serially,
  in the parent, in that same order — reproducing sequential
  `run_experiment` calls byte-for-byte (E1). This split exists *because*
  DuckDB allows only one process to hold `trial_registry.duckdb` at a
  time (fails fast otherwise) and, separately, because even a
  lock-protected concurrent registry write would make each trial's
  provisional DSR depend on wall-clock scheduling instead of `configs`
  order — both verified/derived in ADR-0038, not assumed.
- `optimize.py::optimize_1d` gained `max_workers: int | None = None` —
  routes through `run_experiment_parallel` when set (default: sequential,
  unchanged). `crucible optimize --workers N` on the CLI.
- `crucible compare FAMILY` (`crucible/cli/main.py`):
  lists every trial recorded for a family via
  `validation.trial_registry.DuckDBTrialRegistry.all_trials`, sorted by
  per-period Sharpe descending, with each trial's DSR read back from its
  own `manifest.json` when still on disk (`dsr=unknown` otherwise — a
  missing sibling artifact for an old trial is expected, not exceptional).

## Extension points
New config sections join `ExperimentConfig` as (discriminated-union) fields
in their phase; hash coverage extends automatically because the hash is over
the whole model.

## Known gaps
- `ArtifactStore` and `RunRegistry` are stub Protocols: `run_experiment` writes the layout itself and `crucible compare` reads the trial registry directly.
- Adding any config field renames every experiment id (the hash covers defaults); see `docs/COMPATIBILITY.md` §2 for the open decision.
Checkpoint/resume (E7) is library API only (`BacktestEngine.run_until`/`checkpoint`/`resume_from`); no runner integration, auto-checkpointing or CLI. `report.html`/`equity.svg` sit
outside the golden byte surface (ADR-0011). `null_tests.py`'s
per-iteration temp stores under `_null_test_stores/` aren't cleaned up
automatically. The vectorized path has a parallel runner and trial recording
(`run_vectorized_experiment_parallel`, ADR-0061); `crucible optimize --vectorized` drives it.
