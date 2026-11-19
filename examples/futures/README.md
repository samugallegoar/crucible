# futures — a futures run on a continuous CME series

`es_sma_cross.yaml` is one complete **futures run** (ADR-0095): the ES root, one contract, a
30-bar SMA crossing traded long and short, four weeks of Globex trade dates
(2024-03-04 .. 2024-03-28), an explicit cost and execution policy and no overnight position. The
rule itself is `es_sma_cross_spec.yaml` (a strategy spec, resolved relative to the config's
directory, so editing it changes the run's config hash and therefore its run id).

`es_zscore_reversion.yaml` is the same run decided by a **DSL expression** instead of a spec
(ADR-0098): `strategy.expression` is a 60-bar z-score reversion with one free parameter,
`$n:int[10,240]=60`. It is compiled at load, so `futures check` prints its canonical text and its
three ids (`DSX-` structure, `DSP-` parameterization, `DSC-` compiled) and a bad expression is
refused before any data is read; `futures run` records the same document in the manifest's
`signal` block. The score reads the ratio-adjusted series, so it must be scale invariant
(ADR-0086): `ts_zscore(close, n)` is dimensionless while a price level or `delta(close, 1)` would
be refused at compile time. The expression language is documented in
[`docs/modules/dsl.md`](../../docs/modules/dsl.md).

`es_zscore_screen.yaml` is the same z-score run at a **fidelity level** (`fidelity: {preset:
screen}` = 15-minute bars + commission-only costs, ADR-0100): the cheap first pass over many
expressions. It is OPTIMISTIC about the cost of trading — spread and slippage are not charged — and
the manifest's `approximations` says so; a candidate that survives a screen must be re-run at
`standard` (5m, full costs) or `full` (1m, full costs). Its family is its own: marks at 15-minute
spacing are not poolable with 1-minute ones (ADR-0071).

`es_batch_screen.yaml` is a **batch** of three candidates on that base: `z60` and `z120` (the same
expression with `$n` bound to 60 and to 120: one structure id, two parameterizations) and
`z60-swapped`, a deliberate duplicate of `z60` written with `max(2, x)` instead of `max(x, 2)`. The
duplicate canonicalizes to the same expression, so the batch computes TWO runs and reports the third
candidate as `cached` with the first one's run and artifact ids. Every submitted candidate is
recorded in the trial registry's `submissions` table, while `trials` keeps one row per distinct run.

```bash
# validate the config without touching any data
uv run crucible futures check --config examples/futures/es_sma_cross.yaml
uv run crucible futures check --config examples/futures/es_zscore_reversion.yaml
uv run crucible futures check --config examples/futures/es_zscore_screen.yaml

# three expressions on that base, one sealed run each (plus the batch document)
uv run crucible futures batch --batch examples/futures/es_batch_screen.yaml     --store data/processed --artifacts experiments

# the run: one sealed artifact under experiments/
uv run crucible futures run --config examples/futures/es_sma_cross.yaml \
    --store data/processed --artifacts experiments
uv run crucible futures run --config examples/futures/es_zscore_reversion.yaml \
    --store data/processed --artifacts experiments
```

`futures run` prints the run id, the artifact id, the trial family and its count, the window, bars,
fills, the final balance and equity, every approximation the run recorded and the run directory;
`--json` prints the same as one document (`kind: futures_run`). A second identical run is refused
unless `--overwrite`, and a reproduction keeps the same artifact id and does not grow the family's
trial count.

## What it needs

The four `v3` continuous datasets of one CME root, built from the Databento delivery described in
[`docs/data/glbx-futures-1m.md`](../../docs/data/glbx-futures-1m.md):

```bash
uv run crucible data build examples/imports/glbx_futures_1m.yaml --store data/processed
uv run crucible data continuous --store data/processed --roots es --trim-to-calendar
```

The config names no datasets: `root: ES` defaults them to `es_1m_cont_v3`, `es_1m_cont_ratio_v3`,
`es_1m_rolls_v3` and `es_1m_raw`.

## This is not a strategy result

The example demonstrates the command and the artifact layout; **it makes no performance claim**
and none of its numbers is evidence of an edge. Read the artifact's `manifest.json`
`approximations` first: the spread and slippage in ticks are the config's assumption, not a
measurement on this instrument and period, and the marks and the P&L read each bar's OHLC without
a book. The artifact's `metrics.json` is descriptive (fills, costs, final balance and equity, the
intraday drawdown); a headline statistic with its confidence interval, trial count and DSR belongs
to `crucible run`/`validate`, not here (ADR-0008).

Tests: `tests/integration/test_futures_cli.py` validates these configs on every run and runs them
against a real store only under `-m bench`
(`CRUCIBLE_DATA_STORE=… uv run pytest -m bench tests/integration/test_futures_cli.py`); the batch
example is exercised (including the "no 15-minute bar spans a maintenance break" check) by
`tests/integration/test_futures_batch.py` under `-m bench`.
