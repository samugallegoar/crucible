"""Schema version 2 and the C7b vocabulary (ADR-0107 sections 7-13), hand-computed.

Every money number below is written out as arithmetic. The data is synthetic: "SyntheticFirm A",
example.invalid URLs and ``synthetic: true`` on every attribution.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import numpy as np
import polars as pl
import pytest
import yaml
from pydantic import ValidationError

from crucible.core.errors import ConfigurationError
from crucible.data.cme_session_table import cme_session_table
from crucible.data.cme_sessions import SessionCalendar
from crucible.data.contracts import ROLL_SCHEMA
from crucible.data.futures_specs import futures_spec
from crucible.execution.futures_sim import CostSchedule
from crucible.execution.interfaces import AccountMarks
from crucible.prop import rules as rl
from crucible.prop.attempt import estimate_status, practical_eligibility, simulate_attempt
from crucible.prop.coverage import evaluation_status, rule_coverage
from crucible.prop.lifecycle import EOD_ORDER, Lifecycle
from crucible.prop.news import (
    NewsEvent,
    coverage_covers,
    events_in_window,
    unknown_time_gaps,
)
from crucible.prop.overlay import PropAccountOverlay
from crucible.prop.ruleset import (
    Attribution,
    PropRuleset,
    load_ruleset,
    write_verification_sidecar,
)
from crucible.prop.scenarios import scenarios

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


FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "prop"
TICK = 12_500_000
_NS = 1_000_000_000
_MIN = 60 * _NS
CALENDAR = SessionCalendar(cme_session_table(), "ES")


def _source(**extra: object) -> Attribution:
    data: dict[str, object] = {
        "url": "https://example.invalid/synthetic-rules",
        "quote": "Synthetic rule value invented for a test, not a real firm's rule",
        "snapshot_sha256": "0" * 64,
        "retrieved_at": dt.datetime(2024, 1, 1, tzinfo=dt.UTC),
        "synthetic": True,
    }
    data.update(extra)
    return Attribution.model_validate(data)


def _declare(rule: dict[str, object]) -> None:
    """Fill the explicit declarations a hand-built test rule relies on (never a model default)."""
    kind = rule.get("kind")
    if kind == "profit_target":
        rule.setdefault("comparison", ">=")
        rule.setdefault("action", "promote_phase")
    elif kind == "static_drawdown":
        rule.setdefault("basis", "equity")
        rule.setdefault("comparison", "<=")
        rule.setdefault("action", "fail")
    elif kind == "trailing_drawdown":
        rule.setdefault("basis", "equity")
        rule.setdefault("hwm_basis", rule["basis"])
        rule.setdefault("comparison", "<=")
        rule.setdefault("action", "fail")
        lock = rule.get("lock")
        if isinstance(lock, dict):
            lock.setdefault("on", ["hwm"])
    elif kind == "daily_loss":
        rule.setdefault("basis", "equity")
        rule.setdefault("comparison", "<=")
        rule.setdefault("action", "soft_lock_until_reset")
    elif kind == "max_contracts":
        rule.setdefault("comparison", "<=")
        rule.setdefault("action", "clip")
    elif kind == "scaling_plan":
        rule.setdefault("evaluated", "eod")
        rule.setdefault("basis", "equity")
        rule.setdefault("comparison", "<=")
        rule.setdefault("action", "clip")
    elif kind == "flat_by":
        rule.setdefault("comparison", ">=")
        rule.setdefault("action", "auto_liquidate")
    elif kind == "min_trading_days":
        rule.setdefault("unit", "trading_days")
        rule.setdefault("day_counts_if", {"min_trades": 1})
        rule.setdefault("comparison", ">=")
        rule.setdefault("action", "promote_phase")
    elif kind == "consistency":
        rule.setdefault("max_day_share", "0.5")
        rule.setdefault("measure", "best_day_profit/total_profit")
        rule.setdefault("applies_to", "pass")
        rule.setdefault("window", "all_time")
        rule.setdefault("comparison", "<=")
        rule.setdefault(
            "action", "block_payout" if rule["applies_to"] == "payout" else "promote_phase"
        )
    elif kind == "payout":
        rule.setdefault("window", "all_time")
        rule.setdefault("comparison", ">=")
        rule.setdefault("action", "withdraw")
        rule.setdefault("threshold_after_payout", "unchanged")
    elif kind == "time_limit":
        rule.setdefault(
            "unit", "calendar_days" if rule.get("max_calendar_days") else "trading_days"
        )
        rule.setdefault("comparison", ">=")
        rule.setdefault("action", "timeout")
    elif kind == "fee":
        rule.setdefault("comparison", ">=")
        rule.setdefault("action", "charge")
    elif kind == "daily_profit_cap":
        rule.setdefault("comparison", ">=")
    elif kind == "inactivity":
        rule.setdefault("observed", "eod")
        rule.setdefault("comparison", ">")
        rule.setdefault("action", "fail")
    elif kind == "news_restriction":
        rule.setdefault("effect", "block")
        rule.setdefault("comparison", ">=")
    elif kind == "compliance":
        rule.setdefault("comparison", ">=")
        rule.setdefault("action", "block")


def _ruleset(
    rules: list[dict[str, object]],
    *,
    pass_conditions: list[dict[str, object]] | None = None,
    fees: list[dict[str, object]] | None = None,
    commissions: dict[str, object] | None = None,
    conflicts: list[dict[str, object]] | None = None,
) -> PropRuleset:
    source = _source().model_dump(mode="json")
    for rule in rules + (pass_conditions or []) + (fees or []):
        _declare(rule)
        rule.setdefault("source", source)
        rule.setdefault("evidence", "official_quote")
    raw: dict[str, object] = {
        "schema_version": 2,
        "ruleset_id": "synthetic-v2",
        "version": 1,
        "firm": "SyntheticFirm A",
        "program": "Synthetic Evaluation",
        "account_size_usd": "50000",
        "as_of": "2024-01-01",
        "effective_from": "2024-01-01",
        "instruments": [{"root": "ES", "contract_weight": "1"}],
        "reset": {"time": "17:00:00", "tz": "America/Chicago"},
        "commissions": commissions
        or {
            "status": "known",
            "components": _COMPONENTS_ALL_IN,
            "per_side_usd": {"ES": "2.00"},
            "platform": None,
            "source": source,
        },
        "conflicts": conflicts or [],
        "phases": [
            {
                "phase_id": "evaluation",
                "kind": "evaluation",
                "starting_balance_usd": "50000",
                "rules": rules,
                "pass_conditions": pass_conditions or [],
                "fees": fees or [],
            }
        ],
    }
    return PropRuleset.model_validate(raw)


def _marks(
    bar: int,
    balance: str,
    *,
    open_ns: int = 0,
    close_ns: int = 0,
    position: int = 0,
    entry_ticks: int = 20_000,
    close_ticks: int = 20_000,
    open_ticks: int = 20_000,
    high_ticks: int = 20_000,
    low_ticks: int = 20_000,
) -> AccountMarks:
    return AccountMarks(
        bar=bar,
        open_time_ns=open_ns,
        close_time_ns=close_ns,
        open_ticks=open_ticks,
        high_ticks=high_ticks,
        low_ticks=low_ticks,
        close_ticks=close_ticks,
        position=position,
        balance_micro=rl.micro(Decimal(balance)),
        cost_basis_ticks=position * entry_ticks,
        tick_micro=TICK,
    )


# --------------------------------------------------------------------------- lifecycle


def test_the_lifecycle_records_every_transition_and_refuses_a_noop() -> None:
    life = Lifecycle.for_phase("evaluation")
    assert life.state == "evaluation"
    life.transition("passed_terminal", time_ns=10, cause="pass")
    assert life.terminal
    assert [(t.from_state, t.to_state) for t in life.transitions] == [
        ("evaluation", "passed_terminal")
    ]
    with pytest.raises(ValueError, match="terminal"):
        life.transition("funded_active", time_ns=11, cause="late")
    with pytest.raises(ValueError, match="no-op"):
        Lifecycle.for_phase("funded").transition("funded_active", time_ns=1, cause="same")


def test_the_end_of_day_order_is_the_one_in_the_adr() -> None:
    assert EOD_ORDER == (
        "eod_marks",
        "threshold_tests",
        "pass_conditions",
        "payout_eligibility",
        "withdrawal",
        "post_payout_transitions",
        "cap_and_consistency_windows_reopen",
    )


def test_a_soft_lock_is_a_lifecycle_state_the_reset_leaves() -> None:
    """A daily loss of 1,000 from a 50,000 start: equity 49,000 touches the threshold."""
    ruleset = _ruleset(
        [
            {
                "kind": "daily_loss",
                "rule_id": "dll",
                "amount_usd": "1000",
                "reference": "day_start_balance",
                "basis": "equity",
                "evaluated": "intraday",
                "reset": {"time": "17:00:00", "tz": "America/Chicago"},
                "action": "soft_lock_until_reset",
            }
        ]
    )
    overlay = PropAccountOverlay(
        ruleset=ruleset,
        phase=ruleset.phases[0],
        root="ES",
        tick_micro=TICK,
        session_close_ns=np.zeros(2, dtype=np.int64),
        start_day=dt.date(2024, 1, 7),
    )
    first = 1_704_758_400 * _NS  # 2024-01-08 17:00 UTC, before the 17:00 Chicago reset
    book = _marks(
        0,
        "49979.25",
        open_ns=first,
        close_ns=first + _MIN,
        position=1,
        low_ticks=19_600,
        close_ticks=19_600,
    )
    overlay.begin_bar(0, book)
    overlay.breach_filled(0, book, 19_801, "dll", False)
    assert overlay.lifecycle.state == "funded_locked_until_reset"
    next_day = first + 30 * 60 * _MIN
    overlay.begin_bar(1, replace(book, bar=1, open_time_ns=next_day))
    assert overlay.lifecycle.state == "evaluation"
    assert [t.to_state for t in overlay.lifecycle.transitions] == [
        "funded_locked_until_reset",
        "evaluation",
    ]


# ----------------------------------------------------------------------- payouts v2


def _day(pnl: str, trades: int = 1) -> rl.DayStats:
    stats = rl.DayStats(50_000_000_000)
    stats.close_balance = 50_000_000_000 + rl.micro(Decimal(pnl))
    stats.trades = trades
    return stats


def test_payout_caps_by_payout_number_and_share_of_withdrawable() -> None:
    """Balance 56,000.00, buffer 1,000.00 -> withdrawable 5,000.00.

    Payout #1 cap [1,000, 2,000]: 1,000 binds; #2 cap 2,000 binds; #3 keeps the last cap 2,000.
    A 25% share of withdrawable (5,000 * 0.25 = 1,250) would bind before a 2,000 cap.
    """
    ruleset = _ruleset(
        [
            {
                "kind": "payout",
                "rule_id": "pay",
                "buffer_usd": "1000",
                "split": "1",
                "min_usd": "100",
                "max_usd": "unlimited",
                "max_usd_by_payout": ["1000", "2000"],
                "max_share_of_withdrawable": "0.25",
            }
        ]
    )
    evaluator = rl.Payout(ruleset.phases[0].rules[0], 50_000_000_000, Decimal(1))
    book = _marks(0, "56000")
    days = {1: _day("6000")}
    decision = evaluator.decision(
        book, days, trading_days=1, calendar_days=1, consistency_holds=True
    )
    assert decision is not None
    # min(1,000 cap, 25% * 5,000 = 1,250) = 1,000.00
    assert decision.gross == 1_000_000_000
    evaluator.apply(decision, day=1, trading_days=1, balance=55_000_000_000)
    book2 = _marks(1, "56000")
    second = evaluator.decision(
        book2, days, trading_days=2, calendar_days=2, consistency_holds=True
    )
    assert second is not None
    # min(2,000 cap, 1,250) = 1,250.00
    assert second.gross == 1_250_000_000


def test_payout_since_last_window_and_cumulative_cycle_goal() -> None:
    """After a first withdrawal, only days after it count, and profit since it must reach 500.

    Balance 51,500.00, base 50,000.00, buffer 1,000.00 -> withdrawable 500.00.
    Days after payout day 1: day 2 has +200, day 3 has +500 -> profitable days 2, profit since
    the payout balance 50,000 is 1,500 >= the 500 cycle goal; gross 500.
    """
    ruleset = _ruleset(
        [
            {
                "kind": "payout",
                "rule_id": "pay",
                "buffer_usd": "1000",
                "split": "0.8",
                "min_usd": "100",
                "max_usd": "2000",
                "min_profitable_days": 2,
                "min_day_profit_usd": "100",
                "window": "since_last_payout",
                "cycle_goal_usd": "500",
            }
        ]
    )
    evaluator = rl.Payout(ruleset.phases[0].rules[0], 50_000_000_000, Decimal(1))
    evaluator.count = 1
    evaluator.last_payout_day = 1
    evaluator.last_payout_trading_day = 1
    evaluator.last_payout_balance = 50_000_000_000
    days = {
        1: _day("900"),  # before the payout: never counts in the window
        2: _day("200"),
        3: _day("500"),
    }
    decision = evaluator.decision(
        _marks(3, "51500"),
        days,
        trading_days=3,
        calendar_days=5,
        consistency_holds=True,
    )
    assert decision is not None
    assert decision.gross == 500_000_000  # withdrawable = 51,500 - (50,000 + 1,000)
    assert decision.net == 400_000_000  # 0.8 * 500


def test_first_payout_needs_the_declared_calendar_days() -> None:
    ruleset = _ruleset(
        [
            {
                "kind": "payout",
                "rule_id": "pay",
                "buffer_usd": "0",
                "split": "1",
                "min_usd": "100",
                "max_usd": "1000",
                "first_payout_after_calendar_days": 14,
            }
        ]
    )
    evaluator = rl.Payout(ruleset.phases[0].rules[0], 50_000_000_000, Decimal(1))
    early = evaluator.decision(
        _marks(0, "52000"),
        {1: _day("2000")},
        trading_days=1,
        calendar_days=13,
        consistency_holds=True,
    )
    assert early is None
    later = evaluator.decision(
        _marks(0, "52000"),
        {1: _day("2000")},
        trading_days=1,
        calendar_days=14,
        consistency_holds=True,
    )
    assert later is not None
    assert later.gross == 1_000_000_000


def test_trailing_lock_on_the_first_payout_freezes_the_threshold() -> None:
    """Trailing 2,000 with a lock on the first payout at 49,000; HWM starts at 50,000."""
    ruleset = _ruleset(
        [
            {
                "kind": "trailing_drawdown",
                "rule_id": "trail",
                "amount_usd": "2000",
                "mode": "eod",
                "evaluated": "intraday",
                "lock": {"on": ["first_payout"], "locked_threshold_usd": "49000"},
            }
        ]
    )
    evaluator = rl.TrailingDrawdown(ruleset.phases[0].rules[0], 50_000_000_000, Decimal(1))
    assert evaluator.threshold == 48_000_000_000
    evaluator.on_first_payout()
    assert evaluator.locked == 49_000_000_000
    assert evaluator.threshold == 49_000_000_000


def test_the_hwm_basis_is_separate_from_the_tested_basis() -> None:
    """A balance-basis HWM and an equity-basis test: the mark uses the close balance.

    Start 50,000, amount 2,000. A 1-lot long entered at 5,000 with close balance 50,000 marks the
    HWM from the balance (50,000), so the threshold is 48,000 and the breach price is 4,960.00.
    If the HWM were marked from equity at a 5,010 close (50,500) the threshold would be 48,500.
    """
    ruleset = _ruleset(
        [
            {
                "kind": "trailing_drawdown",
                "rule_id": "trail",
                "amount_usd": "2000",
                "mode": "eod",
                "evaluated": "intraday",
                "basis": "equity",
                "hwm_basis": "balance",
            }
        ]
    )
    evaluator = rl.TrailingDrawdown(ruleset.phases[0].rules[0], 50_000_000_000, Decimal(1))
    book = _marks(
        0,
        "50000",
        position=1,
        entry_ticks=20_000,
        close_ticks=20_040,
    )
    assert [b.price_ticks for b in evaluator.eod(book)] == []  # EOD only raises the mark
    assert evaluator.hwm == 50_000_000_000
    assert evaluator.threshold == 48_000_000_000


# ----------------------------------------------------------------- daily loss v2


def test_daily_loss_by_balance_tier_uses_the_largest_tier_at_or_below_the_balance() -> None:
    """Tiers 50,000 -> 1,000 and 100,000 -> 2,000: at 100,000 the amount is 2,000."""
    ruleset = _ruleset(
        [
            {
                "kind": "daily_loss",
                "rule_id": "dll",
                "amount_by_balance_tier": [
                    {"min_balance_usd": "50000", "amount_usd": "1000"},
                    {"min_balance_usd": "100000", "amount_usd": "2000"},
                ],
                "reference": "day_start_balance",
                "basis": "equity",
                "evaluated": "intraday",
                "reset": {"time": "17:00:00", "tz": "America/Chicago"},
            }
        ]
    )
    evaluator = rl.DailyLoss(ruleset.phases[0].rules[0], 50_000_000_000, Decimal(1))
    evaluator.new_day(1, _marks(0, "50000"))
    assert evaluator.amount == 1_000_000_000
    evaluator.new_day(2, _marks(0, "100000"))
    assert evaluator.amount == 2_000_000_000


def test_a_ratcheting_daily_loss_follows_peak_profit_and_never_decreases() -> None:
    """60% of peak profit: peak 1,000 -> 600; then a drawdown to a 0 peak keeps 600."""
    ruleset = _ruleset(
        [
            {
                "kind": "daily_loss",
                "rule_id": "dll",
                "pct_of_peak_profit": "60",
                "non_decreasing": True,
                "reference": "day_start_balance",
                "basis": "equity",
                "evaluated": "intraday",
                "reset": {"time": "17:00:00", "tz": "America/Chicago"},
            }
        ]
    )
    evaluator = rl.DailyLoss(ruleset.phases[0].rules[0], 50_000_000_000, Decimal(1))
    evaluator.new_day(1, _marks(0, "50000"))
    flat_high = _marks(0, "50000", close_ticks=20_000)
    del flat_high
    # equity = balance + (p*1 - 0) * 12.5, so a 80-tick rise is +1,000.00
    rich = _marks(0, "50000", position=1, entry_ticks=0, close_ticks=80)
    evaluator.favorable(rich, 80)
    assert evaluator.amount == 600_000_000  # 0.6 * 1,000.00
    poor = _marks(0, "50000", position=1, entry_ticks=0, close_ticks=0)
    evaluator.favorable(poor, 0)
    assert evaluator.amount == 600_000_000


# -------------------------------------------------------------- other vocabulary


def test_a_daily_profit_cap_reports_the_excess_over_the_days_start() -> None:
    ruleset = _ruleset(
        [
            {
                "kind": "daily_profit_cap",
                "rule_id": "cap",
                "amount_usd": "1000",
                "action": "forfeit_excess",
                "basis": "balance",
                "evaluated": "eod",
            }
        ]
    )
    evaluator = rl.DailyProfitCap(ruleset.phases[0].rules[0], 50_000_000_000, Decimal(1))
    book = _marks(0, "51250")
    assert evaluator.excess(book, 50_000_000_000) == 250_000_000


def test_inactivity_counts_the_gap_and_resets_on_a_fill() -> None:
    ruleset = _ruleset(
        [
            {
                "kind": "inactivity",
                "rule_id": "idle",
                "max_gap": 2,
                "unit": "trading_days",
            }
        ]
    )
    evaluator = rl.Inactivity(ruleset.phases[0].rules[0], 50_000_000_000, Decimal(1))
    day = dt.date(2024, 1, 8)
    assert evaluator.on_new_day(1, day) is False
    assert evaluator.on_new_day(2, day) is False
    assert evaluator.on_new_day(3, day) is True  # 3 > 2
    evaluator.note_trade(4, day)
    assert evaluator.on_new_day(5, day) is False


def test_a_scaling_plan_can_reject_an_order_above_the_tier() -> None:
    ruleset = _ruleset(
        [
            {
                "kind": "scaling_plan",
                "rule_id": "scale",
                "steps": [{"min_profit_usd": "0", "max_contracts": "1"}],
                "action": "reject",
            }
        ]
    )
    evaluator = rl.ScalingPlan(ruleset.phases[0].rules[0], 50_000_000_000, Decimal(1))
    assert evaluator.on_excess() == "reject"


def test_flat_by_relative_to_the_session_end_uses_the_calendar_early_close() -> None:
    """2024-07-03 is a CME early close; 60 minutes before it is 12:00 Chicago, not 16:00."""
    session = CALENDAR.session(dt.date(2024, 7, 3))
    ruleset = _ruleset(
        [
            {
                "kind": "flat_by",
                "rule_id": "flat",
                "minutes_before_session_end": 60,
                "action": "auto_liquidate",
            }
        ]
    )
    evaluator = rl.FlatBy(ruleset.phases[0].rules[0], 50_000_000_000, Decimal(1))
    window = evaluator.flat_and_reopen(0, 0, session.close_ns)
    assert window is not None
    flat, _ = window
    assert flat == session.close_ns - 60 * _MIN
    # the early close is well before the regular 16:00 Chicago close
    assert session.close_ns < CALENDAR.session(dt.date(2024, 7, 5)).close_ns


def test_monthly_and_reset_fees_are_counted_in_the_attempt(monkeypatch: pytest.MonkeyPatch) -> None:
    """A fee for every STARTED calendar month: Jan 8 -> Mar 9 spans three months (3 * 100)."""
    from crucible.prop import attempt as attempt_module

    ruleset = _ruleset(
        [],
        fees=[
            {
                "kind": "fee",
                "rule_id": "evaluation",
                "fee_kind": "evaluation",
                "amount_usd": "50",
                "when": "at_start",
            },
            {
                "kind": "fee",
                "rule_id": "monthly",
                "fee_kind": "monthly",
                "amount_usd": "100",
                "when": "per_month",
            },
            {
                "kind": "fee",
                "rule_id": "reset",
                "fee_kind": "reset",
                "amount_usd": "75",
                "when": "on_reset",
            },
        ],
    )
    fees = attempt_module._fees(
        ruleset, dt.date(2024, 1, 8), dt.date(2024, 3, 9), passed=True, resets_purchased=2
    )
    assert fees.evaluation_usd == 50
    assert fees.monthly_usd == 300  # Jan, Feb, Mar: three started months * 100
    assert fees.reset_usd == 150  # 2 resets * 75
    assert fees.total_usd == 500


# ------------------------------------------------------------------ news


def test_news_windows_block_entries_and_flatten_by_scope() -> None:
    """A 5-minute pre / 5-minute post window around an FOMC event at 18:00 UTC.

    A bar at 17:58 UTC is inside the pre-window for ``new_entries`` (a new position is refused);
    a ``holding`` rule flattens at that bar; ``all_trading`` refuses even a reduction.
    """
    event = NewsEvent(
        "fomc-1", "FOMC", 1_704_758_400 * _NS, time_known=True
    )  # 2024-01-08T18:00:00Z
    ruleset = _ruleset(
        [
            {
                "kind": "news_restriction",
                "rule_id": "news",
                "event_types": ["FOMC"],
                "pre_minutes": 5,
                "post_minutes": 5,
                "scope": "holding",
                "flatten": "before_window",
                "action": "flatten_and_block",
            }
        ]
    )
    overlay = PropAccountOverlay(
        ruleset=ruleset,
        phase=ruleset.phases[0],
        root="ES",
        tick_micro=TICK,
        session_close_ns=np.zeros(1, dtype=np.int64),
        start_day=dt.date(2024, 1, 7),
        news_events=(event,),
        news_covered=True,
    )
    inside = _marks(
        0,
        "50000",
        open_ns=event.scheduled_ns - 2 * _MIN,
        close_ns=event.scheduled_ns - _MIN,
        position=1,
    )
    action = overlay.forced_flat(0, inside)
    assert action is not None
    assert action.kind == "liquidate"
    assert overlay.admit(0, inside, 2) == 1  # no increase while the window is active


def test_a_news_rule_without_calendar_coverage_is_not_modeled() -> None:
    ruleset = _ruleset(
        [
            {
                "kind": "news_restriction",
                "rule_id": "news",
                "event_types": ["FOMC"],
                "pre_minutes": 5,
                "post_minutes": 5,
                "scope": "new_entries",
                "flatten": "none",
                "action": "block_entries",
            }
        ]
    )
    rows = rule_coverage(ruleset, news_covered=False)
    assert evaluation_status(rows) == "conditional_on_modeled_rules"
    assert [row.modeled for row in rows] == [False]
    assert coverage_covers(None, 0, 1) is False
    status, reasons = estimate_status(
        coverage=rows,
        verified=True,
        commissions_known=True,
        cost_assumption=None,
        news_covered=False,
    )
    assert status == "partial"
    assert any("calendar" in reason for reason in reasons)


# ------------------------------------------------------- compliance, estimate status


def _compliance_ruleset() -> PropRuleset:
    return _ruleset(
        [
            {
                "kind": "compliance",
                "rule_id": "no_bots",
                "restriction": "automated_trading",
                "applies_to_execution": ["automated"],
                "materiality": "critical",
            }
        ],
        pass_conditions=[
            {
                "kind": "profit_target",
                "rule_id": "target",
                "amount_usd": "1000",
                "basis": "balance",
                "evaluated": "eod",
            }
        ],
    )


def test_a_critical_compliance_rule_blocks_an_automated_but_not_a_manual_strategy() -> None:
    ruleset = _compliance_ruleset()
    assert practical_eligibility(ruleset, "automated") == "blocked_by_compliance"
    assert practical_eligibility(ruleset, "manual") == "eligible"


def test_estimate_status_unknown_commissions_unless_a_cost_assumption_is_named() -> None:
    ruleset = _ruleset(
        [],
        commissions={
            "status": "unknown",
            "components": _COMPONENTS_UNKNOWN,
            "platform": None,
            "source": _source().model_dump(mode="json"),
        },
    )
    rows = rule_coverage(ruleset)
    unavailable, reasons = estimate_status(
        coverage=rows,
        verified=True,
        commissions_known=False,
        cost_assumption=None,
        news_covered=None,
    )
    assert unavailable == "unavailable"
    assert any("commissions" in reason for reason in reasons)
    conditional, reasons = estimate_status(
        coverage=rows,
        verified=True,
        commissions_known=False,
        cost_assumption="owner's broker schedule",
        news_covered=None,
    )
    assert conditional == "conditional"
    assert any("cost assumption" in reason for reason in reasons)


# ------------------------------------------------------------------ conflicts


def _conflict_ruleset() -> PropRuleset:
    ruleset = _ruleset(
        [
            {
                "kind": "static_drawdown",
                "rule_id": "dd",
                "amount_usd": "2000",
                "basis": "equity",
                "evaluated": "intraday",
            }
        ]
    )
    raw = ruleset.model_dump(mode="python")
    raw["conflicts"] = [
        {
            "conflict_id": "dd-amount",
            "rule_id": "dd",
            "field": "amount_usd",
            "selected_value": "2000",
            "alternatives": [{"value": "2500", "source": _source().model_dump(mode="json")}],
            "selected_source": _source().model_dump(mode="json"),
            "rationale": "the stricter reading keeps the smaller drawdown",
            "applicability_checked": True,
        }
    ]
    return PropRuleset.model_validate(raw)


def test_each_conflict_alternative_is_a_labelled_sensitivity_scenario() -> None:
    ruleset = _conflict_ruleset()
    generated = scenarios(ruleset)
    assert [item.scenario_id for item in generated] == ["primary", "dd-amount#0"]
    assert generated[0].label == "official"
    assert generated[1].label == "sensitivity"
    assert generated[1].conflict_id == "dd-amount"
    switched = generated[1].ruleset.phases[0].rules[0]
    assert switched.amount_usd == Decimal("2500")  # type: ignore[attr-defined]
    assert generated[0].ruleset.phases[0].rules[0].amount_usd == Decimal("2000")  # type: ignore[attr-defined]


def test_a_conflict_needs_applicability_checked_and_a_different_alternative() -> None:
    ruleset = _conflict_ruleset()
    raw = ruleset.model_dump(mode="python")
    raw["conflicts"][0]["applicability_checked"] = False
    with pytest.raises(ValidationError, match="applicability_checked"):
        PropRuleset.model_validate(raw)
    raw = ruleset.model_dump(mode="python")
    raw["conflicts"][0]["alternatives"][0]["value"] = "2000"
    with pytest.raises(ValidationError, match="contradiction"):
        PropRuleset.model_validate(raw)


# ------------------------------------------------------------------- schema refusals


def test_schema_refusals() -> None:
    base = _ruleset([]).model_dump(mode="python")
    v1 = dict(base, schema_version=1)
    with pytest.raises(ValidationError, match=r"(?i)migrate"):
        PropRuleset.model_validate(v1)
    missing_evaluated = dict(base)
    missing_evaluated["phases"] = [
        {
            "phase_id": "evaluation",
            "kind": "evaluation",
            "starting_balance_usd": "50000",
            "rules": [
                {
                    "kind": "static_drawdown",
                    "rule_id": "dd",
                    "amount_usd": "2000",
                    "source": _source().model_dump(mode="json"),
                }
            ],
        }
    ]
    with pytest.raises(ValidationError):
        PropRuleset.model_validate(missing_evaluated)
    sentinel = dict(base)
    sentinel["phases"] = [
        {
            "phase_id": "funded",
            "kind": "funded",
            "starting_balance_usd": "50000",
            "rules": [
                {
                    "kind": "payout",
                    "rule_id": "pay",
                    "buffer_usd": "0",
                    "split": "1",
                    "min_usd": "100",
                    "max_usd": "1000000",
                    "window": "all_time",
                    "comparison": ">=",
                    "action": "withdraw",
                    "threshold_after_payout": "unchanged",
                    "source": _source().model_dump(mode="json"),
                }
            ],
        }
    ]
    with pytest.raises(ValidationError, match="sentinel"):
        PropRuleset.model_validate(sentinel)
    in_file = dict(base, verification={"status": "verified"})
    with pytest.raises(ValidationError, match="verification"):
        PropRuleset.model_validate(in_file)


# --------------------------------------------------------------- hash and sidecar


def test_the_content_hash_excludes_verification_and_the_sidecar_verifies(
    tmp_path: Path,
) -> None:
    ruleset = _ruleset([])
    path = tmp_path / "synthetic.v1.yaml"
    path.write_text(
        yaml.safe_dump(ruleset.model_dump(mode="json"), sort_keys=False), encoding="utf-8"
    )
    before = load_ruleset(path)
    assert before.verified is False
    sidecar = write_verification_sidecar(
        path, before, confirmed_by="owner", confirmation_note="checked every rule"
    )
    after = load_ruleset(path)
    assert after.ruleset_sha256 == before.ruleset_sha256  # verification is not in the hash
    assert after.verified is True
    assert sidecar.exists()
    # tampering with the content after confirmation leaves it unverified
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    raw["program"] = "Changed After Confirmation"
    path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    assert load_ruleset(path).verified is False


class _TTY:
    def isatty(self) -> bool:
        return True


def test_prop_confirm_refuses_without_a_tty_and_writes_the_sidecar_with_one(
    tmp_path: Path,
) -> None:
    from io import StringIO

    from crucible.prop.confirm import confirm_ruleset

    ruleset = _ruleset([])
    path = tmp_path / "synthetic.v1.yaml"
    path.write_text(
        yaml.safe_dump(ruleset.model_dump(mode="json"), sort_keys=False), encoding="utf-8"
    )
    with pytest.raises(ConfigurationError, match="TTY"):
        confirm_ruleset(path, stdin=StringIO(), stdout=StringIO())
    out = StringIO()
    written = confirm_ruleset(
        path,
        stdin=_TTY(),
        stdout=out,
        reader=lambda prompt: ruleset.ruleset_sha256[:12],
    )
    assert written.exists()
    assert "content hash" in out.getvalue()
    assert load_ruleset(path).verified is True
    with pytest.raises(ConfigurationError, match="already verified"):
        confirm_ruleset(path, stdin=_TTY(), stdout=StringIO(), reader=lambda p: "x")


def test_the_index_lists_every_ruleset_file_and_is_append_only() -> None:
    import json
    import subprocess

    from crucible.prop.index import build_index

    root = Path(__file__).resolve().parents[2]
    document = build_index(root / "rulesets" / "prop")
    by_path = {entry["path"]: entry for entry in document["entries"]}
    files = sorted(
        path.relative_to(root).as_posix()
        for path in (root / "rulesets" / "prop").rglob("*.yaml")
        if not path.name.endswith(".verification.yaml")
    )
    assert sorted(by_path) == files
    try:
        previous = json.loads(
            subprocess.run(
                # the RELEASED lock: what is merged to main is immutable, whatever its verification
                # status; a branch may still correct its own unmerged files in place
                ["git", "show", "origin/main:rulesets/prop/INDEX.json"],
                cwd=root,
                capture_output=True,
                text=True,
                check=True,
            ).stdout
        )
    except subprocess.CalledProcessError:
        previous = None
    if previous is not None:
        for entry in previous["entries"]:
            # a version never disappears from the lock
            current = by_path.get(entry["path"])
            assert current is not None
            assert (current["ruleset_id"], current["version"]) == (
                entry.get("ruleset_id"),
                entry.get("version"),
            )
            # a released version is immutable data, verified or not: a correction is a new version
            if "ruleset_sha256" in entry:
                assert current["ruleset_sha256"] == entry["ruleset_sha256"]


def test_a_payout_group_pays_at_most_once_per_close_and_takes_the_largest_net() -> None:
    """Two paths in one group: caps 1,000 and 1,500 on a 53,000 balance with a 0 buffer.

    withdrawable = 53,000 - 50,000 = 3,000; path A pays min(1,000, 3,000) = 1,000, path B pays
    min(1,500, 3,000) = 1,500, so ``max_eligible`` takes B once and A never pays at that close.
    """
    ruleset = _ruleset(
        [],
        commissions={
            "status": "known",
            "components": _COMPONENTS_ALL_IN,
            "per_side_usd": {"ES": "2.00"},
            "platform": None,
            "source": _source().model_dump(mode="json"),
        },
    )
    raw = ruleset.model_dump(mode="python")
    raw["phases"][0]["kind"] = "funded"
    raw["phases"][0]["rules"] = [
        {
            "kind": "payout",
            "rule_id": "a",
            "buffer_usd": "0",
            "split": "1",
            "min_usd": "100",
            "max_usd": "1000",
            "payout_group": "g1",
            "source": _source().model_dump(mode="json"),
        },
        {
            "kind": "payout",
            "rule_id": "b",
            "buffer_usd": "0",
            "split": "1",
            "min_usd": "100",
            "max_usd": "1500",
            "payout_group": "g1",
            "source": _source().model_dump(mode="json"),
        },
    ]
    for rule in raw["phases"][0]["rules"]:
        _declare(rule)
    grouped = PropRuleset.model_validate(raw)
    open_ns = 1_704_758_400 * _NS
    close_ns = open_ns + _MIN
    overlay = PropAccountOverlay(
        ruleset=grouped,
        phase=grouped.phases[0],
        root="ES",
        tick_micro=TICK,
        session_close_ns=np.array([close_ns], dtype=np.int64),
        start_day=dt.date(2024, 1, 8),
        payout_policy="max_eligible",
    )
    book = _marks(0, "53000", open_ns=open_ns, close_ns=close_ns)
    assert overlay.begin_bar(0, book) is None
    overlay.end_bar(0, book)
    assert [record[3] for record in overlay.payouts] == ["b"]
    assert overlay.withdrawn == 1_500_000_000  # 1,500.00


def test_payout_max_pct_of_balance_caps_the_gross() -> None:
    """10% of a 56,000 balance is 5,600, below the 10,000 cap and the 5,000 withdrawable."""
    ruleset = _ruleset(
        [
            {
                "kind": "payout",
                "rule_id": "pay",
                "buffer_usd": "1000",
                "split": "1",
                "min_usd": "100",
                "max_usd": "10000",
                "max_pct_of_balance": "10",
            }
        ]
    )
    evaluator = rl.Payout(ruleset.phases[0].rules[0], 50_000_000_000, Decimal(1))
    decision = evaluator.decision(
        _marks(0, "56000"),
        {1: _day("6000")},
        trading_days=1,
        calendar_days=1,
        consistency_holds=True,
    )
    assert decision is not None
    # withdrawable = 56,000 - (50,000 + 1,000) = 5,000; 10% of 56,000 = 5,600 -> 5,000 binds
    assert decision.gross == 5_000_000_000


def test_an_event_without_a_known_release_time_never_gets_a_window() -> None:
    """A statement the source dates but does not time (``time_known`` false) is a coverage gap.

    The whole trade date 2024-01-08 is outside news coverage: no window is invented, the attempt
    reports the event id, and a holding rule therefore cannot flatten. Treating it as "no news"
    would be an unrestricted window the source does not support.
    """
    event = NewsEvent("statement-no-time", "FOMC_STATEMENT", 1_704_758_400 * _NS, time_known=False)
    day_start = 1_704_672_000 * _NS  # 2024-01-08T00:00:00Z
    day_end = day_start + 24 * 60 * 60 * _NS
    assert unknown_time_gaps((event,), day_start, day_end) == ("statement-no-time",)
    assert events_in_window((event,), ["FOMC_STATEMENT"], day_start, day_end) == []

    ruleset = _ruleset(
        [
            {
                "kind": "news_restriction",
                "rule_id": "news",
                "event_types": ["FOMC_STATEMENT"],
                "pre_minutes": 5,
                "post_minutes": 5,
                "scope": "holding",
                "flatten": "before_window",
                "action": "flatten_and_block",
            }
        ]
    )
    overlay = PropAccountOverlay(
        ruleset=ruleset,
        phase=ruleset.phases[0],
        root="ES",
        tick_micro=TICK,
        session_close_ns=np.zeros(1, dtype=np.int64),
        start_day=dt.date(2024, 1, 8),
        news_events=(event,),
        news_covered=False,
    )
    book = _marks(0, "50000", position=1)
    assert overlay.forced_flat(0, book) is None
    status, reasons = estimate_status(
        coverage=rule_coverage(ruleset, news_covered=False),
        verified=True,
        commissions_known=True,
        cost_assumption=None,
        news_covered=False,
        news_coverage_gaps=("statement-no-time",),
    )
    assert status == "partial"
    assert any("statement-no-time" in reason for reason in reasons)


def test_a_known_news_window_is_still_enforced_when_another_event_has_no_time() -> None:
    """F2: an unknown-time event gaps only its own date; the timed event's window still blocks.

    The known FOMC event sits at the close of bar 3, so its 1-minute pre-window covers that bar.
    The target asks for 1 contract there and the account is flat, so the entry is refused
    (requested 1, allowed 0); the unknown-time event on the same date changes nothing about the
    timed window, it only makes the estimate partial and is reported by id.
    """
    first = CALENDAR.session(dt.date(2024, 1, 8)).bar_ends(60)
    rows = [
        {
            "event_time": first[index],
            "open": 5000.0,
            "high": 5000.0,
            "low": 5000.0,
            "close": 5000.0,
            "contract": "ESH4",
        }
        for index in range(4)
    ]
    bars = pl.DataFrame(rows)
    targets = pl.DataFrame(
        {
            "event_time": bars["event_time"],
            "target": pl.Series([1, 0, 1, 0], dtype=pl.Int64),
        }
    )
    known = NewsEvent("known-1", "FOMC", int(first[3]), time_known=True)
    unknown = NewsEvent("unknown-1", "FOMC", 1_704_672_000 * _NS, time_known=False)
    ruleset = _ruleset(
        [
            {
                "kind": "news_restriction",
                "rule_id": "news",
                "event_types": ["FOMC"],
                "pre_minutes": 1,
                "post_minutes": 1,
                "scope": "new_entries",
                "flatten": "none",
                "action": "block_entries",
            }
        ]
    )
    result = simulate_attempt(
        bars=bars,
        targets=targets,
        rolls=pl.DataFrame(schema=ROLL_SCHEMA),
        spec=futures_spec("ES"),
        costs=CostSchedule(commission=Decimal("2.00")),
        ruleset=ruleset,
        start_trade_date=dt.date(2024, 1, 8),
        max_horizon_days=5,
        calendar=CALENDAR,
        execution_mode="manual",
        news_events=(known, unknown),
        news_coverage=((0, 2**62),),
    )
    assert result.news_coverage_gaps == ("unknown-1",)
    assert result.estimate_status == "partial"
    blocked = [
        event for event in result.overlay_events if event.kind == "resize" and event.bar == 3
    ]
    assert blocked
    assert (blocked[0].requested, blocked[0].allowed) == (1, 0)
