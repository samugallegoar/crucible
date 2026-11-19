# Module: cli

## What exists

The `crucible` command (`crucible/cli/main.py`: `build_parser`, `main`). Every command, with its
options, is listed in `docs/INVENTORY.md`: `backtest`, `results`, `simulate-paths`, `spec check`, `spec templates`,
`config show`, `config set-home`, `run`, `run-vectorized`, `promote`, `report`, `debug`, `optimize`, `walk-forward`,
`validate`, `compare`, `schema`, `artifact show`, `artifact verify`, `data build`, `data continuous`,
`data fetch`, `data check`, `data integrity`, `data catalog`, `data list`, `futures run`,
`futures check`, `futures batch`, `futures walkforward`, `futures compare`, `futures trials`.
Handlers are
thin and import lazily; a `CrucibleError` becomes `refused: <message>` and exit code 1 (with `--json`
also the structured `{"error": {schema_version, code, type, message, location}}` document on
stdout, ADR-0084). `run` and `run-vectorized` take `--detail` (full manifest and file inventory in
the `--json` document); `artifact show <ART-.../EXP-...>` prints the same document for a finished
run, `artifact verify` recomputes its id from the files; a futures run's `artifact show` prints its
futures-run document (`experiments.futures_document`, ADR-0097); `schema --kind` also serves `run`,
`verification`, `error`, `manifest`, `futures-run-document`, `futures-batch`, `futures-walkforward`,
`futures-compare` (the comparison document of C5c, ADR-0102) and `futures-trials` (the
effective-trials report of C6b, ADR-0104). stdout and
stderr are reconfigured to UTF-8 (unencodable text is replaced) so a table never raises
`UnicodeEncodeError` on a legacy Windows code page.

## Product commands (ADR-0067, ADR-0068; implemented in `cli/product_commands.py`)

- `crucible backtest (--spec FILE | --entry RULE [--exit RULE] [--short-entry RULE --short-exit RULE]
  [--direction long_only|long_short] [--fraction F] [--stop-loss-pct P] [--take-profit-pct P]
  [--max-holding-bars N] [--name TEXT]) --symbols A,B --start YYYY-MM-DD --end YYYY-MM-DD
  [--capital N] [--costs none|standard|conservative] [--slippage-bps X] [--commission-bps X]
  [--provider yfinance|tiingo] [--price-basis adjusted|raw] [--calendar XNYS]
  [--offline] [--null-iterations N] [--family NAME] [--realism-check] [--home DIR] [--json]` — the
  one-step backtest (`docs/modules/product.md`). Prints the headline, the verdict, strategy against
  buy-and-hold, the warnings and the report path; `--json` prints the result document. `--spec`
  also accepts a YAML/JSON text.
- `crucible results [--home DIR] [--limit N] [--json]` — earlier one-step backtests, newest first.
- `crucible simulate-paths RUN [--home DIR] [--paths N] [--seed N] [--horizon BARS] [--mean-block B]
  [--ruin-loss F] [--export-paths FILE] [--json]` — resamples a finished run (a folder holding
  `equity.parquet`, or an experiment id in the home) with the stationary bootstrap and prints the
  distribution of final value, worst fall, chance of loss and of ruin (ADR-0083). **Return-sequence
  risk, not evidence of an edge.** Individual paths are written only with `--export-paths` (Parquet:
  `path`, `step`, `multiple`; refused above 25 million values).
- `crucible spec check` (the same strategy options) validates a spec and prints it back in plain
  language; `crucible spec templates [--name NAME]` lists ready-made specs or prints one.
- `crucible config show [--home DIR]` prints the resolved home folder, its subfolders, the settings
  file, the version and provider availability; `crucible config set-home PATH` remembers a home.
- `crucible schema --kind strategy-spec` prints the spec's JSON Schema (default: the experiment
  config's).
- `crucible data fetch --ohlc-repair clamp_rounding` repairs only float-rounding-sized OHLC
  violations (<= 1e-6 of the close) and still refuses larger ones.

## Responsibility
The `crucible` command.

## Behavior (Phases 1-3, 6)
- `crucible run <config.yaml> [--runtime backtest|paper|live] [--artifacts DIR]` — full
  experiment (ADR-0051). `--runtime` only changes how the engine is built: `paper`
  runs `PaperRuntime` (results equal the backtest's, I14), `live` runs
  `LiveRuntime` on the simulated venue and needs `live: {enabled: true}` in the config;
  `backtest`/`paper` refuse a live-enabled config, and scenarios run only with
  `backtest`. Paper and live runs record no trial; `manifest.json` records the
  `runtime`. Prints
  experiment id, artifact dir, report path. When the config declares
  `execution.scenarios`, runs base + every scenario and prints all ids plus
  the decay report path (R3.10). Exit 1 with `refused: ...` on any
  `CrucibleError` (quality failure, config error, lookahead).
  Checkpoint flags (ADR-0058): `--stop-at TIME --checkpoint FILE` runs to the boundary at or
  before `TIME`, writes `FILE` and stops (no experiment, report or trial); `--resume FILE`
  continues from a checkpoint and finishes normally (one trial, artifacts equal an
  uninterrupted run's); `--checkpoint-every INTERVAL --checkpoint FILE` (`30s`, `15m`, `4h`,
  `1d`, `2w` of simulated time) atomically rewrites `FILE` while the run continues. Every bad
  combination is refused before any work (`_checkpoint_options`), and `--stop-at` with
  `--checkpoint-every` cannot be combined.
- `crucible run-vectorized <config.yaml> [--artifacts DIR]` — the vectorized engine
  (`run_vectorized_experiment`, ADR-0036); prints id, artifact dir, report path;
  out-of-scope configs are refused.
- `crucible promote <config.yaml> --level N --lookback N --execution FILE [--out FILE]
  [--run] [--artifacts DIR]` — turns a vectorized config into an event-driven config
  at Level 2+ (`promote_config`, ADR-0037). `--execution` is a YAML mapping of
  `ExecutionConfig` fields (nothing defaulted); the promoted canonical YAML goes to
  `--out` or stdout; `--run` (needs `--out`) also runs it.
- `crucible report <EXP-ID> [--artifacts DIR]` — re-renders report.html
  from stored artifacts (`experiments.runner.rebuild_report`).
- `crucible debug <EXP-ID> --at TS [--artifacts DIR] [--order ID]` —
  deterministic replay from the run's stored config: prints the event
  stream up to TS (ISO or raw ns), then cash/positions, order states, and
  `why_not_filled` reason trails.
- `crucible optimize` also prints and emits (`reality_check`) White's Reality Check and Hansen's SPA over
  the sweep's return panel (ADR-0083): does the best swept value beat zero once the search is paid for?
- `crucible optimize <config.yaml> --param NAME --values "v1,v2,..." [--metric
  sharpe] [--pbo-groups N] [--workers N] [--vectorized] [--artifacts DIR]` — 1D parameter
  sweep (`experiments.optimize.optimize_1d`, ADR-0022); every point
  counted as a trial (ADR-0016). Refuses (exit 1) unless the config's
  `experiment.mode` is already `optimization` — never silently overridden.
  `--vectorized` (ADR-0061) runs every point on the vectorized engine (signal-function strategies,
  Levels 0-1, each point a trial). Assembles the trials × periods returns panel PBO has needed since
  and prints `PBO: <value> (n_combinations=..., n_trials=...)`.
  `--workers N` (ADR-0038) runs the sweep's trials
  through a process pool instead of sequentially — byte-identical result
  either way, purely a speed knob.
- `crucible compare <FAMILY> [--artifacts DIR]` (ADR-0038) — every trial recorded for a family
  (`validation.trial_registry.DuckDBTrialRegistry.all_trials`), sorted by
  per-period Sharpe descending, each line's `dsr=` read back from that
  trial's own `manifest.json` (`unknown` if the artifact directory is
  gone — the registry row alone is still valid). Prints
  `no trials recorded for family ...` (exit 0) rather than erroring on an
  empty/unknown family.
- `crucible walk-forward <config.yaml> --param NAME --values "v1,v2" --train SPAN --test SPAN
  --step SPAN [--metric sharpe] [--holdout SPAN] [--max-runs N] [--artifacts DIR]` — chooses the
  parameter on each fold's train window and reports only out-of-fold metrics
  (`experiments.walk_forward.walk_forward`, ADR-0081). Test runs are not recorded as trials, so
  the per-fold selection is not deflated; the summary says so and lives in
  `<artifacts>/walk_forward.json`. Refuses a metric whose best value is the smallest, a single
  candidate, a plan with no fitting fold, or one above `--max-runs`.
- `crucible validate <config.yaml> [--factors CSV] [--artifacts DIR]` —
  runs the config like `run`; if `--factors` is given, regresses the run's
  own returns on the CSV's factor columns (one column per factor, one row
  per period, row-aligned — no date column) and merges the result into
  the run's manifest/report (`experiments.validate.validate_run`,
  ADR-0022).
- `crucible futures run --config FILE [--store S] [--artifacts DIR | --home DIR] [--overwrite]
  [--json]` — one
  futures run (`experiments.futures_run.run_futures`, ADR-0095): the four datasets of the config's
  continuous build, one strategy, a window of Globex trade dates, explicit costs and execution.
  Prints the run id, the artifact id, the trial family and count, the window and its trade dates,
  bars, fills, the final balance and equity, the verdict line ("not assessed (C6/C7) — absence of
  assessment, not evidence of no edge"), every approximation the run recorded and the run
  directory; `--json` prints the futures-run document (`futures_document`, ADR-0097):
  `schema_version`, `kind`, `artifact_id`, `experiment_id`, `run_name`, `trial_family`,
  `trial_count`, `root`, `window`, `fidelity`, `run_dir`, `datasets`, `approximations`,
  `strict_execution`, `verdict`, `headline`, `metrics`, `files` — the same document `artifact show`
  prints for it. A second run of the same config and data is refused unless `--overwrite` (a
  reproduction keeps the artifact id and does not grow the trial count).
- `crucible artifact show|verify <ART-...> [--artifacts DIR | --home DIR] [--json]` — an equity
  run prints its run document; a futures run prints its futures-run document (ADR-0097). Both
  subcommands take `--home` and `--artifacts`.
- **`--home` precedence (also for `futures run`, `futures batch` and `artifact show|verify`).**
  The home is resolved
  by `crucible.product.home.resolve_home`, the same resolver `backtest --home` and
  `config show` use. With `--home DIR` the artifacts root is `DIR/experiments` and the trial
  registry is `DIR/experiments/trial_registry.duckdb` — one registry per artifacts root, never two;
  `futures run` also defaults `--store` to `DIR/data`. `--artifacts` and `--home` together are
  refused (`configuration_error`: "pass one of --artifacts or --home"); `--artifacts` alone behaves
  as before; neither keeps the historical default (`experiments/` under the working directory).
  Without `--home`, `futures run` still requires `--store`.
- `crucible futures check --config FILE [--json]` — loads and validates the config only (no store,
  no run): prints the config hash and the canonical YAML, or under `--json`
  `{"kind": "futures_run_config", "config_hash", "config"}`. `schema --kind futures-run` prints
  the futures-run config's JSON Schema; `schema --kind futures-run-document` prints the JSON Schema
  of the document a sealed futures run prints (ADR-0097).
- `crucible futures batch --batch FILE [--store S] [--artifacts DIR | --home DIR] [--overwrite]
  [--json]` — N DSL expressions on ONE base futures config (`experiments.futures_batch`,
  ADR-0100): every candidate shares the base's data, window, contracts, costs, execution, session
  and fidelity, and only its strategy and run name differ. Writes
  `<artifacts>/<BAT-ID>/batch.json` and prints it (`--json`) or a per-candidate list in SUBMISSION
  order with status (`computed`/`cached`), run id and the descriptive metrics; the text rendering
  ends with the verdict line. A candidate that duplicates an earlier parameterization, or whose
  sealed run already exists, is `cached` and reuses that run; the `--overwrite` flag re-simulates
  instead. The `--home` / `--artifacts` / `--store` precedence is `futures run`'s.
  `schema --kind futures-batch` prints the batch file's JSON Schema.
- `crucible futures walkforward --config FILE [--store S] [--artifacts DIR | --home DIR]
  [--overwrite] [--json]` — a walk-forward (`experiments.futures_walkforward`,
  ADR-0101) on a futures-walkforward file: its base config gives the trade dates the folds are cut
  from, its candidates are the batch format and its constraints decide eligibility.
  Each fold trains every candidate on the training window, selects the eligible one with the
  largest TRAINING net P&L (a tie goes to the earlier submission) and evaluates it on the fold's
  test window with a costed terminal exit. Writes `<artifacts>/<WFA-ID>/walkforward.json` and
  `oos_daily.parquet` and prints the document (`--json`) or a fold table (dates, selection, status,
  each fold's OOS net P&L and terminal exit cost) followed by the OOS totals, the stability counts
  and the verdict line. A re-run reuses every run it already computed (`cached`) and records no
  duplicate submission. The `--home` / `--artifacts` / `--store` precedence is `futures run`'s.
  `schema --kind futures-walkforward` prints the walk-forward file's JSON Schema.
- `crucible futures compare --target ID [--artifacts DIR | --home DIR] [--min-overlap N] [--json]`
  — the cross-run comparison (`experiments.futures_compare.compare_futures`, ADR-0102, C5c). Reads
  the artifacts root ONLY: no store, no `--store`, no simulation. `--target` is a `FUT-...` run or a
  `WFA-...` walk-forward, and the pool is every other `FUT-`/`WFA-` directory there (minus the
  target and, for a walk-forward target, its own training and test runs). Each pair gets a status
  (`ok`, `incompatible` with the differing comparison-key paths, `insufficient_overlap`,
  `constant_series`, `unverified` for a member whose seal does not verify) and, when the keys agree,
  a DESCRIPTIVE Pearson correlation of the two daily USD P&L series over the trade dates they both
  have. `--min-overlap N` (default 20, refused below 10) is how many overlapping trade dates a
  value needs. Writes `<artifacts>/<CMP-ID>/cross_run.json` (never inside a sealed run) and prints
  it (`--json`) or a table of the pool in ID ORDER with the target's metrics, each member's status,
  overlap and value, the largest absolute correlation and the verdict line. No Sharpe, no interval,
  no significance and no ranking by any statistic.
- `crucible futures trials --family F [--threshold R] [--min-overlap N] [--artifacts DIR | --home
  DIR] [--json]` — the family's EFFECTIVE number of trials (C6b, `experiments.futures_trials`,
  ADR-0104). Reads the artifacts root only: no `--store`, no simulation, no new trial. `--threshold`
  is the estimator's `rho*` (default 0.5, a correlation in [-1, 1]) and `--min-overlap N` the
  overlapping trade dates a pair's correlation needs (default 20, refused below 10). Writes
  `<artifacts>/<EFT-ID>/trials.json` and prints it (`--json`) or the counts, each candidate with its
  representative run, every pair with its status/overlap/rho, the estimate with its threshold and
  clusters, the sensitivity table for `rho*` 0.3/0.5/0.7/0.9, the reasons when it is unavailable and
  the verdict line. The estimate is labelled an estimator, is threshold-dependent, is never a count
  of independent hypotheses and never replaces the primary `dsr` deflated by `total_trials`.
  `schema --kind futures-trials` prints the report's JSON Schema.
- `crucible data check --store S --dataset D --calendar C` — quality
  battery; `data list --store S` — datasets with manifest hashes;
  `--skip NAME --skip-reason TEXT` (repeatable) skips named checks with a
  recorded reason.
- `crucible data build <spec.yaml> --store S [--start T] [--end T]
  [--max-contracts N] [--max-rows N]` — builds the datasets a spec
  describes (`data.importers.build.build_from_spec`, ADR-0052; specs in
  `examples/imports/`, sources in `docs/data/`). The quality battery and
  the `--max-rows` guard (default 5,000,000) run before anything is
  written; `--start/--end/--max-contracts` apply to Polymarket specs only.
- `crucible data continuous --store S --roots es,nq,... [--raw {root}_1m_raw] [--threshold 1.0]
  [--backstop-sessions 1] [--trim-to-calendar]` — builds each root's continuous futures series,
  ratio-adjusted series and rolls table from its raw per-contract dataset
  (`data.continuous.build_continuous_datasets`, ADR-0086; trade dates from the CME session calendar,
  ADR-0092; counts in `docs/data/glbx-futures-1m.md`). Raw bars outside the calendar's coverage are
  refused; `--trim-to-calendar` drops them and reports the count. A root whose build refuses writes
  nothing and stops the command; roots before it are kept.
- `crucible data integrity --store S --dataset D [--bar-seconds 60] [--session cme|utc]
  [--calendar CMES] [--top 10] [--json]` — the minute-level integrity report
  (`data.integrity.integrity_report`, ADR-0088): bars, absent minutes, largest hole, short and weekend
  sessions per symbol. `--session cme` dates bars by the CME session calendar of the symbols' root
  (ADR-0092) and counts bars outside it (`outside_calendar_bars`); it refuses a root the calendar
  does not cover. Exit 1 only when a row breaks the data contract (`ok` false); gaps are findings
  and leave the exit code at 0. Figures for the Databento datasets: `docs/data/glbx-futures-1m.md`.
- `crucible data catalog --store S [--dataset D ...] [--verify] [--top 10] [--json]` — the dataset
  registry (`data.catalog.dataset_catalog`, ADR-0089): per dataset identity, origin and root origin,
  price basis, lineage, contract and range. Exit 1 only when a manifest disagrees with its data file
  (row count, name, missing file, or the SHA-256 with `--verify`); a rebuilt parent or a superseded
  continuous builder is a finding. It also carries `futures_run`: per CME root of the contract-spec
  table, `{"supported": bool, "reasons": [...]}`, true only when the root has a CME session
  calendar, a contract specification and the four default v3 datasets in the store (ADR-0097). That
  field is computed in the CLI (`_futures_run_support`), because the default dataset names live in
  `experiments.futures_config` and `crucible.data` must not import `crucible.experiments`.
- `crucible data fetch --store S --dataset D --symbols A,B --start YYYY-MM-DD --end YYYY-MM-DD
  [--provider yfinance|tiingo] [--interval 1d] [--price-basis adjusted|raw] [--calendar XNYS]
  [--allow-partial] [--cache-dir P | --no-cache] [--refresh] [--ohlc-repair refuse|clamp]
  [--max-rows N]` — fetches bars from a data provider (`data.providers.fetch.fetch_dataset`,
  ADR-0063) and writes them through the same checked path as `data build`
  (`importers.build.write_import_result`). The provider is the flag, else `CRUCIBLE_DATA_PROVIDER`,
  else `yfinance`; keys come from the environment or `.env` and are never printed. A symbol that
  fails refuses the whole fetch and writes nothing unless `--allow-partial`; a symbol whose first bar
  is more than 7 days after `--start`, or whose last bar is more than 7 days before `--end`, is warned about (on stderr, and under `--json` in the document's `failed_symbols`/`warnings`) and recorded in the import report.

- `promote --json` prints one document `{"config": <file or null>, "yaml": <text or null>, "run":
  <the run document or null>}` (`yaml` when there is no `--out`; `run` with `--run`, which still needs
  `--out`). `debug --json` prints `{"experiment_id", "at", "events_total", "last_events" (the final 20:
  ts, seq, kind, symbol), "state": {"cash": {"currency", "amount"}, "positions", "orders" (each with
  `why_not_filled`)}}`; quantities and amounts are strings (exact decimals). Without `--json` both
  commands print what they always did.
- `--json` (ADR-0059) on `run`, `run-vectorized`, `validate`, `optimize`, `compare`, `report` and
  `data list|check|build`: one JSON document on stdout (`crucible/cli/machine.py`), text output
  unchanged. A refusal also prints `{"error": {"type", "message"}}`.
- `--override PATH=VALUE` (repeatable) on `run`, `run-vectorized`, `validate`, `optimize`,
  `promote`: edits the config before validation (`config.apply_overrides`), so the hash, id and
  stored config include it.
- `crucible schema [--out FILE]` prints the `ExperimentConfig` JSON Schema.

## Extension points
Handlers stay thin: parse args, call into `experiments`/`analytics`/`data`,
print. Engine logic never lives here.

## Known gaps
Checkpoint flags are offered on `run` only (not `optimize`, `validate`, `promote` or
scenario fan-out), and periodic checkpointing keeps only the latest file (no numbered
history, ADR-0058); `debug` replays a live-enabled run through `LiveRuntime`. Strategy entrypoints resolve relative to the working directory (documented
in `runner._load_strategy`); `--override` has no `debug` form (ADR-0059). `optimize`
is 1D only (mirrors `sweep_1d`'s scope, not `sensitivity_surface_2d`'s);
its panel isn't persisted to disk, only printed (ADR-0022). Factor files
are a CLI flag, not a config field — `ExperimentConfig`'s hash doesn't
cover them (ADR-0022).
