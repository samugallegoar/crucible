# real_data — examples on the imported datasets

Three runnable configs on datasets built from the sources described in `docs/data/` (ADR-0052). Build a
dataset first, then run:

```bash
uv run crucible data build examples/imports/equities_daily.yaml --store data/processed
uv run crucible run examples/real_data/equities_momentum.yaml
```

| Config | Strategy | Dataset | Build spec |
|---|---|---|---|
| `equities_momentum.yaml` | `examples.momentum.strategy:Momentum` | `equities_daily_v1` | `examples/imports/equities_daily.yaml` |
| `gold_trend.yaml` | `examples.trend_demo.strategy:TrendFollower` | `xauusd_15m_v1` | `examples/imports/xau_15m.yaml` |
| `polymarket_up.yaml` | `examples.real_data.polymarket_up:BuyCheapUp` | `polymarket_btc5m_csv_v1` (+ `_actions`) | `examples/imports/polymarket_csv.yaml` |

The equities config lists three symbols as a template: put the tickers you want in
`strategy.params.symbols` (the benchmark uses all 569). Every config skips `calendar_coverage`
with a recorded reason (see the data pages under `docs/data/`).

Tests: `tests/integration/test_real_data_examples.py` (small hand-built stores with the same
dataset ids), `tests/lookahead/test_poisoned_future_polymarket_up.py`, and the opt-in
benchmarks in `tests/bench/` (`uv run pytest -m bench tests/bench -s`), whose results are in
`docs/data/scale.md`.

Limits: adjusted equity prices are not raw prices; the gold timezone is unverified; Polymarket
bars hold the bid/ask mid with zero volume, so `polymarket_up.yaml` (Level 1) fills at the mid and
is optimistic; `polymarket_up_quoted.yaml` (Level 2, `spread: quoted`, ADR-0060) fills buys at the
ask and sells at the bid using the quotes the bars carry (rebuild the dataset to get them).
