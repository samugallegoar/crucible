"""The session-relative ``flat_by`` blocks entries from its flat instant to the session close.

ADR-0107's vocabulary adds ``flat_by.minutes_before_session_end`` so a holiday early close comes
from the CME calendar instead of a guessed clock time. The two halves of the rule are separate
facts and both are asserted here, on the sourced early close of 2024-11-29:

- ``flat_and_reopen`` gives ``(flat, reopen)`` = (17:15, 18:15) UTC for a 60-minute offset on a
  session that closes at 18:15 UTC (12:15 Chicago, the day after Thanksgiving 2024). The reopen is
  the SCHEDULED SESSION CLOSE, not the flat instant: between the two the account is flat and no new
  position may be opened, and the next chance to trade is the next session's open (17:00 Chicago,
  23:00 UTC).
- ``admit`` refuses an entry for every bar whose ``[open, close]`` overlaps that window, while a bar
  before the flat instant still admits one.

The hand arithmetic: a session closing at 18:15 UTC with a 60-minute offset flattens at
18:15 - 1:00 = 17:15 UTC; a bar closing at 17:14 is free to enter, a bar closing at 17:15 or later
and opening before 18:15 may not. A regular session that week closes at 22:00 UTC, so the same rule
flattens at 21:00 there -- the early close is a calendar fact, never a constant.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from zoneinfo import ZoneInfo

import numpy as np

from crucible.data.cme_session_table import cme_session_table
from crucible.data.cme_sessions import SessionCalendar
from crucible.execution.interfaces import AccountMarks
from crucible.prop import rules as rl
from crucible.prop.overlay import PropAccountOverlay
from crucible.prop.ruleset import Attribution, PropRuleset

NS = 1_000_000_000
MINUTE = 60 * NS
TICK_MICRO = 12_500_000
CALENDAR = SessionCalendar(cme_session_table(), "ES")
EARLY_CLOSE_DAY = dt.date(2024, 11, 29)
REGULAR_DAY = dt.date(2024, 12, 2)


def _instant(day: dt.date, hour: int, minute: int) -> int:
    """UTC nanoseconds of a UTC wall clock (the November early close is stated in UTC here)."""
    return (
        int(dt.datetime(day.year, day.month, day.day, hour, minute, tzinfo=dt.UTC).timestamp()) * NS
    )


CHICAGO = ZoneInfo("America/Chicago")
"""The zone a firm states its clocks in (``reset.tz``), used only to compute expected instants."""


def _chicago(day: dt.date, hour: int, minute: int) -> int:
    """UTC nanoseconds of a Chicago wall clock on ``day``."""
    stamp = dt.datetime.combine(day, dt.time(hour, minute), tzinfo=CHICAGO)
    return int(stamp.timestamp()) * NS


def _source() -> Attribution:
    return Attribution(
        url="https://example.invalid/synthetic-rules",
        quote="Synthetic rule value invented for a test, not a real firm's rule",
        snapshot_sha256="0" * 64,
        retrieved_at=dt.datetime(2024, 1, 1, tzinfo=dt.UTC),
        synthetic=True,
    )


def _ruleset() -> PropRuleset:
    source = _source().model_dump(mode="json")
    return PropRuleset.model_validate(
        {
            "schema_version": 2,
            "ruleset_id": "synthetic-flat-by",
            "version": 1,
            "firm": "SyntheticFirm A",
            "program": "Synthetic Day Trading",
            "account_size_usd": "50000",
            "as_of": "2024-01-01",
            "effective_from": "2024-01-01",
            "instruments": [{"root": "ES", "contract_weight": "1"}],
            "reset": {"time": "17:00:00", "tz": "America/Chicago"},
            "commissions": {
                "status": "known",
                "includes_exchange_and_regulatory_fees": True,
                "per_side_usd": {"ES": "2.00"},
                "platform": None,
                "source": source,
            },
            "phases": [
                {
                    "phase_id": "evaluation",
                    "kind": "evaluation",
                    "starting_balance_usd": "50000",
                    "rules": [
                        {
                            "kind": "flat_by",
                            "rule_id": "flat",
                            "minutes_before_session_end": 60,
                            "comparison": ">=",
                            "action": "auto_liquidate",
                            "source": source,
                            "evidence": "official_quote",
                        }
                    ],
                    "pass_conditions": [],
                    "fees": [],
                }
            ],
        }
    )


def _marks(open_ns: int, close_ns: int, *, position: int = 0, bar: int = 0) -> AccountMarks:
    """A flat-price mark book (5,000.00 points, one ES tick = $12.50)."""
    ticks = 20_000
    return AccountMarks(
        bar=bar,
        open_time_ns=open_ns,
        close_time_ns=close_ns,
        open_ticks=ticks,
        high_ticks=ticks,
        low_ticks=ticks,
        close_ticks=ticks,
        position=position,
        balance_micro=rl.micro(Decimal("50000")),
        cost_basis_ticks=position * ticks,
        tick_micro=TICK_MICRO,
    )


def _overlay(session_close_ns: int, bars: int) -> PropAccountOverlay:
    ruleset = _ruleset()
    return PropAccountOverlay(
        ruleset=ruleset,
        phase=ruleset.phases[0],
        root="ES",
        tick_micro=TICK_MICRO,
        session_close_ns=np.full(bars, session_close_ns, dtype=np.int64),
        start_day=EARLY_CLOSE_DAY,
    )


def test_the_early_close_is_the_calendars_and_the_reopen_is_its_close() -> None:
    """2024-11-29 closes at 18:15 UTC (12:15 Chicago): 60 minutes before it is 17:15 UTC.

    A fixed 16:00 Chicago clock would flatten at 22:00 UTC, an hour and 45 minutes after the
    session closed; the session-relative rule reads the calendar instead. The same rule on the
    following Monday (a regular 22:00 UTC close) flattens at 21:00 UTC, so the offset is what is
    declared and the close is what the calendar says.
    """
    early = CALENDAR.session(EARLY_CLOSE_DAY)
    assert early.verified is True
    assert early.close_ns == _instant(EARLY_CLOSE_DAY, 18, 15)
    evaluator = rl.FlatBy(_ruleset().phases[0].rules[0], rl.micro(Decimal("50000")), Decimal(1))
    window = evaluator.flat_and_reopen(early.open_ns, early.close_ns, early.close_ns)
    assert window == (_instant(EARLY_CLOSE_DAY, 17, 15), _instant(EARLY_CLOSE_DAY, 18, 15))

    regular = CALENDAR.session(REGULAR_DAY)
    assert regular.close_ns == _instant(REGULAR_DAY, 22, 0)
    window = evaluator.flat_and_reopen(regular.open_ns, regular.close_ns, regular.close_ns)
    assert window == (_instant(REGULAR_DAY, 21, 0), _instant(REGULAR_DAY, 22, 0))


def test_no_entry_is_admitted_between_the_flat_instant_and_the_session_close() -> None:
    """Every bar of the flat window is refused; the bar before it is not.

    Bars (UTC close instants) on 2024-11-29: 16:01 (before the flat), 17:15 (the flat instant),
    17:16, 18:14 and 18:15 (the session close). ``admit`` returns the requested 1 at 16:01 and the
    position (0) for the four window bars. The ``flat_by`` also liquidates a position at the bar
    that reaches the flat instant, which is the other half of the same rule.
    """
    close = _instant(EARLY_CLOSE_DAY, 18, 15)
    overlay = _overlay(close, 5)
    bars = [16 * 60 + 1, 17 * 60 + 15, 17 * 60 + 16, 18 * 60 + 14, 18 * 60 + 15]
    minutes = [
        dt.datetime(
            EARLY_CLOSE_DAY.year,
            EARLY_CLOSE_DAY.month,
            EARLY_CLOSE_DAY.day,
            minute // 60,
            minute % 60,
            tzinfo=dt.UTC,
        )
        for minute in bars
    ]
    admitted: list[int] = []
    for index, instant in enumerate(minutes):
        open_ns = int(instant.timestamp()) * NS - MINUTE
        close_ns = int(instant.timestamp()) * NS
        marks = _marks(open_ns, close_ns, position=1 if index == 1 else 0, bar=index)
        assert overlay.begin_bar(index, marks) is None
        if index == 1:
            # the bar that reaches 17:15 liquidates the position that was opened before it
            action = overlay.forced_flat(index, marks)
            assert action is not None
            assert action.kind == "liquidate"
            assert action.rule_id == "flat"
            marks = _marks(open_ns, close_ns, bar=index)
        admitted.append(overlay.admit(index, marks, 1))
    assert admitted == [1, 0, 0, 0, 0]
    # the flat window is the interval, not the bar: it is what admit tests on every bar in it
    assert overlay._flat_window(_marks(close - 2 * MINUTE, close - MINUTE, bar=4)) is True
    assert (
        overlay._flat_window(
            _marks(_instant(EARLY_CLOSE_DAY, 14, 0), _instant(EARLY_CLOSE_DAY, 14, 1), bar=0)
        )
        is False
    )


def test_the_window_ends_at_the_scheduled_close_not_at_the_flat_instant() -> None:
    """A bar opening at the session close (18:15) is past the window and may re-enter.

    The reopen is the scheduled close, so the entry block lasts exactly the distance the firm
    declares (60 minutes here) and not a moment longer: a bar opening at 18:13 is refused and a bar
    opening at 18:15 -- the first moment after the close -- is admitted.
    """
    close = _instant(EARLY_CLOSE_DAY, 18, 15)
    overlay = _overlay(close, 2)
    inside = _marks(close - 2 * MINUTE, close - MINUTE, bar=0)
    assert overlay.begin_bar(0, inside) is None
    assert overlay.admit(0, inside, 1) == 0
    after = _marks(close, close + MINUTE, bar=1)
    assert overlay.begin_bar(1, after) is None
    assert overlay.admit(1, after, 1) == 1


def test_an_absolute_clock_reopen_still_wins_when_the_firm_states_one() -> None:
    """A ``flat_by`` with a clock and a reopen keeps the stated reopen, not the session close.

    The vocabulary allows both forms; the session-relative default (reopen at the close) must not
    override a firm that states a reopen clock. An absolute clock is placed on the calendar day the
    session OPENS on, which is where the C7a form has always put it -- and on this holiday the
    session opens on Wednesday 2024-11-27 17:00 Chicago (Thanksgiving itself is closed) and runs to
    Friday 12:15, so 15:10 Chicago is 21:10 UTC on 11-27 and the stated 17:00 reopen is 23:00 UTC
    on 11-27, not the 18:15 UTC close of 11-29 the session-relative form would use.
    """
    source = _source().model_dump(mode="json")
    raw = _ruleset().model_dump(mode="json")
    raw["phases"][0]["rules"] = [
        {
            "kind": "flat_by",
            "rule_id": "flat",
            "time": "15:10:00",
            "tz": "America/Chicago",
            "reopen": "17:00:00",
            "comparison": ">=",
            "action": "auto_liquidate",
            "source": source,
            "evidence": "official_quote",
        }
    ]
    ruleset = PropRuleset.model_validate(raw)
    evaluator = rl.FlatBy(ruleset.phases[0].rules[0], rl.micro(Decimal("50000")), Decimal(1))
    early = CALENDAR.session(EARLY_CLOSE_DAY)
    window = evaluator.flat_and_reopen(early.open_ns, early.close_ns, early.close_ns)
    assert window is not None
    flat, reopen = window
    opened = dt.datetime.fromtimestamp(early.open_ns // NS, dt.UTC).astimezone(CHICAGO)
    assert opened == dt.datetime(2024, 11, 27, 17, 0, tzinfo=CHICAGO)
    assert flat == _chicago(opened.date(), 15, 10)
    assert reopen == _chicago(opened.date(), 17, 0)
    assert reopen != early.close_ns


def test_a_session_relative_flat_by_without_a_session_has_no_window() -> None:
    """An off-schedule bar has no scheduled close, so the session-relative clock has no instant.

    An absolute clock needs no session at all (it is a wall-clock time), which is why only the
    session-relative form can return ``None`` -- and the overlay then simply has no flat window for
    that bar rather than inventing one.
    """
    evaluator = rl.FlatBy(_ruleset().phases[0].rules[0], rl.micro(Decimal("50000")), Decimal(1))
    assert evaluator.flat_and_reopen(0, MINUTE, 0) is None
    overlay = _overlay(0, 1)
    marks = _marks(0, MINUTE, bar=0)
    assert overlay.begin_bar(0, marks) is None
    assert overlay.forced_flat(0, marks) is None
    assert overlay.admit(0, marks, 1) == 1
