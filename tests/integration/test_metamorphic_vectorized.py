"""Metamorphic properties of the vectorized engine (ADR-0070). It sizes positions as
fractional weights and charges costs in bps of traded notional, so its returns must be
invariant to the price scale and to the row order of the stored bars. (The event-driven
engine trades whole shares with per-share commissions, so price scale is not invariant
there and is not asserted.)"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import numpy as np
import polars as pl
import pytest

from crucible.analytics.metrics import simple_returns
from crucible.core.types import DatasetId, RealismLevel, TimestampNs
from crucible.data.contracts import BAR_SCHEMA, BAR_SORT_KEYS
from crucible.data.store import ParquetDataStore, build_dataset
from crucible.vectorized.engine import VectorizedBacktestEngine, VectorizedConfig

DAY = 86_400 * 10**9
N = 400
BARS = DatasetId("meta_bars")


def _bars(scale: float) -> pl.DataFrame:
    rng = np.random.default_rng(42)
    frames = []
    for symbol, drift in (("A", 0.0006), ("B", -0.0002)):
        closes = 50.0 * scale * np.cumprod(1.0 + rng.normal(drift, 0.012, N))
        opens = np.r_[50.0 * scale, closes[:-1]] * (1.0 + rng.normal(0.0, 0.002, N))
        frames.append(
            pl.DataFrame(
                {
                    "symbol": [symbol] * N,
                    "event_time": [d * DAY for d in range(1, N + 1)],
                    "available_at": [d * DAY for d in range(1, N + 1)],
                    "open": opens,
                    "high": np.maximum(opens, closes) * 1.003,
                    "low": np.minimum(opens, closes) * 0.997,
                    "close": closes,
                    "volume": np.full(N, 1e6),
                }
            )
        )
    return pl.concat(frames)


def _momentum(bars: pl.DataFrame, params: dict[str, object]) -> pl.DataFrame:
    return (
        bars.select(pl.col("event_time").alias("ts"), "symbol", "close")
        .sort(["symbol", "ts"])
        .with_columns(
            score=(pl.col("close") / pl.col("close").shift(20).over("symbol") - 1.0)
            .sign()
            .fill_null(0.0)
        )
        .select("ts", "symbol", "score")
    )


def _returns(root: Path, bars: pl.DataFrame) -> np.ndarray:
    build_dataset(root, BARS, bars, schema=BAR_SCHEMA, sort_keys=BAR_SORT_KEYS, source="test")
    result = VectorizedBacktestEngine().run(
        VectorizedConfig(
            store=ParquetDataStore(root),
            bars_dataset=BARS,
            signal=_momentum,
            params={},
            initial_cash=Decimal("100000"),
            realism_level=RealismLevel.BASIC_FRICTION,
            start=TimestampNs(DAY),
            end=TimestampNs(N * DAY),
            slippage_bps=2.0,
            commission_bps=1.0,
        )
    )
    return simple_returns(result.equity)


@pytest.mark.parametrize("scale", [0.01, 7.0, 1000.0])
def test_returns_are_invariant_to_the_price_scale(tmp_path: Path, scale: float) -> None:
    base = _returns(tmp_path / "base", _bars(1.0))
    scaled = _returns(tmp_path / "scaled", _bars(scale))
    np.testing.assert_allclose(scaled, base, rtol=0, atol=1e-12)


def test_returns_do_not_depend_on_the_row_order_of_the_input(tmp_path: Path) -> None:
    bars = _bars(1.0)
    shuffled = bars.sample(fraction=1.0, shuffle=True, seed=3)
    assert shuffled["event_time"].to_list() != bars["event_time"].to_list()
    base = _returns(tmp_path / "base", bars)
    np.testing.assert_array_equal(_returns(tmp_path / "shuffled", shuffled), base)
