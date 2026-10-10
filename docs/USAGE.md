# USAGE — running a backtest, reading the result, comparing runs

> How to *use* Crucible (as opposed to extending it: `docs/WHERE_THINGS_GO.md`). Every
> ```` ```python run ```` block on this page is executed by
> `tests/integration/test_usage_doc.py` (against a temporary artifact root), so the
> snippets stay true. Column meanings: `docs/SCHEMAS.md`. Units: `docs/CONVENTIONS.md`.
> Every command and option: `docs/INVENTORY.md` (CLI) and `docs/modules/cli.md`.

## 1. Prerequisites

```bash
uv sync                                          # install (never pip install)
uv run python examples/momentum/build_data.py    # build the seeded synthetic dataset
```

`examples/momentum/build_data.py` writes three datasets (`momentum_bars_v1`,
`momentum_ca_v1`, `momentum_universe_v1`) into `examples/momentum/data/` (gitignored).
To use your own files, follow `docs/data/adding-a-dataset.md` (`crucible data build`)
and check `docs/data/` first: the dataset may already be documented and built.

A run is fully described by one YAML file (fields: `docs/SCHEMAS.md` §1.2). The shipped
one, `examples/momentum/config.yaml`, is a good template: a data block pointing at the
store, a `strategy.entrypoint` (`module:Class`), execution friction, `initial_cash`, and
`start` / `end`.

## 2. Running from the command line

```bash
uv run crucible run examples/momentum/config.yaml
# EXP-<12 hex>
# artifacts: experiments/EXP-<12 hex>
# report:    experiments/EXP-<12 hex>/report.html
```

- `--artifacts DIR` chooses the artifact root (default `experiments/`, gitignored).
- `--runtime paper` runs the same engine through the paper runtime (results equal the
  backtest's, invariant I14); `--runtime live` needs `live: {enabled: true}` in the config and
  runs against the simulated venue. Paper and live runs are not new trials.
- A config with `execution.scenarios` runs the base run plus every scenario and writes
  `scenario_decay.{json,html}` next to the base run.
- Long runs can be stopped, saved and continued (ADR-0058). A stopped run writes only the
  checkpoint (no experiment, report or trial); a resumed run finishes normally and its
  artifacts equal an uninterrupted run's:

  ```bash
  uv run crucible run cfg.yaml --stop-at 2021-03-10 --checkpoint run.ckpt   # save and stop
  uv run crucible run cfg.yaml --resume run.ckpt                            # continue to the end
  uv run crucible run cfg.yaml --checkpoint-every 1w --checkpoint run.ckpt  # save while running
  ```

  `--checkpoint-every` takes `30s`, `15m`, `4h`, `1d` or `2w` of *simulated* time and keeps only
  the latest file; after a crash, `--resume run.ckpt` continues from it. The config given to
  `--resume` must describe the same simulation, or the engine refuses.
- Agents and scripts (ADR-0059): `--json` prints one JSON document instead of text (metrics with
  CI, `trial_count`, `dsr`, `pbo`, `realism_level` together); `--override
  strategy.params.lookback=60` (repeatable) changes a config field without editing the file, and
  the run's hash and stored config include it; `uv run crucible schema` prints the config's JSON
  Schema.
- Exit code 1 and `refused: <message>` mean a `CrucibleError` (a failed quality check, a bad
  config, a lookahead attempt); the message says what, where and how to fix it.

Other entry points: `run-vectorized` (Level 0/1, fast research path), `promote` (vectorized
config -> event-driven config at Level >= 2), `optimize` (1-D sweep counted as trials, PBO; `--vectorized` runs the sweep on the vectorized engine),
`validate` (run plus an optional factor regression), `report <EXP-ID>` (re-render), `debug
<EXP-ID> --at <time>` (deterministic replay with reason trails for unfilled orders), `compare
<family>` (every trial in a family), `data build|check|fetch|list`. The same commands are available to MCP clients through `crucible-mcp`
(installed with Crucible, `docs/modules/mcp_server.md`). For a one-step backtest from a strategy
spec, with no config or dataset to prepare, see `crucible backtest` (`docs/guide/`). Options and help text:
`uv run crucible <command> --help` and `docs/INVENTORY.md`.

## 3. Running from Python

```python run
from pathlib import Path

from crucible.experiments.config import load_config
from crucible.experiments.runner import run_experiment
from examples.momentum.build_data import build_all

build_all(Path("examples/momentum/data"))               # idempotent, seeded
config = load_config(Path("examples/momentum/config.yaml"))
run = run_experiment(config, Path("experiments"))       # quality gate -> engine -> artifacts

print(run.experiment_id)                                # EXP-<12 hex>: config + data hashes
print(run.path, run.report_path)
sharpe = run.metrics["sharpe"]                          # MetricValue: value + bootstrap CI
print(sharpe.value, sharpe.ci_low, sharpe.ci_high)
```

`run_experiment` is deterministic: the same config, data and seed return the same experiment id
and byte-identical artifacts. Useful variants (all in `crucible.experiments`):

| Call | Purpose |
|------|---------|
| `runner.run_experiment(config, root, runtime="paper")` | paper / live runtime (same as `--runtime`) |
| `runner.run_experiment_parallel(configs, root, max_workers=N)` | many configs in a process pool, byte-identical to sequential |
| `runner.run_with_scenarios(config, root)` | base + execution scenarios |
| `vectorized_runner.run_vectorized_experiment(config, root)` | the vectorized engine |
| `optimize.optimize_1d(config, "lookback", [40, 60, 80], root)` | a sweep with PBO |
| `validate.validate_run(config, root, factors=...)` | run plus factor regression |

Config objects are frozen pydantic models: derive a variant with
`config.model_copy(update={...})` or by editing the dict before
`ExperimentConfig.model_validate(raw)`. A different config is a different experiment id.

## 4. The result objects

There are three layers, from the outside in.

**`RunArtifacts`** — what `run_experiment` returns (`crucible/experiments/runner.py`):

| Field | Meaning |
|-------|---------|
| `experiment_id` | `EXP-<12 hex>` |
| `path` | the run's artifact directory |
| `metrics` | `dict[str, MetricValue]`: `sharpe`, `cagr`, `volatility`, `max_drawdown`, `n_periods`, `n_trades`, `hit_rate` (keys and units: `docs/INVENTORY.md`, `docs/CONVENTIONS.md` §2) |
| `report_path` | `report.html` (provenance header, metrics with CIs, DSR/PBO summary, Monte Carlo) |

**`MetricValue`** — `value`, `ci_low`, `ci_high` (95 % circular block bootstrap; the CI is `None`
only for counts). A metric is never quoted without its CI, the trial count, DSR/PBO status and
the realism level (AGENTS.md §9): `manifest.json` carries the last three.

**The artifact directory** — the durable result (`docs/SCHEMAS.md` §2): `manifest.json`
(provenance, `trial_count`, `dsr`, `contamination`, `realism_level`, `data_manifests`),
`equity.parquet`, `trades.parquet`, `fills.parquet`, `orders.parquet`, `ledger.parquet` (the
source of truth), `metrics.json`, `logs/run.jsonl`, `report.html`.

Below `run_experiment`, `BacktestEngine(...).run()` returns a **`BacktestResult`** in memory
(`equity_rows`, `order_rows`, `fill_rows`, `ledger_rows`, `log`, `final_snapshot`,
`order_reasons`); `experiments.runner.assemble_engine(config)` builds the engine the runner
would use. Use it for tests and stepping (`run_until`, `checkpoint`, `resume_from`); the
runner serializes it for you.

## 5. Loading a past experiment

Nothing is re-simulated: the artifact directory is read back.

```python run
from pathlib import Path

from crucible.experiments.artifacts import load_experiment

past = load_experiment(Path("experiments"), str(run.experiment_id))
print(past.manifest["realism_level"], past.manifest["trial_count"], past.manifest["dsr"])
print(past.metrics["sharpe"].value)          # MetricValue, as on the RunArtifacts
print(past.equity.tail(3))                   # polars: ts, equity, cash, realized_pnl, fees_paid
print(past.trades.height, past.fills.height, past.orders.height, past.ledger.height)
print(past.config.experiment.name)           # the validated ExperimentConfig it ran with
```

`LoadedExperiment` fields: `experiment_id`, `path`, `config`, `manifest`, `metrics`, `equity`,
`trades`, `orders`, `fills`, `ledger` (frames a runner did not write are empty; a vectorized run
has no orders/fills/ledger, and its `trades` frame is the position-episode log with
`EPISODE_SCHEMA` columns, not the FIFO round trips of `TRADE_SCHEMA`: `docs/SCHEMAS.md` §2.5a). `load_experiment` raises `ExperimentError` for a missing run
and refuses a run written by a newer artifact `schema_version`
(`docs/COMPATIBILITY.md` §3). `Decimal` quantities and amounts in the frames are strings: parse
them with `Decimal(...)`.

Ledger identities can be re-checked from a loaded run: the ledger's cash amounts are the
source of truth from which every equity row is derived (`docs/INVARIANTS.md`).

## 6. Comparing experiments

```python run
from pathlib import Path

from crucible.experiments.artifacts import compare_metrics, load_experiment

variant = config.model_copy(
    update={"strategy": config.strategy.model_copy(
        update={"params": {**config.strategy.params, "lookback": 40}})}
)
other = run_experiment(variant, Path("experiments"))
table = compare_metrics(
    [load_experiment(Path("experiments"), str(r.experiment_id)) for r in (run, other)],
    ["sharpe", "max_drawdown"],
)
print(table)
```

`compare_metrics` returns one polars row per run with the identity and provenance columns
(`experiment_id`, `realism_level`, `mode`, `trial_family`, `trial_count`, `dsr`) and each requested
metric with `<name>_ci_low` / `<name>_ci_high` — so a comparison can never drop the uncertainty.

From the shell, `uv run crucible compare <family>` lists every trial recorded for a trial family
(`experiment.family`) from `trial_registry.duckdb`, ranked by **per-period** Sharpe (not the
annualized figure of `metrics.json`), with each run's DSR. Trials in a family accumulate on
purpose: the more variants you try, the more the DSR deflates (ADR-0008/0014). Re-running an
identical config does not add a trial; a changed parameter does. To see one run again:
`uv run crucible report <EXP-ID>` re-renders its report; `uv run crucible debug <EXP-ID> --at
<time>` replays it and shows why an order did or did not fill.

## 7. Stepping, checkpointing and resuming (library)

```python
engine = assemble_engine(config)              # crucible.experiments.runner
engine.run_until(some_ts)                     # stops after the last event of a timestamp
engine.checkpoint(Path("state.json"))
resumed = assemble_engine(config)
resumed.resume_from(Path("state.json"))       # verifies data hashes, setup, strategy STATE_VERSION
result = resumed.run()                        # identical to the uninterrupted run (I13)
```

On the CLI, `crucible run --stop-at TIME --checkpoint FILE` stops at a session boundary and
`--resume FILE` continues (`docs/modules/cli.md`, ADR-0058). A strategy
that holds state outside `ctx.state` must be a `StatefulStrategy` or the engine refuses to
checkpoint it (ADR-0042/0048).

## 8. Reading the report honestly

- `realism_level` is in the header: a Level 1 Sharpe is not a Level 4 Sharpe.
- `trial_count` and `dsr`: a Sharpe from the 40th variant of a family is not the Sharpe of the
  first; the DSR says how much of it survives the multiple testing.
- `contamination`: true if an `optimization`-mode trial in the family already saw this window.
- `pbo` is null for a single run by construction; `crucible optimize` builds the panel it needs.
- `dirty: true` in the manifest means the working tree had uncommitted changes when the run was
  made: it is not reproducible from the recorded `commit`.

## Known gaps

- No Python API to *list* experiments in an artifact root; use `crucible compare <family>` or
  list the directories (`EXP-*`).
- `compare` works within one family only, not across families.
- `load_experiment` re-validates `config.yaml` with the current code: a run whose config used a
  field that has since been removed will not load (`docs/COMPATIBILITY.md` §5 says fields are
  deprecated, not deleted, for this reason).
