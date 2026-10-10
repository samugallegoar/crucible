"""Deliberately bad vectorized signal functions for the refusal tests (ADR-0061).

Importable from ``tests/integration`` only (like ``checkpoint_support``); sequential runs only,
because a spawn worker would not have this directory on its path.
"""

from __future__ import annotations

import polars as pl

from examples.trend_demo.vectorized_signal import trend_follower_signal


def nan_signal(bars: pl.LazyFrame, params: dict[str, object]) -> pl.LazyFrame:
    """The trend signal with every score replaced by NaN (a z-score over a zero rolling std)."""
    return trend_follower_signal(bars, params).with_columns(score=pl.lit(float("nan")))


def missing_score_signal(bars: pl.LazyFrame, params: dict[str, object]) -> pl.LazyFrame:
    """Returns a frame without the required ``score`` column."""
    return trend_follower_signal(bars, params).select("ts", "symbol")
