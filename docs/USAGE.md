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

## 9. Out-of-sample evaluation (walk-forward)

`crucible walk-forward` chooses a parameter on each fold's **train** window and reports only the
following **test** window (ADR-0081):

```bash
crucible walk-forward experiments/my_config.yaml \
  --param lookback --values 10,20,40 \
  --train 26w --test 13w --step 13w --holdout 26w
```

Spans use `s/m/h/d/w` (months and years vary in length, so they are refused). Each fold runs
every candidate on train, picks the best by `--metric` (higher-is-better only -- `volatility` and
`max_drawdown` are refused), then runs that value on test and keeps the test metrics. The summary
(`<artifacts>/walk_forward.json` and the terminal table) lists the chosen value per fold, the
out-of-fold metric, its mean and spread across folds, and the share of positive folds. With
`--holdout` the tail window never takes part in selection and is evaluated once at the end.

Read it honestly: the only out-of-sample number is the test column. Test runs do not record
trials, so the per-fold selection is **not** deflated by DSR, and the fold spread matters more
than the mean. `--max-runs` (default 250) refuses a plan that would run for hours.

## 10. Finding a run by its artifact id

A finished run has two ids: `EXP-<12 hex>` (config + data; the directory name) and
`ART-<16 hex>`, the **artifact id**, which also covers the manifest and the result files
(ADR-0084). The same code, config, data and seed give the same one.

```bash
uv run crucible run config.yaml --artifacts experiments --json            # prints artifact_id
uv run crucible artifact show ART-0123456789abcdef --artifacts experiments --json
uv run crucible artifact show ART-0123456789abcdef --artifacts experiments --detail --json
uv run crucible artifact verify ART-0123456789abcdef --artifacts experiments
uv run crucible artifact show ART-0123456789abcdef --home ~/crucible --json
uv run crucible schema --kind run      # also: verification, error, manifest, futures-run-document
```

`show` prints the compact document (ids, headline fields, every metric with its interval);
`--detail` adds the full manifest and the file inventory. A futures run prints its own document
instead (§11). `--home` selects `<home>/experiments` as the artifacts root; pass it or
`--artifacts`, not both. `verify` recomputes the id from the
files and refuses (exit 1) if a result file or the manifest was edited. A refusal under `--json`
prints `{"error": {"code", "message", "location", ...}}`; branch on `code`.

From Python: `crucible.experiments.artifact_id.find_artifact(root, id)` returns the directory and
`verify_artifact(dir)` the id; `RunArtifacts.artifact_id` is set on every finished run.

## 11. A futures run (CME equity-index futures)

```bash
uv run crucible futures check --config examples/futures/es_sma_cross.yaml
# a strategy written in the DSL instead of a spec: check prints its canonical text and three ids
uv run crucible futures check --config examples/futures/es_zscore_reversion.yaml
uv run crucible futures run --config examples/futures/es_sma_cross.yaml --store data/processed --json
# a home-based run: the artifacts root is <home>/experiments and the store defaults to <home>/data
uv run crucible futures run --config examples/futures/es_sma_cross.yaml --home ~/crucible
uv run crucible artifact show ART-0123456789abcdef --home ~/crucible --json
uv run crucible schema --kind futures-run-document
```

`--home` uses the same resolver `crucible backtest --home` and `crucible config show` use: its
`experiments/` folder becomes the artifacts root (with the family's one
`trial_registry.duckdb`), its `data/` folder the default store. Pass it or `--artifacts`, never
both (a refusal); without `--home`, `futures run` still requires `--store`.

The config (`kind: futures_run`, `crucible schema --kind futures-run`) names:
- the root and its continuous datasets (ADR-0092);
- a window in Globex trade dates;
- a strategy: a spec, a Python function returning signed contracts, or a DSL expression
  (`strategy.expression`, compiled at load: `docs/modules/dsl.md`);
- contracts, capital and costs;
- tick brackets (ADR-0093);
- the signal input (ratio-adjusted by default, ADR-0094);
- the CME session rules;
- a trial family, which is required.

The sealed run directory holds:
- `marks.parquet`: per bar, the position, the balance, the close equity and the intrabar
  low/high equity estimate;
- `daily.parquet`: per trade date, the opening and closing balance and equity, realized P&L,
  costs, minimum and maximum equity, and the maximum contracts;
- `fills.parquet`: with the position after each fill;
- `rolls.parquet`;
- `metrics.json`: descriptive totals only.

`manifest.json` records the datasets with their hashes, the signal and scale checks, the execution
policy, the calendar version, the marking policy, the **fidelity** block, the **statistics** block
and every approximation. The statistics are inferential; the run still makes no performance claim
(ADR-0095, ADR-0103).

**What the statistics mean (C6a, ADR-0103).** Every futures run reports six statistics next to its
descriptive totals: `sharpe_per_period` (mean daily return over its standard deviation — the one
PSR and DSR use), `sharpe_annualized` (`x sqrt(252)`, PRESENTATION only), `mean_daily_return`,
`psr`, `dsr` and `ic_mean`. The daily return is
`(closing_equity_t - closing_equity_{t-1}) / initial_capital`: FIXED capital, so the series does
not compound, a session with no position is a real zero, and a session with no bars is excluded and
counted as `missing_sessions` instead of being filled with zero. The Sharpe, the mean return and the
IC carry a seeded circular-block-bootstrap interval; PSR and DSR are closed-form probabilities with
no interval; a statistic that cannot be computed is null WITH its reason (fewer than 3 daily
observations, a series with no dispersion, fewer than 2 candidate Sharpes for DSR).

`config.statistics` decides only the interval: `ic_horizon_bars` (default 1), `resamples` (default
1000, at least 200) and `confidence` (default 0.95). The manifest's `statistics` block records the
returns convention, `annualization: {periods_per_year: 252, convention: "sqrt"}`, the bootstrap
recipe (`numpy.random.PCG64`, the seed of each statistic, `ceil(sqrt(n))` block length, the block
length, resamples, confidence), the family's `trials` counts, the `candidate_id`, `missing_sessions`,
`zero_position_days` and the IC record (`horizon_bars`, `days`, `by_month`, `reason`). The seed is a
function of the run id and the statistic's name, so a re-run reproduces every interval byte for byte.

The information coefficient exists for a DSL expression only: it is the per-trade-date Spearman
correlation between the score at each decision bar and the close-to-close return over
`ic_horizon_bars` bars of the signal series, with pairs that cross a session edge or a contract
change dropped and trade dates with fewer than 10 valid pairs skipped. A spec or Python strategy
records a null IC with the reason.

**Still no verdict.** `verdict.verdict_level` stays null with
`verdict.verdict_reason.code: "robustness_not_assessed"`: robustness and prop-firm rules are C7, so
no document states an edge. Read the statistics as numbers with stated uncertainty, never as a
recommendation.

**Fidelity (C5a, ADR-0100).** `fidelity` decides how finely and how expensively the run reads its
series: `resolution` (`1m` default, `5m`, `15m`, a causal aggregate of the stored one-minute
series), `cost_detail` (`full` default, or `commission_only`, which zeroes spread and slippage and
is recorded as an optimistic approximation) and an optional `preset` (`screen` = 15m +
commission_only, `standard` = 5m + full, `full` = 1m + full). A preset that contradicts an explicit
field is refused. The fidelity is part of the config hash, so it is part of the run id, and the
manifest records both the block and the resampling counts.

**A batch of expressions (C5a, ADR-0100).** One base config, N expressions:

```bash
uv run crucible futures batch --batch examples/futures/es_batch_screen.yaml \
    --store data/processed --artifacts experiments --json
uv run crucible schema --kind futures-batch
```

Every candidate shares the base's data, window, contracts, costs, execution, session and fidelity;
only its strategy and its run name change, so all candidates are compared under the same
conditions. `<artifacts>/<BAT-ID>/batch.json` lists them in **submission order** (never sorted by a
metric) with their status (`computed`/`cached`), run and artifact ids, five descriptive metrics
(net P&L, costs, fills, the conservative intraday drawdown, the minimum equity) with null
intervals, their `CND-` `candidate_id` and a `statistics` block copied from the run (Sharpe, PSR,
DSR, IC with their intervals and reasons); the batch's verdict is null with
`robustness_not_assessed`. A candidate that duplicates an earlier one after canonicalization and
binding is `cached` and reuses that run, and one whose sealed run already exists is `cached` too
(re-running a batch is a reproduction). Every submitted candidate is recorded in the trial
registry's `submissions` table with its `candidate_id`, while `trials` keeps one row per distinct
run; `batch.json`'s `trials` block reports the family's `submission_count`,
`unique_candidate_count` and `total_trials` (ADR-0103).

**A signal warm-up (C5b, ADR-0101).** `window.warmup_trade_dates` (integer, default 0) makes the
run READ the N Globex trade dates immediately before its window to compute the signal, and then
drop them: no fill, mark, ledger row, position or roll comes from the warm-up, so the simulated
window stays exactly the one you wrote. It is what stops every window from starting flat while the
strategy's own window fills up, and it is past data, so it adds no lookahead. A run whose warm-up
does not cover the expression's own window (240 bars for `ts_zscore(close, 240)`) is refused rather
than decided flat, and so is a warm-up the dataset cannot reach back for. The manifest's `warmup`
block records the trade dates read and the bars they held. With 0 the run is exactly the ADR-0095
one.

**A walk-forward (C5b, ADR-0101).** Folds over the base window's trade dates, trained and selected
inside each training window, evaluated on the test window that follows:

```bash
uv run crucible futures walkforward --config examples/futures/es_walkforward_screen.yaml \
    --store data/processed --artifacts experiments --json
uv run crucible schema --kind futures-walkforward
```

The file (`kind: futures_walkforward`) names a `base` futures-run config, the `candidates` (the
batch format), `train_trade_dates` (N), `test_trade_dates` (M), `scheme` (`rolling` or `anchored`),
`warmup_trade_dates` (overrides the base's) and `constraints`. Fold k tests on trade dates
`[N + k*M, N + (k+1)*M)` of the base window and trains on the N before it (`rolling`) or on every
date from the first one (`anchored`); a trailing remainder shorter than M is reported as
`unused_trade_dates` and fewer than one complete fold is refused. In each fold every candidate runs
on the training window, a candidate is ELIGIBLE only if it satisfies every constraint
(`max_intraday_drawdown_usd` is required; `min_equity_usd`, `max_fills` and `max_time_in_market` are
optional), and the eligible one with the largest training net P&L is selected (a tie goes to the
earlier submission). With no eligible candidate the fold is FLAT - zero P&L and zero costs, status
`no_eligible_candidate` - rather than missing. The selected candidate then runs on the test window
alone, and the contracts open at its last bar are charged one side of the full per-contract cost as
its **terminal exit**, so every fold starts and ends flat at a known, pessimistic price.

`<artifacts>/<WFA-ID>/walkforward.json` holds the folds, the out-of-sample summary (with its C6a
`statistics`, computed on the OOS chain alone and deflated by the family's `total_trials`), the
`window_stability` list, the family's `trials` counts and, under `in_sample_audit`, every training
run marked `in_sample: true` with its own statistics;
`oos_daily.parquet` is the concatenated chain (one row per test trade date, the terminal exit booked
on the fold's last date), whose `closing_equity_usd` starts each fold at the base capital plus the
previous folds' net P&L. Only the concatenated series is presented as out-of-sample performance; the
training numbers are audit only, the OOS IC is null with a reason (a concatenation of folds has no
single signal), and the verdict is `robustness_not_assessed` (ADR-0095, ADR-0097, ADR-0101,
ADR-0103). Re-running a walk-forward is a reproduction: every run it already computed is `cached`
and no submission is duplicated.

**Effective trials and PBO (C6b, ADR-0104).** A family's Deflated Sharpe Ratio is deflated by
`total_trials`, its count of distinct candidates; two variants that differ only in a window
length are not two independent bets, so C6b ESTIMATES the effective number of trials and
reports a second deflation beside the first:

```bash
uv run crucible futures trials --family es-screen --artifacts experiments --json
uv run crucible futures trials --family es-screen --threshold 0.7 --min-overlap 20
uv run crucible schema --kind futures-trials
```

`crucible futures trials` reads the artifacts root ONLY (no store, no simulation, no new
trial): each distinct candidate is represented by its run with the most observations, every
pair is correlated over the trade dates both have (an inner join, nothing filled, at least
`--min-overlap` dates, default 20 and never below 10) and only when their comparison keys
agree, and average-linkage clustering of `d = sqrt((1 - rho) / 2)` counts the clusters at
`--threshold` (`rho*`, default 0.5). It writes `<artifacts>/<EFT-ID>/trials.json`: the
counts, each candidate with its representative run, every pair with its status and `rho`,
the estimate with its threshold and clusters, the sensitivity table for `rho*` 0.3/0.5/0.7/0.9
and the null verdict. Read it as an ESTIMATOR: threshold-dependent, not a count of independent
hypotheses, and UNAVAILABLE (never 0, never 1) when any pair has too little overlap, an
incompatible key, a constant series or an artifact that does not verify.

Every futures run, `batch.json` and a walk-forward's `oos.statistics` carry the SUPPLEMENTARY
reading (`supplementary.dsr_effective_trials`) computed when they were written: the same
series and the same candidate-Sharpe dispersion as the primary `dsr`, with `N` = the effective
count. The primary `dsr` is unchanged and remains the conservative result. PBO is optional:
put `pbo: {n_groups: 8}` in a batch file (even, at least 4) to get `batch.json`'s `pbo` block
for the candidates' own daily-returns panel, or in a walk-forward file to get
`in_sample_audit.pbo_panel` from one extra run per distinct candidate on the base window — the
selected out-of-sample chain is never an input, and those runs do not grow `total_trials`.

`futures run --json` and `crucible artifact show <ART-...> --json` print the same **futures-run
document** (`schema_version: 1`, `crucible schema --kind futures-run-document`; keys in
`docs/SCHEMAS.md`, ADR-0097, ADR-0103). Its verdict is null with a reason:
`verdict.verdict_level: null`, `verdict.verdict_reason.code: "robustness_not_assessed"` — Crucible
reports the statistics but has not assessed robustness before milestone C7, and an absence of a
verdict is not evidence of no edge. A metric is `{value, ci_low, ci_high, assessment, unit,
method, reason}`: a `descriptive` one carries null intervals, an `inferential` one carries the
bootstrap interval of its statistic (or none, with a `method`, when it is a closed-form probability
like PSR/DSR), and a null value always states a `reason` — never a zero.

**Comparing a run with what you already have (C5c, ADR-0102).** A comparison reads the
artifacts root only — no store, no simulation — and reports the target's dollar metrics and
the DESCRIPTIVE daily P&L correlation of every other `FUT-`/`WFA-` artifact there with it:

```bash
uv run crucible futures compare --target FUT-0123456789abcdef --artifacts experiments
uv run crucible futures compare --target WFA-0123456789abcdef --home ~/crucible --json
uv run crucible schema --kind futures-compare
```

The text output is one row per member IN ID ORDER (never sorted by a correlation): its id,
its kind, its status, how many trade dates it shares with the target (and the first and
last) and the coefficient when there is one. `--json` prints `cross_run.json` itself
(`<artifacts>/<CMP-ID>/cross_run.json`, keys in `docs/SCHEMAS.md`).

How to read it:

- `ok` — the two members were simulated under the same rules (their *comparison key*: the
  simulator version, the fidelity level, the execution section, the session section and the
  signal input — NOT the root, size, costs, strategy, window or capital) and the value is
  Pearson's correlation of their daily USD P&L over the trade dates they BOTH have. A date
  one of them does not have is excluded, never treated as a zero P&L; `--min-overlap`
  (default 20, never below 10) is how many shared dates a value needs.
- `insufficient_overlap` — fewer shared trade dates than that: no value, because there is
  nothing to read.
- `constant_series` — one of the two series never moved over the overlap, so the coefficient
  does not exist.
- `incompatible` — the keys differ; `differing_keys` names the paths (for example
  `fidelity.resolution` for a 1m run against a 15m one, or `execution.brackets.stop_ticks`
  for a bracketed run against a bare one). Two runs that differ only in how they filled or
  what they bracketed are not comparable, and no value is reported.
- `unverified` — the member's seal (a run's, or a walk-forward test run's) does not verify.
  It is listed with no value, never silently dropped.

The comparison makes no claim: the correlation's value carries null intervals, the verdict is
`robustness_not_assessed`, no member is ranked by it, and `max_abs_correlation` is a summary of what
was computed rather than a leaderboard. A correlation near 1 means the two runs earned and lost on
the same days; it says nothing about whether either is good. The comparison also repeats each
member's OWN recorded statistics (`sharpe_per_period`, `sharpe_annualized`, `psr`, `dsr`) — read
from its artifact, never recomputed — so a pool member's numbers are the ones its own document
reports. (Inferential statistics from C6a; no edge verdict before C7.)

## 12. The holdout vault (C6c): the protected period and its one evaluation

ADR-0105 declares a protected period for the futures family: Globex trade dates from **2025-01-01,
open-ended**, for `ES, NQ, YM, RTY, NKD`. Everything up to 2024-12-31 is research data; the protected
period can be read only through a registered, human-authorized, single evaluation. The lock is in the
**data layer**: a read, a `futures run|batch|walkforward` window or a whole-file access that reaches
it raises `VaultLockedError`, whether it comes from the CLI, the MCP server or Python.

### Installing the lock (a human, once)

```bash
uv run crucible vault declare --start 2025-01-01 --audit-ref "the exposure audit of 2026-11-19"
```

It writes `vault.json` into the store root AND the home, and prints the vault id plus the instant the
lock starts (2024-12-31T23:00:00Z: the 17:00 CT open of trade date 2025-01-01). Either copy locks the
period, so copying the store or switching home does not lift it. A later declaration can only WIDEN
it (an earlier or equal start, a superset universe).

The admin token is a human's and is never generated by Crucible:

```bash
uv run crucible vault set-admin        # interactive TTY only; stores a salted scrypt hash
```

### Registering a candidate (anyone)

```bash
uv run crucible vault register --config examples/futures/es_sma_cross.yaml   # prints VR-...
uv run crucible vault status                                               # statuses, counter, no metric
```

The registration records the config's complete hash, the datasets' content hashes, the `CND-`
candidate id and the window, which must lie inside the vault (so the window starts at 2025-01-01 or
later). Editing the config afterwards changes its hash and refuses the evaluation.

### Authorizing and evaluating (a human)

```bash
uv run crucible vault authorize --registration VR-...   # TTY prompt, or CRUCIBLE_VAULT_TOKEN
uv run crucible vault evaluate  --registration VR-...   # exactly once
```

The evaluation increments the persistent open counter BEFORE it reads anything (a crash consumes the
evaluation), opens the data-layer session for the registered datasets only, runs the config, and
seals the artifact under `<artifacts>/VAULT/<VR-...>/`. A second evaluation of the same registration
is refused. The sealed run is an ordinary futures run (its `artifact show` and its statistics work),
but it stays out of `futures compare` and `futures trials` pools unless they are given
`--include-vault`, and its trial is counted in the family's registry, so the family's `total_trials`
deflates for it.

### Auditing

```bash
uv run crucible vault log --limit 50    # every attempt, allowed or refused
```

Each row names the time, caller, purpose, dataset, `as_of`, outcome and registration.
`vault status` and `vault log` never report a metric: the numbers of the protected period live in the
sealed artifact of an evaluation that has run.

## 13. A prop-firm attempt (C7a/C7b, ADR-0106/0107)

A prop-firm ruleset is sourced, versioned data (`docs/modules/prop.md`); the engine knows rule
kinds, never a firm. Check one before using it:

```bash
uv run crucible prop validate path/to/ruleset.yaml          # identity, hash, evidence, scenarios
uv run crucible prop validate path/to/ruleset.yaml --json   # the same document
uv run crucible prop list --firm <firm> --json              # every ruleset, hash and evidence
uv run crucible prop confirm path/to/ruleset.yaml           # OWNER ONLY: interactive TTY
uv run crucible schema --kind prop-ruleset                  # the file's JSON Schema
uv run crucible schema --kind prop-attempt                  # the result's JSON Schema
```

`prop list` lists `rulesets/prop/**` with each file's id, version, content hash, evidence counts,
conflicts, unmodeled rules by materiality and verification status; a v1 file is shown as
`pending_migration`. `prop confirm` is the owner's step only: it refuses without a TTY, prints
every rule with its quotation and URL, asks for the first 12 hex of the content hash and writes
`<file>.verification.yaml`. It is never exposed over MCP. `rulesets/prop/INDEX.json` is generated
by `uv run python -m tools.docgen --write` and is append-only.

`prop validate` changes no file. It reports the ruleset's `ruleset_sha256`, its verification status
(only the owner can confirm a ruleset, and a synthetic one can never be `verified`), one
`rule_coverage` row per rule, the `evaluation_status` (`complete`, `conditional_on_modeled_rules`
or `blocked`) and the warnings those gaps imply. A ruleset marked `unverified` makes every result
`unverified_ruleset: true`, and a data window that starts before the ruleset's `effective_from` is
labelled a counterfactual application.

Running an attempt is a library call until C7c gives it a run config:

```python
from crucible.prop import load_ruleset, scenarios, simulate_attempt

ruleset = load_ruleset("path/to/ruleset.yaml")
for item in scenarios(ruleset):   # primary, then one sensitivity per conflict alternative
    result = simulate_attempt(
        bars=bars, targets=targets, rolls=rolls, spec=spec, costs=costs,
        ruleset=item.ruleset, start_trade_date=date(2024, 1, 8), max_horizon_days=20,
        calendar=calendar,            # the CME session calendar: it decides when a rule-day ends
        payout_policy="max_eligible", # the trader's choice, not a firm rule; "none" takes none
        execution_mode="manual",      # REQUIRED: automated|manual, for compliance eligibility
        news_events=events,           # Sequence[NewsEvent] or None
        news_coverage=coverage,       # Sequence[(start_ns, end_ns)] or None
        scenario_id=item.scenario_id,
    )
    result.outcome          # pass | fail | timeout | censored (the mechanical account)
    result.mechanical_outcome, result.estimate_status   # what may be claimed, and why
    result.practical_eligibility  # eligible | blocked_by_compliance | unknown
    result.breached_rule    # which rule ended it, and when
    result.min_buffer_usd   # the smallest distance to a failure threshold, and where
    result.fees             # evaluation, activation, monthly (per started month) and reset
    result.payouts          # gross and net of every withdrawal
    result.evaluation_status, result.estimate_reasons, result.warnings
```

The ruleset's `commissions` replace the run's fee schedule; spread and slippage still come from
the run's `CostSchedule`. Unknown costs are never zero: `commissions.components` declares, per cost
component (exchange, clearing, NFA, other), whether the firm's per-side commission contains it
(`included`), charges it on top (`excluded`) or does not say (`unknown`), and every gap keeps the
cost-dependent statistics `unavailable`. A news rule with no calendar coverage is `not_modeled`
(material), so the estimate becomes `partial` rather than "no news".

A `censored` attempt is the data ending before the attempt resolved: it is its own class, never a
failure. `min_buffer_usd` and every money field are `Decimal`; the breach, lock, resize and payout
decisions are in `overlay_events`. The semantics are the conservative OHLC approximation
(`high_before_low_conservative`): a breach liquidates as a market order at its trigger price, not
at the threshold, so a fast market can fill worse.

## 14. A prop evaluation over a futures run (C7b, ADR-0107)

One attempt answers what one account did. A prop evaluation answers what MANY streaks of the same
strategy would have done: an attempt starts on every Globex trade date of a futures run's window,
over the run's own causal signal, and the result is the attempt sequence with its statistics.

```bash
uv run crucible futures prop     --config examples/futures/es_sma_cross.yaml     --ruleset rulesets/prop/topstep/topstep-trading-combine-50k.v1.yaml     --horizon 20 --execution-mode automated     --store data/processed --artifacts experiments
```

- `--horizon H` is the ANALYST's horizon, in TRADING days: an attempt still unresolved after H trade
  dates is a `horizon` outcome (or `censored` when the data itself ends first). It is refused when it
  is shorter than the ruleset's own time limit, because the firm's limit could then never fire.
- `--execution-mode automated|manual` is required and decides `practical_eligibility`: a firm that
  bans automated trading makes an automated strategy `blocked_by_compliance` even when the
  mechanical account passes.
- `--payout-policy max_eligible|none` is the trader's choice, and `--scenarios primary|all` adds one
  sensitivity scenario per ruleset conflict.
- `--participant-profile FILE` is a flat YAML mapping from classification dimension to value that
  states who the run's account is, e.g.

  ```yaml
  cme_membership_status: non_member
  nfa_assessment_eligibility: fcm_member
  ```

  Each fee row names the ONE dimension it needs (`cme_membership_status` for the exchange and
  clearing fees, `nfa_assessment_eligibility` for the NFA assessment), so the profile is what
  resolves every component the firm charges on top of the commission. It is required as soon as a
  component is declared `excluded`; a dimension the profile leaves out (or declares `unknown`) makes
  that component a named gap, never a guess, and no fee is ever taken from a row whose value the
  profile does not match. The profile's canonical SHA-256 is recorded in `summary.json`, the sealed
  manifest and every `attempts.parquet` row, and it is part of the evaluation id, so two profiles are
  two artifacts. Using it makes the cost estimate `conditional` (`participant profile declared by
  the run, not stated by the firm`), never `complete`.
- `--cost-assumption FILE` is a YAML file (not a bare name) that prices the cost gaps the sources
  leave. It is the user's own unverified statement, it prices only the root and components it lists,
  and it is recorded by SHA-256; the estimate becomes `conditional`, never complete:

  ```yaml
  name: owner-estimate-2026-11-22
  description: the owner's working per-side figure, composition unknown
  provided_by: owner
  status: unverified            # the only accepted value
  evidence: the owner's note of 2026-11-22; no document states the split
  amounts:
    ES:
      - covers: [exchange, clearing]
        per_side_usd: '0.77'    # SYNTHETIC value, this file is an example
        unit: per_contract_per_side
      - covers: [nfa]
        per_side_usd: '0.02'
        unit: per_contract_per_side
  ```

  Every amount states `unit: per_contract_per_side` (a monthly or platform charge is refused: a
  fixed charge belongs in the ruleset's fee schedule), and an amount covering `other` also gives a
  `charge_name` — a specific one, since a generic name (`misc`, `CME other fees`) is refused.

  A component the file does not price stays a gap and the cash number stays `unavailable`. An
  `unknown` component it prices is ADDED (worse for the strategy), and it may not override a
  component the ruleset declares `included` or the fee dataset already priced.
- `--json` prints `summary.json` itself (the text rendering says the same numbers).

Reading it, in order:

1. **The counts.** `pass`, `fail`, `timeout`, `horizon`, `censored` per scenario. `censored` is
   never a failure and never a pass; `horizon` is the analyst's horizon, not a firm rule.
2. **The probability and its name.** `p` is passes over COMPLETE starts (those whose H trade dates
   fit in the data). The field is `pass_probability` only when nothing qualifies it; otherwise it is
   `conditional_pass_probability` with `definitive: false` and every reason: unmodeled rules, an
   unverified ruleset, a cost assumption, an unknown cost component, a declared participant profile, a
   news-calendar gap, an unsourced session-calendar window, the counterfactual application of a
   current ruleset to pre-2025 data, or a compliance blocker. Read the reasons before the number.
   `summary.json`'s `cost_components` lists, per root, the status each component ended with and the
   gaps that remained, so a cost that is not complete says exactly which component is missing.
3. **The bounds.** `p_low` counts censored attempts as failures and `p_high` counts them as passes.
   A wide `[p_low, p_high]` says the window is too short for the horizon, not that the strategy is
   uncertain in the same way.
4. **The interval.** A seeded circular block bootstrap over the complete starts in date order, with
   blocks at least H trade dates long, because attempt sequences overlap and are NOT independent.
   With fewer than two blocks it is `unavailable` with its reason. `effective_independent_attempts
   ≈ n / H` says how much independent information there is; on a one-year window with H = 20 it is
   about twelve.
5. **The cash.** Mean net cash per attempt (payouts minus the ruleset's fees), labelled `exact`,
   `conditional`, `upper_bound` or `unavailable`. The commissions are inside the simulated equity;
   the fee columns are the ruleset's own fees.
6. **The eligibility.** `eligible`, or `blocked_by_compliance` with `practically_valid_passes: 0`:
   a mechanically successful attempt under a compliance blocker is never a practically valid pass.

The artifact is `<artifacts>/PRP-<16 hex>/` with `attempts.parquet` (one row per scenario and start),
`summary.json`, the `ruleset.yaml` that was read and `manifest.json` with the seal. It is NOT a
submission: no trial is recorded and `submission_count`/`total_trials` do not move. There is no
threshold and no verdict — a pass probability is not evidence of an edge, and the same data under a
different ruleset is a different question.

## Known gaps

- No Python API to *list* experiments in an artifact root; use `crucible compare <family>` or
  list the directories (`EXP-*`).
- `compare` works within one family only, not across families.
- `load_experiment` re-validates `config.yaml` with the current code: a run whose config used a
  field that has since been removed will not load (`docs/COMPATIBILITY.md` §5 says fields are
  deprecated, not deleted, for this reason).
