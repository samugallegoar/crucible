"""The economic-event calendar against the REAL raw snapshots and the REAL store (C7b).

Run: CRUCIBLE_DATA_STORE=D:/proyectos/crucible/data/processed uv run pytest -m bench \\
        tests/bench/test_econ_events_real.py

Skipped when the raw folder or the built dataset is absent. The counts asserted here are the ones
`docs/data/econ-events.md` quotes: a change in a parsing rule that silently moves a row fails
this test, which is why the table in the page and the numbers below are the same numbers.

`econ_events_v2` is asserted row by row against the *stored* `econ_events_v1`: every v1 row must
appear in v2 unchanged except `dataset_version` (and the record hash that covers it). That is the
whole promise of the v2 build — the three new types are an addition, not a revision.
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

DATASET = DatasetId("econ_events_v2")
DATASET_V1 = DatasetId("econ_events_v1")

# the coverage table of docs/data/econ-events.md: events per type per year
EXPECTED = {
    2010: (9, 0, 7, 12, 12, 12),  # FOMC: 8 scheduled + the 2010-05-09 conference-call statement
    2011: (8, 3, 8, 12, 12, 12),  # press conferences start in April 2011 (3 that year)
    2012: (8, 5, 8, 12, 12, 12),
    2013: (8, 4, 8, 12, 12, 12),  # the October 2013 shutdown moved BLS releases inside the year
    2014: (8, 4, 8, 12, 12, 12),
    2015: (8, 4, 8, 12, 12, 12),
    2016: (8, 4, 8, 12, 12, 12),  # the Fed starts stating the statement release hour
    2017: (8, 4, 8, 12, 12, 12),
    2018: (8, 4, 8, 12, 12, 12),
    2019: (9, 8, 8, 12, 12, 12),  # FOMC: + the 2019-10-11 unscheduled statement
    2020: (10, 9, 8, 12, 12, 12),  # FOMC: 7 meetings + 2020-03-03, -03-15, -03-23
    2021: (8, 8, 8, 12, 12, 12),
    2022: (8, 8, 8, 12, 12, 12),
    2023: (8, 8, 8, 12, 12, 12),
    2024: (8, 8, 8, 12, 12, 12),  # minutes: 2023-12-13's set landed in 2024, 2024-11-07's in 2025
    2025: (8, 8, 9, 12, 12, 11),  # press conference minutes + 3 rows rescheduled, 1 PPI cancelled
    # FOMC: 2026-12-09 still `scheduled`; PPI: the 2025 release the shutdown moved landed here
    2026: (8, 7, 7, 12, 12, 13),
    2027: (8, 0, 0, 12, 12, 12),  # all `scheduled`; no press conference or minutes linked yet
    2028: (1, 0, 0, 0, 0, 0),  # the first meeting of 2028, announced in the 2027 calendar
}
TYPES = (
    "FOMC_STATEMENT",
    "FOMC_PRESS_CONFERENCE",
    "FOMC_MINUTES",
    "CPI",
    "NFP",
    "PPI",
)


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
        int(row["year"]): tuple(int(row[event_type]) for event_type in TYPES)
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
    # both emergency actions had a press conference, and the Fed files its minutes under the
    # 2020-03-15 meeting's page (there is no separate set for 2020-03-03)
    conferences = frame.filter(
        pl.col("event_id").is_in(
            ["FOMC_PRESS_CONFERENCE-20200303", "FOMC_PRESS_CONFERENCE-20200315"]
        )
    )
    assert conferences.height == 2
    assert conferences["unscheduled"].all()


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


def test_the_v1_rows_are_untouched_by_the_v2_build(frame: pl.DataFrame) -> None:
    """The reason v2 is a separate dataset: a consumer that pinned v1 sees the same rows.

    Every v1 row appears in v2 under the same id, with the same instants, status, source and
    snapshot hash; only ``dataset_version`` and the ``record_sha256`` that covers it differ.
    """
    stored_v1 = STORE / DATASET_V1 / "data.parquet"
    if not stored_v1.exists():
        pytest.skip(f"{DATASET_V1} not in {STORE}; the comparison needs both versions")
    v1 = pl.read_parquet(stored_v1)
    columns = [name for name in v1.columns if name not in ("dataset_version", "record_sha256")]
    left = v1.select(columns).sort("event_id")
    right = frame.filter(pl.col("event_type").is_in(ee.EVENT_TYPES_V1)).select(columns)
    assert left.height == right.height
    assert left.equals(right.sort("event_id"))
    assert set(frame["dataset_version"].unique()) == {ee.DATASET_VERSION}


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


def test_no_page_states_the_hour_of_a_press_conference(frame: pl.DataFrame) -> None:
    conferences = frame.filter(pl.col("event_type") == "FOMC_PRESS_CONFERENCE")
    assert conferences.height == 96
    # a press conference is dated to its meeting's day and no page states its hour
    assert not conferences["time_known"].any()
    assert set(conferences["scheduled_time_source"].unique()) == {"not_stated"}
    midnight = conferences["scheduled_local"].str.slice(10)
    assert ((midnight == "T00:00:00-04:00") | (midnight == "T00:00:00-05:00")).all()
    assert set(conferences["status"].unique()) == {"released"}


def test_the_minutes_hour_is_known_where_the_fed_states_it(frame: pl.DataFrame) -> None:
    minutes = _local_year(frame.filter(pl.col("event_type") == "FOMC_MINUTES"))
    per_year = {
        int(row["year"]): (int(row["len"]), int(row["known"]))
        for row in minutes.group_by("year")
        .agg(pl.len(), pl.col("time_known").sum().alias("known"))
        .iter_rows(named=True)
    }
    # 2010-2011 press-conference pages state the minutes *day* only; 2012 on state 2:00 p.m.
    assert per_year[2010] == (7, 0)
    assert per_year[2011] == (8, 0)
    assert per_year[2012] == (8, 4)  # four meetings had a press conference that year
    assert per_year[2013] == (8, 4)
    assert per_year[2019] == (8, 8)
    assert per_year[2024] == (8, 7)  # the 2024-11-07 press-conference page omits the entry
    assert per_year[2026] == (7, 7)
    known = frame.filter((pl.col("event_type") == "FOMC_MINUTES") & pl.col("time_known"))
    # every stated hour is 2:00 p.m. Eastern, and the row cites the press-conference page
    assert set(known["scheduled_local"].str.slice(10, 9).unique()) == {"T14:00:00"}
    assert known["source_url"].str.contains("conf").all()


def test_the_2025_shutdown_left_three_cancelled_and_six_rescheduled_rows(
    frame: pl.DataFrame,
) -> None:
    statuses = dict(frame.group_by("status").len().iter_rows())
    assert statuses["cancelled"] == 3
    assert statuses["rescheduled"] == 6
    cancelled = frame.filter(pl.col("status") == "cancelled")
    assert set(cancelled["event_type"].to_list()) == {"CPI", "NFP", "PPI"}
    assert cancelled["actual_publication_date"].is_null().all()
    # a rescheduled row keeps both dates: the earlier schedule and the one that materialised
    moved = frame.filter(pl.col("status") == "rescheduled")
    assert moved["actual_publication_date"].is_not_null().all()
    for row in moved.iter_rows(named=True):
        scheduled = str(row["scheduled_local"])[:10]
        assert scheduled < str(row["actual_publication_date"])
    # one PPI release moved from the 2025 schedule onto the 2026 page, and is not double-counted
    november_ppi = frame.filter(pl.col("event_id") == "PPI-20251211")
    assert november_ppi.height == 1
    (row,) = november_ppi.iter_rows(named=True)
    assert row["status"] == "rescheduled"
    assert row["actual_publication_date"] == "2026-01-14"
    assert frame.filter(pl.col("actual_publication_date") == "2026-01-14").height == 1


def test_coverage_reports_the_three_months_the_shutdown_left_empty(frame: pl.DataFrame) -> None:
    cov = ee.coverage_of(frame)
    gaps = {(gap.event_type, _period_start(gap.start_at)) for gap in cov.gaps}
    assert gaps == {
        ("NFP", dt.date(2025, 10, 1)),
        ("PPI", dt.date(2025, 10, 1)),
        ("PPI", dt.date(2025, 12, 1)),
    }


def _period_start(stamp: int) -> dt.date:
    local = dt.datetime.fromtimestamp(stamp / 1e9, tz=dt.UTC).astimezone(ZoneInfo(ee.NEW_YORK))
    return local.date()


def test_a_v1_rebuild_reproduces_the_stored_v1_rows(tmp_path: Path) -> None:
    """``version=1`` still means v1: same ids, same instants, same hashes, only the column moved.

    The stored ``econ_events_v1`` carries the dataset *name* in a ``String`` column; a rebuild under
    the current schema writes ``1`` in the ``Int64`` column. Every other field must match.
    """
    stored = STORE / DATASET_V1 / "data.parquet"
    if not stored.exists():
        pytest.skip(f"{DATASET_V1} not in {STORE}")
    ee.build_econ_events(RAW, tmp_path, version=1)
    rebuilt = pl.read_parquet(tmp_path / DATASET_V1 / "data.parquet")
    v1 = pl.read_parquet(stored)
    columns = [name for name in v1.columns if name not in ("dataset_version", "record_sha256")]
    assert rebuilt.height == v1.height
    assert rebuilt.select(columns).sort("event_id").equals(v1.select(columns).sort("event_id"))
    assert set(rebuilt["dataset_version"].unique()) == {ee.DATASET_VERSION_V1}
