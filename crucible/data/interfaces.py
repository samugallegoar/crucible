"""Data-layer Protocols: point-in-time access, storage, universe, calendars, quality.

Timing semantics: every accessor takes ``as_of`` and returns only rows with
``available_at <= as_of`` (R1.1-R1.2). There is deliberately no
method that returns a full unfiltered history; the vectorized path has its own
shift-disciplined API in ``crucible.vectorized``.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

import polars as pl

from crucible.core.types import DatasetId, Symbol, TimestampNs


@dataclass(frozen=True, slots=True)
class DatasetManifest:
    """Identity of a dataset version; backtests record the hashes they consume.

    ``built_at`` is a UTC ns timestamp taken at build time (an I/O boundary,
    where wall-clock is allowed).
    """

    dataset: DatasetId
    schema_version: str
    content_hash: str
    row_count: int
    source: str
    built_at: TimestampNs


class PITAccessor(Protocol):
    """Point-in-time reads. The only door strategies have to data.

    Pessimism: a row whose ``available_at`` is unknown is treated as not yet
    available. Requests that would expose the future raise ``LookaheadError``.
    """

    def get(
        self,
        dataset: DatasetId,
        fields: Sequence[str],
        symbols: Sequence[Symbol],
        as_of: TimestampNs,
    ) -> pl.DataFrame:
        """Rows for ``symbols`` with ``available_at <= as_of``, latest per key.

        Knowable at ``as_of`` by construction.
        """
        ...

    def history(
        self,
        dataset: DatasetId,
        fields: Sequence[str],
        symbols: Sequence[Symbol],
        as_of: TimestampNs,
        lookback: int,
    ) -> pl.DataFrame:
        """Up to ``lookback`` most recent rows per symbol, all available at ``as_of``."""
        ...


class DataStore(Protocol):
    """Parquet/DuckDB-backed dataset storage with manifests."""

    def read(self, dataset: DatasetId, as_of: TimestampNs) -> pl.LazyFrame:
        """Lazy scan filtered to ``available_at <= as_of``. No unfiltered read exists."""
        ...

    def manifest(self, dataset: DatasetId) -> DatasetManifest: ...

    def list_datasets(self) -> Sequence[DatasetId]: ...


class UniverseProvider(Protocol):
    """Universe membership as of a time; delisted names remain historical members."""

    def members(self, as_of: TimestampNs) -> frozenset[Symbol]:
        """Symbols with ``start_at <= as_of < end_at`` in the membership table."""
        ...


class TradingCalendar(Protocol):
    """Session calendar for one market. Wraps ``exchange_calendars``; the only
    place timezone/DST logic is allowed besides I/O boundaries."""

    def is_open(self, ts: TimestampNs) -> bool: ...

    def session_closes(self, start: TimestampNs, end: TimestampNs) -> Sequence[TimestampNs]:
        """Close timestamps of all sessions within ``[start, end]``, ascending."""
        ...

    def next_session_close(self, ts: TimestampNs) -> TimestampNs:
        """Close of the session containing ``ts``, or of the next session if closed."""
        ...


class QualityCheck(Protocol):
    """A pre-run dataset check. Failures raise ``DataQualityError``; overriding
    a check happens only via config with a logged reason."""

    @property
    def name(self) -> str: ...

    def run(self, frame: pl.LazyFrame, calendar: TradingCalendar | None) -> None: ...
