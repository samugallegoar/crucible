"""Causal resampling of a one-minute futures series to 5- and 15-minute bars (Fathom C5a).

Hand-computed buckets on REAL ES Globex trade dates of 2024-03 (the CME session calendar of
ADR-0091 decides where a bucket starts and stops), plus the cases that make the rule honest: an
early close, a session whose close is off the m-minute grid (a synthetic table: the real one opens
and closes on 5-minute boundaries), a data gap, off-schedule prints, a delayed constituent, a
bucket that mixes contracts, and causality.

Every expected value is written out, never derived from the resampler: a bucket's open is its first
constituent's open, its high the max of the highs, its low the min of the lows, its close the last
close, its volume the sum, its `bars` the count of one-minute constituents and its event_time the
bucket's END clipped to the session close.
"""

from __future__ import annotations

import dataclasses
import datetime as dt

import polars as pl
import pytest

from crucible.core.errors import ConfigurationError, DataQualityError
from crucible.data.calendars import chicago_wall_to_utc_ns
from crucible.data.cme_sessions import (
    SessionCalendar,
    SessionRegime,
    SessionTable,
    session_trade_dates,
)
from crucible.data.continuous import calendar_for
from crucible.data.contracts import CONTINUOUS_BAR_SCHEMA
from crucible.data.resample import resample_session_bars

_NS = 1_000_000_000
_MIN = 60 * _NS
ES = calendar_for("ES")

# 2024-03-05 is a regular ES trade date: one segment, 2024-03-04 23:00 UTC -> 2024-03-05 22:00 UTC
# (17:00 -> 16:00 Chicago, CST). 1380 one-minute bars, ending on the close.
REGULAR = dt.date(2024, 3, 5)
REGULAR_BARS = 23 * 60  # 23:00 -> 22:00 is 23 hours of one-minute bars
ESH, ESM = "ESH2024", "ESM2024"


def utc(wall: str) -> int:
    """UTC ns of a naive America/Chicago wall clock."""
    return chicago_wall_to_utc_ns([dt.datetime.fromisoformat(wall)])[0]


def _bars(
    session: object,
    *,
    contract: str = ESH,
    base: float = 4400.0,
    latency_ns: int = 1,
    skip: tuple[int, ...] = (),
    symbol: str = "ES",
) -> pl.DataFrame:
    """One-minute bars of a session, element ``i`` of its schedule.

    Prices are a function of the element index so a bucket's expected OHLC is arithmetic:
    ``open = base + i``, ``high = open + 0.5``, ``low = open - 0.5``, ``close = open + 0.25``,
    ``volume = 10 + i``.
    """
    ends: list[int] = []
    for start, end in session.segments:  # type: ignore[attr-defined]
        ends.extend(range(start + _MIN, end + 1, _MIN))
    rows = [(position, instant) for position, instant in enumerate(ends) if position not in skip]
    return pl.DataFrame(
        {
            "symbol": [symbol] * len(rows),
            "event_time": [instant for _, instant in rows],
            "available_at": [instant + latency_ns for _, instant in rows],
            "open": [base + position for position, _ in rows],
            "high": [base + position + 0.5 for position, _ in rows],
            "low": [base + position - 0.5 for position, _ in rows],
            "close": [base + position + 0.25 for position, _ in rows],
            "volume": [float(10 + position) for position, _ in rows],
            "contract": [contract] * len(rows),
        },
        schema=CONTINUOUS_BAR_SCHEMA,
    )


def _row(frame: pl.DataFrame, event_time: int) -> dict[str, object]:
    rows = frame.filter(pl.col("event_time") == event_time)
    assert rows.height == 1, f"expected exactly one bar ending at {event_time} ns"
    return rows.row(0, named=True)


def _expected(position: int, base: float = 4400.0) -> dict[str, float]:
    """The OHLCV a bucket of five constituents starting at element ``position`` must carry."""
    first, last = position, position + 4
    return {
        "open": base + first,
        "high": base + last + 0.5,
        "low": base + first - 0.5,
        "close": base + last + 0.25,
        "volume": float(sum(10 + i for i in range(first, last + 1))),
    }


# ---------------------------------------------------------------------------------------------
# 5 and 15 minute buckets on a regular session


def test_five_minute_buckets_are_hand_computed_on_a_regular_trade_date() -> None:
    session = ES.session(REGULAR)
    bars = _bars(session)
    assert bars.height == REGULAR_BARS == 1380
    result = resample_session_bars(bars, calendar=ES, minutes=5)
    assert result.buckets == 1380 // 5 == 276
    assert result.dropped_off_schedule == 0
    assert result.partial_buckets == 0
    out = result.bars
    assert out["event_time"].to_list() == sorted(out["event_time"].to_list())

    # the first bucket: one-minute bars 23:01..23:05 UTC, labelled by its END (23:05)
    first = _row(out, utc("2024-03-04 17:05"))
    expected = _expected(0)
    assert first["open"] == expected["open"] == 4400.0
    assert first["high"] == expected["high"] == 4404.5
    assert first["low"] == expected["low"] == 4399.5
    assert first["close"] == expected["close"] == 4404.25
    assert first["volume"] == expected["volume"] == 5 * 10 + (0 + 1 + 2 + 3 + 4)
    assert first["bars"] == 5
    assert first["partial"] is False
    assert first["contract"] == ESH
    assert first["available_at"] == utc("2024-03-04 17:05") + 1

    # the last bucket ends exactly on the scheduled close (16:00 Chicago) and holds 5 bars
    last = _row(out, utc("2024-03-05 16:00"))
    assert last["bars"] == 5
    assert last["partial"] is False
    assert last["close"] == _expected(1375)["close"]
    assert out["event_time"].max() == session.close_ns

    # every label is the END of a 5-minute interval on the UTC clock
    width = 5 * 60 * _NS
    assert all(int(value) % width == 0 for value in out["event_time"].to_list())
    assert all(int(value) == 5 for value in out["bars"].to_list())


def test_fifteen_minute_buckets_are_hand_computed_on_a_regular_trade_date() -> None:
    session = ES.session(REGULAR)
    bars = _bars(session)
    result = resample_session_bars(bars, calendar=ES, minutes=15)
    assert result.buckets == 1380 // 15 == 92
    out = result.bars
    first = _row(out, utc("2024-03-04 17:15"))
    assert first["open"] == 4400.0
    assert first["high"] == 4414.5  # element 14
    assert first["low"] == 4399.5
    assert first["close"] == 4414.25
    assert first["volume"] == float(sum(10 + i for i in range(15)))
    assert first["bars"] == 15
    assert _row(out, utc("2024-03-05 16:00"))["bars"] == 15
    assert out["event_time"].max() == session.close_ns
    width = 15 * 60 * _NS
    assert all(int(value) % width == 0 for value in out["event_time"].to_list())


def test_no_bucket_spans_the_maintenance_break_or_a_session_boundary() -> None:
    previous = ES.session(dt.date(2024, 3, 4))
    session = ES.session(REGULAR)
    bars = pl.concat([_bars(previous), _bars(session, base=4500.0)])
    for minutes in (5, 15):
        result = resample_session_bars(bars, calendar=ES, minutes=minutes)
        out = result.bars
        width = minutes * 60 * _NS
        # the break is 16:00 -> 17:00 Chicago: no output bucket's interval covers it
        break_start, break_end = previous.close_ns, session.open_ns
        for label in out["event_time"].to_list():
            start = int(label) - width
            assert not (start < break_end and int(label) > break_start), (minutes, label)
        # every bucket holds one contract and one session's bars
        assert set(out["contract"].to_list()) == {ESH}
        # each session contributes its own number of buckets, and the labels are disjoint
        first_day = out.filter(pl.col("event_time") < session.open_ns)
        second_day = out.filter(pl.col("event_time") > previous.close_ns)
        assert first_day.height == second_day.height == 1380 // minutes
        assert second_day["open"].min() == 4500.0
        # the calendars place every bucket on the trade date its constituents belong to
        days, on_schedule = session_trade_dates(ES, out["event_time"].to_numpy(), minutes * 60)
        assert bool(on_schedule.all())
        assert [str(day) for day in days] == sorted([str(day) for day in days])
        assert {str(day) for day in days} == {str(dt.date(2024, 3, 4)), str(REGULAR)}


# ---------------------------------------------------------------------------------------------
# clipping: an early close and a close off the m-minute grid


def test_an_early_close_gives_exact_buckets_and_a_late_label_is_the_session_close() -> None:
    # 2024-11-29 (the Friday after Thanksgiving) closes at 12:15 Chicago = 18:15 UTC
    early = dt.date(2024, 11, 29)
    session = ES.session(early)
    assert len(session.segments) == 2  # the previous evening and the short Friday
    bars = _bars(session)
    for minutes in (5, 15):
        result = resample_session_bars(bars, calendar=ES, minutes=minutes)
        assert result.partial_buckets == 0
        assert result.bars["event_time"].max() == session.close_ns
        assert int(session.close_ns) % (minutes * 60 * _NS) == 0
        assert all(int(value) == minutes for value in result.bars["bars"].to_list())


def _toy_calendar(close: dt.time) -> SessionCalendar:
    """A one-root session table whose afternoon close is ``close`` Chicago wall clock."""
    regime = SessionRegime(
        name="toy",
        roots=frozenset({"ES"}),
        first_trade_date=dt.date(2024, 1, 1),
        last_trade_date=None,
        open_previous_day=dt.time(17, 0),
        close=close,
        breaks=(),
        sources=("toy",),
    )
    table = SessionTable(
        version="toy-1",
        retrieved="2026-01-01",
        coverage={"ES": (dt.date(2024, 1, 1), dt.date(2024, 12, 31))},
        regimes=(regime,),
        overrides=(),
        no_trade_dates=(),
        unsourced=(),
        unscheduled=(),
        sources=(),
    )
    return SessionCalendar(dataclasses.replace(table), "ES")


def test_a_close_off_the_grid_gives_a_shorter_last_bucket_flagged_partial() -> None:
    calendar = _toy_calendar(dt.time(16, 12))  # 16:12 Chicago: two minutes past a 5-minute grid
    session = calendar.session(REGULAR)
    bars = _bars(session)
    result = resample_session_bars(bars, calendar=calendar, minutes=5)
    out = result.bars
    # 23:00 Chicago -> 16:12 Chicago is 23h12m of one-minute bars (CST: 05:00 -> 22:12 UTC)
    assert bars.height == 23 * 60 + 12 == 1392
    clipped = out.filter(pl.col("partial"))
    assert clipped.height == 1
    last = out.row(out.height - 1, named=True)
    assert last["partial"] is True
    assert last["event_time"] == session.close_ns  # clipped to the scheduled close
    assert last["bars"] == 2  # 16:11 and 16:12: the bucket lost its last three minutes
    assert last["open"] == 4400.0 + 1390
    assert last["close"] == 4400.0 + 1391 + 0.25
    assert result.partial_buckets == 1
    # the bucket BEFORE the clipped one is a full five-minute bucket
    previous = out.row(out.height - 2, named=True)
    assert previous["partial"] is False
    assert previous["bars"] == 5


# ---------------------------------------------------------------------------------------------
# gaps


def test_a_gap_leaves_the_bucket_short_and_an_empty_bucket_produces_no_row() -> None:
    session = ES.session(REGULAR)
    full = resample_session_bars(_bars(session), calendar=ES, minutes=5)
    # elements 0..4 are the first bucket; drop the middle minute of it (element 2)
    # elements 5..9 are the second bucket, dropped entirely
    gapped = _bars(session, skip=(2, 5, 6, 7, 8, 9))
    result = resample_session_bars(gapped, calendar=ES, minutes=5)
    assert result.buckets == full.buckets - 1  # the empty bucket has no row
    assert result.dropped_off_schedule == 0
    first = _row(result.bars, utc("2024-03-04 17:05"))
    assert first["bars"] == 4
    assert first["open"] == 4400.0  # element 0
    assert first["high"] == 4404.5  # element 4
    assert first["low"] == 4399.5  # element 0
    assert first["close"] == 4404.25  # element 4
    assert first["volume"] == float(10 + 0 + 10 + 1 + 10 + 3 + 10 + 4)
    assert result.bars.filter(pl.col("event_time") == utc("2024-03-04 17:10")).height == 0
    # the third bucket onwards is untouched by the gap
    third = _row(result.bars, utc("2024-03-04 17:15"))
    assert third == _row(full.bars, utc("2024-03-04 17:15"))


def test_off_schedule_bars_are_dropped_and_counted_never_aggregated() -> None:
    session = ES.session(REGULAR)
    bars = _bars(session)
    # the maintenance break: 16:00 -> 17:00 Chicago, printed at 16:30 and 16:59
    late = pl.DataFrame(
        {
            "symbol": ["ES", "ES"],
            "event_time": [utc("2024-03-05 16:30"), utc("2024-03-05 16:59")],
            "available_at": [utc("2024-03-05 16:30") + 1, utc("2024-03-05 16:59") + 1],
            "open": [1.0, 2.0],
            "high": [1.0, 2.0],
            "low": [1.0, 2.0],
            "close": [1.0, 2.0],
            "volume": [1.0, 1.0],
            "contract": [ESH, ESH],
        },
        schema=CONTINUOUS_BAR_SCHEMA,
    )
    result = resample_session_bars(pl.concat([bars, late]), calendar=ES, minutes=5)
    clean = resample_session_bars(bars, calendar=ES, minutes=5)
    assert result.dropped_off_schedule == 2
    assert result.buckets == 276  # unchanged: neither print entered a bucket
    assert result.bars.equals(clean.bars)


# ---------------------------------------------------------------------------------------------
# availability, contracts, refusals


def test_available_at_is_the_later_of_the_label_and_the_last_constituent() -> None:
    session = ES.session(REGULAR)
    bars = _bars(session, latency_ns=1)
    label = utc("2024-03-04 17:05")
    delayed = bars.with_columns(
        pl.when(pl.col("event_time") == utc("2024-03-04 17:04"))
        .then(pl.col("event_time") + 65 * _NS)
        .otherwise(pl.col("available_at"))
        .alias("available_at")
    )
    plain = resample_session_bars(bars, calendar=ES, minutes=5)
    late = resample_session_bars(delayed, calendar=ES, minutes=5)
    # the constituents' own latency is inside the bucket: the label is what the aggregate knows
    assert _row(plain.bars, label)["available_at"] == label + 1
    # a constituent known 65s after it printed pushes the aggregate past the label
    assert _row(late.bars, label)["available_at"] == utc("2024-03-04 17:04") + 65 * _NS
    assert int(_row(late.bars, label)["available_at"]) > label


def test_a_bucket_that_mixes_contracts_is_refused() -> None:
    session = ES.session(REGULAR)
    bars = _bars(session)
    label = utc("2024-03-04 17:05")
    rolled = bars.with_columns(
        pl.when(pl.col("event_time") == utc("2024-03-04 17:04"))
        .then(pl.lit(ESM))
        .otherwise(pl.col("contract"))
        .alias("contract")
    )
    with pytest.raises(DataQualityError, match="holds 2 contracts"):
        resample_session_bars(rolled, calendar=ES, minutes=5)
    with pytest.raises(DataQualityError, match=str(label)):
        resample_session_bars(rolled, calendar=ES, minutes=5)


def test_only_the_documented_resolutions_are_built() -> None:
    session = ES.session(REGULAR)
    bars = _bars(session)
    for minutes in (1, 2, 10, 30, 60):
        with pytest.raises(ConfigurationError, match="not a resampling resolution"):
            resample_session_bars(bars, calendar=ES, minutes=minutes)
    with pytest.raises(ConfigurationError, match="whole number of"):
        resample_session_bars(bars, calendar=ES, minutes=5, source_seconds=90)
    with pytest.raises(ConfigurationError, match="seconds >= 1"):
        resample_session_bars(bars, calendar=ES, minutes=5, source_seconds=0)


def test_a_series_without_the_contract_column_is_refused() -> None:
    session = ES.session(REGULAR)
    bars = _bars(session).drop("contract")
    with pytest.raises(DataQualityError, match="lacks"):
        resample_session_bars(bars, calendar=ES, minutes=5)


def test_two_bars_ending_at_one_instant_are_refused() -> None:
    session = ES.session(REGULAR)
    bars = _bars(session)
    duplicated = pl.concat([bars, bars.slice(0, 1)])
    with pytest.raises(DataQualityError, match="same instant"):
        resample_session_bars(duplicated, calendar=ES, minutes=5)


def test_the_output_is_sorted_and_independent_of_the_input_order() -> None:
    session = ES.session(REGULAR)
    bars = _bars(session)
    ordered = resample_session_bars(bars, calendar=ES, minutes=5)
    reversed_input = bars.reverse()
    shuffled = resample_session_bars(reversed_input, calendar=ES, minutes=5)
    assert ordered.bars.equals(shuffled.bars)
    assert ordered.bars["event_time"].to_list() == sorted(ordered.bars["event_time"].to_list())


# ---------------------------------------------------------------------------------------------
# causality


def test_a_bucket_ending_at_t_is_identical_when_every_later_bar_is_removed() -> None:
    session = ES.session(REGULAR)
    bars = _bars(session)
    cutoff = utc("2024-03-05 11:00")
    for minutes in (5, 15):
        full = resample_session_bars(bars, calendar=ES, minutes=minutes)
        truncated = resample_session_bars(
            bars.filter(pl.col("event_time") <= cutoff), calendar=ES, minutes=minutes
        )
        kept = full.bars.filter(pl.col("event_time") <= cutoff)
        assert kept.equals(truncated.bars)
        # the cutoff bucket itself is unchanged, so nothing after it leaks backwards
        assert _row(full.bars, cutoff) == _row(truncated.bars, cutoff)


def test_poisoned_later_bars_cannot_change_an_earlier_bucket() -> None:
    session = ES.session(REGULAR)
    bars = _bars(session)
    cutoff = utc("2024-03-05 11:00")
    poisoned = bars.with_columns(
        pl.when(pl.col("event_time") > cutoff)
        .then(pl.col("close") + 1000.0)
        .otherwise(pl.col("close"))
        .alias("close")
    )
    clean = resample_session_bars(bars, calendar=ES, minutes=5)
    dirty = resample_session_bars(poisoned, calendar=ES, minutes=5)
    assert clean.bars.filter(pl.col("event_time") <= cutoff).equals(
        dirty.bars.filter(pl.col("event_time") <= cutoff)
    )
