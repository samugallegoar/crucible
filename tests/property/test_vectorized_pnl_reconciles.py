"""Property: the engine's per-symbol pnl frame reconciles with its equity (ADR-0062).

With zero costs, at every timestamp the per-symbol gross pnl sums to the change in equity (the first
row against ``initial_cash``), for any number of symbols and any lagged weights.
"""

from __future__ import annotations

import tempfile
from decimal import Decimal
from pathlib import Path

import polars as pl
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from crucible.core.types import DatasetId, RealismLevel, TimestampNs
from crucible.data.contracts import BAR_SCHEMA, BAR_SORT_KEYS
from crucible.data.store import ParquetDataStore, build_dataset
from crucible.vectorized.engine import VectorizedBacktestEngine, VectorizedConfig

_WEIGHTS = st.sampled_from([-1.0, -0.5, 0.0, 0.5, 1.0])
_DATASET = DatasetId("pnl_bars")


@settings(max_examples=60, deadline=None)
@given(
    data=st.data(),
    n_symbols=st.integers(min_value=1, max_value=3),
    n_bars=st.integers(min_value=3, max_value=25),
)
def test_pnl_frame_sums_to_the_equity_change(
    data: st.DataObject, n_symbols: int, n_bars: int
) -> None:
    symbols = [f"S{i}" for i in range(n_symbols)]
    rows: list[dict[str, object]] = []
    weights: dict[tuple[str, int], float] = {}
    for symbol in symbols:
        close = 100.0
        for t in range(1, n_bars + 1):
            close *= 1.0 + data.draw(st.floats(min_value=-0.2, max_value=0.2))
            rows.append(
                {
                    "symbol": symbol,
                    "event_time": t,
                    "available_at": t,
                    "open": close,
                    "high": close,
                    "low": close,
                    "close": close,
                    "volume": 1.0,
                }
            )
            weights[(symbol, t)] = data.draw(_WEIGHTS)

    def signal(bars: pl.LazyFrame, params: dict[str, object]) -> pl.LazyFrame:
        return bars.select(
            symbol="symbol",
            ts=pl.col("event_time"),
            score=pl.struct("symbol", "event_time").map_elements(
                lambda s: weights[(s["symbol"], s["event_time"])], return_dtype=pl.Float64
            ),
        )

    with tempfile.TemporaryDirectory() as tmp:
        build_dataset(
            Path(tmp),
            _DATASET,
            pl.from_dicts(rows, schema=BAR_SCHEMA),
            schema=BAR_SCHEMA,
            sort_keys=BAR_SORT_KEYS,
            source="test",
        )
        result = VectorizedBacktestEngine().run(
            VectorizedConfig(
                store=ParquetDataStore(Path(tmp)),
                bars_dataset=_DATASET,
                signal=signal,
                params={},
                initial_cash=Decimal("1000"),
                realism_level=RealismLevel.FRICTIONLESS,
                start=TimestampNs(1),
                end=TimestampNs(n_bars),
            )
        )

    equity = dict(
        zip(result.equity["ts"].to_list(), result.equity["equity"].to_list(), strict=True)
    )
    per_ts = result.pnl.group_by("ts").agg(pl.col("pnl").sum()).sort("ts")
    previous = 1000.0
    for ts, pnl_sum in per_ts.iter_rows():
        assert pnl_sum == pytest.approx(equity[ts] - previous, abs=1e-9 * 1000.0, rel=1e-9)
        previous = equity[ts]
    assert set(result.pnl["ts"].to_list()) <= set(range(1, n_bars + 1))
