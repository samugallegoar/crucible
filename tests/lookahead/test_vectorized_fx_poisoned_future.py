"""Poisoned-future test (R2.2a/R2.3) for the vectorized FX path (ADR-0062).

Absurd EUR/USD rates are injected into every FX row published after a cutoff; every output at or
before the cutoff (equity, lagged weights, per-symbol pnl) must be unchanged: a bar never reads a
rate that was not yet available, and the sizing at a bar uses the rate known at that bar.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import polars as pl
import pytest

from crucible.core.types import DatasetId, RealismLevel, TimestampNs
from crucible.data.contracts import (
    BAR_SCHEMA,
    BAR_SORT_KEYS,
    FX_RATE_SCHEMA,
    FX_RATE_SORT_KEYS,
)
from crucible.data.store import ParquetDataStore, build_dataset
from crucible.vectorized.engine import VectorizedBacktestEngine, VectorizedConfig

BARS = DatasetId("poison_fx_bars")
FX = DatasetId("poison_fx_rates")
N_BARS = 12
CUTOFF = 6
POISON = 1_000.0


def _signal(bars: pl.LazyFrame, params: dict[str, object]) -> pl.LazyFrame:
    return bars.select(
        symbol="symbol",
        ts=pl.col("event_time"),
        score=pl.when(pl.col("symbol") == "A").then(pl.lit(0.5)).otherwise(pl.lit(1.0)),
    )


def _build(root: Path, *, poison: bool) -> ParquetDataStore:
    bar_rows = [
        {
            "symbol": symbol,
            "event_time": ts,
            "available_at": ts,
            "open": px,
            "high": px,
            "low": px,
            "close": px,
            "volume": 1.0,
        }
        for symbol, base in (("A", 100.0), ("B", 50.0))
        for ts in range(1, N_BARS + 1)
        for px in [base * (1.0 + 0.01 * ((ts * 7) % 5 - 2))]
    ]
    fx_rows = [
        {
            "symbol": "EURUSD",
            "event_time": ts,
            "available_at": ts,
            "mid": (1.0 + 0.02 * ts) * (POISON if poison and ts > CUTOFF else 1.0),
            "bid": 1.0,
            "ask": 1.0,
        }
        for ts in range(1, N_BARS + 1)
    ]
    build_dataset(
        root,
        BARS,
        pl.from_dicts(bar_rows, schema=BAR_SCHEMA),
        schema=BAR_SCHEMA,
        sort_keys=BAR_SORT_KEYS,
        source="test",
    )
    build_dataset(
        root,
        FX,
        pl.from_dicts(fx_rows, schema=FX_RATE_SCHEMA),
        schema=FX_RATE_SCHEMA,
        sort_keys=FX_RATE_SORT_KEYS,
        source="test",
    )
    return ParquetDataStore(root)


def _run(store: ParquetDataStore):  # type: ignore[no-untyped-def]
    return VectorizedBacktestEngine().run(
        VectorizedConfig(
            store=store,
            bars_dataset=BARS,
            signal=_signal,
            params={},
            initial_cash=Decimal("1000"),
            realism_level=RealismLevel.FRICTIONLESS,
            start=TimestampNs(1),
            end=TimestampNs(N_BARS),
            base_currency="USD",
            symbol_currency={"B": "EUR"},
            fx_dataset=FX,
        )
    )


@pytest.mark.lookahead
def test_poisoning_future_fx_rates_does_not_change_outputs_at_or_before_the_cutoff(
    tmp_path: Path,
) -> None:
    clean = _run(_build(tmp_path / "clean", poison=False))
    poisoned = _run(_build(tmp_path / "poisoned", poison=True))
    for name, a, b in (
        ("equity", clean.equity, poisoned.equity),
        ("weights", clean.weights, poisoned.weights),
        ("pnl", clean.pnl, poisoned.pnl),
    ):
        assert a.filter(pl.col("ts") <= CUTOFF).equals(b.filter(pl.col("ts") <= CUTOFF)), (
            f"{name}: outputs at or before the cutoff changed: lookahead leak"
        )
    # sanity: the poison had teeth after the cutoff
    assert not clean.equity.filter(pl.col("ts") > CUTOFF).equals(
        poisoned.equity.filter(pl.col("ts") > CUTOFF)
    )
