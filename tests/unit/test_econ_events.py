"""The economic-event calendar: parsing, ids, hashes, availability, coverage (C7b, ADR-0107).

Every fixture here is a small hand-written page in the shape the source serves — the Fed's
statement/calendar/historical pages and the BLS "Schedule of Selected Releases" page — so a
parsing rule is tested without a network and with hand-computed expectations. The real snapshots
and the real store are exercised by ``tests/bench/test_econ_events_real.py``.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from pathlib import Path
from typing import TYPE_CHECKING

import polars as pl
import pytest

from crucible.core.errors import ConfigurationError, DataQualityError
from crucible.core.types import DatasetId
from crucible.data import econ_events as ee
from crucible.data.store import ParquetDataStore

if TYPE_CHECKING:
    from collections.abc import Iterator

FED = "https://www.federalreserve.gov"
BLS = "https://www.bls.gov"


# --------------------------------------------------------------------------------- fixtures


def statement_page(date_text: str, release_line: str) -> str:
    """An FOMC statement press release page, in the Fed's markup."""
    return (
        '<div id="article"><div class="heading">'
        f'<p class="article__time">{date_text}</p>'
        '<h3 class="title">FOMC statement</h3>'
        f'<p class="releaseTime">{release_line}'
        "</p></div></div>"
    )


def historical_page(panels: list[tuple[str, str, str]]) -> str:
    """An ``fomchistorical<YEAR>.htm`` page: ``(heading, link href, link label)`` per panel."""
    body = "".join(
        f'<div class="panel panel-default">\n<div class="panel-heading"><h5>{heading}</h5></div>'
        f'\n<div class="row"><p><a href="{href}">{label}</a></p></div>\n</div>'
        for heading, href, label in panels
    )
    return f'<div id="article"><h3>2010</h3>{body}</div>'


def calendar_page(years: dict[int, list[tuple[str, str, str]]]) -> str:
    """An ``fomccalendars.htm`` page: per year, ``(month, date range, statement href or "")``."""
    body = ""
    for year, rows in years.items():
        body += f'<h4><a id="{year}">{year} FOMC Meetings</a></h4>'
        for index, (month, dates, href) in enumerate(rows):
            css = "fomc-meeting--shaded row fomc-meeting" if index % 2 else "row fomc-meeting"
            links = (
                f'<strong>Statement:</strong><br><a href="{href}">PDF</a> | '
                f'<a href="{href}">HTML</a>'
                if href
                else ""
            )
            body += (
                f'<div class="{css}" ">'
                f'<div class="fomc-meeting__month col-xs-5"><strong>{month}</strong></div>'
                f'<div class="fomc-meeting__date col-xs-4">{dates}</div>'
                f'<div class="col-xs-12">{links}</div></div>'
            )
    return f'<div id="article">{body}</div>'


def bls_page(rows: list[tuple[str, str, str]]) -> str:
    """A BLS "Schedule of Selected Releases" page: ``(date, time, description)`` per row."""
    body = "".join(
        f'<tr class="release-list-odd-row"><td class="date-cell"><p>{date}</p></td>'
        f'<td class="time-cell"><p>{time or "&nbsp;"}</p></td>'
        f'<td class="desc-cell"><p><strong>{desc}</strong></p></td></tr>'
        for date, time, desc in rows
    )
    return f'<table class="release-list"><tbody>{body}</tbody></table>'


class RawDir:
    """A raw folder built by hand: one page per (source, file name) plus its MANIFEST.json."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.entries: list[dict[str, object]] = []

    def add(
        self,
        source: str,
        name: str,
        origin: str,
        body: str,
        *,
        retrieved_at: str = "2026-11-22T02:40:00Z",
        capture_at: str | None = None,
        url: str | None = None,
    ) -> RawDir:
        path = self.root / source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        data = body.encode("utf-8")
        path.write_bytes(data)
        self.entries.append(
            {
                "url": url or origin,
                "origin_url": origin,
                "source": source,
                "path": path.relative_to(self.root).as_posix(),
                "retrieved_at": retrieved_at,
                "capture_at": capture_at,
                "sha256": hashlib.sha256(data).hexdigest(),
                "bytes": len(data),
            }
        )
        return self

    def write(self) -> Path:
        (self.root / ee.MANIFEST_NAME).write_text(
            json.dumps({"entries": self.entries}, indent=2) + "\n", encoding="utf-8"
        )
        return self.root


def fed_statement(raw: RawDir, key: str, date_text: str, release_line: str) -> str:
    url = f"{FED}/newsevents/pressreleases/monetary{key}.htm"
    raw.add(
        "federalreserve",
        f"20261122_monetary{key}.html",
        url,
        statement_page(date_text, release_line),
    )
    return url


@pytest.fixture
def raw_dir(tmp_path: Path) -> RawDir:
    """One Fed historical page (2010), one calendar page (2026/2027), one BLS year, and the
    statement pages they link."""
    raw = RawDir(tmp_path / "raw")
    fed_statement(raw, "20100127a", "January 27, 2010", "For immediate release")
    fed_statement(raw, "20100509a", "May 09, 2010", "For release at 9:15 p.m. EDT")
    fed_statement(raw, "20260128a", "January 28, 2026", "For release at 2:00 p.m. EST")
    raw.add(
        "federalreserve",
        "20261122_fomchistorical2010.html",
        f"{FED}/monetarypolicy/fomchistorical2010.htm",
        historical_page(
            [
                (
                    "January 26-27 Meeting - 2010",
                    "/newsevents/press/monetary/20100127a.htm",
                    "Statement",
                ),
                (
                    "May 9 Conference Call - 2010",
                    "/newsevents/press/monetary/20100509a.htm",
                    "Statement",
                ),
                ("March 16 Meeting - 2010", "/newsevents/press/monetary/20100316a.htm", "Minutes"),
            ]
        ),
    )
    raw.add(
        "federalreserve",
        "20261122_fomccalendars.html",
        f"{FED}/monetarypolicy/fomccalendars.htm",
        calendar_page(
            {
                2026: [
                    ("January", "27-28", "/newsevents/pressreleases/monetary20260128a.htm"),
                    ("March", "17-18*", ""),
                    ("August", "22 (notation vote)", ""),
                ],
                2027: [("January", "26-27", "")],
            }
        )
        + (
            "<p>Note: A two-day meeting is scheduled for January 25-26, 2028. Each meeting date is "
            "tentative until confirmed at the meeting immediately preceding it.</p>"
        ),
    )
    raw.add(
        "bls",
        "20261122_schedule_2010.html",
        f"{BLS}/schedule/2010/home.htm",
        bls_page(
            [
                ("Friday, January 08, 2010", "08:30 AM", "Employment Situation for December 2009"),
                ("Friday, January 15, 2010", "08:30 AM", "Consumer Price Index for December 2009"),
                (
                    "Friday, March 12, 2010",
                    "10:00 AM",
                    "Employment Situation of Veterans for Annual 2009",
                ),
                ("Friday, December 31, 2010", "", "New Year's Day"),
            ]
        ),
    )
    raw.write()
    return raw


def build(raw: RawDir, store: Path) -> ee.BuildReport:
    return ee.build_econ_events(raw.root, store)


def by_id(frame: pl.DataFrame) -> dict[str, dict[str, object]]:
    return {str(row["event_id"]): row for row in frame.iter_rows(named=True)}


# ---------------------------------------------------------------------------- statement pages


def test_statement_page_states_the_hour_and_the_offset() -> None:
    day, clock, source = ee.parse_fomc_statement(
        statement_page("January 28, 2026", "For release at 2:00 p.m. EST"),
        f"{FED}/newsevents/pressreleases/monetary20260128a.htm",
    )
    assert (day, clock, source) == (dt.date(2026, 1, 28), dt.time(14, 0), "fed_stated")


def test_statement_page_without_an_hour_says_so_instead_of_inventing_one() -> None:
    day, clock, source = ee.parse_fomc_statement(
        statement_page("January 27, 2010", "For immediate release"),
        f"{FED}/newsevents/pressreleases/monetary20100127a.htm",
    )
    assert day == dt.date(2010, 1, 27)
    assert clock is None
    assert source == "not_stated"


def test_statement_page_refuses_a_url_date_that_disagrees_with_the_page() -> None:
    with pytest.raises(DataQualityError, match="file name says 2010-01-26"):
        ee.parse_fomc_statement(
            statement_page("January 27, 2010", "For immediate release"),
            f"{FED}/newsevents/pressreleases/monetary20100126a.htm",
        )


def test_statement_page_refuses_a_zone_abbreviation_that_contradicts_the_date() -> None:
    # January in New York is EST: a page printing EDT in January contradicts itself
    with pytest.raises(DataQualityError, match="prints EDT"):
        ee.parse_fomc_statement(
            statement_page("January 28, 2026", "For release at 2:00 p.m. EDT"),
            f"{FED}/newsevents/pressreleases/monetary20260128a.htm",
        )


def test_statement_page_refuses_an_unreadable_release_line() -> None:
    with pytest.raises(DataQualityError, match="cannot read the release time"):
        ee.parse_fomc_statement(
            statement_page("January 28, 2026", "Available now"),
            f"{FED}/newsevents/pressreleases/monetary20260128a.htm",
        )


# ------------------------------------------------------------------------- historical page


def test_historical_page_reads_meetings_and_flags_intermeeting_actions() -> None:
    statements = {
        f"{FED}/newsevents/pressreleases/monetary20100127a.htm": (
            dt.date(2010, 1, 27),
            None,
            "not_stated",
        ),
        f"{FED}/newsevents/pressreleases/monetary20100509a.htm": (
            dt.date(2010, 5, 9),
            dt.time(21, 15),
            "fed_stated",
        ),
    }
    text = historical_page(
        [
            (
                "January 26-27 Meeting - 2010",
                "/newsevents/press/monetary/20100127a.htm",
                "Statement",
            ),
            (
                "May 9 Conference Call - 2010",
                "/newsevents/press/monetary/20100509a.htm",
                "Statement",
            ),
            (
                "March 15 (unscheduled) Meeting - 2010",
                "/newsevents/press/monetary/20100315a.htm",
                "Statement",
            ),
            ("March 16 Meeting - 2010", "/newsevents/press/monetary/20100316a.htm", "Minutes"),
            ("March 17-18 (cancelled) Meeting - 2010", "", ""),
        ]
    )
    statements[f"{FED}/newsevents/pressreleases/monetary20100315a.htm"] = (
        dt.date(2010, 3, 15),
        dt.time(10, 0),
        "fed_stated",
    )
    events = ee.parse_fomc_historical(
        text, f"{FED}/monetarypolicy/fomchistorical2010.htm", statements
    )
    assert [(e.scheduled_day, e.unscheduled) for e in events] == [
        (dt.date(2010, 1, 27), False),
        (dt.date(2010, 5, 9), True),
        (dt.date(2010, 3, 15), True),
    ]


def test_historical_page_refuses_a_statement_it_has_no_snapshot_of() -> None:
    text = historical_page(
        [("January 26-27 Meeting - 2010", "/newsevents/press/monetary/20100127a.htm", "Statement")]
    )
    with pytest.raises(ConfigurationError, match="no snapshot of it"):
        ee.parse_fomc_historical(text, f"{FED}/monetarypolicy/fomchistorical2010.htm", {})


def test_notation_vote_labelled_statement_is_an_intermeeting_action() -> None:
    statements = {
        f"{FED}/newsevents/pressreleases/monetary20200323a.htm": (
            dt.date(2020, 3, 23),
            dt.time(8, 0),
            "fed_stated",
        )
    }
    text = historical_page(
        [
            (
                "March 23 (notation vote) - 2020",
                "/newsevents/pressreleases/monetary20200323a.htm",
                "Statement",
            )
        ]
    )
    events = ee.parse_fomc_historical(
        text, f"{FED}/monetarypolicy/fomchistorical2020.htm", statements
    )
    assert [(e.scheduled_day, e.unscheduled) for e in events] == [(dt.date(2020, 3, 23), True)]


# --------------------------------------------------------------------------- calendar page


def test_calendar_page_reads_released_and_future_meetings() -> None:
    statements = {
        f"{FED}/newsevents/pressreleases/monetary20260128a.htm": (
            dt.date(2026, 1, 28),
            dt.time(14, 0),
            "fed_stated",
        )
    }
    text = calendar_page(
        {
            2026: [
                ("January", "27-28", "/newsevents/pressreleases/monetary20260128a.htm"),
                ("March", "17-18*", ""),
                ("August", "22 (notation vote)", ""),
            ],
            2027: [("January", "26-27", "")],
        }
    )
    events = ee.parse_fomc_calendar(text, f"{FED}/monetarypolicy/fomccalendars.htm", statements)
    assert [(e.scheduled_day, e.scheduled_clock, e.status) for e in events] == [
        (dt.date(2026, 1, 28), dt.time(14, 0), "released"),
        (dt.date(2026, 3, 18), None, "scheduled"),
        (dt.date(2027, 1, 27), None, "scheduled"),
    ]


def test_calendar_page_next_year_note_is_one_more_meeting() -> None:
    text = calendar_page({2027: [("January", "26-27", "")]}) + (
        "<p>Note: A two-day meeting is scheduled for January 25-26, 2028. Each meeting date is "
        "tentative until confirmed at the meeting immediately preceding it.</p>"
    )
    events = ee.parse_fomc_calendar(text, f"{FED}/monetarypolicy/fomccalendars.htm", {})
    assert [e.scheduled_day for e in events] == [dt.date(2027, 1, 27), dt.date(2028, 1, 26)]


def test_calendar_page_refuses_a_future_range_that_wraps_a_month_end() -> None:
    text = calendar_page({2026: [("Apr/May", "30-1", "")]})
    with pytest.raises(DataQualityError, match="wraps a month end"):
        ee.parse_fomc_calendar(text, f"{FED}/monetarypolicy/fomccalendars.htm", {})


# ------------------------------------------------------------------------------- bls page


def test_bls_page_reads_cpi_and_employment_situation_only() -> None:
    text = bls_page(
        [
            ("Friday, January 08, 2010", "08:30 AM", "Employment Situation for December 2009"),
            ("Friday, January 15, 2010", "08:30 AM", "Consumer Price Index for December 2009"),
            (
                "Friday, March 12, 2010",
                "10:00 AM",
                "Employment Situation of Veterans for Annual 2009",
            ),
            ("Friday, January 01, 2010", "", "New Year's Day"),
        ]
    )
    events = ee.parse_bls_schedule(text, f"{BLS}/schedule/2010/home.htm")
    assert [(e.event_type, e.scheduled_day, e.scheduled_clock, e.period) for e in events] == [
        ("NFP", dt.date(2010, 1, 8), dt.time(8, 30), "December 2009"),
        ("CPI", dt.date(2010, 1, 15), dt.time(8, 30), "December 2009"),
    ]


def test_bls_page_keeps_a_row_without_a_time_and_says_the_time_is_unknown() -> None:
    text = bls_page([("Friday, January 15, 2010", "", "Consumer Price Index for December 2009")])
    (event,) = ee.parse_bls_schedule(text, f"{BLS}/schedule/2010/home.htm")
    assert event.scheduled_clock is None
    assert event.scheduled_time_source == "not_stated"


def test_bls_page_refuses_a_row_outside_the_page_year() -> None:
    text = bls_page(
        [("Friday, January 15, 2011", "08:30 AM", "Consumer Price Index for December 2010")]
    )
    with pytest.raises(DataQualityError, match="but the page is the 2010 schedule"):
        ee.parse_bls_schedule(text, f"{BLS}/schedule/2010/home.htm")


# ----------------------------------------------------------------------- daylight saving


@pytest.mark.parametrize(
    ("day", "expected_iso", "expected_ns"),
    [
        # 08:30 EDT on 2026-03-11, 08:30 EST on 2026-11-10: one hour apart in UTC
        (dt.date(2026, 3, 11), "2026-03-11T08:30:00-04:00", 1773232200),
        (dt.date(2026, 11, 10), "2026-11-10T08:30:00-05:00", 1794317400),
    ],
)
def test_new_york_wall_clock_carries_the_offset_of_that_date(
    day: dt.date, expected_iso: str, expected_ns: int
) -> None:
    ns, iso = ee.new_york_ns(day, dt.time(8, 30))
    assert iso == expected_iso
    assert ns == expected_ns * ee._NS_PER_S


def test_new_york_midnight_is_the_start_of_the_local_day() -> None:
    ns, iso = ee.new_york_ns(dt.date(2010, 1, 27), None)
    assert iso == "2010-01-27T00:00:00-05:00"
    assert ns == 1264568400 * ee._NS_PER_S


# ----------------------------------------------------------------------------- the build


def test_build_writes_the_contract_and_the_expected_rows(raw_dir: RawDir, tmp_path: Path) -> None:
    report = build(raw_dir, tmp_path / "store")
    frame = pl.read_parquet(tmp_path / "store" / ee.DATASET / "data.parquet")
    assert frame.schema == ee.ECON_EVENT_SCHEMA
    # FOMC: 2010-01-27 (day only), 2010-05-09, 2026-01-28, and three meetings still ahead
    assert report.rows == frame.height == 8
    assert report.events_by_type == {"FOMC_STATEMENT": 6, "CPI": 1, "NFP": 1}
    assert report.events_by_status == {
        "released": 5,
        "rescheduled": 0,
        "scheduled": 3,
        "cancelled": 0,
    }
    rows = by_id(frame)
    assert rows["FOMC_STATEMENT-20100127"]["time_known"] is False
    assert rows["FOMC_STATEMENT-20100127"]["scheduled_local"] == "2010-01-27T00:00:00-05:00"
    assert rows["FOMC_STATEMENT-20100509"]["scheduled_local"] == "2010-05-09T21:15:00-04:00"
    assert rows["FOMC_STATEMENT-20100509"]["unscheduled"] is True
    assert rows["CPI-20100115"]["scheduled_local"] == "2010-01-15T08:30:00-05:00"
    assert rows["NFP-20100108"]["actual_publication_date"] == "2010-01-08"


def test_build_is_byte_identical_for_identical_snapshots(raw_dir: RawDir, tmp_path: Path) -> None:
    first = build(raw_dir, tmp_path / "a")
    second = build(raw_dir, tmp_path / "b")
    assert first.content_hash == second.content_hash
    assert (tmp_path / "a" / ee.DATASET / "data.parquet").read_bytes() == (
        tmp_path / "b" / ee.DATASET / "data.parquet"
    ).read_bytes()


def test_build_refuses_to_overwrite_a_stored_dataset(raw_dir: RawDir, tmp_path: Path) -> None:
    build(raw_dir, tmp_path / "store")
    with pytest.raises(ConfigurationError, match="refuses to overwrite"):
        build(raw_dir, tmp_path / "store")


def test_event_id_is_stable_and_the_record_hash_covers_every_other_field(
    raw_dir: RawDir, tmp_path: Path
) -> None:
    build(raw_dir, tmp_path / "store")
    frame = pl.read_parquet(tmp_path / "store" / ee.DATASET / "data.parquet")
    row = by_id(frame)["FOMC_STATEMENT-20100127"]
    payload = {key: value for key, value in row.items() if key != "record_sha256"}
    assert ee.record_sha256(payload) == row["record_sha256"]
    assert row["event_id"] == "FOMC_STATEMENT-20100127"
    # a hash of every row is unique: two rows never collide
    assert frame["record_sha256"].n_unique() == frame.height


def test_event_ids_are_unique(raw_dir: RawDir, tmp_path: Path) -> None:
    build(raw_dir, tmp_path / "store")
    frame = pl.read_parquet(tmp_path / "store" / ee.DATASET / "data.parquet")
    assert frame["event_id"].n_unique() == frame.height


def test_available_at_is_the_event_instant_when_no_page_states_a_publication_date(
    raw_dir: RawDir, tmp_path: Path
) -> None:
    build(raw_dir, tmp_path / "store")
    frame = pl.read_parquet(tmp_path / "store" / ee.DATASET / "data.parquet")
    assert set(frame["availability_basis"].unique()) == {"schedule_publication_unknown"}
    assert (frame["available_at"] == frame["event_time"]).all()


def test_a_stated_publication_date_moves_available_at_earlier() -> None:
    """A schedule published in advance is knowable before the event: the one case where
    ``available_at < event_time``, which is why the column carries its basis."""
    event = ee.RawEvent(
        event_type="CPI",
        scheduled_day=dt.date(2026, 3, 11),
        scheduled_clock=dt.time(8, 30),
        scheduled_time_source="bls_stated",
        status="scheduled",
        actual_day=None,
        unscheduled=False,
        source_url="https://www.bls.gov/schedule/2026/home.htm",
        stated_publication_day=dt.date(2025, 12, 10),
    )
    (row,) = ee._event_rows([event], {"https://www.bls.gov/schedule/2026/home.htm": "0" * 64})
    assert row["availability_basis"] == "schedule_page_stated_date"
    assert row["available_at"] == ee.new_york_ns(dt.date(2025, 12, 10), None)[0]
    assert row["available_at"] < row["event_time"]


def test_snapshots_and_manifest_are_the_source_of_truth(raw_dir: RawDir, tmp_path: Path) -> None:
    build(raw_dir, tmp_path / "store")
    page = raw_dir.root / "bls" / "20261122_schedule_2010.html"
    page.write_text(page.read_text(encoding="utf-8") + " ", encoding="utf-8")
    with pytest.raises(DataQualityError, match="was modified"):
        build(raw_dir, tmp_path / "second")


def test_missing_manifest_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ConfigurationError, match=r"MANIFEST\.json"):
        ee.build_econ_events(tmp_path / "empty", tmp_path / "store")


# ------------------------------------------------------------- rescheduled and cancelled rows


def _schedule_raw(tmp_path: Path, *, delayed: bool) -> RawDir:
    raw = RawDir(tmp_path / ("delayed" if delayed else "current"))
    fed_statement(raw, "20100127a", "January 27, 2010", "For release at 2:15 p.m. EST")
    raw.add(
        "federalreserve",
        "20261122_fomchistorical2010.html",
        f"{FED}/monetarypolicy/fomchistorical2010.htm",
        historical_page(
            [
                (
                    "January 26-27 Meeting - 2010",
                    "/newsevents/press/monetary/20100127a.htm",
                    "Statement",
                )
            ]
        ),
    )
    current = bls_page(
        [
            ("Friday, February 05, 2010", "08:30 AM", "Employment Situation for January 2010"),
            ("Friday, February 19, 2010", "08:30 AM", "Consumer Price Index for January 2010"),
        ]
    )
    raw.add("bls", "20261122_schedule_2010.html", f"{BLS}/schedule/2010/home.htm", current)
    earlier = bls_page(
        [
            ("Friday, February 05, 2010", "08:30 AM", "Employment Situation for January 2010"),
            ("Wednesday, February 17, 2010", "08:30 AM", "Consumer Price Index for January 2010"),
            ("Friday, March 05, 2010", "08:30 AM", "Employment Situation for February 2010"),
        ]
    )
    raw.add(
        "bls",
        "20261122_schedule_2010_20100201.html",
        f"{BLS}/schedule/2010/home.htm",
        earlier,
        capture_at="2010-02-01T00:00:00Z",
        url="https://web.archive.org/web/20100201000000/https://www.bls.gov/schedule/2010/home.htm",
    )
    raw.write()
    return raw


def test_a_moved_release_keeps_both_dates(tmp_path: Path) -> None:
    build(_schedule_raw(tmp_path, delayed=True), tmp_path / "store")
    frame = pl.read_parquet(tmp_path / "store" / ee.DATASET / "data.parquet")
    row = by_id(frame)["CPI-20100217"]
    assert row["status"] == "rescheduled"
    assert row["scheduled_local"] == "2010-02-17T08:30:00-05:00"
    assert row["actual_publication_date"] == "2010-02-19"
    assert row["event_time"] == ee.new_york_ns(dt.date(2010, 2, 19), dt.time(8, 30))[0]
    assert row["source_url"] == f"{BLS}/schedule/2010/home.htm"


def test_a_release_the_current_schedule_drops_is_cancelled(tmp_path: Path) -> None:
    build(_schedule_raw(tmp_path, delayed=True), tmp_path / "store")
    frame = pl.read_parquet(tmp_path / "store" / ee.DATASET / "data.parquet")
    row = by_id(frame)["NFP-20100305"]
    assert row["status"] == "cancelled"
    assert row["actual_publication_date"] is None
    assert row["scheduled_local"] == "2010-03-05T08:30:00-05:00"
    assert "web.archive.org" in str(row["source_url"])


def test_an_unchanged_release_is_not_duplicated_by_the_earlier_snapshot(tmp_path: Path) -> None:
    build(_schedule_raw(tmp_path, delayed=True), tmp_path / "store")
    frame = pl.read_parquet(tmp_path / "store" / ee.DATASET / "data.parquet")
    # the unchanged release appears once, under its own id, and the moved one under the earlier date
    assert frame.filter(pl.col("event_id") == "NFP-20100205").height == 1
    assert frame.filter(pl.col("event_id") == "CPI-20100217").height == 1
    assert frame.filter(pl.col("status") == "released").height == 2


# -------------------------------------------------------------------------------- coverage


def test_coverage_reports_the_month_without_a_release(tmp_path: Path) -> None:
    build(_schedule_raw(tmp_path, delayed=True), tmp_path / "store")
    store = ParquetDataStore(tmp_path / "store")
    cov = ee.coverage(store)
    # CPI: February (the moved release) and March (cancelled NFP keeps its month) are covered;
    # NFP has no release at all in March because the current schedule dropped the March 5 one
    assert cov.gaps_of("NFP") == ()
    assert cov.gaps_of("CPI") == ()
    assert [span.event_type for span in cov.spans if span.event_type == "NFP"] == ["NFP"]


def test_a_monthly_type_reports_a_hole_and_an_irregular_type_a_missing_year() -> None:
    frame = pl.DataFrame(
        [
            _synthetic_row("CPI", dt.date(2026, 1, 13)),
            _synthetic_row("CPI", dt.date(2026, 3, 11)),
            _synthetic_row("FOMC_STATEMENT", dt.date(2025, 1, 29)),
            _synthetic_row("FOMC_STATEMENT", dt.date(2027, 1, 27)),
        ],
        orient="row",
        schema=ee.ECON_EVENT_SCHEMA,
    )
    cov = ee.coverage_of(frame)
    cpi_gap = cov.gaps_of("CPI")
    assert len(cpi_gap) == 1
    assert cpi_gap[0].periods == 1
    assert cpi_gap[0].start_at == ee.new_york_ns(dt.date(2026, 2, 1), None)[0]
    fomc_gap = cov.gaps_of("FOMC_STATEMENT")
    assert len(fomc_gap) == 1
    assert fomc_gap[0].periods == 1
    assert fomc_gap[0].start_at == ee.new_york_ns(dt.date(2026, 1, 1), None)[0]


def _synthetic_row(event_type: str, day: dt.date) -> dict[str, object]:
    ns, iso = ee.new_york_ns(day, dt.time(8, 30))
    row: dict[str, object] = {
        "event_id": f"{event_type}-{day.strftime('%Y%m%d')}",
        "event_type": event_type,
        "scheduled_local": iso,
        "timezone": ee.NEW_YORK,
        "event_time": ns,
        "time_known": True,
        "scheduled_time_source": "bls_stated",
        "status": "released",
        "actual_publication_date": day.isoformat(),
        "unscheduled": False,
        "source_url": f"{BLS}/schedule/{day.year}/home.htm",
        "snapshot_sha256": "0" * 64,
        "available_at": ns,
        "availability_basis": "schedule_publication_unknown",
        "dataset_version": ee.DATASET_VERSION,
    }
    row["record_sha256"] = ee.record_sha256(row)
    return row


# ---------------------------------------------------------------------------------- access


def test_load_econ_events_filters_by_type_and_window(raw_dir: RawDir, tmp_path: Path) -> None:
    build(raw_dir, tmp_path / "store")
    store = ParquetDataStore(tmp_path / "store")
    start, _ = ee.new_york_ns(dt.date(2010, 1, 1), None)
    end, _ = ee.new_york_ns(dt.date(2010, 2, 1), None)
    frame = ee.load_econ_events(store, ["CPI", "NFP"], start, end)
    assert sorted(frame["event_id"].to_list()) == ["CPI-20100115", "NFP-20100108"]
    assert frame.schema == ee.ECON_EVENT_SCHEMA


def test_load_econ_events_refuses_an_unknown_type(raw_dir: RawDir, tmp_path: Path) -> None:
    build(raw_dir, tmp_path / "store")
    store = ParquetDataStore(tmp_path / "store")
    with pytest.raises(ConfigurationError, match="unknown event_type"):
        ee.load_econ_events(store, ["GDP"])


def test_load_econ_events_honours_an_explicit_as_of(raw_dir: RawDir, tmp_path: Path) -> None:
    build(raw_dir, tmp_path / "store")
    store = ParquetDataStore(tmp_path / "store")
    before, _ = ee.new_york_ns(dt.date(2010, 1, 1), None)
    with_as_of = ee.load_econ_events(store, ee.EVENT_TYPES, 0, ee.END_AT_OPEN, as_of=before)
    assert with_as_of.height == 0
    assert ee.load_econ_events(store, ee.EVENT_TYPES, 0, ee.END_AT_OPEN).height == 8


def test_day_only_events_are_the_ones_a_window_must_widen(raw_dir: RawDir, tmp_path: Path) -> None:
    build(raw_dir, tmp_path / "store")
    store = ParquetDataStore(tmp_path / "store")
    frame = ee.load_econ_events(store, ee.EVENT_TYPES)
    assert ee.day_only_events(frame)["event_id"].sort().to_list() == [
        "FOMC_STATEMENT-20100127",
        "FOMC_STATEMENT-20260318",
        "FOMC_STATEMENT-20270127",
        "FOMC_STATEMENT-20280126",
    ]


# ----------------------------------------------------------------------------------- fetch


def test_fetch_raw_discovers_the_linked_statements_and_never_refetches(tmp_path: Path) -> None:
    pages = {
        f"{FED}/monetarypolicy/fomccalendars.htm": calendar_page(
            {2026: [("January", "27-28", "/newsevents/pressreleases/monetary20260128a.htm")]}
        ),
        **{
            f"{FED}/monetarypolicy/fomchistorical{year}.htm": (
                historical_page(
                    [
                        (
                            "January 26-27 Meeting - 2010",
                            "/newsevents/press/monetary/20100127a.htm",
                            "Statement",
                        )
                    ]
                )
                if year == 2010
                else historical_page([])
            )
            for year in range(2010, 2021)
        },
        f"{FED}/newsevents/pressreleases/monetary20260128a.htm": statement_page(
            "January 28, 2026", "For release at 2:00 p.m. EST"
        ),
        f"{FED}/newsevents/pressreleases/monetary20100127a.htm": statement_page(
            "January 27, 2010", "For immediate release"
        ),
        **{f"{BLS}/schedule/{year}/home.htm": bls_page([]) for year in range(2010, 2028)},
        "https://web.archive.org/web/20250912150817/https://www.bls.gov/schedule/2025/home.htm": (
            bls_page([])
        ),
    }
    calls: list[str] = []

    def transport(url: str) -> bytes:
        calls.append(url)
        if url not in pages:
            msg = f"the test has no page for {url}"
            raise AssertionError(msg)
        return pages[url].encode("utf-8")

    now = int(dt.datetime(2026, 11, 22, 2, 40, tzinfo=dt.UTC).timestamp())
    entries = ee.fetch_raw(tmp_path / "raw", transport=transport, now=lambda: now * ee._NS_PER_S)
    names = {str(entry["path"]) for entry in entries}
    assert "federalreserve/20261122_monetary20260128a.html" in names
    assert "federalreserve/20261122_monetary20100127a.html" in names
    assert "bls/20261122_schedule_2027.html" in names
    assert "internet-archive/20261122_schedule_2025_20250912.html" in names
    assert len(calls) == len(entries)
    # the second pass finds every file on disk and fetches nothing
    again = ee.fetch_raw(tmp_path / "raw", transport=transport, now=lambda: now * ee._NS_PER_S)
    assert len(calls) == len(entries)
    assert again == entries
    # and what was fetched loads back as snapshots with the same hashes
    snapshots = ee.load_snapshots(tmp_path / "raw")
    assert len(snapshots) == len(entries)
    assert {snapshot.sha256 for snapshot in snapshots} == {str(e["sha256"]) for e in entries}


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """No test in this module may reach the network: a fetch here always uses a fake transport."""

    def refuse(url: str, attempts: int = 3) -> bytes:
        msg = f"test reached the network for {url}"
        raise AssertionError(msg)

    monkeypatch.setattr(ee, "_http_get", refuse)
    yield
    assert DatasetId("econ_events_v1") == ee.DATASET
