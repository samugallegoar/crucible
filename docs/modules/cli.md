# Module: cli

## What exists

The `crucible` command (`crucible/cli/main.py`: `build_parser`, `main`). Every command, with its
options, is listed in `docs/INVENTORY.md`: `run`, `run-vectorized`, `promote`, `report`, `debug`,
`optimize`, `validate`, `compare`, `data build`, `data fetch`, `data check`, `data list`. Handlers are thin and
import lazily; a `CrucibleError` becomes `refused: <message>` and exit code 1.

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
- `crucible validate <config.yaml> [--factors CSV] [--artifacts DIR]` —
  runs the config like `run`; if `--factors` is given, regresses the run's
  own returns on the CSV's factor columns (one column per factor, one row
  per period, row-aligned — no date column) and merges the result into
  the run's manifest/report (`experiments.validate.validate_run`,
  ADR-0022).
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
in `runner._load_strategy`); `--override` has no `debug` form and `--json` no `debug`/`promote` form (ADR-0059). `optimize`
is 1D only (mirrors `sweep_1d`'s scope, not `sensitivity_surface_2d`'s);
its panel isn't persisted to disk, only printed (ADR-0022). Factor files
are a CLI flag, not a config field — `ExperimentConfig`'s hash doesn't
cover them (ADR-0022).
