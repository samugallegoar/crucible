"""The real-data examples run end to end on small hand-built stores (ADR-0054).

The configs point at the imported datasets in ``data/processed/`` (local, gitignored); these
tests keep the configs' structure and swap in tiny stores with the same dataset ids and schema,
so the default suite never depends on local data.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any

import polars as pl
import pytest
import yaml

from crucible.core.types import DatasetId, to_timestamp_ns
from crucible.data.calendars import ExchangeCalendarAdapter
from crucible.data.contracts import BAR_SCHEMA, BAR_SORT_KEYS
from crucible.data.importers.build import build_from_spec
from crucible.data.store import build_dataset
from crucible.experiments.config import ExperimentConfig
from crucible.experiments.runner import run_experiment

NS = 10**9
CSV_HEADER = (
    "slug,start_time,elapsed,ask_YES,bid_YES,ask_NO,bid_NO,btc_strike,btc_current,btc_gap,"
    "timestamp_log,resolved,winner"
)


def _raw(name: str, store: Path) -> dict[str, Any]:
    raw = yaml.safe_load(Path(f"examples/real_data/{name}").read_text(encoding="utf-8"))
    raw["data"]["store"] = str(store)
    return raw


def _bars(symbol_closes: dict[str, list[float]], closes_ns: list[int]) -> pl.DataFrame:
    rows: list[dict[str, Any]] = []
    for symbol, closes in symbol_closes.items():
        for ts, close in zip(closes_ns, closes, strict=True):
            rows.append(
                {
                    "symbol": symbol,
                    "event_time": ts,
                    "available_at": ts,
                    "open": close * 0.999,
                    "high": close * 1.002,
                    "low": close * 0.997,
                    "close": close,
                    "volume": 1000.0,
                }
            )
    return pl.DataFrame(rows)


def test_all_example_configs_load_and_record_their_quality_skip() -> None:
    for name in (
        "equities_momentum.yaml",
        "gold_trend.yaml",
        "polymarket_up.yaml",
        "polymarket_up_quoted.yaml",
    ):
        config = ExperimentConfig.model_validate(_raw(name, Path("data/processed")))
        assert config.data.quality_skip == ("calendar_coverage",)
        assert config.data.quality_skip_reason


def test_the_equities_momentum_example_runs_on_a_small_store(tmp_path: Path) -> None:
    start = to_timestamp_ns(dt.datetime(2020, 1, 1, tzinfo=dt.UTC))
    end = to_timestamp_ns(dt.datetime(2020, 4, 1, tzinfo=dt.UTC))
    calendar = ExchangeCalendarAdapter("XNYS", start=start, end=end)
    closes_ns = [int(c) for c in calendar.session_closes(start, end)]
    n = len(closes_ns)
    symbols = {f"S{i}": [100.0 + i + k * (0.5 + 0.2 * i) for k in range(n)] for i in range(6)}
    build_dataset(
        tmp_path / "store",
        DatasetId("equities_daily_v1"),
        _bars(symbols, closes_ns),
        schema=BAR_SCHEMA,
        sort_keys=BAR_SORT_KEYS,
        source="test",
    )
    raw = _raw("equities_momentum.yaml", tmp_path / "store")
    raw["start"], raw["end"] = "2020-01-01", "2020-04-01"
    raw["strategy"]["params"].update(
        {"symbols": list(symbols), "lookback": 10, "top_k": 2, "rebalance_every": 5}
    )
    run = run_experiment(ExperimentConfig.model_validate(raw), tmp_path / "out", record_trial=False)
    assert pl.read_parquet(run.path / "fills.parquet").height > 0
    assert pl.read_parquet(run.path / "equity.parquet").height > 0


def test_the_gold_trend_example_runs_on_a_small_store(tmp_path: Path) -> None:
    start = to_timestamp_ns(dt.datetime(2020, 1, 6, tzinfo=dt.UTC))
    closes_ns = [start + (k + 1) * 900 * NS for k in range(96 * 4)]  # four days of 15m bars
    closes = [1500.0 + 0.4 * k + (3.0 if k % 7 == 0 else 0.0) for k in range(len(closes_ns))]
    build_dataset(
        tmp_path / "store",
        DatasetId("xauusd_15m_v1"),
        _bars({"XAUUSD": closes}, closes_ns),
        schema=BAR_SCHEMA,
        sort_keys=BAR_SORT_KEYS,
        source="test",
    )
    raw = _raw("gold_trend.yaml", tmp_path / "store")
    raw["start"], raw["end"] = "2020-01-06", "2020-01-11"
    raw["strategy"]["params"].update({"lookback": 8, "rebalance_every": 4})
    run = run_experiment(ExperimentConfig.model_validate(raw), tmp_path / "out", record_trial=False)
    assert pl.read_parquet(run.path / "equity.parquet").height > 0


def test_the_polymarket_example_holds_a_cheap_up_contract_through_settlement(
    tmp_path: Path,
) -> None:
    """UP bars at mid 0.40 (bid 0.38, ask 0.42) close at 1102, 1104, 1106. BuyCheapUp buys 100
    on the first bar (mid 0.40 < 0.45); it fills at the next bar's open 0.40 (cash 9960); the
    contract settles at 1.0 (winner Up), the delisting pays 100: final equity 10060."""
    rows = [
        f"btc-updown-5m-1000,1000,{ts - 1000},0.42,0.38,0.62,0.58,100.0,100.0,0.0,{ts},True,Up"
        for ts in (1100, 1102, 1104)
    ]
    (tmp_path / "pm.csv").write_text("\n".join([CSV_HEADER, *rows]) + "\n", encoding="utf-8")
    spec = tmp_path / "spec.yaml"
    spec.write_text(
        f"kind: polymarket_csv\ndataset: polymarket_btc5m_csv_v1\n"
        f"input: '{tmp_path / 'pm.csv'}'\nbar_seconds: 2\n",
        encoding="utf-8",
    )
    build_from_spec(spec, tmp_path / "store")
    raw = _raw("polymarket_up.yaml", tmp_path / "store")
    raw["start"], raw["end"] = "1970-01-01", "1970-01-01T01:00:00+00:00"
    run = run_experiment(ExperimentConfig.model_validate(raw), tmp_path / "out", record_trial=False)
    equity = pl.read_parquet(run.path / "equity.parquet").sort("ts")
    assert equity["equity"].to_list()[-1] == pytest.approx(10060.0)
    fills = pl.read_parquet(run.path / "fills.parquet")
    assert fills["price"].to_list() == [0.4]
