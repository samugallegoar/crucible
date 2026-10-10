"""Vectorized-path Protocols. Level 0/1 only.

Shift discipline: signals may be computed on full arrays, but the engine
applies a mandatory lag (>= 1 bar) between signal and position and verifies
via a poison test that positions at ``t`` do not depend on data at ``>= t``.
There is no opt-out; the lag is configurable only upward.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

import polars as pl

if TYPE_CHECKING:
    from crucible.vectorized.engine import VectorizedConfig, VectorizedResult


class SignalFunction(Protocol):
    """A vectorized signal: full price history in, per-symbol scores out.

    The engine — not the signal author — lags the output before it becomes a
    position. Signal code never sees portfolio state.
    """

    def __call__(self, bars: pl.LazyFrame, params: dict[str, object]) -> pl.LazyFrame:
        """Frame keyed (ts, symbol) with a ``score`` column."""
        ...


class VectorizedEngine(Protocol):
    """Runs a shift-disciplined vectorized backtest; same config schema and
    metrics module as the event-driven path so results are comparable
    (``crucible.analytics.metrics.compute_metrics`` operates on this
    engine's ``VectorizedResult.equity`` exactly as it does on the
    event-driven ``equity.parquet`` shape)."""

    def run(self, config: VectorizedConfig) -> VectorizedResult:
        """Pinned in ADR-0035; see docs/modules/vectorized.md."""
        ...
