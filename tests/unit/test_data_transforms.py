"""Null-test bar transformations (ADR-0019, ADR-0070).

Reference values are hand-computable (round numbers below); the property-style checks
assert what each null is documented to preserve. ``_BARS`` has no overnight gaps (every
open equals the previous close), so the gap-carrying cases use ``_GAPPY``."""

from __future__ import annotations

import numpy as np
import polars as pl
import pytest

from crucible.core.errors import DataQualityError
from crucible.data.transforms import (
    shuffle_bar_returns,
    shuffle_intrabar_returns,
    shuffle_overnight_gaps,
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


# three bars: +10% intraday; then a +10% gap and +10% intraday; then a -50% gap and +20%
_HAND = pl.DataFrame(
    {
        "symbol": ["X", "X", "X"],
        "event_time": [1, 2, 3],
        "available_at": [1, 2, 3],
        "open": [100.0, 121.0, 66.55],
        "high": [110.0, 133.1, 79.86],
        "low": [100.0, 121.0, 66.55],
        "close": [110.0, 133.1, 79.86],
        "volume": [1.0, 2.0, 3.0],
    }
)


def test_shuffle_matches_hand_computed_reference() -> None:
    # bar 0 stays; bars 1 and 2 either keep their order or swap. Swapped: bar 2's -50% gap
    # lands on 110 -> 55, +20% -> 66; then bar 1's +10% gap -> 72.6, +10% -> 79.86.
    seen: set[tuple[float, ...]] = set()
    for seed in range(20):
        x = shuffle_bar_returns(_HAND, np.random.default_rng(seed)).sort("event_time")
        opens = tuple(round(v, 9) for v in x["open"].to_list())
        closes = tuple(round(v, 9) for v in x["close"].to_list())
        assert opens in {(100.0, 121.0, 66.55), (100.0, 55.0, 72.6)}
        assert closes in {(110.0, 133.1, 79.86), (110.0, 66.0, 79.86)}
        assert x["volume"].to_list() in ([1.0, 2.0, 3.0], [1.0, 3.0, 2.0])
        seen.add(closes)
    assert len(seen) == 2  # both orders occur


def _close_to_close(bars: pl.DataFrame, symbol: str) -> list[float]:
    closes = bars.filter(pl.col("symbol") == symbol).sort("event_time")["close"].to_numpy()
    return sorted((closes[1:] / closes[:-1] - 1.0).tolist())


_GAPPY = pl.DataFrame(
    {
        "symbol": ["G"] * 6,
        "event_time": [1, 2, 3, 4, 5, 6],
        "available_at": [1, 2, 3, 4, 5, 6],
        "open": [100.0, 104.0, 99.0, 103.0, 110.0, 101.0],
        "high": [103.0, 105.0, 102.0, 109.0, 111.0, 104.0],
        "low": [99.0, 98.0, 98.5, 102.0, 100.0, 100.5],
        "close": [102.0, 100.0, 101.0, 108.0, 102.0, 103.0],
        "volume": [10.0, 20.0, 30.0, 40.0, 50.0, 60.0],
    }
)


@pytest.mark.parametrize("seed", range(5))
def test_shuffle_preserves_close_to_close_returns_and_final_close_with_gaps(seed: int) -> None:
    # regression: re-chaining open[k+1] = close[k] dropped every overnight gap, so the
    # shuffled path's close-to-close returns and final close differed from the real ones
    result = shuffle_bar_returns(_GAPPY, np.random.default_rng(seed))
    assert _close_to_close(result, "G") == pytest.approx(_close_to_close(_GAPPY, "G"))
    assert result.sort("event_time")["close"][-1] == pytest.approx(103.0)
    assert result.sort("event_time")["open"][0] == 100.0
    _assert_valid_ohlc(result)


@pytest.mark.parametrize("seed", range(5))
def test_intrabar_shuffle_keeps_each_gap_on_its_date(seed: int) -> None:
    result = shuffle_intrabar_returns(_GAPPY, np.random.default_rng(seed)).sort("event_time")
    gaps = result["open"].to_numpy()[1:] / result["close"].to_numpy()[:-1] - 1.0
    real = _GAPPY["open"].to_numpy()[1:] / _GAPPY["close"].to_numpy()[:-1] - 1.0
    assert gaps == pytest.approx(real)
    intraday = sorted((result["close"] / result["open"] - 1.0).to_list())
    assert intraday == pytest.approx(sorted((_GAPPY["close"] / _GAPPY["open"] - 1.0).to_list()))
    assert result["close"][-1] == pytest.approx(103.0)
    _assert_valid_ohlc(result)


@pytest.mark.parametrize("seed", range(5))
def test_gap_shuffle_keeps_each_intraday_shape_on_its_date(seed: int) -> None:
    result = shuffle_overnight_gaps(_GAPPY, np.random.default_rng(seed)).sort("event_time")
    assert (result["close"] / result["open"]).to_list() == pytest.approx(
        (_GAPPY["close"] / _GAPPY["open"]).to_list()
    )
    assert result["volume"].to_list() == _GAPPY["volume"].to_list()
    assert result["close"][-1] == pytest.approx(103.0)
    _assert_valid_ohlc(result)


def test_shuffle_of_a_constant_return_path_is_the_identity() -> None:
    # every bar is identical in components, so any order rebuilds the same prices
    closes = [100.0 * 1.01**k for k in range(1, 9)]
    opens = [100.0 * 1.01 ** (k - 1) * 1.002 for k in range(1, 9)]
    bars = pl.DataFrame(
        {
            "symbol": ["C"] * 8,
            "event_time": list(range(8)),
            "available_at": list(range(8)),
            "open": opens,
            "high": [max(o, c) for o, c in zip(opens, closes, strict=True)],
            "low": [min(o, c) for o, c in zip(opens, closes, strict=True)],
            "close": closes,
            "volume": [5.0] * 8,
        }
    )
    result = shuffle_bar_returns(bars, np.random.default_rng(3)).sort("event_time")
    assert result["close"].to_list() == pytest.approx(closes)
    assert result["open"].to_list() == pytest.approx(opens)


def test_shuffle_destroys_a_trend_but_not_the_drift() -> None:
    # 200 up-days then 200 down-days: the real path peaks in the middle; a shuffle keeps the
    # endpoint (same multiset of returns) but not the shape
    rng = np.random.default_rng(11)
    rets = np.r_[np.full(200, 0.004), np.full(200, -0.003)] + rng.normal(0, 1e-4, 400)
    closes = 100.0 * np.cumprod(1.0 + rets)
    opens = np.r_[100.0, closes[:-1]]
    bars = pl.DataFrame(
        {
            "symbol": ["T"] * 400,
            "event_time": list(range(400)),
            "available_at": list(range(400)),
            "open": opens,
            "high": np.maximum(opens, closes),
            "low": np.minimum(opens, closes),
            "close": closes,
            "volume": np.ones(400),
        }
    )
    shuffled = shuffle_bar_returns(bars, np.random.default_rng(4)).sort("event_time")
    assert shuffled["close"][-1] == pytest.approx(closes[-1])
    assert float(shuffled["close"].max()) < 0.8 * float(closes.max())


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


def test_synthetic_gbm_matches_its_specification() -> None:
    # independent of the module: bar 0 kept, then i.i.d. normal close-to-close returns with
    # the real close-to-close mean/stdev, all of it open-to-close (no gap)
    closes = _GAPPY["close"].to_numpy()
    c2c = closes[1:] / closes[:-1] - 1.0
    draws = np.random.default_rng(5).normal(c2c.mean(), c2c.std(ddof=1), size=5)
    expected = [102.0, *(102.0 * np.cumprod(1.0 + draws)).tolist()]
    result = synthetic_gbm_like(_GAPPY, np.random.default_rng(5)).sort("event_time")
    assert result["close"].to_list() == pytest.approx(expected)
    assert result["open"].to_list()[1:] == pytest.approx(expected[:-1])
    _assert_valid_ohlc(result)


def test_sign_flip_negates_gaps_as_well() -> None:
    result = sign_flip_returns(_GAPPY).sort("event_time")
    gaps = result["open"].to_numpy()[1:] / result["close"].to_numpy()[:-1] - 1.0
    real = _GAPPY["open"].to_numpy()[1:] / _GAPPY["close"].to_numpy()[:-1] - 1.0
    assert gaps == pytest.approx(-real)


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
