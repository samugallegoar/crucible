"""Bar transformations for null tests (ADR-0019):
return-order shuffle, sign-flip, and synthetic-GBM replacement — each
destroys a specific kind of structure a strategy might be exploiting
while preserving the calendar/availability scaffolding
(``event_time``/``available_at``/``symbol``) the engine needs.

All three decompose each symbol's bars into per-bar "shape" features that
survive shuffling/replacement without producing invalid OHLC data:
``intrabar_return = close/open - 1``, ``high_wick = high/max(open,close) - 1``,
``low_wick = 1 - low/min(open,close)`` (both wicks >= 0 by construction from
real data), then re-chain opens from closes (``open[k+1] = close[k]``,
matching ``examples/momentum/build_data.py``'s existing "no overnight gap
model" convention) so every reconstructed bar is valid by construction:
``high >= max(open, close)`` and ``low <= min(open, close)`` always hold
because the wick fractions that produce them are never negative.

Corporate actions and universe membership are NOT touched by any of
these — only bar prices/volume are transformed (ADR-0019).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

import numpy as np
import polars as pl

from crucible.core.errors import DataQualityError
from crucible.data.contracts import BAR_SCHEMA

if TYPE_CHECKING:
    from numpy.typing import NDArray


class _ShapeTransform(Protocol):
    def __call__(
        self,
        intrabar_return: NDArray[np.float64],
        high_wick: NDArray[np.float64],
        low_wick: NDArray[np.float64],
        volume: NDArray[np.float64],
        *,
        symbol: str,
    ) -> tuple[NDArray[np.float64], ...]: ...


def _decompose(symbol_bars: pl.DataFrame) -> tuple[NDArray[np.float64], ...]:
    """Per-bar shape features, in ``event_time`` order."""
    opens = symbol_bars.get_column("open").to_numpy()
    highs = symbol_bars.get_column("high").to_numpy()
    lows = symbol_bars.get_column("low").to_numpy()
    closes = symbol_bars.get_column("close").to_numpy()
    volumes = symbol_bars.get_column("volume").to_numpy()
    intrabar_return = closes / opens - 1.0
    upper = np.maximum(opens, closes)
    lower = np.minimum(opens, closes)
    high_wick = highs / upper - 1.0
    low_wick = 1.0 - lows / lower
    return intrabar_return, high_wick, low_wick, volumes


def _reconstruct(
    first_open: float,
    intrabar_return: NDArray[np.float64],
    high_wick: NDArray[np.float64],
    low_wick: NDArray[np.float64],
    volume: NDArray[np.float64],
    *,
    symbol: str,
) -> dict[str, NDArray[np.float64]]:
    """Chains opens from closes (``open[k+1] = close[k]``); raises if any
    reconstructed price would be non-positive rather than emitting a
    corrupt dataset."""
    n = len(intrabar_return)
    opens = np.empty(n)
    closes = np.empty(n)
    opens[0] = first_open
    for k in range(n):
        closes[k] = opens[k] * (1.0 + intrabar_return[k])
        if k + 1 < n:
            opens[k + 1] = closes[k]
    if np.any(opens <= 0) or np.any(closes <= 0):
        msg = (
            f"null-test bar reconstruction for {symbol!r} produced a "
            "non-positive price; the source data's return magnitudes are "
            "too large relative to the starting price for this transform"
        )
        raise DataQualityError(msg)
    upper = np.maximum(opens, closes)
    lower = np.minimum(opens, closes)
    highs = upper * (1.0 + high_wick)
    lows = lower * (1.0 - low_wick)
    return {"open": opens, "high": highs, "low": lows, "close": closes, "volume": volume}


def _apply_per_symbol(
    bars: pl.DataFrame,
    transform: _ShapeTransform,
) -> pl.DataFrame:
    """``transform(intrabar_return, high_wick, low_wick, volume, symbol=...)
    -> (new_intrabar_return, new_high_wick, new_low_wick, new_volume)``,
    applied independently per symbol; timestamps/symbol are untouched."""
    parts: list[pl.DataFrame] = []
    for symbol in bars.get_column("symbol").unique(maintain_order=True):
        symbol_bars = bars.filter(pl.col("symbol") == symbol).sort("event_time")
        intrabar_return, high_wick, low_wick, volume = _decompose(symbol_bars)
        new_ret, new_high_wick, new_low_wick, new_volume = transform(
            intrabar_return, high_wick, low_wick, volume, symbol=symbol
        )
        rebuilt = _reconstruct(
            float(symbol_bars.get_column("open")[0]),
            new_ret,
            new_high_wick,
            new_low_wick,
            new_volume,
            symbol=symbol,
        )
        parts.append(
            symbol_bars.with_columns(
                open=pl.Series(rebuilt["open"]),
                high=pl.Series(rebuilt["high"]),
                low=pl.Series(rebuilt["low"]),
                close=pl.Series(rebuilt["close"]),
                volume=pl.Series(rebuilt["volume"]),
            )
        )
    return pl.concat(parts).select(list(BAR_SCHEMA)).cast(BAR_SCHEMA)  # type: ignore[arg-type]


def shuffle_bar_returns(bars: pl.DataFrame, rng: np.random.Generator) -> pl.DataFrame:
    """The "shuffled returns" null test: independently permutes each
    symbol's sequence of per-bar shapes (return + both wicks + volume, kept
    together as one unit), destroying any exploitable temporal ordering
    while preserving each symbol's own return/wick/volume distribution
    exactly."""

    def _shuffle(
        intrabar_return: NDArray[np.float64],
        high_wick: NDArray[np.float64],
        low_wick: NDArray[np.float64],
        volume: NDArray[np.float64],
        *,
        symbol: str,
    ) -> tuple[NDArray[np.float64], ...]:
        order = rng.permutation(len(intrabar_return))
        return intrabar_return[order], high_wick[order], low_wick[order], volume[order]

    return _apply_per_symbol(bars, _shuffle)


def sign_flip_returns(bars: pl.DataFrame) -> pl.DataFrame:
    """The "sign-flipped" null test: negates every bar's intrabar return
    (inverting the price series' directionality) while keeping wicks,
    volume, and bar order exactly as they were. Deterministic -- no rng,
    run once, not a distribution (ADR-0019)."""

    def _flip(
        intrabar_return: NDArray[np.float64],
        high_wick: NDArray[np.float64],
        low_wick: NDArray[np.float64],
        volume: NDArray[np.float64],
        *,
        symbol: str,
    ) -> tuple[NDArray[np.float64], ...]:
        return -intrabar_return, high_wick, low_wick, volume

    return _apply_per_symbol(bars, _flip)


def synthetic_gbm_like(bars: pl.DataFrame, rng: np.random.Generator) -> pl.DataFrame:
    """The "synthetic GBM" null test: replaces each symbol's intrabar
    returns with a fresh draw from a normal distribution matched to that
    symbol's own real mean/stdev (same convention as
    ``examples/momentum/build_data.py``'s synthetic generator), keeping
    its real wicks/volume -- randomizes only the directional structure a
    strategy could exploit, not the intrabar volatility shape."""

    def _replace(
        intrabar_return: NDArray[np.float64],
        high_wick: NDArray[np.float64],
        low_wick: NDArray[np.float64],
        volume: NDArray[np.float64],
        *,
        symbol: str,
    ) -> tuple[NDArray[np.float64], ...]:
        n = len(intrabar_return)
        mu = float(intrabar_return.mean())
        sigma = float(intrabar_return.std(ddof=1)) if n > 1 else 0.0
        synthetic = rng.normal(mu, sigma, size=n)
        return synthetic, high_wick, low_wick, volume

    return _apply_per_symbol(bars, _replace)
