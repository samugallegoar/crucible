"""Null-test bar transformations (ADR-0019).

Reference values were computed independently (a standalone script, not
this module) with the exact same decompose/reconstruct math, then
hardcoded."""

from __future__ import annotations

import numpy as np
import polars as pl
import pytest

from crucible.core.errors import DataQualityError
from crucible.data.transforms import (
    shuffle_bar_returns,
    sign_flip_returns,
    synthetic_gbm_like,
)

_BARS = pl.DataFrame(
    {
        "symbol": ["AAA", "AAA", "AAA", "AAA", "BBB", "BBB", "BBB", "BBB"],
        "event_time": [1, 2, 3, 4, 1, 2, 3, 4],
        "available_at": [1, 2, 3, 4, 1, 2, 3, 4],
        "open": [100.0, 102.0, 101.0, 105.0, 50.0, 49.0, 51.0, 50.5],
        "high": [103.0, 103.5, 106.0, 106.0, 50.5, 51.5, 52.0, 51.5],
        "low": [99.5, 100.5, 100.5, 104.0, 49.0, 48.5, 50.5, 49.5],
        "close": [102.0, 101.0, 105.0, 104.0, 49.0, 51.0, 50.5, 51.0],
        "volume": [1000.0, 1100.0, 1200.0, 1300.0, 500.0, 600.0, 700.0, 800.0],
    }
)


def _assert_valid_ohlc(bars: pl.DataFrame) -> None:
    for row in bars.iter_rows(named=True):
        assert row["high"] >= max(row["open"], row["close"]) - 1e-9
        assert row["low"] <= min(row["open"], row["close"]) + 1e-9
        assert row["open"] > 0
        assert row["close"] > 0


def _aaa(bars: pl.DataFrame) -> pl.DataFrame:
    return bars.filter(pl.col("symbol") == "AAA").sort("event_time")


def test_shuffle_matches_hand_computed_reference() -> None:
    result = shuffle_bar_returns(_BARS, np.random.default_rng(5))
    aaa = _aaa(result)
    assert aaa["open"].to_list() == pytest.approx(
        [100.0, 99.04761904761905, 98.07656396137973, 101.96078431372548]
    )
    assert aaa["close"].to_list() == pytest.approx(
        [99.04761904761905, 98.07656396137973, 101.96078431372548, 104.0]
    )
    assert aaa["high"].to_list() == pytest.approx(
        [100.95238095238095, 100.50420168067227, 102.93183940242764, 105.01960784313725]
    )
    assert aaa["low"].to_list() == pytest.approx(
        [99.04761904761905, 97.59103641456583, 97.59103641456583, 101.45098039215686]
    )
    _assert_valid_ohlc(result)


def test_shuffle_preserves_timestamps_and_symbol() -> None:
    result = shuffle_bar_returns(_BARS, np.random.default_rng(0))
    assert (
        result.sort(["symbol", "event_time"])["event_time"].to_list()
        == _BARS.sort(["symbol", "event_time"])["event_time"].to_list()
    )
    assert set(result["symbol"]) == {"AAA", "BBB"}


def test_shuffle_preserves_each_symbols_volume_multiset() -> None:
    result = shuffle_bar_returns(_BARS, np.random.default_rng(1))
    aaa = _aaa(result)
    assert sorted(aaa["volume"].to_list()) == sorted(_aaa(_BARS)["volume"].to_list())


def test_sign_flip_matches_hand_computed_reference() -> None:
    result = sign_flip_returns(_BARS)
    aaa = _aaa(result)
    assert aaa["open"].to_list() == pytest.approx(
        [100.0, 98.0, 98.96078431372549, 95.04154533088236]
    )
    assert aaa["close"].to_list() == pytest.approx(
        [98.0, 98.96078431372549, 95.04154533088236, 95.94670290732436]
    )
    assert aaa["high"].to_list() == pytest.approx(
        [100.98039215686275, 100.41608997050147, 99.90326797385621, 96.86048103096964]
    )
    assert aaa["low"].to_list() == pytest.approx(
        [97.51, 97.51485148514851, 94.57104263067692, 95.04154533088236]
    )
    _assert_valid_ohlc(result)


def test_sign_flip_is_deterministic() -> None:
    a = sign_flip_returns(_BARS)
    b = sign_flip_returns(_BARS)
    assert a["close"].to_list() == b["close"].to_list()


def test_sign_flip_order_is_unchanged() -> None:
    # unlike shuffle, sign-flip keeps each bar's own wick/volume in place
    result = sign_flip_returns(_BARS)
    aaa = _aaa(result)
    assert aaa["volume"].to_list() == _aaa(_BARS)["volume"].to_list()


def test_synthetic_gbm_matches_hand_computed_reference() -> None:
    result = synthetic_gbm_like(_BARS, np.random.default_rng(5))
    aaa = _aaa(result)
    assert aaa["close"].to_list() == pytest.approx(
        [99.07019577275854, 96.89907590070806, 97.29355038814977, 99.26112260032562]
    )
    _assert_valid_ohlc(result)


def test_synthetic_gbm_is_random_across_seeds() -> None:
    a = synthetic_gbm_like(_BARS, np.random.default_rng(1))
    b = synthetic_gbm_like(_BARS, np.random.default_rng(2))
    assert a["close"].to_list() != b["close"].to_list()


def test_reconstruction_refuses_a_non_positive_price() -> None:
    # intrabar_return[0] = 250/100 - 1 = 1.5; sign-flipped that's -1.5,
    # which drives the reconstructed close to 100 * (1 - 1.5) = -50.
    closes = _BARS["close"].to_list()
    closes[0] = 250.0
    bad = _BARS.with_columns(close=pl.Series(closes))
    with pytest.raises(DataQualityError, match="non-positive"):
        sign_flip_returns(bad)
