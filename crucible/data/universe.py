"""Universe membership as of a time (R1.3). Delisted names stay in history."""

from __future__ import annotations

from typing import TYPE_CHECKING

import polars as pl

from crucible.core.types import Symbol, TimestampNs

if TYPE_CHECKING:
    from crucible.core.types import DatasetId
    from crucible.data.store import ParquetDataStore


class TableUniverseProvider:
    """Membership from a `(symbol, start_at, end_at, reason)` table;
    satisfies ``UniverseProvider``. ``end_at`` is exclusive."""

    def __init__(self, table: pl.DataFrame) -> None:
        self._table = table

    @classmethod
    def from_store(
        cls, store: ParquetDataStore, dataset: DatasetId, as_of: TimestampNs
    ) -> TableUniverseProvider:
        return cls(store.read(dataset, as_of).collect())

    def members(self, as_of: TimestampNs) -> frozenset[Symbol]:
        rows = self._table.filter(
            (pl.col("start_at") <= int(as_of)) & (pl.col("end_at") > int(as_of))
        )
        return frozenset(Symbol(s) for s in rows.get_column("symbol").to_list())

    def all_symbols(self) -> frozenset[Symbol]:
        """Every symbol that was ever a member — the survivorship-bias-free set."""
        return frozenset(Symbol(s) for s in self._table.get_column("symbol").to_list())
