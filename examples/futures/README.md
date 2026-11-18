# futures — a futures run on a continuous CME series

`es_sma_cross.yaml` is one complete **futures run** (ADR-0095): the ES root, one contract, a
30-bar SMA crossing traded long and short, four weeks of Globex trade dates
(2024-03-04 .. 2024-03-28), an explicit cost and execution policy and no overnight position. The
rule itself is `es_sma_cross_spec.yaml` (a strategy spec, resolved relative to the config's
directory, so editing it changes the run's config hash and therefore its run id).

```bash
# validate the config without touching any data
uv run crucible futures check --config examples/futures/es_sma_cross.yaml

# the run: one sealed artifact under experiments/
uv run crucible futures run --config examples/futures/es_sma_cross.yaml \
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

Tests: `tests/integration/test_futures_cli.py` validates this config on every run and runs it
against a real store only under `-m bench`
(`CRUCIBLE_DATA_STORE=… uv run pytest -m bench tests/integration/test_futures_cli.py`).
