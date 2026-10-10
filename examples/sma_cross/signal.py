"""Long-only SMA crossover signal for the vectorized engine.

Enter long when the fast SMA crosses above the slow SMA; exit (go flat) when it
crosses below. Never short. The position starts flat and only opens after a
genuine upward cross, so a series that begins with ``fast > slow`` stays flat
until the next crossover.

Params: ``fast`` (default 10), ``slow`` (default 30). Timing: the score for bar
``t`` uses closes up to and including ``t``; the engine's mandatory
``lag_bars`` shift means the position is held from the following bar.
"""

from __future__ import annotations

import polars as pl


def sma_cross_signal(bars: pl.LazyFrame, params: dict[str, object]) -> pl.LazyFrame:
    fast = int(str(params.get("fast", 10)))
    slow = int(str(params.get("slow", 30)))
    if not 1 <= fast < slow:
        msg = f"need 1 <= fast < slow, got fast={fast}, slow={slow}"
        raise ValueError(msg)

    return (
        bars.select(["symbol", "event_time", "close"])
        .rename({"event_time": "ts"})
        .sort(["symbol", "ts"])
        .with_columns(
            fast_sma=pl.col("close").rolling_mean(window_size=fast).over("symbol"),
            slow_sma=pl.col("close").rolling_mean(window_size=slow).over("symbol"),
        )
        .with_columns(above=pl.col("fast_sma") > pl.col("slow_sma"))
        .with_columns(prev_above=pl.col("above").shift(1).over("symbol"))
        .with_columns(
            event=pl.when(pl.col("above") & (pl.col("prev_above") == False))  # noqa: E712
            .then(1.0)
            .when((~pl.col("above")) & (pl.col("prev_above") == True))  # noqa: E712
            .then(0.0)
            .otherwise(None)
        )
        .with_columns(score=pl.col("event").forward_fill().over("symbol").fill_null(0.0))
        .select(["ts", "symbol", "score"])
    )
