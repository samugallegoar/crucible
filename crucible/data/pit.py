"""Point-in-time accessor: the information barrier, enforced (R2.1, I8).

The accessor is constructed with the simulation clock. Any request with
``as_of > clock.now`` raises ``LookaheadError`` before touching data; the
store then filters ``available_at <= as_of`` on top. There is no code path
that returns rows from the future.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import polars as pl

from crucible.core.errors import LookaheadError

if TYPE_CHECKING:
    from collections.abc import Sequence

    from crucible.core.interfaces import Clock
    from crucible.core.types import DatasetId, Symbol, TimestampNs
    from crucible.data.store import ParquetDataStore


class StorePITAccessor:
    """Satisfies ``crucible.data.interfaces.PITAccessor``."""

    def __init__(self, store: ParquetDataStore, clock: Clock) -> None:
        self._store = store
        self._clock = clock

    def _guard(self, dataset: DatasetId, as_of: TimestampNs) -> None:
        if as_of > self._clock.now:
            msg = (
                f"lookahead: requested as_of={as_of} but clock.now={self._clock.now} "
                f"(dataset={dataset}). Strategies may only query the past; "
                "pass as_of <= ctx.clock.now."
            )
            raise LookaheadError(msg)

    def _scan(
        self,
        dataset: DatasetId,
        fields: Sequence[str],
        symbols: Sequence[Symbol],
        as_of: TimestampNs,
    ) -> pl.LazyFrame:
        self._guard(dataset, as_of)
        return (
            self._store.read(dataset, as_of)
            .filter(pl.col("symbol").is_in([str(s) for s in symbols]))
            .select(["symbol", "event_time", "available_at", *fields])
            .sort(["symbol", "event_time", "available_at"])
        )

    def get(
        self,
        dataset: DatasetId,
        fields: Sequence[str],
        symbols: Sequence[Symbol],
        as_of: TimestampNs,
    ) -> pl.DataFrame:
        """Latest available row per symbol as of ``as_of``. Symbols with no
        available data are absent from the result — absence is typed
        missingness (`unavailable`), never a fabricated row."""
        return (
            self._scan(dataset, fields, symbols, as_of)
            .group_by("symbol", maintain_order=True)
            .last()
            .collect()
        )

    def history(
        self,
        dataset: DatasetId,
        fields: Sequence[str],
        symbols: Sequence[Symbol],
        as_of: TimestampNs,
        lookback: int,
    ) -> pl.DataFrame:
        """Up to ``lookback`` most recent available rows per symbol, ascending
        in ``event_time`` within each symbol."""
        if lookback <= 0:
            msg = f"lookback must be positive, got {lookback}"
            raise ValueError(msg)
        return (
            self._scan(dataset, fields, symbols, as_of)
            .group_by("symbol", maintain_order=True)
            .tail(lookback)
            .collect()
        )
