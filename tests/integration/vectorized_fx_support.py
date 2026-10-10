"""Shared fixtures for the vectorized FX runner and promotion tests (ADR-0062).

``build_store(root, symbols=("B",))`` gives the single-foreign-symbol store the promotion
agreement test needs; the default two-symbol store (``A`` USD, ``B`` EUR) backs the multi-symbol
agreement tests (``PromotedSignalStrategy`` rebalances on the last bar of each timestamp, ADR-0064).


Importable from ``tests/integration`` only (like ``checkpoint_support``). A two-symbol store: ``A``
quoted in USD and ``B`` quoted in EUR, 30 daily bars on one aligned calendar, every bar's ``open``
equal to the previous close (so a next-open fill equals the previous close), plus an ``EURUSD`` rate
series that starts at 1.25. ``constant_weights`` is the signal: 0.5 in each symbol on every bar.
"""

from __future__ import annotations

from pathlib import Path

import polars as pl
import yaml

from crucible.core.types import DatasetId
from crucible.data.contracts import (
    BAR_SCHEMA,
    BAR_SORT_KEYS,
    FX_RATE_SCHEMA,
    FX_RATE_SORT_KEYS,
)
from crucible.data.store import build_dataset
from crucible.experiments.config import ExperimentConfig

DAY_NS = 86_400 * 10**9
N_BARS = 30
BARS = "fx_support_bars"
FX = "fx_support_rates"
B_FIRST_CLOSE = 50.0
FX_FIRST = 1.25


def closes(symbol: str) -> list[float]:
    if symbol == "A":
        return [100.0 + (k * 3) % 7 - 3 for k in range(N_BARS)]
    return [B_FIRST_CLOSE + ((k * 5) % 9) * 0.5 for k in range(N_BARS)]


def rates() -> list[float]:
    return [FX_FIRST + 0.01 * ((k * 2) % 5) for k in range(N_BARS)]


def constant_weights(bars: pl.LazyFrame, params: dict[str, object]) -> pl.LazyFrame:
    """0.5 in every symbol on every bar (a vectorized SignalFunction)."""
    return bars.select(symbol="symbol", ts=pl.col("event_time"), score=pl.lit(0.5))


def build_store(root: Path, symbols: tuple[str, ...] = ("A", "B")) -> None:
    rows: list[dict[str, object]] = []
    for symbol in symbols:
        series = closes(symbol)
        for k, close in enumerate(series):
            open_ = series[k - 1] if k else close
            ts = (k + 1) * DAY_NS
            rows.append(
                {
                    "symbol": symbol,
                    "event_time": ts,
                    "available_at": ts,
                    "open": open_,
                    "high": max(open_, close),
                    "low": min(open_, close),
                    "close": close,
                    "volume": 1e9,
                }
            )
    build_dataset(
        root,
        DatasetId(BARS),
        pl.from_dicts(rows, schema=BAR_SCHEMA),
        schema=BAR_SCHEMA,
        sort_keys=BAR_SORT_KEYS,
        source="test",
    )
    fx_rows = [
        {
            "symbol": "EURUSD",
            "event_time": (k + 1) * DAY_NS,
            "available_at": (k + 1) * DAY_NS,
            "mid": mid,
            "bid": mid,
            "ask": mid,
        }
        for k, mid in enumerate(rates())
    ]
    build_dataset(
        root,
        DatasetId(FX),
        pl.from_dicts(fx_rows, schema=FX_RATE_SCHEMA),
        schema=FX_RATE_SCHEMA,
        sort_keys=FX_RATE_SORT_KEYS,
        source="test",
    )


def vectorized_config(root: Path, *, with_fx: bool = True) -> ExperimentConfig:
    raw = yaml.safe_load(
        Path("examples/trend_demo/config_vectorized.yaml").read_text(encoding="utf-8")
    )
    assert isinstance(raw, dict)
    raw["data"].update(
        {
            "store": str(root),
            "bars": BARS,
            "calendar": "24/7",
            "base_currency": "USD",
            "symbol_currency": {"B": "EUR"},
            "quality_skip": ["calendar_coverage"],
            "quality_skip_reason": "synthetic daily bars on a 24/7 calendar",
        }
    )
    if with_fx:
        raw["data"]["fx_rates"] = FX
    raw["strategy"]["entrypoint"] = "vectorized_fx_support:constant_weights"
    raw["strategy"]["params"] = {}
    raw["initial_cash"] = "1000000000"
    raw["start"], raw["end"] = "1970-01-01", "1970-03-01"
    raw["periods_per_year"] = 365.0
    return ExperimentConfig.model_validate(raw)
