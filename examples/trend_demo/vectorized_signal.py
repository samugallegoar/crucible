"""Vectorized mirror of ``TrendFollower`` (ADR-0035).

``TrendFollower`` (see ``strategy.py``) rebalances every bar, sizing off the
mean of the ``lookback`` trailing returns computed from closes *strictly
before* the current bar's own close, then submits a market order that (Level
1, ADR-0010) fills at the *next* bar's open. With this generator's
no-overnight-gap convention (``open[t] = close[t-1]``), that means: a signal
built from returns ending at bar ``t-1`` results in a position that captures
bar ``t+1``'s return -- a **two-bar** total lag from the signal's last input
to the return it captures, not one.

The vectorized engine only ever contributes *one* mandatory lag
(``VectorizedBacktestEngine`` shifts ``score`` by ``lag_bars`` bars, default
1). To reproduce the event-driven engine's actual two-bar lag exactly, this
signal function supplies the other bar of lag itself, internally, via its
own ``.shift(1)`` on the rolling mean -- exactly mirroring
``TrendFollower._rebalance``'s own ``event_time < current_event_time``
filter, which excludes the current bar's own close from the signal's inputs
before the engine's lag is ever applied. See ADR-0035 for the full
bar-by-bar derivation and the agreement test this makes possible.
"""

from __future__ import annotations

import polars as pl


def trend_follower_signal(bars: pl.LazyFrame, params: dict[str, object]) -> pl.LazyFrame:
    """Long (score=1.0) when the trailing mean return is positive, flat
    (score=0.0) otherwise -- same binary long/flat rule as
    ``TrendFollower``. ``params["lookback"]`` matches the event-driven
    strategy's own parameter of the same name."""
    lookback = int(str(params["lookback"]))
    if lookback < 1:
        msg = f"lookback must be >= 1, got {lookback}"
        raise ValueError(msg)

    return (
        bars.select(["symbol", "event_time", "close"])
        .rename({"event_time": "ts"})
        .sort(["symbol", "ts"])
        .with_columns(ret=(pl.col("close") / pl.col("close").shift(1).over("symbol") - 1.0))
        .with_columns(trailing_mean=pl.col("ret").rolling_mean(window_size=lookback).over("symbol"))
        .with_columns(
            # Mirrors TrendFollower's own `event_time < current_event_time`
            # filter: the signal for bar t must not use bar t's own return.
            score=(pl.col("trailing_mean").shift(1).over("symbol") > 0.0)
            .cast(pl.Float64)
            .fill_null(0.0)
        )
        .select(["ts", "symbol", "score"])
    )
