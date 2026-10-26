"""The annualization factor is derived from the bars, not assumed daily (2026-10 audit, M5).

A per-bar Sharpe is annualized by sqrt(bars/year). The config default 252 is a *daily* factor;
an intraday run that left it untouched under-annualized by sqrt(bars per session) -- hourly on
XNYS: 0.81 instead of 2.13 for the same series.
"""

from __future__ import annotations

from pathlib import Path

import polars as pl
import yaml

from crucible.core.types import DatasetId, TimestampNs
from crucible.data.calendars import bars_per_session, get_trading_calendar, periods_per_year_for
from crucible.data.contracts import BAR_SCHEMA, BAR_SORT_KEYS
from crucible.data.store import ParquetDataStore, build_dataset
from crucible.experiments.config import ExperimentConfig
from crucible.experiments.runner import _periods_per_year

HOUR_NS = 3_600 * 10**9
BARS = DatasetId("bars_hourly_test")


def _session_closes() -> list[int]:
    cal = get_trading_calendar(
        "XNYS", start=TimestampNs(1_704_067_200 * 10**9), end=TimestampNs(1_704_931_200 * 10**9)
    )
    return [
        int(c)
        for c in cal.session_closes(
            TimestampNs(1_704_067_200 * 10**9), TimestampNs(1_704_931_200 * 10**9)
        )
    ][:5]


def _hourly_store(root: Path) -> ParquetDataStore:
    closes = _session_closes()
    stamps = sorted(close - k * HOUR_NS for close in closes for k in range(7))
    frame = pl.DataFrame(
        {
            "symbol": ["AAA"] * len(stamps),
            "event_time": stamps,
            "available_at": stamps,
            "open": [100.0] * len(stamps),
            "high": [101.0] * len(stamps),
            "low": [99.0] * len(stamps),
            "close": [100.0] * len(stamps),
            "volume": [1e6] * len(stamps),
        },
        schema=BAR_SCHEMA,
    )
    build_dataset(root, BARS, frame, schema=BAR_SCHEMA, sort_keys=BAR_SORT_KEYS, source="test")
    return ParquetDataStore(root)


def test_hourly_xnys_bars_are_1764_a_year() -> None:
    closes = _session_closes()
    stamps = sorted(close - k * HOUR_NS for close in closes for k in range(7))
    assert bars_per_session(stamps, "XNYS") == 7
    assert periods_per_year_for(stamps, "XNYS") == 1764.0
    daily = sorted(closes)
    assert periods_per_year_for(daily, "XNYS") == 252.0


def _config(store: Path, *, years: float | None = None) -> ExperimentConfig:
    raw = yaml.safe_load(
        Path("examples/trend_demo/config_vectorized.yaml").read_text(encoding="utf-8")
    )
    assert isinstance(raw, dict)
    raw["data"]["store"] = str(store)
    raw["data"]["bars"] = str(BARS)
    raw["data"]["calendar"] = "XNYS"
    raw.pop("periods_per_year", None)  # the shipped example sets it: exercise the untouched case
    raw["start"] = "2024-01-02"
    raw["end"] = "2024-01-09"
    if years is not None:
        raw["periods_per_year"] = years
    return ExperimentConfig.model_validate(raw)


def test_the_runner_derives_the_factor_from_the_bars(tmp_path: Path) -> None:
    store = _hourly_store(tmp_path)
    config = _config(tmp_path)
    assert "periods_per_year" not in config.model_fields_set
    assert _periods_per_year(config, store) == 1764.0


def test_an_explicit_factor_is_respected(tmp_path: Path) -> None:
    store = _hourly_store(tmp_path)
    config = _config(tmp_path, years=252.0)
    assert "periods_per_year" in config.model_fields_set
    assert _periods_per_year(config, store) == 252.0
