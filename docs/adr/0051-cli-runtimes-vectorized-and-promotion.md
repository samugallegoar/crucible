# ADR-0051: CLI for the runtimes, the vectorized runner and promotion

- **Status**: accepted
- **Date**: 2026-09-25

## Context

`PaperRuntime` (ADR-0039/0040), `LiveRuntime` (ADR-0043/0044), the vectorized
runner (ADR-0036) and config promotion (ADR-0037) were library calls only. The
`live` feature flag was silently ignored by `crucible run`, which ran the
config as a backtest.

## Decision

1. **`run_experiment(config, root, *, runtime="backtest"|"paper"|"live")`**
   changes only how the engine is built (`assemble_engine`,
   `PaperRuntime(...).engine`, `LiveRuntime(...).engine`); everything after
   `engine.run()` (metrics, trades, Monte Carlo, artifacts, report) is the same
   pipeline. `crucible run <config> --runtime ...` exposes it (default
   `backtest`).
2. **The runtime and `live.enabled` must agree**, checked before any artifact
   is written (`ConfigurationError`): `live` needs the flag; `backtest` and
   `paper` refuse a live-enabled config, saying to pass `--runtime live` or turn
   the flag off. Scenario fan-out (`execution.scenarios`) runs only with the
   backtest runtime.
3. **Paper and live runs record no trial** (like scenario fan-out, ADR-0014):
   they re-run the same strategy parameters under another runtime and must not
   inflate DSR deflation. The report still states the family's trial count.
4. **`manifest.json` and the report header gain `runtime`.** A paper run
   equals its backtest (I14, ADR-0039), so it shares the backtest's experiment
   id and artifact directory. A later paper run rewrites that directory's
   `manifest.json` and report (`runtime`, and `trial_count`, `dsr`, `commit`
   recomputed against the registry as it is then, as re-running a backtest
   already does) while the registry keeps listing the id as the backtest
   trial; a live config differs (`live` is serialized), so it has its own id.
   Every refusal that depends on the config alone (`_check_runtime`, and a
   runtime constructor's refusals such as `LiveRuntime` at Level 0) happens
   before any artifact directory is created.
5. **`crucible debug`** replays a stored live-enabled config through
   `LiveRuntime`, so the stream includes the venue's fill events.
6. **`crucible run-vectorized <config>`** and **`crucible promote <config>
   --level N --lookback N --execution <yaml> [--out FILE] [--run]`** are thin
   wrappers of `run_vectorized_experiment` and `promote_config`. `promote`
   requires the level, lookback and an explicit `ExecutionConfig` YAML (nothing
   is defaulted, as `promote_config` requires), prints or writes the promoted
   canonical YAML, and `--run` (which needs `--out`, so stdout stays pure YAML)
   also runs it. A non-UTF-8 `--execution` file and an `--out` directory that
   does not exist are refused with a message.

## Alternatives considered

- **Separate `paper` and `live` commands.** Duplicates the artifact pipeline
  for no behavioral difference.
- **A runtime derived from the config alone.** Removes the explicit second key
  for going live; the flag plus `--runtime live` is a deliberate two-key
  arrangement.
- **Checkpoint flags on the CLI (`--stop-at`, `--checkpoint`, `--resume`).**
  Deferred: a partial run's artifacts need their own design.

## Consequences

- A live-enabled config is no longer silently run as a backtest by `run`,
  `optimize`, `validate` or the library's `run_experiment`; that is intended.
  Only `run` has `--runtime`, so `optimize`, `validate`, sensitivity and
  scenario runs need the flag off (the refusal message says so). A stored
  live-enabled config from a run made before this ADR was executed as a
  backtest, but `debug` now replays it through `LiveRuntime`.
- Paper and backtest runs of the same config share an experiment id and
  artifact directory; the manifest's `runtime` shows which wrote last.
- Deferred: checkpoint/resume flags and auto-checkpointing, `data build`
  vendor ingest, a real vendor adapter, wall-clock streaming.
- Amended by ADR-0058: the checkpoint flags on `crucible run` are implemented.
