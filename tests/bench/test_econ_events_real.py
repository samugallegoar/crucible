"""The economic-event calendar against the REAL raw snapshots and the REAL store (C7b).

Run: CRUCIBLE_DATA_STORE=D:/proyectos/crucible/data/processed uv run pytest -m bench \\
        tests/bench/test_econ_events_real.py

Skipped when the raw folder or the built dataset is absent. The counts asserted here are the ones
`docs/data/econ-events.md` quotes: a change in a parsing rule that silently moves a row fails
this test, which is why the table in the page and the numbers below are the same numbers.
"""

from __future__ import annotations

import datetime as dt
import os
from pathlib import Path
from zoneinfo import ZoneInfo

import polars as pl
import pytest

from crucible.core.types import DatasetId
from crucible.data import econ_events as ee
from crucible.data.store import ParquetDataStore

STORE = Path(os.environ.get("CRUCIBLE_DATA_STORE", "data/processed"))
RAW = Path(os.environ.get("CRUCIBLE_ECON_RAW", "D:/proyectos/databases/econ_events/raw"))
pytestmark = pytest.mark.bench

DATASET = DatasetId("econ_events_v1")

# the coverage table of docs/data/econ-events.md: events per type per year
EXPECTED = {
    2010: (9, 12, 12),  # FOMC: 8 scheduled + the 2010-05-09 conference-call statement
    2011: (8, 12, 12),
    2012: (8, 12, 12),
    2013: (8, 12, 12),  # the October 2013 shutdown moved BLS releases inside the year
    2014: (8, 12, 12),
    2015: (8, 12, 12),
    2016: (8, 12, 12),
    2017: (8, 12, 12),
    2018: (8, 12, 12),
    2019: (9, 12, 12),  # FOMC: + the 2019-10-11 unscheduled statement
    2020: (10, 12, 12),  # FOMC: 7 meetings + 2020-03-03, -03-15, -03-23
    2021: (8, 12, 12),
    2022: (8, 12, 12),
    2023: (8, 12, 12),
    2024: (8, 12, 12),
    2025: (8, 12, 12),  # CPI/NFP: 3 rows each are rescheduled or cancelled (shutdown)
    2026: (8, 12, 12),  # FOMC: 7 released, 2026-12-09 still scheduled
    2027: (8, 12, 12),  # all scheduled
    2028: (1, 0, 0),  # the first meeting of 2028, announced in the 2027 calendar
}


def _need() -> None:
    if not (STORE / DATASET / "data.parquet").exists():
        pytest.skip(f"{DATASET} not built in {STORE}; see docs/data/econ-events.md")
    if not (RAW / "MANIFEST.json").exists():
        pytest.skip(f"the raw snapshots are not in {RAW}; see docs/data/econ-events.md")


@pytest.fixture(scope="module")
def frame() -> pl.DataFrame:
    _need()
    return pl.read_parquet(STORE / DATASET / "data.parquet")


def _local_year(frame: pl.DataFrame) -> pl.DataFrame:
    return frame.with_columns(
        pl.col("event_time")
        .cast(pl.Datetime("ns", "UTC"))
        .dt.convert_time_zone(ee.NEW_YORK)
        .dt.year()
        .alias("year")
    )


def test_per_year_counts_match_the_documented_table(frame: pl.DataFrame) -> None:
    counted = (
        _local_year(frame)
        .group_by("event_type", "year")
        .len()
        .pivot(on="event_type", index="year", values="len")
        .fill_null(0)
        .sort("year")
    )
    actual = {
        int(row["year"]): (
            int(row["FOMC_STATEMENT"]),
            int(row["CPI"]),
            int(row["NFP"]),
        )
        for row in counted.iter_rows(named=True)
    }
    assert actual == EXPECTED


def test_the_two_march_2020_unscheduled_actions_are_present(frame: pl.DataFrame) -> None:
    rows = frame.filter(
        pl.col("event_id").is_in(["FOMC_STATEMENT-20200303", "FOMC_STATEMENT-20200315"])
    )
    assert rows.height == 2
    local = {
        str(row["event_id"]): str(row["scheduled_local"]) for row in rows.iter_rows(named=True)
    }
    # 10:00 a.m. EST, and 5:00 p.m. EDT on a Sunday: both stated by the Fed's own press release
    assert local["FOMC_STATEMENT-20200303"] == "2020-03-03T10:00:00-05:00"
    assert local["FOMC_STATEMENT-20200315"] == "2020-03-15T17:00:00-04:00"
    assert rows["unscheduled"].all()


def test_no_duplicate_event_id(frame: pl.DataFrame) -> None:
    assert frame["event_id"].n_unique() == frame.height
    assert frame["record_sha256"].n_unique() == frame.height


def test_every_row_cites_a_snapshot_in_the_raw_folder(frame: pl.DataFrame) -> None:
    snapshots = {snapshot.sha256 for snapshot in ee.load_snapshots(RAW)}
    cited = set(frame["snapshot_sha256"].to_list())
    assert cited <= snapshots
    assert {row["source_url"] for row in frame.iter_rows(named=True)} <= {
        url for snapshot in ee.load_snapshots(RAW) for url in (snapshot.url, snapshot.origin_url)
    }


def test_the_stored_dataset_rebuilds_to_the_same_bytes(frame: pl.DataFrame, tmp_path: Path) -> None:
    report = ee.build_econ_events(RAW, tmp_path)
    stored = pl.read_parquet(STORE / DATASET / "data.parquet")
    assert report.content_hash == ParquetDataStore(STORE).manifest(DATASET).content_hash
    assert (tmp_path / DATASET / "data.parquet").read_bytes() == (
        STORE / DATASET / "data.parquet"
    ).read_bytes()
    assert report.rows == frame.height == stored.height


def test_the_dataset_starts_with_the_2010_releases_and_reaches_the_published_future(
    frame: pl.DataFrame,
) -> None:
    first = dt.datetime.fromtimestamp(frame["event_time"].min() / 1e9, tz=dt.UTC)
    last = dt.datetime.fromtimestamp(frame["event_time"].max() / 1e9, tz=dt.UTC)
    assert first.date() == dt.date(2010, 1, 8)  # the first release after 2010-01-01
    assert last.date() == dt.date(2028, 1, 26)  # the last meeting the Fed has announced


def test_the_release_time_is_known_from_2016_on_and_often_unknown_before(
    frame: pl.DataFrame,
) -> None:
    fomc = _local_year(frame.filter(pl.col("event_type") == "FOMC_STATEMENT"))
    by_year = {
        int(row["year"]): (int(row["len"]), int(row["len_right"]))
        for row in fomc.group_by("year")
        .agg(pl.len(), pl.col("time_known").sum())
        .rename({"time_known": "len_right"})
        .iter_rows(named=True)
    }
    for year in range(2011, 2016):  # the statements the Fed posted "for immediate release"
        assert by_year[year][1] == 0
    for year in range(2016, 2026):
        assert by_year[year][1] == by_year[year][0]
    assert by_year[2027][1] == 0  # a scheduled meeting states a date, not an hour


def test_the_2025_shutdown_left_two_cancelled_and_four_rescheduled_rows(
    frame: pl.DataFrame,
) -> None:
    statuses = dict(frame.group_by("status").len().iter_rows())
    assert statuses["cancelled"] == 2
    assert statuses["rescheduled"] == 4
    cancelled = frame.filter(pl.col("status") == "cancelled")
    assert set(cancelled["event_type"].to_list()) == {"CPI", "NFP"}
    assert cancelled["actual_publication_date"].is_null().all()
    # a rescheduled row keeps both dates: the earlier schedule and the one that materialised
    moved = frame.filter(pl.col("status") == "rescheduled")
    assert moved["actual_publication_date"].is_not_null().all()
    for row in moved.iter_rows(named=True):
        scheduled = str(row["scheduled_local"])[:10]
        assert scheduled < str(row["actual_publication_date"])


def test_coverage_has_exactly_one_hole(frame: pl.DataFrame) -> None:
    cov = ee.coverage_of(frame)
    gaps = cov.gaps
    assert len(gaps) == 1
    (gap,) = gaps
    # NFP: the October 2025 release was moved to 2025-11-20, so October holds no NFP event
    assert gap.event_type == "NFP"
    assert gap.periods == 1
    local = dt.datetime.fromtimestamp(gap.start_at / 1e9, tz=dt.UTC).astimezone(
        ZoneInfo(ee.NEW_YORK)
    )
    assert (local.year, local.month, local.day) == (2025, 10, 1)
