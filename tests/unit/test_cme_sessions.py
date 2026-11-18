"""The CME Globex session calendar (ADR-0091): regular sessions, DST, schedule changes, holidays,
trade-date session rules, flat-by-close timing, validation and refusals.

Expected values are hand-derived from the published schedules cited in
``crucible/data/cme_session_table.py``, never from the engine."""

# Wall-clock datetimes here are naive America/Chicago times by design (the schedule unit).
# ruff: noqa: DTZ001

from __future__ import annotations

import dataclasses
import datetime as dt

import numpy as np
import pytest

from crucible.core.errors import ConfigurationError, DataQualityError
from crucible.data.calendars import chicago_wall_to_utc_ns, utc_ns_to_chicago_wall
from crucible.data.cme_session_table import TABLE_VERSION, cme_session_table
from crucible.data.cme_sessions import (
    NoTradeDate,
    SessionCalendar,
    SessionOverride,
    SessionRegime,
    SessionTable,
    assign_bars,
    schedule_report,
    session_rule_masks,
    table_hash,
    table_summary,
    trade_date_instant,
    trade_date_of,
)

TABLE = cme_session_table()
ES = SessionCalendar(TABLE, "ES")
NKD = SessionCalendar(TABLE, "NKD")
MIN = 60_000_000_000


def d(text: str) -> dt.date:
    return dt.date.fromisoformat(text)


def utc(text: str) -> int:
    """UTC ns of a Chicago wall-clock 'YYYY-MM-DD HH:MM'."""
    return chicago_wall_to_utc_ns([dt.datetime.fromisoformat(text)])[0]


def walls(session_segments: tuple[tuple[int, int], ...]) -> list[str]:
    flat = [x for seg in session_segments for x in seg]
    return [w.strftime("%Y-%m-%d %H:%M") for w in utc_ns_to_chicago_wall(flat)]


def bars(session_or_ends: object) -> np.ndarray:
    ends = session_or_ends.bar_ends() if hasattr(session_or_ends, "bar_ends") else session_or_ends
    return np.asarray(ends, dtype=np.int64)


# --- 1. regular sessions and the daily breaks -------------------------------------------------


def test_regular_session_2024_runs_17_to_16_with_no_halt() -> None:
    s = ES.session(d("2024-03-06"))
    assert walls(s.segments) == ["2024-03-05 17:00", "2024-03-06 16:00"]
    assert len(s.bar_ends()) == 23 * 60
    assert s.verified
    assert s.regime == "globex-2021-06"


def test_monday_session_opens_sunday_17() -> None:
    s = ES.session(d("2024-03-04"))
    assert walls(s.segments) == ["2024-03-03 17:00", "2024-03-04 16:00"]


def test_2019_session_has_the_1515_1530_halt() -> None:
    s = ES.session(d("2019-10-16"))
    assert walls(s.segments) == [
        "2019-10-15 17:00",
        "2019-10-16 15:15",
        "2019-10-16 15:30",
        "2019-10-16 16:00",
    ]
    assert len(s.bar_ends()) == 23 * 60 - 15


def test_2011_session_opens_1530_with_the_1630_1700_maintenance() -> None:
    s = ES.session(d("2011-03-16"))
    assert walls(s.segments) == [
        "2011-03-15 15:30",
        "2011-03-15 16:30",
        "2011-03-15 17:00",
        "2011-03-16 15:15",
    ]
    assert len(s.bar_ends()) == (23 * 60 + 45) - 30


def test_weekend_and_out_of_coverage_dates_are_refused() -> None:
    with pytest.raises(ConfigurationError, match="not a ES Globex trade date"):
        ES.session(d("2024-03-09"))
    with pytest.raises(ConfigurationError, match="outside the CME session calendar"):
        ES.session(d("2009-06-01"))
    with pytest.raises(ConfigurationError, match="outside the CME session calendar"):
        SessionCalendar(TABLE, "RTY").session(d("2016-06-01"))
    with pytest.raises(ConfigurationError, match="no schedule for root"):
        SessionCalendar(TABLE, "CL")


def test_trade_date_of_assigns_evening_bars_to_the_next_trade_date() -> None:
    ends = np.asarray(
        [utc("2024-03-05 17:01"), utc("2024-03-05 23:59"), utc("2024-03-06 16:00")], dtype=np.int64
    )
    assert trade_date_of(ES, ends) == [d("2024-03-06")] * 3


def test_bars_in_breaks_and_after_the_close_are_off_schedule() -> None:
    ends = np.asarray(
        [
            utc("2019-10-16 15:15"),  # last bar before the halt: on schedule
            utc("2019-10-16 15:16"),  # the minute after the halt starts: off
            utc("2019-10-16 15:31"),  # first bar after the halt
            utc("2019-10-16 16:01"),  # after the close: off
            utc("2019-10-16 17:00"),  # ends at the reopen, so it started before it: off
        ],
        dtype=np.int64,
    )
    placed = assign_bars(ES, ends)
    assert placed.on_schedule.tolist() == [True, False, True, False, False]


# --- 2. DST and historical schedule changes -----------------------------------------------------


def test_dst_moves_utc_but_not_the_wall_clock_or_the_bar_count() -> None:
    before = ES.session(d("2024-03-08"))  # CST, UTC-6
    after = ES.session(d("2024-03-11"))  # first session after the 2024-03-10 change, CDT
    assert walls(before.segments)[-1] == "2024-03-08 16:00"
    assert walls(after.segments) == ["2024-03-10 17:00", "2024-03-11 16:00"]
    assert before.close_ns - before.open_ns == 23 * 3600 * 10**9
    assert after.close_ns - after.open_ns == 23 * 3600 * 10**9
    fall = ES.session(d("2024-11-04"))  # opens Sunday 2024-11-03 17:00 CST, after the change
    assert walls(fall.segments)[0] == "2024-11-03 17:00"
    assert (utc("2024-11-03 17:00") - utc("2024-11-01 16:00")) == (49 + 1) * 3600 * 10**9


def test_wall_times_inside_a_dst_transition_are_refused() -> None:
    with pytest.raises(ValueError, match="DST transition"):
        chicago_wall_to_utc_ns([dt.datetime(2024, 3, 10, 2, 30)])
    with pytest.raises(ValueError, match="DST transition"):
        chicago_wall_to_utc_ns([dt.datetime(2024, 11, 3, 1, 30)])


@pytest.mark.parametrize(
    ("root", "before", "after", "before_walls", "after_walls"),
    [
        (
            "ES",
            "2012-11-16",
            "2012-11-19",
            ["2012-11-15 15:30", "2012-11-15 16:30", "2012-11-15 17:00", "2012-11-16 15:15"],
            ["2012-11-18 17:00", "2012-11-19 15:15", "2012-11-19 15:30", "2012-11-19 16:15"],
        ),
        (
            "ES",
            "2015-09-18",
            "2015-09-21",
            ["2015-09-17 17:00", "2015-09-18 15:15", "2015-09-18 15:30", "2015-09-18 16:15"],
            ["2015-09-20 17:00", "2015-09-21 15:15", "2015-09-21 15:30", "2015-09-21 16:00"],
        ),
        (
            "ES",
            "2021-06-25",
            "2021-06-28",
            ["2021-06-24 17:00", "2021-06-25 15:15", "2021-06-25 15:30", "2021-06-25 16:00"],
            ["2021-06-27 17:00", "2021-06-28 16:00"],
        ),
        (
            "NKD",
            "2013-03-01",
            "2013-03-04",
            ["2013-02-28 17:00", "2013-03-01 15:15", "2013-03-01 15:30", "2013-03-01 16:15"],
            ["2013-03-03 17:00", "2013-03-04 16:15"],
        ),
    ],
)
def test_historical_schedule_changes(
    root: str, before: str, after: str, before_walls: list[str], after_walls: list[str]
) -> None:
    cal = SessionCalendar(TABLE, root)
    assert walls(cal.session(d(before)).segments) == before_walls
    assert walls(cal.session(d(after)).segments) == after_walls


def test_the_pre_2012_trade_date_boundary_is_1530_not_1700() -> None:
    """The defect ADR-0087's fixed 17:00 rule carries before 2012-11-19 (ADR-0091)."""
    ends = np.asarray([utc("2011-03-15 15:31"), utc("2011-03-15 17:01")], dtype=np.int64)
    assert trade_date_of(ES, ends) == [d("2011-03-16"), d("2011-03-16")]


# --- 3. holidays, early closes, special closures ------------------------------------------------


def test_thanksgiving_2024_halts_and_closes_early() -> None:
    assert not ES.is_trade_date(d("2024-11-28"))
    s = ES.session(d("2024-11-29"))
    assert walls(s.segments) == [
        "2024-11-27 17:00",
        "2024-11-28 12:00",
        "2024-11-28 17:00",
        "2024-11-29 12:15",
    ]
    assert s.notes
    assert "Thanksgiving" in s.notes[0]


def test_monday_holiday_belongs_to_tuesday() -> None:
    s = ES.session(d("2025-01-21"))
    assert walls(s.segments) == [
        "2025-01-19 17:00",
        "2025-01-20 12:00",
        "2025-01-20 17:00",
        "2025-01-21 16:00",
    ]
    with pytest.raises(ConfigurationError, match="not a ES Globex trade date"):
        ES.session(d("2025-01-20"))


def test_good_friday_closed_or_early_close() -> None:
    assert not ES.is_trade_date(d("2024-03-29"))
    assert walls(ES.session(d("2021-04-02")).segments)[-1] == "2021-04-02 08:15"
    assert walls(ES.session(d("2012-04-06")).segments)[-1] == "2012-04-06 08:15"


def test_friday_holiday_session_belongs_to_monday() -> None:
    """Juneteenth 2026: Thursday 17:00 opens Monday's trade date; Friday halts at 12:00."""
    assert not ES.is_trade_date(d("2026-06-19"))
    s = ES.session(d("2026-06-22"))
    assert walls(s.segments) == [
        "2026-06-18 17:00",
        "2026-06-19 12:00",
        "2026-06-21 17:00",
        "2026-06-22 16:00",
    ]


def test_july_4_2025_is_its_own_short_trade_date() -> None:
    assert walls(ES.session(d("2025-07-03")).segments)[-1] == "2025-07-03 12:15"
    assert walls(ES.session(d("2025-07-04")).segments) == ["2025-07-03 17:00", "2025-07-04 12:00"]


def test_christmas_2011_reopens_tuesday_0500() -> None:
    assert walls(ES.session(d("2011-12-27")).segments) == ["2011-12-27 05:00", "2011-12-27 15:15"]


def test_special_closures_apply_to_us_roots_only() -> None:
    assert walls(ES.session(d("2018-12-05")).segments)[-1] == "2018-12-05 08:30"
    assert walls(NKD.session(d("2018-12-05")).segments)[-1] == "2018-12-05 16:00"
    assert walls(ES.session(d("2025-01-09")).segments)[-1] == "2025-01-09 08:30"
    assert walls(NKD.session(d("2025-01-09")).segments)[-1] == "2025-01-09 16:00"
    assert walls(ES.session(d("2012-10-30")).segments) == ["2012-10-29 17:00", "2012-10-30 08:15"]


def test_unsourced_holidays_are_flagged_unverified() -> None:
    assert not ES.session(d("2023-01-16")).verified  # MLK 2023: schedule not archived
    assert not ES.session(d("2023-01-17")).verified
    assert ES.session(d("2023-01-18")).verified
    assert ES.session(d("2024-07-05")).verified
    assert not NKD.session(d("2024-07-05")).verified  # the 2024 capture covers ES only


def test_the_unscheduled_outage_keeps_the_scheduled_session() -> None:
    s = ES.session(d("2025-11-28"))
    assert walls(s.segments) == [
        "2025-11-26 17:00",
        "2025-11-27 12:00",
        "2025-11-27 17:00",
        "2025-11-28 12:15",
    ]
    assert any(u.trade_date == d("2025-11-28") for u in TABLE.unscheduled)


def test_missing_bars_are_gaps_not_closures() -> None:
    s = ES.session(d("2024-03-06"))
    ends = bars(s)
    report = schedule_report(ES, ends[: len(ends) // 2])
    assert report["off_schedule_bars"] == 0
    assert report["missing_scheduled_bars"] == 0  # bars outside the observed range are not gaps
    holed = np.delete(ends, slice(100, 160))
    report = schedule_report(ES, holed)
    assert report["missing_scheduled_bars"] == 60
    assert report["largest_gaps"][0] == {
        "trade_date": "2024-03-06",
        "missing": 60,
        "scheduled": 1380,
    }
    # the calendar itself is unchanged by what the bars show
    assert walls(ES.session(d("2024-03-06")).segments) == ["2024-03-05 17:00", "2024-03-06 16:00"]


# --- table validation ---------------------------------------------------------------------------


def _toy(**changes: object) -> SessionTable:
    regime = SessionRegime(
        name="toy",
        roots=frozenset({"ES"}),
        first_trade_date=d("2024-01-01"),
        last_trade_date=None,
        open_previous_day=dt.time(17, 0),
        close=dt.time(16, 0),
        breaks=(),
        sources=("s",),
    )
    base = SessionTable(
        version="toy-1",
        retrieved="2026-11-17",
        coverage={"ES": (d("2024-01-01"), d("2024-12-31"))},
        regimes=(regime,),
        overrides=(),
        no_trade_dates=(),
        unsourced=(),
        unscheduled=(),
        sources=(),
    )
    return dataclasses.replace(base, **changes)  # type: ignore[arg-type]


def test_a_session_after_a_closed_weekday_needs_an_explicit_open() -> None:
    table = _toy(no_trade_dates=(NoTradeDate(d("2024-07-04"), frozenset({"ES"}), "s", "x"),))
    with pytest.raises(DataQualityError, match="no explicit open"):
        SessionCalendar(table, "ES").session(d("2024-07-05"))


def test_overlapping_sessions_are_refused() -> None:
    table = _toy(
        overrides=(
            SessionOverride(
                d("2024-07-05"),
                frozenset({"ES"}),
                "s",
                "holiday",
                "x",
                open=dt.datetime(2024, 7, 4, 12, 0),
            ),
        )
    )
    with pytest.raises(DataQualityError, match="overlap"):
        SessionCalendar(table, "ES").sessions(d("2024-07-04"), d("2024-07-05"))


def test_the_table_is_versioned_hashed_and_cites_known_sources() -> None:
    summary = table_summary(TABLE)
    assert summary["version"] == TABLE_VERSION
    assert summary["sha256"] == table_hash(cme_session_table())
    keys = {s.key for s in TABLE.sources}
    assert {o.source for o in TABLE.overrides} <= keys
    assert all(s.sha256 is None or len(s.sha256) == 64 for s in TABLE.sources)
    assert TABLE.coverage["NKD"][0] == d("2012-11-19")


def test_every_covered_trade_date_builds() -> None:
    """The whole table: no overlap, no closed-weekday successor without an open, one regime."""
    for root, (first, last) in TABLE.coverage.items():
        sessions = SessionCalendar(TABLE, root).sessions(first, last)
        assert len(sessions) > 1000, root
        assert all(s.segments for s in sessions)


# --- 4. trade-date session rules ----------------------------------------------------------------


def test_entry_window_spans_midnight_on_the_trade_date_clock() -> None:
    s = ES.session(d("2024-03-06"))
    ends = bars(s)
    masks = session_rule_masks(ES, ends, entry_window=("18:00", "10:00"))
    ok = [
        w.strftime("%m-%d %H:%M")
        for w, e in zip(utc_ns_to_chicago_wall(list(ends)), masks.entry_ok, strict=True)
        if e
    ]
    assert ok[0] == "03-05 18:00"
    assert ok[-1] == "03-06 10:00"
    assert len(ok) == 16 * 60 + 1


def test_entry_window_on_a_monday_counts_from_sunday_evening() -> None:
    s = ES.session(d("2024-03-04"))
    masks = session_rule_masks(ES, bars(s), entry_window=("18:00", "10:00"))
    first_ok = utc_ns_to_chicago_wall([int(bars(s)[np.argmax(masks.entry_ok)])])[0]
    assert first_ok == dt.datetime(2024, 3, 3, 18, 0)


def test_exit_at_is_an_instant_of_the_trade_date() -> None:
    s = ES.session(d("2024-03-06"))
    ends = bars(s)
    masks = session_rule_masks(ES, ends, exit_at="02:00")
    first_flat = utc_ns_to_chicago_wall([int(ends[np.argmax(masks.force_flat)])])[0]
    assert first_flat == dt.datetime(2024, 3, 6, 2, 0)
    assert trade_date_instant(ES, s, "18:30") == utc("2024-03-05 18:30")
    assert trade_date_instant(ES, s, "15:50") == utc("2024-03-06 15:50")


def test_exit_at_after_an_early_close_falls_back_to_flat_by_close() -> None:
    s = ES.session(d("2024-11-29"))
    ends = bars(s)
    masks = session_rule_masks(ES, ends, exit_at="15:00")
    first_flat = utc_ns_to_chicago_wall([int(ends[np.argmax(masks.force_flat)])])[0]
    assert first_flat == dt.datetime(2024, 11, 29, 12, 14)


def test_a_reversed_entry_window_or_bad_clock_is_refused() -> None:
    ends = bars(ES.session(d("2024-03-06")))
    with pytest.raises(ConfigurationError, match="ends before it starts"):
        session_rule_masks(ES, ends, entry_window=("09:00", "18:00"))
    with pytest.raises(ConfigurationError, match="HH:MM"):
        session_rule_masks(ES, ends, exit_at="3pm")


# --- 5. flat-by-close timing --------------------------------------------------------------------


def test_flat_by_close_decides_on_the_penultimate_bar_and_fills_on_the_final_bar() -> None:
    s = ES.session(d("2024-03-06"))
    ends = bars(s)
    masks = session_rule_masks(ES, ends, flat_by_close=True)
    flat = np.flatnonzero(masks.force_flat)
    assert ends[flat[0]] == utc("2024-03-06 15:59")  # decided at the close of 15:58-15:59
    assert flat.tolist() == [len(ends) - 2, len(ends) - 1]
    assert not masks.entry_ok[-2:].any()
    assert masks.entry_ok[-3]
    assert masks.missing_final == ()


def test_flat_by_close_on_an_early_close_uses_its_own_final_bar() -> None:
    ends = bars(ES.session(d("2024-12-24")))
    masks = session_rule_masks(ES, ends, flat_by_close=True)
    assert ends[np.argmax(masks.force_flat)] == utc("2024-12-24 12:14")


def test_a_missing_final_bar_is_reported_not_replaced() -> None:
    ends = bars(ES.session(d("2024-03-06")))[:-1]
    masks = session_rule_masks(ES, ends, flat_by_close=True)
    assert masks.missing_final == (d("2024-03-06"),)


def test_a_missing_penultimate_bar_moves_the_decision_earlier() -> None:
    ends = bars(ES.session(d("2024-03-06")))
    holed = np.delete(ends, [len(ends) - 2, len(ends) - 3])
    masks = session_rule_masks(ES, holed, flat_by_close=True)
    assert holed[np.argmax(masks.force_flat)] == utc("2024-03-06 15:57")
    assert masks.missing_final == ()


def test_off_schedule_bars_never_force_a_position_flat() -> None:
    ends = np.append(bars(ES.session(d("2024-03-06"))), utc("2024-03-06 16:01"))
    masks = session_rule_masks(ES, ends)
    assert not masks.on_schedule[-1]
    assert not masks.force_flat.any()
    assert not masks.entry_ok[-1]
    assert masks.off_schedule == 1


# --- 6. refusals --------------------------------------------------------------------------------


def test_unverified_sessions_are_listed_for_a_strict_caller() -> None:
    ends = bars(ES.session(d("2023-01-17")))
    masks = session_rule_masks(ES, ends, flat_by_close=True)
    assert masks.unverified == (d("2023-01-17"),)
