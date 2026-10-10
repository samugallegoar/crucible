"""Property: all three null-test bar transforms always produce valid OHLC
bars (high >= max(open,close), low <= min(open,close), positive prices)
and never touch event_time/available_at/symbol (ADR-0019)."""

from __future__ import annotations

import numpy as np
import polars as pl
from hypothesis import given, settings
from hypothesis import strategies as st

from crucible.data.transforms import (
    shuffle_bar_returns,
    sign_flip_returns,
    synthetic_gbm_like,
)


def _make_bars(n_bars: int, first_open: float, returns: list[float]) -> pl.DataFrame:
    """A single symbol's worth of valid bars, built from small returns so
    reconstruction can never drive a price non-positive."""
    opens = [first_open]
    closes = []
    for r in returns:
        c = opens[-1] * (1.0 + r)
        closes.append(c)
        opens.append(c)
    opens = opens[:n_bars]
    highs = [max(o, c) * 1.01 for o, c in zip(opens, closes, strict=True)]
    lows = [min(o, c) * 0.99 for o, c in zip(opens, closes, strict=True)]
    return pl.DataFrame(
        {
            "symbol": ["SYM"] * n_bars,
            "event_time": list(range(1, n_bars + 1)),
            "available_at": list(range(1, n_bars + 1)),
            "open": opens,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": [1000.0 + i for i in range(n_bars)],
        }
    )


def _assert_valid(bars: pl.DataFrame, original: pl.DataFrame) -> None:
    for row in bars.iter_rows(named=True):
        assert row["high"] >= max(row["open"], row["close"]) - 1e-6
        assert row["low"] <= min(row["open"], row["close"]) + 1e-6
        assert row["open"] > 0
        assert row["close"] > 0
    assert bars["event_time"].to_list() == original["event_time"].to_list()
    assert bars["available_at"].to_list() == original["available_at"].to_list()
    assert bars["symbol"].to_list() == original["symbol"].to_list()


_small_returns = st.lists(
    st.floats(min_value=-0.05, max_value=0.05, allow_nan=False, allow_infinity=False),
    min_size=3,
    max_size=15,
)


@settings(deadline=None)
@given(returns=_small_returns, seed=st.integers(min_value=0, max_value=2**31 - 1))
def test_shuffle_always_produces_valid_ohlc(returns: list[float], seed: int) -> None:
    bars = _make_bars(len(returns), 100.0, returns)
    result = shuffle_bar_returns(bars, np.random.default_rng(seed))
    _assert_valid(result, bars)


@settings(deadline=None)
@given(returns=_small_returns)
def test_sign_flip_always_produces_valid_ohlc(returns: list[float]) -> None:
    bars = _make_bars(len(returns), 100.0, returns)
    result = sign_flip_returns(bars)
    _assert_valid(result, bars)


@settings(deadline=None)
@given(returns=_small_returns, seed=st.integers(min_value=0, max_value=2**31 - 1))
def test_synthetic_gbm_always_produces_valid_ohlc(returns: list[float], seed: int) -> None:
    bars = _make_bars(len(returns), 100.0, returns)
    result = synthetic_gbm_like(bars, np.random.default_rng(seed))
    _assert_valid(result, bars)
