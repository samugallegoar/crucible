"""PIT accessor: as-of filtering and the lookahead guard (I8, R2.1)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import polars as pl
import pytest

from crucible.core.clock import SimulationClock
from crucible.core.errors import LookaheadError
from crucible.core.types import DatasetId, Symbol, TimestampNs
from crucible.data.contracts import BAR_SCHEMA, BAR_SORT_KEYS
from crucible.data.pit import StorePITAccessor
from crucible.data.store import ParquetDataStore, build_dataset

if TYPE_CHECKING:
    from pathlib import Path

BARS = DatasetId("bars_test")
AAA, BBB = Symbol("AAA"), Symbol("BBB")


@pytest.fixture
def accessor(tmp_path: Path) -> tuple[StorePITAccessor, SimulationClock]:
    frame = pl.DataFrame(
        {
            "symbol": ["AAA"] * 3 + ["BBB"] * 3,
            "event_time": [100, 200, 300] * 2,
            "available_at": [100, 200, 300] * 2,
            "open": [1.0] * 6,
            "high": [2.0] * 6,
            "low": [0.5] * 6,
            "close": [1.0, 1.1, 1.2, 2.0, 2.1, 2.2],
            "volume": [1.0] * 6,
        }
    )
    build_dataset(tmp_path, BARS, frame, schema=BAR_SCHEMA, sort_keys=BAR_SORT_KEYS, source="test")
    clock = SimulationClock(TimestampNs(200))
    return StorePITAccessor(ParquetDataStore(tmp_path), clock), clock


def test_get_returns_latest_available_row(
    accessor: tuple[StorePITAccessor, SimulationClock],
) -> None:
    pit, _ = accessor
    result = pit.get(BARS, ["close"], [AAA, BBB], TimestampNs(200)).sort("symbol")
    assert result.get_column("close").to_list() == [1.1, 2.1]
    assert result.get_column("event_time").to_list() == [200, 200]


def test_future_as_of_raises_lookahead(
    accessor: tuple[StorePITAccessor, SimulationClock],
) -> None:
    pit, _ = accessor
    with pytest.raises(LookaheadError, match="as_of=201"):
        pit.get(BARS, ["close"], [AAA], TimestampNs(201))


def test_history_respects_lookback_and_as_of(
    accessor: tuple[StorePITAccessor, SimulationClock],
) -> None:
    pit, clock = accessor
    clock.advance(TimestampNs(300))
    result = pit.history(BARS, ["close"], [AAA], TimestampNs(300), lookback=2)
    assert result.get_column("close").to_list() == [1.1, 1.2]


def test_symbol_without_data_is_absent_not_fabricated(
    accessor: tuple[StorePITAccessor, SimulationClock],
) -> None:
    pit, _ = accessor
    result = pit.get(BARS, ["close"], [Symbol("ZZZ")], TimestampNs(200))
    assert result.height == 0
