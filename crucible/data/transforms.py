"""Bar transformations for null tests (ADR-0019, ADR-0070): each
destroys a specific kind of structure a strategy might be exploiting
while preserving the calendar/availability scaffolding
(``event_time``/``available_at``/``symbol``) the engine needs.

Every transform decomposes each symbol's bars, in ``event_time`` order, into per-bar
components that survive re-ordering without producing invalid OHLC data:

- ``gap[k] = open[k] / close[k-1] - 1``, the overnight (between-bar) return, for ``k >= 1``;
- ``intrabar_return[k] = close[k] / open[k] - 1``, the open-to-close return;
- ``high_wick = high / max(open, close) - 1`` and ``low_wick = 1 - low / min(open, close)``
  (both >= 0 by construction from valid bars);
- ``volume``, which travels with the bar's intraday shape.

and rebuilds the path from the first bar's real open: ``open[0]`` is kept, ``close[k] =
open[k] * (1 + intrabar_return[k])`` and ``open[k+1] = close[k] * (1 + gap[k+1])``. Every
rebuilt bar is valid by construction (``high >= max(open, close)``, ``low <= min(open,
close)``) because the wick fractions are never negative, and a non-positive price is refused.

The close-to-close return of bar ``k`` is ``(1 + gap[k]) * (1 + intrabar_return[k]) - 1``.
An earlier version chained ``open[k+1] = close[k]`` and so silently dropped every overnight
gap: the "shuffled" path's long-run return was the product of the open-to-close returns
alone, which on daily equity data is a different (and usually lower-drift) series than the
one the strategy was run on (ADR-0070).

What each null holds fixed and what it destroys:

- ``shuffle_bar_returns`` preserves the multiset of whole bars (gap, intraday return, wicks,
  volume), hence every close-to-close return and the final close; bar 0 stays first (it has no
  gap). Destroys the order of daily moves: trends, autocorrelation, volatility clustering,
  calendar effects.
- ``shuffle_intrabar_returns`` preserves each date's overnight gap, the multiset of intraday
  shapes and the final close. Destroys the order of intraday moves relative to the gaps.
- ``shuffle_overnight_gaps`` preserves each date's intraday shape, the multiset of gaps and the
  final close. Destroys the order of overnight moves.
- ``sign_flip_returns`` preserves bar order, wicks and volume. Destroys direction (gap and
  intraday returns negated).
- ``synthetic_gbm_like`` preserves the real wicks, volume and bar 0. Destroys everything but
  the first two moments of the close-to-close returns (i.i.d. normal draws; no
  overnight/intraday split).

The permutation nulls test the hypothesis that the order of the components is exchangeable
(no exploitable temporal structure); they keep the marginal distribution, so a strategy that
profits only from drift performs about as well on them as on the real data. Volume is never
re-scaled. A significant result says the order mattered on this sample; it does not say the
edge will persist, and it does not correct for other strategies tried (ADR-0015).

Corporate actions and universe membership are NOT touched by any of
these — only bar prices/volume are transformed (ADR-0019). The transformed bars are written to
a throwaway store whose manifest records the transform as its ``source``; they never replace
the real dataset.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

import numpy as np
import polars as pl

from crucible.core.errors import DataQualityError
from crucible.data.contracts import BAR_SCHEMA

if TYPE_CHECKING:
    from numpy.typing import NDArray


@dataclass(frozen=True, slots=True)
class BarComponents:
    """One symbol's bars as per-bar components, in ``event_time`` order. ``gap[0]`` is 0.0
    and unused: the first bar has no previous close."""

    gap: NDArray[np.float64]
    intrabar_return: NDArray[np.float64]
    high_wick: NDArray[np.float64]
    low_wick: NDArray[np.float64]
    volume: NDArray[np.float64]

    def take(self, order: NDArray[np.int64]) -> BarComponents:
        return BarComponents(
            self.gap[order],
            self.intrabar_return[order],
            self.high_wick[order],
            self.low_wick[order],
            self.volume[order],
        )


class _ComponentTransform(Protocol):
    def __call__(self, parts: BarComponents, *, symbol: str) -> BarComponents: ...


def decompose(symbol_bars: pl.DataFrame) -> BarComponents:
    """Per-bar components of one symbol's bars, which must already be sorted by
    ``event_time``."""
    opens = symbol_bars.get_column("open").to_numpy().astype(np.float64)
    highs = symbol_bars.get_column("high").to_numpy().astype(np.float64)
    lows = symbol_bars.get_column("low").to_numpy().astype(np.float64)
    closes = symbol_bars.get_column("close").to_numpy().astype(np.float64)
    volumes = symbol_bars.get_column("volume").to_numpy().astype(np.float64)
    gap = np.zeros(len(opens))
    gap[1:] = opens[1:] / closes[:-1] - 1.0
    upper = np.maximum(opens, closes)
    lower = np.minimum(opens, closes)
    return BarComponents(
        gap=gap,
        intrabar_return=closes / opens - 1.0,
        high_wick=highs / upper - 1.0,
        low_wick=1.0 - lows / lower,
        volume=volumes,
    )


def reconstruct(
    first_open: float, parts: BarComponents, *, symbol: str
) -> dict[str, NDArray[np.float64]]:
    """Rebuilds OHLCV from components (``gap[0]`` ignored); raises if any price would be
    non-positive rather than emitting a corrupt dataset."""
    n = len(parts.intrabar_return)
    opens = np.empty(n)
    closes = np.empty(n)
    opens[0] = first_open
    for k in range(n):
        if k > 0:
            opens[k] = closes[k - 1] * (1.0 + parts.gap[k])
        closes[k] = opens[k] * (1.0 + parts.intrabar_return[k])
    if np.any(opens <= 0) or np.any(closes <= 0) or not np.all(np.isfinite(closes)):
        msg = (
            f"null-test bar reconstruction for {symbol!r} produced a "
            "non-positive or non-finite price; the source data's return magnitudes are "
            "too large relative to the starting price for this transform"
        )
        raise DataQualityError(msg)
    upper = np.maximum(opens, closes)
    lower = np.minimum(opens, closes)
    highs = upper * (1.0 + parts.high_wick)
    lows = lower * (1.0 - parts.low_wick)
    return {"open": opens, "high": highs, "low": lows, "close": closes, "volume": parts.volume}


def _apply_per_symbol(bars: pl.DataFrame, transform: _ComponentTransform) -> pl.DataFrame:
    """Applies ``transform`` independently per symbol; timestamps/symbol are untouched."""
    parts: list[pl.DataFrame] = []
    for symbol in bars.get_column("symbol").unique(maintain_order=True):
        symbol_bars = bars.filter(pl.col("symbol") == symbol).sort("event_time")
        rebuilt = reconstruct(
            float(symbol_bars.get_column("open")[0]),
            transform(decompose(symbol_bars), symbol=symbol),
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


def _permute_tail(n: int, rng: np.random.Generator) -> NDArray[np.int64]:
    """Index order that keeps bar 0 first and permutes bars 1..n-1."""
    order = np.arange(n)
    if n > 2:
        order[1:] = 1 + rng.permutation(n - 1)
    return order


def shuffle_bar_returns(bars: pl.DataFrame, rng: np.random.Generator) -> pl.DataFrame:
    """The "shuffled returns" null test: independently per symbol, permutes whole bars
    (overnight gap, intraday return, both wicks and volume together) after the first,
    destroying the order of daily moves while preserving the multiset of close-to-close
    returns, and so the final close, exactly (see the module table)."""

    def _shuffle(parts: BarComponents, *, symbol: str) -> BarComponents:
        return parts.take(_permute_tail(len(parts.gap), rng))

    return _apply_per_symbol(bars, _shuffle)


def shuffle_intrabar_returns(bars: pl.DataFrame, rng: np.random.Generator) -> pl.DataFrame:
    """Intraday-only null: permutes each symbol's open-to-close shapes (return, wicks,
    volume) across all bars while every overnight gap stays on its own date. Asks whether
    the timing of intraday moves matters with overnight moves held fixed."""

    def _shuffle(parts: BarComponents, *, symbol: str) -> BarComponents:
        order = rng.permutation(len(parts.gap))
        moved = parts.take(order)
        return BarComponents(
            parts.gap, moved.intrabar_return, moved.high_wick, moved.low_wick, moved.volume
        )

    return _apply_per_symbol(bars, _shuffle)


def shuffle_overnight_gaps(bars: pl.DataFrame, rng: np.random.Generator) -> pl.DataFrame:
    """Overnight-only null: permutes each symbol's gaps (bars 1..n-1) while every intraday
    shape stays on its own date. Asks whether the timing of overnight moves matters."""

    def _shuffle(parts: BarComponents, *, symbol: str) -> BarComponents:
        moved = parts.take(_permute_tail(len(parts.gap), rng))
        return BarComponents(
            moved.gap, parts.intrabar_return, parts.high_wick, parts.low_wick, parts.volume
        )

    return _apply_per_symbol(bars, _shuffle)


def sign_flip_returns(bars: pl.DataFrame) -> pl.DataFrame:
    """The "sign-flipped" null test: negates every bar's overnight gap and intraday
    return (inverting the price series' directionality) while keeping wicks,
    volume, and bar order exactly as they were. Deterministic -- no rng,
    run once, not a distribution (ADR-0019)."""

    def _flip(parts: BarComponents, *, symbol: str) -> BarComponents:
        return BarComponents(
            -parts.gap, -parts.intrabar_return, parts.high_wick, parts.low_wick, parts.volume
        )

    return _apply_per_symbol(bars, _flip)


def synthetic_gbm_like(bars: pl.DataFrame, rng: np.random.Generator) -> pl.DataFrame:
    """The "synthetic GBM" null test: replaces each symbol's close-to-close returns after
    the first bar with i.i.d. normal draws matched to that symbol's own real close-to-close
    mean/stdev, placed entirely open-to-close (gap 0), keeping its real wicks/volume --
    randomizes the directional structure a strategy could exploit, not the drift or the
    volatility level. The overnight/intraday split is not modelled."""

    def _replace(parts: BarComponents, *, symbol: str) -> BarComponents:
        n = len(parts.gap)
        if n < 2:
            return parts
        c2c = (1.0 + parts.gap[1:]) * (1.0 + parts.intrabar_return[1:]) - 1.0
        mu = float(c2c.mean())
        sigma = float(c2c.std(ddof=1)) if len(c2c) > 1 else 0.0
        intrabar = parts.intrabar_return.copy()
        intrabar[1:] = rng.normal(mu, sigma, size=n - 1)
        return BarComponents(np.zeros(n), intrabar, parts.high_wick, parts.low_wick, parts.volume)

    return _apply_per_symbol(bars, _replace)
