"""Dataset identity of the one-step flow includes the calendar, and a stored dataset is reused
only when its recorded request matches (ADR-0071)."""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from types import SimpleNamespace

import polars as pl
import pytest

from crucible.core.errors import ConfigurationError
from crucible.core.types import DatasetId
from crucible.data.calendars import canonical_calendar
from crucible.data.contracts import BAR_SCHEMA, BAR_SORT_KEYS
from crucible.data.store import build_dataset
from crucible.product import data as product_data
from crucible.product.data import (
    dataset_name,
    dataset_request,
    ensure_dataset,
    read_request_record,
    write_request_record,
)
from crucible.product.home import resolve_home

START, END, TODAY = dt.date(2020, 1, 1), dt.date(2020, 3, 1), dt.date(2024, 1, 1)
DAY = 86_400 * 10**9


def _name(calendar: str) -> str:
    return dataset_name("yfinance", ["SPY"], START, END, "1d", "adjusted", calendar)


def test_two_calendars_do_not_collide() -> None:
    assert _name("XNYS") != _name("24/7")
    assert _name("XNYS") != _name("XLON")


@pytest.mark.parametrize("spelling", ["XNYS", "xnys", " NYSE ", "nyse", "XNAS"])
def test_equivalent_calendar_spellings_share_one_identity(spelling: str) -> None:
    # exchange_calendars maps NYSE and XNAS to the XNYS sessions
    assert canonical_calendar(spelling) == "XNYS"
    assert _name(spelling) == _name("XNYS")
    assert dataset_request("yfinance", ["SPY"], START, END, "1d", "adjusted", spelling) == (
        dataset_request("yfinance", ["SPY"], START, END, "1d", "adjusted", "XNYS")
    )


def test_an_unknown_calendar_is_refused() -> None:
    with pytest.raises(ConfigurationError, match="unknown trading calendar"):
        _name("MOON")


def test_names_are_deterministic_and_the_calendar_defaults_to_xnys() -> None:
    assert _name("XNYS") == _name("XNYS")
    assert dataset_name("yfinance", ["SPY"], START, END, "1d", "adjusted") == _name("XNYS")
    assert _name("24/7").endswith("_247")


def _seed(home_root: Path, *, calendar: str, record: dict[str, object] | None) -> str:
    home = resolve_home(home_root)
    name = _name(calendar)
    bars = pl.DataFrame(
        {
            "symbol": ["SPY"] * 3,
            "event_time": [DAY, 2 * DAY, 3 * DAY],
            "available_at": [DAY, 2 * DAY, 3 * DAY],
            "open": [1.0, 1.0, 1.0],
            "high": [1.0, 1.0, 1.0],
            "low": [1.0, 1.0, 1.0],
            "close": [1.0, 1.0, 1.0],
            "volume": [1.0, 1.0, 1.0],
        }
    )
    build_dataset(
        home.data, DatasetId(name), bars, schema=BAR_SCHEMA, sort_keys=BAR_SORT_KEYS, source="t"
    )
    if record is not None:
        write_request_record(home.data / name, record)
    return name


def _ensure(home_root: Path, calendar: str) -> product_data.DatasetInfo:
    return ensure_dataset(
        resolve_home(home_root),
        symbols=["SPY"],
        start=START,
        end=END,
        provider="yfinance",
        calendar=calendar,
        offline=True,
        today=TODAY,
    )


def test_an_identical_request_reuses_the_stored_dataset(tmp_path: Path) -> None:
    record = dataset_request("yfinance", ["SPY"], START, END, "1d", "adjusted", "XNYS")
    name = _seed(tmp_path, calendar="XNYS", record=record)
    info = _ensure(tmp_path, "nyse")  # an equivalent spelling
    assert info.dataset == name
    assert info.calendar == "XNYS"
    assert not info.fetched_now


def test_a_dataset_whose_record_differs_is_not_reused(tmp_path: Path) -> None:
    # same name, but the record says it was built for another calendar (a collision or tampering)
    other = dataset_request("yfinance", ["SPY"], START, END, "1d", "adjusted", "24/7")
    _seed(tmp_path, calendar="XNYS", record=other)
    with pytest.raises(ConfigurationError, match="not built for this exact request"):
        _ensure(tmp_path, "XNYS")


def test_a_dataset_without_a_record_is_not_reused(tmp_path: Path) -> None:
    # e.g. one stored by an older Crucible: never trusted on its name alone
    _seed(tmp_path, calendar="XNYS", record=None)
    with pytest.raises(ConfigurationError, match="not built for this exact request"):
        _ensure(tmp_path, "XNYS")


def test_a_replaced_version_is_archived_not_erased(tmp_path: Path) -> None:
    home = resolve_home(tmp_path)
    record = dataset_request("yfinance", ["SPY"], START, END, "1d", "adjusted", "XNYS")
    name = _seed(tmp_path, calendar="XNYS", record=record)
    manifest = SimpleNamespace(content_hash="abc123")
    replaced = product_data._archive_previous(home, name, manifest)
    assert replaced == "abc123"
    archived = home.root / "archive" / name / "abc123"
    assert (archived / "data.parquet").exists()
    assert read_request_record(archived) == record
    assert not (home.data / name).exists()
