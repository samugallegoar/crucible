"""Historical, versioned economic-event calendar (Fathom C7b, ADR-0107 section 12).

The release instants of the three events a news restriction has to know about:

- ``FOMC_STATEMENT`` — every FOMC policy statement the Board publishes: scheduled meetings *and*
  intermeeting actions, from 2010-01-01 to the last date the Fed has published;
- ``CPI`` — the BLS Consumer Price Index release;
- ``NFP`` — the BLS Employment Situation release (the "nonfarm payrolls" report).

Everything comes from snapshots of **official** pages kept under ``raw/<source>/`` (AGENTS.md
section 14): ``federalreserve.gov`` for the FOMC calendar, the yearly historical pages and each
statement press release; ``bls.gov`` for the yearly "Schedule of Selected Releases" page; and, for
what a page said *before* a shutdown delay, Internet Archive captures of that schedule page. The
raw bytes are never modified and never re-fetched: :func:`fetch_raw` creates the folder and writes
``MANIFEST.json`` (url, retrieval instant, sha256, bytes) beside it, and :func:`load_snapshots`
refuses a page whose bytes no longer hash to what the manifest recorded.

Timing semantics — what this dataset may and may not be used for:

- ``scheduled_local`` is the release instant **as the source states it**, ISO 8601 with the UTC
  offset ``America/New_York`` had on that date (a March and a November release differ by an hour).
  ``timezone`` names the zone, ``scheduled_time_source`` says who stated the time of day, and
  ``time_known`` is ``False`` when nobody did.
- ``event_time`` is the release instant that *materialised* (UTC ns): when the statement or the
  release happened, or is scheduled to happen. When the source states the day but no hour (a
  2010-2015 FOMC statement went out "for immediate release"; the calendar for a future meeting
  states no hour), ``event_time`` is **00:00 America/New_York on that day** and ``time_known`` is
  ``False``. That instant marks the day, it is not a claim about the minute: a consumer must widen
  a window to the whole local day rather than place it at ``event_time``.
- ``status`` is ``released`` (it happened), ``scheduled`` (it is still in the future),
  ``rescheduled`` (an earlier official snapshot of the same schedule had another date —
  ``scheduled_local`` keeps that earlier date, ``actual_publication_date`` the one that
  materialised) or ``cancelled`` (an earlier official snapshot scheduled it and the current
  schedule drops it, so it never happened; there is then no actual date). Nothing is guessed: a
  row exists only where a snapshot states it.
- ``available_at`` is the instant the *schedule entry* was publicly known. No page we read states
  when its own entries were first published — the Fed's and BLS's footers carry page-maintenance
  dates, which are years later for a historical page — so every row built from these sources is
  ``availability_basis = "schedule_publication_unknown"`` and ``available_at = event_time``. The
  truth runs the other way for a *future* release, whose schedule is published in advance: this
  dataset records only the weaker, provable claim. **A strategy must not use this dataset as a
  signal** without an availability time of its own, because with ``available_at = event_time`` a
  pre-event window is invisible to a point-in-time read. Its intended consumer is a *firm rule*
  (``news_restriction``, ADR-0107 section 12), a constraint fixed by the firm rather than a trade
  signal, which reads the calendar structurally through :func:`load_econ_events`.

Determinism: a row is a pure function of the snapshots' bytes. ``record_sha256`` is the SHA-256 of
the row's other fields in canonical JSON; ``snapshot_sha256`` names the page the row was read
from, so a row cites its evidence. Nothing here reads the wall clock except
:func:`build_econ_events`
(the build instant, which lives in the manifest and never in a row) and :func:`fetch_raw` (an I/O
boundary).
"""

from __future__ import annotations

import datetime as dt
import hashlib
import itertools
import json
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

import polars as pl

from crucible.core.errors import ConfigurationError, DataQualityError
from crucible.core.types import DatasetId, TimestampNs
from crucible.data.contracts import END_AT_OPEN
from crucible.data.store import build_dataset

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Mapping, Sequence
    from pathlib import Path

    from crucible.data.interfaces import DataStore

DATASET: DatasetId = DatasetId("econ_events_v1")
"""The dataset id this module builds: ``<store root>/econ_events_v1``."""

DATASET_VERSION = "econ_events_v1"
"""Version of the *rows* (not of the Parquet layout): bump it when a parsing rule changes what a
row says, so a stale copy in a store can be told from a current one."""

NEW_YORK = "America/New_York"
"""The zone every source states its release times in: BLS prints "All times on calendar are
Eastern Time", the Fed "2:00 p.m. EDT"."""

MANIFEST_NAME = "MANIFEST.json"
"""Index of the raw folder: one entry per fetched page (see :func:`fetch_raw`)."""

EVENT_TYPES: tuple[str, ...] = ("FOMC_STATEMENT", "CPI", "NFP")
"""The ``event_type`` values this dataset holds, in report order."""

EXPECTED_RELEASES_PER_YEAR: dict[str, int] = {"FOMC_STATEMENT": 8, "CPI": 12, "NFP": 12}
"""How many releases a year normally holds, as the sources describe them: eight scheduled FOMC
meetings a year (the Fed's calendar), one CPI release and one Employment Situation release a month
(the BLS schedule). Used by :class:`BuildReport` to count a year short, never to invent a row."""

_CADENCE: dict[str, str] = {"FOMC_STATEMENT": "yearly", "CPI": "monthly", "NFP": "monthly"}
"""How a gap in :func:`coverage` is measured per type: a fixed monthly release is a gap in any
month without one; FOMC meetings are irregular (eight a year, in no fixed months), so only a whole
calendar year without a statement is a gap. A month without a meeting is a fact, not a hole."""

_STATUS_RANK: dict[str, int] = {"released": 0, "rescheduled": 1, "scheduled": 2, "cancelled": 3}

Period = int | tuple[int, int]
"""A coverage period: a calendar year (irregular cadence) or a ``(year, month)`` pair."""

_TIME_SOURCE_FED = "fed_stated"
_TIME_SOURCE_BLS = "bls_stated"
_TIME_SOURCE_NONE = "not_stated"

_NS_PER_S = 1_000_000_000
_DAY_NS = 86_400 * _NS_PER_S

_MONTHS: dict[str, int] = {
    name: number
    for number, name in enumerate(
        (
            "January",
            "February",
            "March",
            "April",
            "May",
            "June",
            "July",
            "August",
            "September",
            "October",
            "November",
            "December",
        ),
        start=1,
    )
}

ECON_EVENT_SCHEMA: dict[str, pl.DataType] = {
    "event_id": pl.String(),  # stable id: <event_type>-<YYYYMMDD>[-<seq>], schedule-dated
    "event_type": pl.String(),  # FOMC_STATEMENT | CPI | NFP
    "scheduled_local": pl.String(),  # stated release instant, ISO 8601 with the New York offset
    "timezone": pl.String(),  # IANA zone scheduled_local is expressed in (America/New_York)
    "event_time": pl.Int64(),  # release instant that materialised (UTC ns); 00:00 local if no hour
    "time_known": pl.Boolean(),  # False when no source stated the hour: event_time marks the day
    "scheduled_time_source": pl.String(),  # fed_stated | bls_stated | not_stated
    "status": pl.String(),  # released | scheduled | rescheduled | cancelled (module docstring)
    "actual_publication_date": pl.String(),  # nullable: YYYY-MM-DD it happened; null if not
    "unscheduled": pl.Boolean(),  # True for an intermeeting action: no advance schedule existed
    "source_url": pl.String(),  # page the row was read from (a statement page or a schedule page)
    "snapshot_sha256": pl.String(),  # SHA-256 of that page's bytes (MANIFEST.json)
    "available_at": pl.Int64(),  # UTC ns the schedule entry was publicly known; the provable bound
    "availability_basis": pl.String(),  # schedule_publication_unknown | schedule_page_stated_date
    "record_sha256": pl.String(),  # SHA-256 of this row's other fields in canonical JSON
    "dataset_version": pl.String(),  # DATASET_VERSION the row was built by
}
ECON_EVENT_SORT_KEYS = ["event_time", "event_type", "event_id"]
"""Stored order: chronologically, then by type and id, so identical inputs rebuild to identical
bytes (ADR-0011)."""

# --------------------------------------------------------------------- source-page patterns

# a statement page's key, from either link form: the 2010 pages say
# /newsevents/press/monetary/20100127a.htm, later ones .../pressreleases/monetary20110126a.htm
_FED_STATEMENT_KEY = re.compile(r"monetary/?(\d{8}a)\.htm")
_FED_ARTICLE_DATE = re.compile(r'<p class="article__time">\s*([A-Z][a-z]+ \d{2}, \d{4})\s*</p>')
_FED_RELEASE_LINE = re.compile(r'<p class="releaseTime">\s*([^<]*?)\s*<')
_FED_RELEASE_TIME = re.compile(
    r"^For release at (?P<hour>\d{1,2}):(?P<minute>\d{2}) (?P<half>a\.m\.|p\.m\.) "
    r"(?P<zone>EST|EDT)$"
)
_FED_HISTORICAL = re.compile(r"/monetarypolicy/fomchistorical(\d{4})\.htm$")
_FED_CALENDAR = re.compile(r"/monetarypolicy/fomccalendars\.htm$")
_YEAR_SECTION = re.compile(r'<h4><a id="\d+">(\d{4}) FOMC Meetings</a></h4>')
_MEETING_ROW = re.compile(r'(?=<div class="[^"]*\brow fomc-meeting")')
_MEETING_MONTH = re.compile(r'fomc-meeting__month[^"]*"><strong>([^<]+)</strong>')
_MEETING_DATE = re.compile(r'fomc-meeting__date[^"]*">([^<]+)<')
_PANEL_HEADING = re.compile(r"<h5[^>]*>(.*?)</h5>", re.DOTALL)
_LINK = re.compile(r'<a href="([^"]+)">([^<]*)</a>')
_NEXT_YEAR_MEETING = re.compile(
    r"Note: A two-day meeting is scheduled for ([A-Z][a-z]+) (\d{1,2})-(\d{1,2}), (\d{4})\."
)
_BLS_SCHEDULE_YEAR = re.compile(r"/schedule/(\d{4})/home\.htm$")
_BLS_ROW_DATE = re.compile(r"^[A-Z][a-z]+, ([A-Z][a-z]+) (\d{1,2}), (\d{4})$")
_BLS_ROW_TIME = re.compile(r"^(\d{1,2}):(\d{2}) (AM|PM)$")
_BLS_CPI = re.compile(r"^Consumer Price Index for (.+)$")
_BLS_NFP = re.compile(r"^Employment Situation for (.+)$")


# ------------------------------------------------------------------------------- time helpers


def new_york_ns(day: dt.date, clock: dt.time | None) -> tuple[int, str]:
    """UTC ns and the ISO 8601 local stamp (with UTC offset) of a New York wall-clock time.

    ``clock is None`` means "the source stated the day, not the hour": the instant returned is
    00:00 local, the start of that day. A wall time the DST rules make ambiguous or non-existent
    (the 01:00-03:00 window) is refused: a release schedule names an instant, and every release
    time in this dataset (08:30, 10:00, 14:00, ...) lies outside that window, so a hit means the
    parse is wrong.
    """
    wall = dt.datetime.combine(day, clock or dt.time(0, 0))
    series = pl.Series("wall", [wall], dtype=pl.Datetime("ns"))
    try:
        local = series.dt.replace_time_zone(NEW_YORK, ambiguous="raise", non_existent="raise")
    except pl.exceptions.ComputeError as exc:  # pragma: no cover - defensive
        msg = f"{wall} is not an America/New_York wall time (DST transition): {exc}"
        raise DataQualityError(msg) from exc
    utc_ns = int(local.dt.convert_time_zone("UTC").dt.epoch("ns").to_list()[0])
    iso = str(local.dt.strftime("%Y-%m-%dT%H:%M:%S%:z").to_list()[0])
    return utc_ns, iso


def _zone_abbrev_ok(day: dt.date, abbrev: str) -> bool:
    """Whether the zone abbreviation a page prints matches New York on that date (EDT is UTC-4,
    EST UTC-5): a page printing the wrong one contradicts itself and is refused."""
    local = dt.datetime.combine(day, dt.time(12, 0), tzinfo=dt.UTC).astimezone(ZoneInfo(NEW_YORK))
    return abbrev == local.strftime("%Z")


def _us_date(text: str, where: str) -> dt.date:
    """A date the source prints in long US form ("January 27, 2010")."""
    match = re.match(r"^([A-Z][a-z]+) (\d{1,2}), (\d{4})$", text.strip())
    if match is None or match.group(1) not in _MONTHS:
        msg = f"{where}: cannot read the date {text!r}; expected e.g. 'January 27, 2010'"
        raise DataQualityError(msg)
    return dt.date(int(match.group(3)), _MONTHS[match.group(1)], int(match.group(2)))


def _day_of_iso(text: str) -> dt.date:
    return dt.datetime.fromisoformat(text.replace("Z", "+00:00")).date()


def _day_of_ns(value: int) -> dt.date:
    return dt.datetime.fromtimestamp(value / _NS_PER_S, tz=dt.UTC).date()


def _ns_of_iso(text: str) -> int:
    parsed = dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
    return int(parsed.timestamp()) * _NS_PER_S


def _iso_of_ns(value: int) -> str:
    return dt.datetime.fromtimestamp(value / _NS_PER_S, tz=dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


# ------------------------------------------------------------------------------ the row model


@dataclass(frozen=True, slots=True)
class RawEvent:
    """One release as a page states it, before ids, instants, availability and hashes are attached.

    ``scheduled_day``/``scheduled_clock`` are the scheduled release (the *earlier* schedule once
    an earlier snapshot has moved it); ``actual_day`` is the day it materialised, when a snapshot
    says it did. ``period`` is the reference period a BLS row names ("December 2009"): the key
    that matches one release across two snapshots of the same schedule, so a moved release is
    recognised rather than guessed.
    """

    event_type: str
    scheduled_day: dt.date
    scheduled_clock: dt.time | None
    scheduled_time_source: str
    status: str
    actual_day: dt.date | None
    unscheduled: bool
    source_url: str
    stated_publication_day: dt.date | None = None
    period: str | None = None
    note: str | None = None


@dataclass(frozen=True, slots=True)
class Snapshot:
    """One fetched page: what was read, where it came from and when.

    ``url`` is what was fetched (an ``web.archive.org`` URL for an archived copy), ``origin_url``
    the page it is a copy of, ``retrieved_at`` the UTC instant of the fetch (ns), and
    ``capture_at`` the archive's capture instant (ns) for an archived copy, ``None`` for a live
    page.
    """

    url: str
    origin_url: str
    source: str
    retrieved_at: int
    capture_at: int | None
    sha256: str
    path: Path
    text: str

    @property
    def archived(self) -> bool:
        return self.capture_at is not None


def record_sha256(row: Mapping[str, object]) -> str:
    """SHA-256 of a row's other fields in canonical JSON (sorted keys, no whitespace).

    ``record_sha256`` is excluded so the hash can be recomputed from a stored row: a row that
    changed under a stable ``event_id`` is detectable, and two rows that differ anywhere (status,
    actual date, availability, source) never share a hash.
    """
    payload = {
        key: value
        for key, value in row.items()
        if key != "record_sha256" and (value is None or isinstance(value, (bool, int, float, str)))
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _event_rows(
    events: Sequence[RawEvent], snapshot_sha: Mapping[str, str]
) -> list[dict[str, object]]:
    """The stored rows: ids, instants, availability and hashes attached, in a stable order."""
    ordered = sorted(
        events,
        key=lambda e: (
            e.scheduled_day,
            e.scheduled_clock or dt.time(0, 0),
            e.event_type,
            e.source_url,
        ),
    )
    seen: dict[str, int] = {}
    rows: list[dict[str, object]] = []
    for event in ordered:
        if event.source_url not in snapshot_sha:
            msg = (
                f"{event.event_type} {event.scheduled_day}: the row cites {event.source_url!r}, "
                "which is not a snapshot in the raw folder"
            )
            raise ConfigurationError(msg)
        base = f"{event.event_type}-{event.scheduled_day.strftime('%Y%m%d')}"
        seen[base] = seen.get(base, 0) + 1
        event_id = base if seen[base] == 1 else f"{base}-{seen[base]}"
        day = event.actual_day or event.scheduled_day
        event_ns, _ = new_york_ns(day, event.scheduled_clock)
        _, scheduled_iso = new_york_ns(event.scheduled_day, event.scheduled_clock)
        if event.stated_publication_day is None:
            available_at = event_ns
            basis = "schedule_publication_unknown"
        else:
            available_at, _ = new_york_ns(event.stated_publication_day, None)
            basis = "schedule_page_stated_date"
        row: dict[str, object] = {
            "event_id": event_id,
            "event_type": event.event_type,
            "scheduled_local": scheduled_iso,
            "timezone": NEW_YORK,
            "event_time": event_ns,
            "time_known": event.scheduled_clock is not None,
            "scheduled_time_source": event.scheduled_time_source,
            "status": event.status,
            "actual_publication_date": (
                None if event.actual_day is None else event.actual_day.isoformat()
            ),
            "unscheduled": event.unscheduled,
            "source_url": event.source_url,
            "snapshot_sha256": snapshot_sha[event.source_url],
            "available_at": available_at,
            "availability_basis": basis,
            "dataset_version": DATASET_VERSION,
        }
        row["record_sha256"] = record_sha256(row)
        rows.append(row)
    return rows


# ------------------------------------------------------------------------------- the parsers


def statement_url(href_or_url: str) -> str:
    """The canonical (live, 2011-onwards) URL of an FOMC statement page from any link the Fed
    serves it under: 2010 pages link ``/newsevents/press/monetary/20100127a.htm``, later ones
    ``/newsevents/pressreleases/monetary20110126a.htm``, and both name the same page."""
    key = _FED_STATEMENT_KEY.search(href_or_url)
    if key is None:
        msg = (
            f"{href_or_url!r} is not an FOMC statement page URL (expected monetary<YYYYMMDD>a.htm)"
        )
        raise ConfigurationError(msg)
    return f"https://www.federalreserve.gov/newsevents/pressreleases/monetary{key.group(1)}.htm"


def statement_key(url: str) -> str:
    """The ``YYYYMMDDa`` key of a statement page URL."""
    key = _FED_STATEMENT_KEY.search(url)
    if key is None:
        msg = f"{url!r} is not an FOMC statement page URL (expected monetary<YYYYMMDD>a.htm)"
        raise ConfigurationError(msg)
    return key.group(1)


def parse_fomc_statement(text: str, url: str) -> tuple[dt.date, dt.time | None, str]:
    """The release day, clock time and time source of one FOMC statement press release.

    The page prints "For release at 2:00 p.m. EDT" from 2016 on and "For immediate release" before
    that. The latter states the *date* (the page's ``article__time``) but no hour, so the row gets
    ``time_known = False`` instead of an invented 14:00. The date in the URL
    (``monetary<YYYYMMDD>a``) must agree with the printed date, and a printed zone abbreviation
    must match New York on that date; either mismatch is refused rather than reconciled.
    """
    article = _FED_ARTICLE_DATE.search(text)
    if article is None:
        msg = f"{url}: no 'article__time' release date on the FOMC statement page"
        raise DataQualityError(msg)
    day = _us_date(article.group(1), url)
    if _FED_STATEMENT_KEY.search(url) is not None:
        key = statement_key(url)
        from_url = dt.date(int(key[:4]), int(key[4:6]), int(key[6:8]))
        if from_url != day:
            msg = (
                f"{url}: the page states {day} but the file name says {from_url}; one of the two "
                "is a transcription error"
            )
            raise DataQualityError(msg)
    release = _FED_RELEASE_LINE.search(text)
    if release is None:
        msg = f"{url}: no 'releaseTime' line on the FOMC statement page"
        raise DataQualityError(msg)
    line = release.group(1).strip()
    if line == "For immediate release":
        return day, None, _TIME_SOURCE_NONE
    match = _FED_RELEASE_TIME.match(line)
    if match is None:
        msg = (
            f"{url}: cannot read the release time {line!r}; expected 'For release at H:MM a.m./"
            "p.m. EST|EDT' or 'For immediate release'"
        )
        raise DataQualityError(msg)
    hour = int(match.group("hour")) % 12 + (12 if match.group("half").startswith("p") else 0)
    clock = dt.time(hour, int(match.group("minute")))
    if not _zone_abbrev_ok(day, match.group("zone")):
        msg = (
            f"{url}: the page prints {match.group('zone')} but New York was on the other offset "
            f"on {day}; the stated time and date contradict each other"
        )
        raise DataQualityError(msg)
    return day, clock, _TIME_SOURCE_FED


def parse_fomc_historical(
    text: str, url: str, statements: Mapping[str, tuple[dt.date, dt.time | None, str]]
) -> list[RawEvent]:
    """The meetings of one ``fomchistorical<YEAR>.htm`` page (the Fed's pages for 2010-2020).

    Each panel is one meeting; the statement link's file name carries the statement's date, which
    is what an event *is* (the March 2, 2020 unscheduled meeting released its statement on
    March 3). A panel is read when it holds a link labelled exactly ``Statement``:

    - a ``(cancelled)`` panel carries no statement and produces no event, which is why the 2020
      calendar has no March meeting;
    - a ``(unscheduled)`` panel or a ``Conference Call`` is an intermeeting action, flagged
      ``unscheduled``;
    - a link labelled anything else (``Press Release``, ``Statement on Longer-Run Goals ...``) is a
      procedural or framework document, not a policy statement, and is skipped; a notation-vote
      panel labelled ``Statement`` (2020-03-23) *is* an intermeeting policy action and is kept.

    ``statements`` maps a canonical statement URL to its parsed release stamp: the snapshot of
    every statement a page links must be in the raw folder, or the row would cite a page nobody
    kept.
    """
    events: list[RawEvent] = []
    panels = list(_PANEL_HEADING.finditer(text))
    for index, panel in enumerate(panels):
        end = panels[index + 1].start() if index + 1 < len(panels) else len(text)
        heading = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", panel.group(1))).strip()
        target = None
        for href, label in _LINK.findall(text[panel.end() : end]):
            if _FED_STATEMENT_KEY.search(href) is not None and label.strip() == "Statement":
                target = statement_url(href)
                break
        if target is None:
            continue
        day, clock, source = _statement_stamp(target, statements)
        events.append(
            RawEvent(
                event_type="FOMC_STATEMENT",
                scheduled_day=day,
                scheduled_clock=clock,
                scheduled_time_source=source,
                status="released",
                actual_day=day,
                unscheduled=any(
                    marker in heading
                    for marker in ("(unscheduled)", "Conference Call", "(notation vote)")
                ),
                source_url=target,
                note=heading,
            )
        )
    return events


def parse_fomc_calendar(
    text: str, url: str, statements: Mapping[str, tuple[dt.date, dt.time | None, str]]
) -> list[RawEvent]:
    """The scheduled meetings of ``fomccalendars.htm`` (the Fed's page for 2021 onwards).

    A released meeting has a statement link, whose file name carries the statement's date. A
    meeting that has not happened yet has none: its statement day is the **last** day of the
    meeting range the calendar states (a statement comes at the end of a meeting) and the calendar
    states no hour, so the row is ``scheduled`` with ``time_known = False``. A range that wraps a
    month end ("30-1") is refused rather than resolved without a statement link, and a
    notation-vote row ("22 (notation vote)") is skipped: it is not a scheduled policy meeting. The
    note announcing the first meeting of the next year is one more scheduled meeting.

    The calendar also warns that "each meeting date is tentative until confirmed at the meeting
    immediately preceding it": a future date may still move, and the row is what the Fed said.
    """
    events: list[RawEvent] = []
    sections = list(_YEAR_SECTION.finditer(text))
    for index, section in enumerate(sections):
        end = sections[index + 1].start() if index + 1 < len(sections) else len(text)
        year = int(section.group(1))
        for block in _MEETING_ROW.split(text[section.end() : end])[1:]:
            month_cell = _MEETING_MONTH.search(block)
            date_cell = _MEETING_DATE.search(block)
            if month_cell is None or date_cell is None:
                continue
            month_text = month_cell.group(1).strip()
            date_text = date_cell.group(1).strip()
            if "notation vote" in date_text or "notation vote" in month_text:
                continue
            target = None
            for href in re.findall(r'href="([^"]+)"', block):
                if _FED_STATEMENT_KEY.search(href) is not None:
                    target = statement_url(href)
                    break
            if target is None:
                events.append(_future_meeting(url, year, month_text, date_text))
                continue
            day, clock, source = _statement_stamp(target, statements)
            events.append(
                RawEvent(
                    event_type="FOMC_STATEMENT",
                    scheduled_day=day,
                    scheduled_clock=clock,
                    scheduled_time_source=source,
                    status="released",
                    actual_day=day,
                    unscheduled=False,
                    source_url=target,
                    note=f"{month_text} {date_text} of {year}",
                )
            )
    note = _NEXT_YEAR_MEETING.search(text)
    if note is not None:
        month = _MONTHS.get(note.group(1))
        if month is None:
            msg = f"{url}: unknown month {note.group(1)!r} in the next-year note"
            raise DataQualityError(msg)
        events.append(
            RawEvent(
                event_type="FOMC_STATEMENT",
                scheduled_day=dt.date(int(note.group(4)), month, int(note.group(3))),
                scheduled_clock=None,
                scheduled_time_source=_TIME_SOURCE_NONE,
                status="scheduled",
                actual_day=None,
                unscheduled=False,
                source_url=url,
                note=f"next-year note of {url}",
            )
        )
    return events


def _future_meeting(url: str, year: int, month_text: str, date_text: str) -> RawEvent:
    if "/" in month_text:
        msg = (
            f"{url}: the meeting {month_text} {date_text} of {year} has no statement link and its "
            "range wraps a month end; the statement date cannot be read from the calendar"
        )
        raise DataQualityError(msg)
    parts = date_text.rstrip("*").strip().split("-")
    last = int(parts[-1])
    if len(parts) == 2 and int(parts[0]) >= last:
        msg = f"{url}: the meeting range {date_text!r} of {year} is not ascending"
        raise DataQualityError(msg)
    month = _MONTHS.get(month_text)
    if month is None:
        msg = f"{url}: unknown month {month_text!r} in the {year} FOMC calendar"
        raise DataQualityError(msg)
    return RawEvent(
        event_type="FOMC_STATEMENT",
        scheduled_day=dt.date(year, month, last),
        scheduled_clock=None,
        scheduled_time_source=_TIME_SOURCE_NONE,
        status="scheduled",
        actual_day=None,
        unscheduled=False,
        source_url=url,
        note=f"{month_text} {date_text} of {year}",
    )


def _statement_stamp(
    url: str, statements: Mapping[str, tuple[dt.date, dt.time | None, str]]
) -> tuple[dt.date, dt.time | None, str]:
    if url not in statements:
        msg = (
            f"the calendars link the statement page {url} but the raw folder holds no snapshot of "
            "it; re-run the ingestion (fetch_raw) so every linked statement is kept"
        )
        raise ConfigurationError(msg)
    return statements[url]


def parse_bls_schedule(text: str, url: str) -> list[RawEvent]:
    """One BLS "Schedule of Selected Releases" page: its CPI and Employment Situation rows.

    Each row is ``date / time / "Release name for period"``. Only the two releases above are kept
    ("Employment Situation of Veterans" is another report). A row with no time of day keeps
    ``scheduled_clock = None``; every release row of this dataset states 08:30 AM. A row dated
    outside the page's year is refused: it would mean the page and its URL disagree.
    """
    year_match = _BLS_SCHEDULE_YEAR.search(url)
    if year_match is None:
        msg = f"{url}: not a BLS schedule page URL (/schedule/<year>/home.htm)"
        raise ConfigurationError(msg)
    page_year = int(year_match.group(1))
    events: list[RawEvent] = []
    for table_row in re.findall(r"<tr[^>]*>(.*?)</tr>", text, flags=re.DOTALL):
        cells = re.findall(r"<td[^>]*>(.*?)</td>", table_row, flags=re.DOTALL)
        if len(cells) != 3:
            continue
        date_text, time_text, desc_text = (
            re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", cell).replace("&nbsp;", " ")).strip()
            for cell in cells
        )
        event_type: str | None = None
        period: str | None = None
        if (cpi := _BLS_CPI.match(desc_text)) is not None:
            event_type, period = "CPI", cpi.group(1)
        elif (nfp := _BLS_NFP.match(desc_text)) is not None:
            event_type, period = "NFP", nfp.group(1)
        if event_type is None or period is None:
            continue
        date_match = _BLS_ROW_DATE.match(date_text)
        if date_match is None:
            msg = f"{url}: cannot read the release date {date_text!r} of {desc_text!r}"
            raise DataQualityError(msg)
        month = _MONTHS.get(date_match.group(1))
        if month is None:
            msg = f"{url}: unknown month {date_match.group(1)!r} of {desc_text!r}"
            raise DataQualityError(msg)
        day = dt.date(int(date_match.group(3)), month, int(date_match.group(2)))
        if day.year != page_year:
            msg = (
                f"{url}: the row {desc_text!r} is dated {day} but the page is the {page_year} "
                "schedule"
            )
            raise DataQualityError(msg)
        clock = None
        if time_text:
            time_match = _BLS_ROW_TIME.match(time_text)
            if time_match is None:
                msg = f"{url}: cannot read the release time {time_text!r} of {desc_text!r}"
                raise DataQualityError(msg)
            hour = int(time_match.group(1)) % 12 + (12 if time_match.group(3) == "PM" else 0)
            clock = dt.time(hour, int(time_match.group(2)))
        events.append(
            RawEvent(
                event_type=event_type,
                scheduled_day=day,
                scheduled_clock=clock,
                scheduled_time_source=(
                    _TIME_SOURCE_BLS if clock is not None else _TIME_SOURCE_NONE
                ),
                status="released",
                actual_day=day,
                unscheduled=False,
                source_url=url,
                period=period,
            )
        )
    return events


# ------------------------------------------------------------------------- snapshots on disk


def load_snapshots(raw_dir: Path) -> list[Snapshot]:
    """The raw folder's pages, in a deterministic order (origin, then capture, then file name).

    The folder must hold the ``MANIFEST.json`` :func:`fetch_raw` writes. A page the manifest lists
    but the disk lacks, or a page whose bytes no longer hash to the manifest's sha256, is refused:
    the raw bytes are the source of truth, and a changed one silently changes every row built
    from it.
    """
    manifest_path = raw_dir / MANIFEST_NAME
    if not manifest_path.is_file():
        msg = (
            f"no {MANIFEST_NAME} in {raw_dir}: this folder must hold the raw snapshots of an "
            "economic-event ingestion (federalreserve.gov, bls.gov); see docs/data/econ-events.md"
        )
        raise ConfigurationError(msg)
    raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    entries = raw.get("entries")
    if not isinstance(entries, list) or not entries:
        msg = f"{manifest_path}: 'entries' must be a non-empty list of fetched pages"
        raise ConfigurationError(msg)
    snapshots: list[Snapshot] = []
    for entry in entries:
        if not isinstance(entry, dict) or "path" not in entry:
            msg = f"{manifest_path}: every entry must be an object with a 'path'"
            raise ConfigurationError(msg)
        path = raw_dir / str(entry["path"])
        if not path.is_file():
            msg = f"{manifest_path} lists {entry['path']} but the file is missing"
            raise ConfigurationError(msg)
        body = path.read_bytes()
        digest = hashlib.sha256(body).hexdigest()
        if digest != entry["sha256"]:
            msg = (
                f"{path} hashes to {digest[:12]}... but the manifest says "
                f"{str(entry['sha256'])[:12]}...: the raw snapshot was modified, so the rows built "
                "from it would not be reproducible; restore it from the source"
            )
            raise DataQualityError(msg)
        capture_at = entry.get("capture_at")
        snapshots.append(
            Snapshot(
                url=str(entry["url"]),
                origin_url=str(entry["origin_url"]),
                source=str(entry["source"]),
                retrieved_at=_ns_of_iso(str(entry["retrieved_at"])),
                capture_at=None if capture_at is None else _ns_of_iso(str(capture_at)),
                sha256=digest,
                path=path,
                text=body.decode("utf-8", errors="replace"),
            )
        )
    snapshots.sort(key=lambda s: (s.origin_url, s.capture_at or 0, s.retrieved_at, s.path.name))
    return snapshots


# ---------------------------------------------------------------------------- the assembly


def _snapshot_index(snapshots: Sequence[Snapshot]) -> dict[str, Snapshot]:
    """Every URL a snapshot can be cited by (as fetched, and the page it is a copy of)."""
    index: dict[str, Snapshot] = {}
    for snapshot in snapshots:
        # an archived copy answers to the URL it was fetched from; only a live page answers to
        # its origin too, or the archived earlier reading of a schedule would shadow the current
        # one (both name the same origin_url)
        for url in {snapshot.url} | (set() if snapshot.archived else {snapshot.origin_url}):
            existing = index.get(url)
            if existing is not None and existing.sha256 != snapshot.sha256:
                msg = (
                    f"two different snapshots claim {url}: {existing.path.name} and "
                    f"{snapshot.path.name}; keep one"
                )
                raise ConfigurationError(msg)
            index[url] = snapshot
    return index


def _dedupe(events: Sequence[RawEvent]) -> list[RawEvent]:
    """One row per event: a second snapshot stating the same release the same way adds nothing.

    The identity of an event is its type, its scheduled date and time, its status and the page it
    was read from. Two snapshots that state the same release differently under the same identity
    are refused rather than silently resolved (a rebuild must not depend on file order).
    """
    kept: dict[tuple[object, ...], RawEvent] = {}
    for event in events:
        key = (
            event.event_type,
            event.scheduled_day,
            event.scheduled_clock,
            event.status,
            event.source_url,
        )
        previous = kept.get(key)
        if previous is None:
            kept[key] = event
            continue
        if previous != event:
            msg = (
                f"{event.event_type} {event.scheduled_day}: two snapshots state this release "
                f"differently ({previous.note!r} vs {event.note!r}); resolve the sources by hand"
            )
            raise DataQualityError(msg)
    return list(kept.values())


def events_from_snapshots(snapshots: Sequence[Snapshot]) -> list[RawEvent]:
    """Every event the snapshots state, in a deterministic order (the build's parsing step)."""
    statements = {
        statement_url(snapshot.origin_url): parse_fomc_statement(snapshot.text, snapshot.url)
        for snapshot in snapshots
        if _FED_STATEMENT_KEY.search(snapshot.origin_url) is not None
    }
    if not statements:
        msg = (
            "the raw folder holds no FOMC statement page: the FOMC rows cannot cite the release "
            "time the Fed stated; re-run the ingestion (fetch_raw)"
        )
        raise ConfigurationError(msg)
    events: list[RawEvent] = []
    schedules: dict[int, dict[str, list[Snapshot]]] = {}
    for snapshot in snapshots:
        origin = snapshot.origin_url
        if _FED_STATEMENT_KEY.search(origin) is not None:
            continue
        if _FED_CALENDAR.search(origin) is not None:
            events.extend(parse_fomc_calendar(snapshot.text, origin, statements))
        elif _FED_HISTORICAL.search(origin) is not None:
            events.extend(parse_fomc_historical(snapshot.text, origin, statements))
        elif (year_match := _BLS_SCHEDULE_YEAR.search(origin)) is not None:
            role = "earlier" if snapshot.archived else "current"
            by_year = schedules.setdefault(int(year_match.group(1)), {"current": [], "earlier": []})
            by_year[role].append(snapshot)
    if not schedules:
        msg = "the raw folder holds no BLS release schedule; nothing to build"
        raise ConfigurationError(msg)
    for year, roles in sorted(schedules.items()):
        if len(roles["current"]) != 1:
            names = ", ".join(s.path.name for s in roles["current"]) or "none"
            msg = (
                f"the raw folder must hold exactly one current BLS schedule for {year} "
                f"(found {names}): a later re-fetch leaves the older snapshot set in place, so "
                "move the superseded files out of the folder (or into an archive subfolder) "
                "before building"
            )
            raise ConfigurationError(msg)
        events.extend(_year_of_bls_releases(year, roles["current"][0], roles["earlier"]))
    return _dedupe(events)


def _year_of_bls_releases(
    year: int, current: Snapshot, earlier: Sequence[Snapshot]
) -> list[RawEvent]:
    """One year of CPI and NFP releases: the current schedule, with the earlier readings folded in.

    A release the current schedule lists is ``released``, or ``scheduled`` when its instant is
    still in the future at the snapshot's retrieval. A release an *earlier* official snapshot of
    the same schedule lists under another date is ``rescheduled``: the earlier date and time go to
    ``scheduled_local``, the one that materialised to ``actual_publication_date``. A release only
    an earlier snapshot lists is ``cancelled`` — the current schedule dropped it, so it did not
    happen — unless its earlier instant was still in the future at retrieval.

    Releases are matched by reference period ("December 2009"), never by date: a move is
    recognised, not inferred.
    """
    current_events = {
        (event.event_type, event.period): event
        for event in parse_bls_schedule(current.text, current.origin_url)
    }
    retrieved_day = _day_of_ns(current.retrieved_at)
    positioned: dict[tuple[str, str | None], RawEvent] = {}
    for revision in sorted(earlier, key=lambda s: s.capture_at or 0):
        if revision.capture_at is not None and revision.capture_at > current.retrieved_at:
            msg = (
                f"{revision.path.name}: captured at {_iso_of_ns(revision.capture_at)}, after the "
                f"current schedule was retrieved ({_iso_of_ns(current.retrieved_at)}); an earlier "
                "reading must be older than the one it revises"
            )
            raise ConfigurationError(msg)
        for original in parse_bls_schedule(revision.text, revision.origin_url):
            key = (original.event_type, original.period)
            if key in positioned:
                continue
            now = current_events.get(key)
            if now is not None:
                if now.scheduled_day == original.scheduled_day:
                    continue
                positioned[key] = replace(
                    now,
                    scheduled_day=original.scheduled_day,
                    scheduled_clock=original.scheduled_clock,
                    status="rescheduled",
                    source_url=current.origin_url,
                    note=f"was {original.scheduled_day} in {revision.path.name}",
                )
            elif original.scheduled_day <= retrieved_day:
                positioned[key] = replace(
                    original,
                    status="cancelled",
                    actual_day=None,
                    source_url=revision.url,
                    note=f"gone from the {year} schedule",
                )
            else:
                positioned[key] = replace(
                    original,
                    status="scheduled",
                    actual_day=None,
                    source_url=current.origin_url,
                )
    for key, event in current_events.items():
        if key in positioned:
            continue
        if event.scheduled_day > retrieved_day:
            event = replace(event, status="scheduled", actual_day=None)
        positioned[key] = event
    return list(positioned.values())


@dataclass(frozen=True, slots=True)
class BuildReport:
    """What a build read and wrote: the counts the ingestion page quotes."""

    dataset: str
    rows: int
    content_hash: str
    events_by_type: dict[str, int]
    events_by_status: dict[str, int]
    per_year: dict[str, dict[int, int]]
    short_years: dict[str, dict[int, int]]
    coverage: Coverage
    snapshots: int
    time_known_rows: int


def build_econ_events(raw_dir: Path, store_root: Path) -> BuildReport:
    """Build ``econ_events_v1`` from the raw snapshots in ``raw_dir`` into ``store_root``.

    Refuses to overwrite an existing ``econ_events_v1``: the dataset is a stable, hash-checked
    artifact, and silently replacing it would invalidate every rule verdict that cited it. Move
    the directory aside (or build into another store root) to rebuild.
    """
    target = store_root / DATASET
    if target.exists():
        msg = (
            f"{target} already exists: this build refuses to overwrite a stored dataset. Move it "
            "aside, or build into another store root, if you mean to replace it"
        )
        raise ConfigurationError(msg)
    snapshots = load_snapshots(raw_dir)
    sha_by_url = {url: snapshot.sha256 for url, snapshot in _snapshot_index(snapshots).items()}
    events = events_from_snapshots(snapshots)
    frame = pl.DataFrame(_event_rows(events, sha_by_url), orient="row", schema=ECON_EVENT_SCHEMA)
    manifest = build_dataset(
        store_root,
        DATASET,
        frame,
        schema=ECON_EVENT_SCHEMA,
        sort_keys=ECON_EVENT_SORT_KEYS,
        source=(
            "official releases: federalreserve.gov (FOMC calendar, yearly historical pages, "
            "statement press releases); bls.gov (/schedule/<year>/home.htm); Internet Archive "
            "captures of the BLS 2025 schedule; "
            f"dataset_version={DATASET_VERSION}; snapshots={len(snapshots)}"
        ),
    )
    stored = pl.read_parquet(target / "data.parquet")
    per_year = _per_year(stored)
    return BuildReport(
        dataset=str(DATASET),
        rows=manifest.row_count,
        content_hash=manifest.content_hash,
        events_by_type={
            event_type: int(stored.filter(pl.col("event_type") == event_type).height)
            for event_type in EVENT_TYPES
        },
        events_by_status={
            status: int(stored.filter(pl.col("status") == status).height) for status in _STATUS_RANK
        },
        per_year=per_year,
        short_years={
            event_type: {
                year: EXPECTED_RELEASES_PER_YEAR[event_type] - count
                for year, count in years.items()
                if count < EXPECTED_RELEASES_PER_YEAR[event_type]
            }
            for event_type, years in per_year.items()
        },
        coverage=coverage_of(stored),
        snapshots=len(snapshots),
        time_known_rows=int(stored.filter(pl.col("time_known")).height),
    )


def _per_year(frame: pl.DataFrame) -> dict[str, dict[int, int]]:
    """Events per type per calendar year of the release day, in New York (an 08:30 ET release is
    still that day in UTC, a 19:00 one would not be, so the local year is the one that counts)."""
    counted = (
        frame.select(
            "event_type",
            pl.col("event_time")
            .cast(pl.Datetime("ns", "UTC"))
            .dt.convert_time_zone(NEW_YORK)
            .dt.year()
            .alias("year"),
        )
        .group_by("event_type", "year")
        .len()
    )
    out: dict[str, dict[int, int]] = {event_type: {} for event_type in EVENT_TYPES}
    for event_type, year, count in counted.iter_rows():
        out[str(event_type)][int(year)] = int(count)
    return {event_type: dict(sorted(years.items())) for event_type, years in out.items()}


# ------------------------------------------------------------------------------- coverage


@dataclass(frozen=True, slots=True)
class CoverageSpan:
    """An unbroken run of periods (months, or years for an irregular type) holding at least one
    event of the type."""

    event_type: str
    first_event: int
    last_event: int
    events: int


@dataclass(frozen=True, slots=True)
class CoverageGap:
    """A period inside the covered window with no release of that type.

    ``start_at`` is 00:00 New York on the first day of the period, ``end_at`` the first instant
    after it (exclusive), so the gap reads as the half-open interval ``[start_at, end_at)`` a rule
    cannot model.
    """

    event_type: str
    start_at: int
    end_at: int
    periods: int
    reason: str


@dataclass(frozen=True, slots=True)
class Coverage:
    """What the calendar covers, per event type (ADR-0107 section 12: gaps are explicit)."""

    spans: tuple[CoverageSpan, ...]
    gaps: tuple[CoverageGap, ...]

    def gaps_of(self, event_type: str) -> tuple[CoverageGap, ...]:
        return tuple(gap for gap in self.gaps if gap.event_type == event_type)


def coverage(store: DataStore) -> Coverage:
    """The covered intervals and the gaps of the built dataset, per event type.

    A gap is measured against the type's cadence (:data:`_CADENCE`): a monthly release (CPI, NFP)
    is missing in any month without a row, and for the irregular FOMC a whole calendar year
    without a statement is a gap while a month without a meeting is simply a month without a
    meeting. A ``cancelled`` row still marks its period as covered — the calendar *did* say
    something about that month, namely that the release would not happen. This is the "a window
    the calendar does not cover is ``not_modeled``" test of ADR-0107.
    """
    return coverage_of(load_econ_events(store, EVENT_TYPES, 0, END_AT_OPEN))


def coverage_of(frame: pl.DataFrame) -> Coverage:
    """:func:`coverage` over a frame already in hand (the build reports it without a store)."""
    spans: list[CoverageSpan] = []
    gaps: list[CoverageGap] = []
    for event_type in EVENT_TYPES:
        rows = frame.filter(pl.col("event_type") == event_type)
        if rows.height == 0:
            continue
        stamps = [int(value) for value in rows["event_time"].to_list()]
        if _CADENCE[event_type] == "monthly":
            months = sorted({_year_month(stamp) for stamp in stamps})
            month_spans, month_gaps = _month_coverage(event_type, stamps, months)
            spans.extend(month_spans)
            gaps.extend(month_gaps)
        else:
            years = sorted({_year_of(stamp) for stamp in stamps})
            year_spans, year_gaps = _year_coverage(event_type, stamps, years)
            spans.extend(year_spans)
            gaps.extend(year_gaps)
    return Coverage(
        spans=tuple(spans),
        gaps=tuple(sorted(gaps, key=lambda gap: (gap.event_type, gap.start_at))),
    )


def _month_coverage(
    event_type: str, stamps: Sequence[int], months: Sequence[tuple[int, int]]
) -> tuple[list[CoverageSpan], list[CoverageGap]]:
    spans: list[CoverageSpan] = []
    gaps: list[CoverageGap] = []
    for run in _runs(months, _next_month):
        in_run = [stamp for stamp in stamps if _year_month(stamp) in set(run)]
        spans.append(
            CoverageSpan(
                event_type=event_type,
                first_event=min(in_run),
                last_event=max(in_run),
                events=len(in_run),
            )
        )
    for previous, following in itertools.pairwise(_runs(months, _next_month)):
        missing = _months_between(previous[-1], following[0])
        if not missing:
            continue
        start_at, _ = new_york_ns(dt.date(missing[0][0], missing[0][1], 1), None)
        end_at, _ = new_york_ns(_first_of_next(missing[-1]), None)
        gaps.append(
            CoverageGap(
                event_type=event_type,
                start_at=start_at,
                end_at=end_at,
                periods=len(missing),
                reason="no release listed",
            )
        )
    return spans, gaps


def _year_coverage(
    event_type: str, stamps: Sequence[int], years: Sequence[int]
) -> tuple[list[CoverageSpan], list[CoverageGap]]:
    spans: list[CoverageSpan] = []
    gaps: list[CoverageGap] = []
    for run in _runs(years, _next_year):
        in_run = [stamp for stamp in stamps if _year_of(stamp) in set(run)]
        spans.append(
            CoverageSpan(
                event_type=event_type,
                first_event=min(in_run),
                last_event=max(in_run),
                events=len(in_run),
            )
        )
    for previous, following in itertools.pairwise(_runs(years, _next_year)):
        missing = list(range(previous[-1] + 1, following[0]))
        if not missing:
            continue
        start_at, _ = new_york_ns(dt.date(missing[0], 1, 1), None)
        end_at, _ = new_york_ns(dt.date(missing[-1] + 1, 1, 1), None)
        gaps.append(
            CoverageGap(
                event_type=event_type,
                start_at=start_at,
                end_at=end_at,
                periods=len(missing),
                reason="no statement listed",
            )
        )
    return spans, gaps


def _runs[PeriodT: (int, tuple[int, int])](
    periods: Sequence[PeriodT], step: Callable[[PeriodT], PeriodT]
) -> list[list[PeriodT]]:
    """Maximal runs of consecutive periods, ``step`` being one period forward."""
    runs: list[list[PeriodT]] = []
    for period in periods:
        if runs and step(runs[-1][-1]) == period:
            runs[-1].append(period)
        else:
            runs.append([period])
    return runs


def _next_month(key: tuple[int, int]) -> tuple[int, int]:
    return (key[0] + 1, 1) if key[1] == 12 else (key[0], key[1] + 1)


def _next_year(year: int) -> int:
    return year + 1


def _months_between(first: tuple[int, int], last: tuple[int, int]) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    cursor = _next_month(first)
    while cursor < last:
        out.append(cursor)
        cursor = _next_month(cursor)
    return out


def _first_of_next(key: tuple[int, int]) -> dt.date:
    return dt.date(key[0] + 1, 1, 1) if key[1] == 12 else dt.date(key[0], key[1] + 1, 1)


def _year_month(value: int) -> tuple[int, int]:
    local = _local_of(value)
    return (local.year, local.month)


def _year_of(value: int) -> int:
    return _local_of(value).year


def _local_of(value: int) -> dt.datetime:
    return dt.datetime.fromtimestamp(value / _NS_PER_S, tz=dt.UTC).astimezone(ZoneInfo(NEW_YORK))


# ---------------------------------------------------------------------------------- access


def load_econ_events(
    store: DataStore,
    event_types: Iterable[str] = EVENT_TYPES,
    start_ns: int = 0,
    end_ns: int = END_AT_OPEN,
    *,
    as_of: int | None = None,
) -> pl.DataFrame:
    """The events of ``event_types`` whose ``event_time`` lies in ``[start_ns, end_ns)``.

    Read with the open-ended sentinel as ``as_of`` unless the caller passes one: a *firm rule*
    constraint is not a strategy signal, and this dataset's ``available_at`` is only the weaker,
    provable bound (module docstring), so a point-in-time read at the strategy's ``as_of`` would
    hide the calendar exactly when a rule needs it — and hide it in the optimistic direction,
    letting the strategy trade through the event. A caller that wants the point-in-time view
    passes ``as_of`` and sees only the rows whose ``available_at <= as_of``.

    Rows come in stored order (``event_time``, ``event_type``, ``event_id``) with the schema's
    columns.
    """
    types = list(event_types)
    unknown = sorted(set(types) - set(EVENT_TYPES))
    if unknown:
        msg = f"unknown event_type(s) {unknown}; this dataset holds {list(EVENT_TYPES)}"
        raise ConfigurationError(msg)
    if int(end_ns) < int(start_ns):
        msg = f"end_ns={end_ns} is before start_ns={start_ns}: pass a non-empty range"
        raise ConfigurationError(msg)
    read_as_of = END_AT_OPEN if as_of is None else int(as_of)
    frame = (
        store.read(DATASET, TimestampNs(read_as_of))
        .filter(
            pl.col("event_type").is_in(types)
            & (pl.col("event_time") >= int(start_ns))
            & (pl.col("event_time") < int(end_ns))
        )
        .collect()
    )
    return frame.select(list(ECON_EVENT_SCHEMA))


def day_only_events(frame: pl.DataFrame) -> pl.DataFrame:
    """The rows whose release hour no source stated (``time_known`` false).

    A consumer that places a window at ``event_time`` would restrict the wrong hours: those rows
    have to be widened to the whole local day. Kept here so a rule engine has one place to ask.
    """
    return frame.filter(~pl.col("time_known"))


# ----------------------------------------------------------------------------------- fetch

_BROWSER_HEADERS: dict[str, str] = {
    # bls.gov answers a bare curl with 403 and a browser-shaped request with the page
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
}
"""Browser-shaped headers: bls.gov refuses an automated client with 403 (AGENTS.md section 14)."""

_FED = "https://www.federalreserve.gov"
_BLS = "https://www.bls.gov"

FOMC_HISTORICAL_YEARS: tuple[int, ...] = tuple(range(2010, 2021))
"""The Fed's yearly historical pages this ingestion reads. The current calendar covers the years
after them; a year the Fed moves from one to the other is still read, because both page kinds are
discovered in the raw folder, not in this list."""

BLS_SCHEDULE_YEARS: tuple[int, ...] = tuple(range(2010, 2028))
"""The BLS schedule pages this ingestion reads: 2010-01-01 through the 2027 calendar."""

ARCHIVED_SCHEDULES: tuple[tuple[int, str, str, str], ...] = (
    (2025, "2025-09-12T15:08:17Z", "20250912150817", "https://www.bls.gov/schedule/2025/home.htm"),
)
"""Earlier official readings of a schedule page, kept only to recognise a *moved* release:
``(year, capture instant, archive timestamp, origin url)``. The 2025 page as it stood before the
autumn 2025 government-shutdown delays, read from the Internet Archive because bls.gov serves only
the current page (an archived copy is a read path to the official bytes, as in
``docs/data/cme-globex-sessions.md``). No pre-shutdown capture of the 2013 page exists, so that
shutdown's original dates are not recorded — see ``docs/data/econ-events.md``."""


def fetch_raw(
    raw_dir: Path,
    *,
    transport: Callable[[str], bytes] | None = None,
    now: Callable[[], int] | None = None,
    pause_s: float = 0.6,
) -> list[dict[str, object]]:
    """Fetch every page this dataset needs into ``raw_dir`` and write its ``MANIFEST.json``.

    The URL set is *discovered from the pages themselves*: the Fed's calendar and historical pages
    are read first and every statement they link is fetched, so a year the Fed adds is picked up
    without touching this code. Files are named ``<YYYYMMDD>_<name>.html`` (retrieval date, then
    the page) under ``<raw_dir>/<source>/``. An existing file is never re-fetched or rewritten:
    the folder is the immutable source of truth and :func:`load_snapshots` refuses a byte that
    changed under a manifest entry.

    ``transport(url) -> bytes``, ``now() -> int`` (UTC ns) and ``pause_s`` are the seams a test
    drives without a network or a clock; the defaults walk the real web and read the real clock
    (an I/O boundary, like the build's timestamp). Returns the manifest entries.
    """
    import pathlib

    root = pathlib.Path(raw_dir)
    clock = now or time.time_ns
    getter = transport or _http_get
    entries: list[dict[str, object]] = []

    def fetch(source: str, name: str, url: str, origin: str, capture_at: str | None) -> None:
        path = root / source / name
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(getter(url))
            if pause_s:
                time.sleep(pause_s)
        body = path.read_bytes()
        entries.append(
            {
                "url": url,
                "origin_url": origin,
                "source": source,
                "path": path.relative_to(root).as_posix(),
                "retrieved_at": _iso_of_ns(int(path.stat().st_mtime_ns)),
                "capture_at": capture_at,
                "sha256": hashlib.sha256(body).hexdigest(),
                "bytes": len(body),
            }
        )

    day = dt.datetime.fromtimestamp(clock() / _NS_PER_S, tz=dt.UTC).strftime("%Y%m%d")
    calendar_url = f"{_FED}/monetarypolicy/fomccalendars.htm"
    fed_pages = [
        calendar_url,
        *[f"{_FED}/monetarypolicy/fomchistorical{y}.htm" for y in FOMC_HISTORICAL_YEARS],
    ]
    for page in fed_pages:
        name = f"{day}_{page.rsplit('/', 1)[-1].replace('.htm', '.html')}"
        fetch("federalreserve", name, page, page, None)
    statements: set[str] = set()
    for page in fed_pages:
        name = f"{day}_{page.rsplit('/', 1)[-1].replace('.htm', '.html')}"
        text = (root / "federalreserve" / name).read_text(encoding="utf-8", errors="replace")
        for href in re.findall(r'href="([^"]+)"', text):
            if _FED_STATEMENT_KEY.search(href) is not None:
                statements.add(statement_url(href))
    for target in sorted(statements):
        fetch(
            "federalreserve",
            f"{day}_monetary{statement_key(target)}.html",
            target,
            target,
            None,
        )
    for year in BLS_SCHEDULE_YEARS:
        schedule_url = f"{_BLS}/schedule/{year}/home.htm"
        fetch("bls", f"{day}_schedule_{year}.html", schedule_url, schedule_url, None)
    for year, capture_at, stamp, origin in ARCHIVED_SCHEDULES:
        capture_day = _day_of_iso(capture_at).strftime("%Y%m%d")
        fetch(
            "internet-archive",
            f"{day}_schedule_{year}_{capture_day}.html",
            f"https://web.archive.org/web/{stamp}/{origin}",
            origin,
            capture_at,
        )
    manifest: dict[str, object] = {
        "store": "econ_events raw snapshots",
        "note": (
            "one entry per fetched page; the bytes are exactly what the source served and are "
            "never modified; 'capture_at' is set for an archived copy, an earlier reading of the "
            "same origin_url"
        ),
        "entries": sorted(entries, key=lambda entry: (str(entry["source"]), str(entry["path"]))),
    }
    (root / MANIFEST_NAME).write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )
    return entries


def _http_get(url: str, attempts: int = 3) -> bytes:
    """One page, with two retries on a network error. A refusal (403) is not retried into a
    different answer: it raises with the URL, so the coverage gap is visible instead of silent."""
    last: Exception | None = None
    for attempt in range(attempts):
        try:
            request = urllib.request.Request(url, headers=_BROWSER_HEADERS, method="GET")
            with urllib.request.urlopen(request, timeout=90) as response:
                body: bytes = response.read()
                return body
        except (urllib.error.URLError, OSError) as exc:  # pragma: no cover - needs a network
            last = exc
            time.sleep(2.0 * (attempt + 1))
    msg = f"cannot fetch {url}: {last}; the page may be gone, or the host refuses automated reads"
    raise DataQualityError(msg) from last
