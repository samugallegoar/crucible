"""Unit tests for the vectorized Level 0/1 engine (ADR-0035):
shift discipline, equity compounding (hand-computed), and level gating.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING

import polars as pl
import pytest

from crucible.core.errors import ConfigurationError
from crucible.core.types import DatasetId, RealismLevel, TimestampNs
from crucible.data.contracts import BAR_SCHEMA, BAR_SORT_KEYS
from crucible.data.store import ParquetDataStore, build_dataset
from crucible.vectorized.engine import VectorizedBacktestEngine, VectorizedConfig

if TYPE_CHECKING:
    from collections.abc import Sequence

BARS_DATASET = DatasetId("test_bars")


def _bar(symbol: str, ts: int, close: float) -> dict[str, object]:
    return {
        "symbol": symbol,
        "event_time": ts,
        "available_at": ts,
        "open": close,
        "high": close,
        "low": close,
        "close": close,
        "volume": 1_000.0,
    }


def _store(tmp_path: Path, rows: Sequence[dict[str, object]]) -> ParquetDataStore:
    frame = pl.from_dicts(list(rows), schema=BAR_SCHEMA)
    build_dataset(
        tmp_path, BARS_DATASET, frame, schema=BAR_SCHEMA, sort_keys=BAR_SORT_KEYS, source="test"
    )
    return ParquetDataStore(tmp_path)


def _identity_score_signal(bars: pl.LazyFrame, params: dict[str, object]) -> pl.LazyFrame:
    """A trivial signal: score == event_time itself. Used to check the
    engine's own shift mechanics in isolation from any real strategy math."""
    return bars.select(
        symbol="symbol",
        ts=pl.col("event_time"),
        score=pl.col("event_time").cast(pl.Float64),
    )


def _constant_long_signal(bars: pl.LazyFrame, params: dict[str, object]) -> pl.LazyFrame:
    return bars.select(symbol="symbol", ts=pl.col("event_time"), score=pl.lit(1.0))


def test_shift_discipline_lags_score_by_exactly_one_bar_per_symbol(tmp_path: Path) -> None:
    rows = [_bar(sym, ts, 100.0 + ts) for sym in ("A", "B") for ts in (1, 2, 3, 4)]
    store = _store(tmp_path, rows)
    config = VectorizedConfig(
        store=store,
        bars_dataset=BARS_DATASET,
        signal=_identity_score_signal,
        params={},
        initial_cash=Decimal("1000"),
        realism_level=RealismLevel.FRICTIONLESS,
        start=TimestampNs(1),
        end=TimestampNs(4),
    )
    result = VectorizedBacktestEngine().run(config)
    by_symbol = {
        sym: {
            row["ts"]: row["weight"]
            for row in result.weights.filter(pl.col("symbol") == sym).to_dicts()
        }
        for sym in ("A", "B")
    }
    # weight[t] must equal score[t-1] (score == ts for this signal); the
    # very first bar of each symbol has no prior score, so it's flat (0.0).
    for sym in ("A", "B"):
        assert by_symbol[sym][1] == 0.0
        assert by_symbol[sym][2] == 1.0
        assert by_symbol[sym][3] == 2.0
        assert by_symbol[sym][4] == 3.0
    # symbols never leak into each other's lag window
    assert set(by_symbol["A"]) == {1, 2, 3, 4}
    assert set(by_symbol["B"]) == {1, 2, 3, 4}


def test_shift_discipline_respects_a_larger_configured_lag(tmp_path: Path) -> None:
    rows = [_bar("A", ts, 100.0 + ts) for ts in (1, 2, 3, 4, 5)]
    store = _store(tmp_path, rows)
    config = VectorizedConfig(
        store=store,
        bars_dataset=BARS_DATASET,
        signal=_identity_score_signal,
        params={},
        initial_cash=Decimal("1000"),
        realism_level=RealismLevel.FRICTIONLESS,
        start=TimestampNs(1),
        end=TimestampNs(5),
        lag_bars=2,
    )
    result = VectorizedBacktestEngine().run(config)
    weight_by_ts = {row["ts"]: row["weight"] for row in result.weights.to_dicts()}
    assert weight_by_ts == {1: 0.0, 2: 0.0, 3: 1.0, 4: 2.0, 5: 3.0}


def test_equity_compounds_close_to_close_returns_hand_computed(tmp_path: Path) -> None:
    closes = {1: 100.0, 2: 110.0, 3: 121.0, 4: 108.9}  # +10%, +10%, -10%
    rows = [_bar("X", ts, px) for ts, px in closes.items()]
    store = _store(tmp_path, rows)
    config = VectorizedConfig(
        store=store,
        bars_dataset=BARS_DATASET,
        signal=_constant_long_signal,
        params={},
        initial_cash=Decimal("1000"),
        realism_level=RealismLevel.FRICTIONLESS,
        start=TimestampNs(1),
        end=TimestampNs(4),
    )
    result = VectorizedBacktestEngine().run(config)
    equity_by_ts = {row["ts"]: row["equity"] for row in result.equity.to_dicts()}
    # bar 1: no prior score -> flat -> unchanged; bars 2-3: fully long into
    # +10%/+10%; bar 4: fully long into -10%.
    assert equity_by_ts[1] == pytest.approx(1000.0)
    assert equity_by_ts[2] == pytest.approx(1100.0)
    assert equity_by_ts[3] == pytest.approx(1210.0)
    assert equity_by_ts[4] == pytest.approx(1089.0)


def test_turnover_cost_applies_at_basic_friction(tmp_path: Path) -> None:
    """score flips 0 -> 1 -> 0 -> 1 each bar (via lag, weight flips one bar
    later); each flip is a full turnover of 1.0, charged at
    (slippage_bps + commission_bps) bps of notional."""

    def flipping_signal(bars: pl.LazyFrame, params: dict[str, object]) -> pl.LazyFrame:
        return bars.select(
            symbol="symbol",
            ts=pl.col("event_time"),
            score=(pl.col("event_time") % 2 == 0).cast(pl.Float64),
        )

    rows = [_bar("X", ts, 100.0) for ts in (1, 2, 3, 4, 5)]  # flat prices: isolates cost from PnL
    store = _store(tmp_path, rows)
    config = VectorizedConfig(
        store=store,
        bars_dataset=BARS_DATASET,
        signal=flipping_signal,
        params={},
        initial_cash=Decimal("1000"),
        realism_level=RealismLevel.BASIC_FRICTION,
        start=TimestampNs(1),
        end=TimestampNs(5),
        slippage_bps=10.0,
        commission_bps=5.0,
    )
    result = VectorizedBacktestEngine().run(config)
    equity_by_ts = {row["ts"]: row["equity"] for row in result.equity.to_dicts()}
    cost_rate = 15.0 / 10_000.0
    # score: ts2=1,ts4=1, others 0 -> weight (shift 1): ts1=0,ts2=0,ts3=1,ts4=0,ts5=1
    # turnover: |0-0|=0, |0-0|=0, |1-0|=1, |0-1|=1, |1-0|=1
    expected = 1000.0
    for turnover in (0.0, 0.0, 1.0, 1.0, 1.0):
        expected *= 1.0 - turnover * cost_rate  # flat prices -> gross return is 0
    assert equity_by_ts[5] == pytest.approx(expected)


def test_frictionless_refuses_nonzero_slippage(tmp_path: Path) -> None:
    store = _store(tmp_path, [_bar("X", 1, 100.0), _bar("X", 2, 101.0)])
    config = VectorizedConfig(
        store=store,
        bars_dataset=BARS_DATASET,
        signal=_constant_long_signal,
        params={},
        initial_cash=Decimal("1000"),
        realism_level=RealismLevel.FRICTIONLESS,
        start=TimestampNs(1),
        end=TimestampNs(2),
        slippage_bps=1.0,
    )
    with pytest.raises(ConfigurationError, match="FRICTIONLESS"):
        VectorizedBacktestEngine().run(config)


def test_refuses_realism_level_two_or_higher(tmp_path: Path) -> None:
    store = _store(tmp_path, [_bar("X", 1, 100.0), _bar("X", 2, 101.0)])
    config = VectorizedConfig(
        store=store,
        bars_dataset=BARS_DATASET,
        signal=_constant_long_signal,
        params={},
        initial_cash=Decimal("1000"),
        realism_level=RealismLevel.SPREAD_LATENCY,
        start=TimestampNs(1),
        end=TimestampNs(2),
    )
    with pytest.raises(ConfigurationError, match="event-driven engine"):
        VectorizedBacktestEngine().run(config)


def test_refuses_lag_bars_below_one(tmp_path: Path) -> None:
    store = _store(tmp_path, [_bar("X", 1, 100.0), _bar("X", 2, 101.0)])
    config = VectorizedConfig(
        store=store,
        bars_dataset=BARS_DATASET,
        signal=_constant_long_signal,
        params={},
        initial_cash=Decimal("1000"),
        realism_level=RealismLevel.FRICTIONLESS,
        start=TimestampNs(1),
        end=TimestampNs(2),
        lag_bars=0,
    )
    with pytest.raises(ConfigurationError, match="lag_bars"):
        VectorizedBacktestEngine().run(config)


def test_refuses_a_signal_function_missing_the_score_column(tmp_path: Path) -> None:
    def broken_signal(bars: pl.LazyFrame, params: dict[str, object]) -> pl.LazyFrame:
        return bars.select(symbol="symbol", ts=pl.col("event_time"))

    store = _store(tmp_path, [_bar("X", 1, 100.0), _bar("X", 2, 101.0)])
    config = VectorizedConfig(
        store=store,
        bars_dataset=BARS_DATASET,
        signal=broken_signal,
        params={},
        initial_cash=Decimal("1000"),
        realism_level=RealismLevel.FRICTIONLESS,
        start=TimestampNs(1),
        end=TimestampNs(2),
    )
    with pytest.raises(ConfigurationError, match="score"):
        VectorizedBacktestEngine().run(config)


def test_result_carries_a_per_symbol_gross_pnl_frame(tmp_path: Path) -> None:
    """Same data as the hand-computed compounding test: closes 100, 110, 121, 108.9 and a constant
    long score, so the lagged weights are 0, 1, 1, 1. Gross pnl per bar is prior equity * weight *
    return: 0, 1000*1*0.10 = 100, 1100*1*0.10 = 110, 1210*1*(-0.10) = -121 (the equity change)."""
    closes = {1: 100.0, 2: 110.0, 3: 121.0, 4: 108.9}
    store = _store(tmp_path, [_bar("X", ts, px) for ts, px in closes.items()])
    result = VectorizedBacktestEngine().run(
        VectorizedConfig(
            store=store,
            bars_dataset=BARS_DATASET,
            signal=_constant_long_signal,
            params={},
            initial_cash=Decimal("1000"),
            realism_level=RealismLevel.FRICTIONLESS,
            start=TimestampNs(1),
            end=TimestampNs(4),
        )
    )
    assert result.pnl.schema == pl.Schema(
        {"ts": pl.Int64(), "symbol": pl.String(), "pnl": pl.Float64()}
    )
    assert result.pnl.sort("ts")["pnl"].to_list() == pytest.approx([0.0, 100.0, 110.0, -121.0])
    assert result.pnl["symbol"].unique().to_list() == ["X"]
