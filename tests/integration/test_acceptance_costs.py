"""Acceptance scenario (ADR-0070): an edge that exists before costs and disappears after
them. A high-turnover strategy (hold the sign of the last return) on synthetic returns with
weak positive autocorrelation earns a positive Sharpe frictionless, and the same rules lose
money once a realistic per-trade cost is charged. The engine must report both honestly."""

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
from crucible.validation.dsr import per_period_sharpe
from crucible.vectorized.engine import VectorizedBacktestEngine, VectorizedConfig

DAY = 86_400 * 10**9
N = 2_000
BARS = DatasetId("ar_bars")


def _ar1_closes(seed: int, phi: float = 0.05, sigma: float = 0.01) -> np.ndarray:
    rng = np.random.default_rng(seed)
    r = np.empty(N)
    r[0] = 0.0
    for t in range(1, N):
        r[t] = phi * r[t - 1] + sigma * rng.standard_normal()
    return 100.0 * np.cumprod(1.0 + r)


@pytest.fixture(scope="module")
def store(tmp_path_factory: pytest.TempPathFactory) -> ParquetDataStore:
    root: Path = tmp_path_factory.mktemp("ar_costs")
    closes = _ar1_closes(20261010)
    opens = np.r_[100.0, closes[:-1]]
    bars = pl.DataFrame(
        {
            "symbol": ["AR"] * N,
            "event_time": [d * DAY for d in range(1, N + 1)],
            "available_at": [d * DAY for d in range(1, N + 1)],
            "open": opens,
            "high": np.maximum(opens, closes) * 1.002,
            "low": np.minimum(opens, closes) * 0.998,
            "close": closes,
            "volume": np.full(N, 1e6),
        }
    )
    build_dataset(root, BARS, bars, schema=BAR_SCHEMA, sort_keys=BAR_SORT_KEYS, source="test")
    return ParquetDataStore(root)


def _follow_last_return(bars: pl.DataFrame, params: dict[str, object]) -> pl.DataFrame:
    return (
        bars.select(pl.col("event_time").alias("ts"), "symbol", "close")
        .sort(["symbol", "ts"])
        .with_columns(score=pl.col("close").pct_change().over("symbol").sign().fill_null(0.0))
        .select("ts", "symbol", "score")
    )


def _sharpe(store: ParquetDataStore, slippage_bps: float, commission_bps: float) -> float:
    result = VectorizedBacktestEngine().run(
        VectorizedConfig(
            store=store,
            bars_dataset=BARS,
            signal=_follow_last_return,
            params={},
            initial_cash=Decimal("100000"),
            realism_level=(
                RealismLevel.FRICTIONLESS
                if slippage_bps == commission_bps == 0
                else RealismLevel.BASIC_FRICTION
            ),
            start=TimestampNs(DAY),
            end=TimestampNs(N * DAY),
            slippage_bps=slippage_bps,
            commission_bps=commission_bps,
        )
    )
    return per_period_sharpe(simple_returns(result.equity))


def test_an_edge_that_exists_before_costs_disappears_after_them(store: ParquetDataStore) -> None:
    gross = _sharpe(store, 0.0, 0.0)
    standard = _sharpe(store, 1.0, 0.5)  # the "standard" preset
    conservative = _sharpe(store, 5.0, 2.0)  # the "conservative" preset
    assert gross > 0.03  # a real, if small, per-period edge from the autocorrelation
    assert gross > standard > conservative  # every basis point of cost comes off the result
    # a small-cap or wide-spread cost (10 + 5 bps): flipping about every other day costs more
    # than the autocorrelation earns (the conservative preset sits just at zero, -0.003)
    assert _sharpe(store, 10.0, 5.0) < -0.05
