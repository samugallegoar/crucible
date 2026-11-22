"""When a pass condition is tested: ``evaluated: eod`` only at the rule-day's last bar.

ADR-0106 section 3 step 8 and ADR-0107 section 9 put the pass conditions at the end of the
rule-day, after the threshold tests: a firm that declares ``evaluated: eod`` tests its target on the
CLOSED figure of the trade date. A target touched inside a bar and lost again by the session's close
therefore does NOT pass, while the same target declared ``evaluated: intraday`` does (the touch
counts at the bar's favourable extreme).

Hand arithmetic, one ES contract at $50 a point on a $50,000 account with a $2.00 per-side
commission (so a round trip costs $4.00):

- target: ``+$1,000`` on equity, i.e. +20 points from the entry price of 4,800.00;
- the mid-session bar reaches a high of 4,830.00 (+30 points = +$1,500 = +$1,496 net): a touch;
- that bar closes at 4,805.00 (+5 points = +$250), and the session's last bar closes there too, so
  the CLOSED figure of the trade date never reaches $1,000;
- the control case closes the session's last bar at 4,830.00, which does.

``tests/unit/test_prop_flat_by_entry_block.py`` covers the other half of the same end-of-day idea
(a session-relative ``flat_by``). The bars are the ES session of the verified 2024-06-12 trade date.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import polars as pl

from crucible.data.cme_session_table import cme_session_table
from crucible.data.cme_sessions import SessionCalendar
from crucible.data.contracts import ROLL_SCHEMA
from crucible.data.futures_specs import futures_spec
from crucible.execution.futures_sim import CostSchedule
from crucible.prop.attempt import simulate_attempt
from crucible.prop.ruleset import Attribution, PropRuleset

_COMPONENTS_ALL_IN = {
    name: {"status": "included", "evidence": "official_quote", "text": "SYNTHETIC TEST VALUE"}
    for name in ("exchange", "clearing", "nfa", "other")
}
"""A commission whose four cost components are all inside it (synthetic, all-in)."""
_COMPONENTS_EXCLUDED = {
    name: {"status": "excluded", "evidence": "official_quote", "text": "SYNTHETIC TEST VALUE"}
    for name in ("exchange", "clearing", "nfa", "other")
}
"""A commission that excludes every component: each is charged on top (synthetic)."""
_COMPONENTS_UNKNOWN = {
    name: {"status": "unknown", "evidence": "not_stated", "text": "SYNTHETIC TEST VALUE"}
    for name in ("exchange", "clearing", "nfa", "other")
}
"""A commission whose four components the source does not state (synthetic)."""


NS = 1_000_000_000
DAY = dt.date(2024, 6, 12)
CALENDAR = SessionCalendar(cme_session_table(), "ES")
ENTRY = 4800.0
TOUCH = 4830.0
LOST = 4805.0


def _source() -> Attribution:
    return Attribution(
        url="https://example.invalid/synthetic-rules",
        quote="Synthetic rule value invented for a test, not a real firm's rule",
        snapshot_sha256="0" * 64,
        retrieved_at=dt.datetime(2024, 1, 1, tzinfo=dt.UTC),
        synthetic=True,
    )


def _ruleset(evaluated: str) -> PropRuleset:
    """One evaluation phase: a $1,000 equity target declared ``evaluated`` as given, no failure."""
    source = _source().model_dump(mode="json")
    return PropRuleset.model_validate(
        {
            "schema_version": 2,
            "ruleset_id": "synthetic-pass-frequency",
            "version": 1,
            "firm": "SyntheticFirm A",
            "program": "Synthetic Evaluation",
            "account_size_usd": "50000",
            "as_of": "2024-01-01",
            "effective_from": "2024-01-01",
            "instruments": [{"root": "ES", "contract_weight": "1"}],
            "reset": {"time": "17:00:00", "tz": "America/Chicago"},
            "commissions": {
                "status": "known",
                "components": _COMPONENTS_ALL_IN,
                "per_side_usd": {"ES": "2.00"},
                "platform": None,
                "source": source,
            },
            "phases": [
                {
                    "phase_id": "evaluation",
                    "kind": "evaluation",
                    "starting_balance_usd": "50000",
                    "rules": [],
                    "pass_conditions": [
                        {
                            "kind": "profit_target",
                            "rule_id": "target",
                            "amount_usd": "1000",
                            "basis": "equity",
                            "evaluated": evaluated,
                            "comparison": ">=",
                            "action": "promote_phase",
                            "require_flat": False,
                            "source": source,
                            "evidence": "official_quote",
                        }
                    ],
                    "fees": [],
                }
            ],
        }
    )


def _bars(*, last_close: float) -> tuple[pl.DataFrame, pl.DataFrame]:
    """The 2024-06-12 session's 60-minute ES bars, long one contract on every bar.

    Every bar is flat at 4,800.00 except the tenth, which touches 4,830.00 and closes at 4,805.00
    (the touch that an intraday target sees and an end-of-day one does not), and the last bar of the
    session, whose close is ``last_close``. The last bar's end IS the session's scheduled close
    (21:00 UTC, 16:00 Chicago), which is what marks the end of the rule-day.
    """
    ends = CALENDAR.session(DAY).bar_ends(3600)
    rows: dict[str, list[float]] = {"open": [], "high": [], "low": [], "close": []}
    for index, _ in enumerate(ends):
        if index == 9:
            prices = (ENTRY, TOUCH, ENTRY, LOST)
        elif index == len(ends) - 1:
            prices = (LOST, last_close, LOST, last_close)
        elif index > 9:
            prices = (LOST, LOST, LOST, LOST)
        else:
            prices = (ENTRY, ENTRY, ENTRY, ENTRY)
        for name, value in zip(("open", "high", "low", "close"), prices, strict=True):
            rows[name].append(value)
    bars = pl.DataFrame(
        {
            "event_time": ends,
            "open": rows["open"],
            "high": rows["high"],
            "low": rows["low"],
            "close": rows["close"],
            "contract": ["ESH4"] * len(ends),
        }
    )
    targets = pl.DataFrame(
        {"event_time": bars["event_time"], "target": pl.Series([1] * len(ends), dtype=pl.Int64)}
    )
    return bars, targets


def _attempt(evaluated: str, *, last_close: float):
    bars, targets = _bars(last_close=last_close)
    return simulate_attempt(
        bars=bars,
        targets=targets,
        rolls=pl.DataFrame(schema=ROLL_SCHEMA),
        spec=futures_spec("ES"),
        costs=CostSchedule(commission=Decimal("2.00")),
        ruleset=_ruleset(evaluated),
        start_trade_date=DAY,
        max_horizon_days=5,
        calendar=CALENDAR,
        execution_mode="manual",
    )


def _pass_bars(result: object) -> list[int]:
    """The bar indices at which the attempt recorded a pass (the overlay's own coordinates)."""
    return [event.bar for event in result.overlay_events if event.kind == "pass"]  # type: ignore[attr-defined]


def test_an_eod_target_touched_intraday_and_lost_by_the_close_does_not_pass() -> None:
    """The session's last bar closes at +5 points (+$250): the CLOSED figure is short of $1,000.

    The mid-session touch of 4,830.00 is +$1,496 net, enough for the target, but the rule is
    ``evaluated: eod``: it is tested only at the rule-day's last scheduled bar, whose close is
    4,805.00. The attempt is therefore unresolved at the end of the data -- ``censored``, never a
    pass -- and no pass event is recorded at the touch.
    """
    result = _attempt("eod", last_close=LOST)
    assert result.outcome == "censored"
    assert result.mechanical_outcome == "censored"
    assert [event.kind for event in result.overlay_events if event.kind == "pass"] == []
    assert result.days_to_pass_trading is None
    assert result.phase_outcomes[0].outcome == "censored"


def test_the_same_target_declared_intraday_passes_on_the_touch() -> None:
    """``evaluated: intraday`` tests every bar's close and counts the bar's favourable extreme.

    The same bars, the same target, the same account: the tenth bar's high of 4,830.00 is +$1,496
    net, so the attempt passes AT THAT BAR -- one hour before the close that would have lost it --
    and the pass instant is that bar's own end, not the session's.
    """
    result = _attempt("intraday", last_close=LOST)
    assert result.outcome == "pass"
    ends = CALENDAR.session(DAY).bar_ends(3600)
    # the touch bar (index 9) is where it passes, and that bar is NOT the session's last one
    assert _pass_bars(result) == [9]
    assert len(ends) - 1 > 9
    assert result.days_to_pass_trading == 1
    assert result.days_to_pass_calendar == 0


def test_an_eod_target_does_pass_at_the_last_bar_when_the_close_reaches_it() -> None:
    """The control: with the session closing at 4,830.00 the end-of-day figure does reach $1,000.

    So the earlier case is a refusal to pass on an intraday figure, not a target the engine cannot
    honour: the pass happens at the rule-day's LAST bar, and its instant is the scheduled close.
    """
    result = _attempt("eod", last_close=TOUCH)
    assert result.outcome == "pass"
    ends = CALENDAR.session(DAY).bar_ends(3600)
    # the last bar of the session IS the rule-day's last scheduled bar (its end is the close)
    assert ends[-1] == CALENDAR.session(DAY).close_ns
    assert _pass_bars(result) == [len(ends) - 1]
    assert result.phase_outcomes[0].last_bar == len(ends) - 1
    assert result.days_to_pass_trading == 1


def test_the_pass_condition_split_is_derived_from_the_rules() -> None:
    """The overlay holds the two buckets the declaration implies, and only intraday early."""
    from crucible.prop import rules as rl
    from crucible.prop.overlay import PropAccountOverlay

    eod = _ruleset("eod")
    overlay = PropAccountOverlay(
        ruleset=eod,
        phase=eod.phases[0],
        root="ES",
        tick_micro=12_500_000,
        session_close_ns=[0],
        start_day=DAY,
    )
    assert [e.rule_id for e in overlay.eod_pass_conditions] == ["target"]
    assert overlay.intraday_pass_conditions == []
    assert rl.pass_frequency(eod.phases[0].pass_conditions[0]) == "eod"

    intraday = _ruleset("intraday")
    overlay = PropAccountOverlay(
        ruleset=intraday,
        phase=intraday.phases[0],
        root="ES",
        tick_micro=12_500_000,
        session_close_ns=[0],
        start_day=DAY,
    )
    assert overlay.eod_pass_conditions == []
    assert [e.rule_id for e in overlay.intraday_pass_conditions] == ["target"]
    assert rl.pass_frequency(intraday.phases[0].pass_conditions[0]) == "intraday"
    # a pass condition that declares no frequency (min_trading_days) is not held back to the close
    assert rl.pass_frequency(object()) == "intraday"
