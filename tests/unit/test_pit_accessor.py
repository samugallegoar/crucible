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


# --- boundaries and revisions (ADR-0071) ---------------------------------------------------


def _revised_store(tmp_path: Path) -> StorePITAccessor:
    # AAA's bar at event_time 200 is first published at 200 (close 1.1) and revised at 250
    # (close 1.15); a later bar at 300.
    frame = pl.DataFrame(
        {
            "symbol": ["AAA"] * 4,
            "event_time": [100, 200, 200, 300],
            "available_at": [100, 200, 250, 300],
            "open": [1.0] * 4,
            "high": [2.0] * 4,
            "low": [0.5] * 4,
            "close": [1.0, 1.1, 1.15, 1.2],
            "volume": [1.0] * 4,
        }
    )
    build_dataset(tmp_path, BARS, frame, schema=BAR_SCHEMA, sort_keys=BAR_SORT_KEYS, source="t")
    return StorePITAccessor(ParquetDataStore(tmp_path), SimulationClock(TimestampNs(400)))


def test_a_row_available_exactly_at_as_of_is_included(
    accessor: tuple[StorePITAccessor, SimulationClock],
) -> None:
    pit, _ = accessor
    result = pit.get(BARS, ["close"], [AAA], TimestampNs(200))
    assert result.get_column("available_at").to_list() == [200]  # available_at <= as_of


def test_a_row_available_one_ns_later_is_excluded(
    accessor: tuple[StorePITAccessor, SimulationClock],
) -> None:
    pit, _ = accessor
    result = pit.history(BARS, ["close"], [AAA], TimestampNs(199), lookback=10)
    assert result.get_column("event_time").to_list() == [100]


def test_get_returns_the_version_known_at_as_of(tmp_path: Path) -> None:
    pit = _revised_store(tmp_path)
    before = pit.get(BARS, ["close"], [AAA], TimestampNs(249))
    after = pit.get(BARS, ["close"], [AAA], TimestampNs(250))
    assert before.get_column("close").to_list() == [1.1]  # the revision is not known yet
    assert after.get_column("close").to_list() == [1.15]


def test_history_counts_a_revised_observation_once(tmp_path: Path) -> None:
    # regression (ADR-0071): history took the last `lookback` rows, so a revision appeared as a
    # second observation of the same moment and a moving average counted that bar twice
    pit = _revised_store(tmp_path)
    known_before = pit.history(BARS, ["close"], [AAA], TimestampNs(249), lookback=10)
    assert known_before.get_column("close").to_list() == [1.0, 1.1]
    known_after = pit.history(BARS, ["close"], [AAA], TimestampNs(300), lookback=10)
    assert known_after.get_column("event_time").to_list() == [100, 200, 300]
    assert known_after.get_column("close").to_list() == [1.0, 1.15, 1.2]
    last_two = pit.history(BARS, ["close"], [AAA], TimestampNs(300), lookback=2)
    assert last_two.get_column("close").to_list() == [1.15, 1.2]


def test_the_store_itself_never_returns_future_rows(tmp_path: Path) -> None:
    # the filter is part of the read: even a caller that bypasses the accessor's guard and
    # collects the raw lazy frame cannot see a row published after as_of
    _revised_store(tmp_path)
    rows = ParquetDataStore(tmp_path).read(BARS, TimestampNs(249)).collect()
    assert rows.get_column("available_at").max() == 200
