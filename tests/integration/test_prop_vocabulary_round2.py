"""The C7b vocabulary, round 2: the gaps the firm migration found (ADR-0107 sections 7-13).

Nine additions, one hand-computed acceptance test each. Every money number below is written out as
arithmetic (micro-dollars: 1 USD = 1,000,000), the data is synthetic ("SyntheticFirm A",
example.invalid URLs, ``synthetic: true`` on every attribution) and the ES tick is 0.25 = $12.50.

1. ``payout.max_usd: unknown`` pays what the other terms allow and labels the payout
   ``upper_bound`` (a partial cash statistic, outcome unchanged).
2. ``lock.on: [hwm, first_payout]`` locks at the FIRST trigger that fires.
3. ``news_restriction.effect: contract_cap`` clips the size inside the window only, and an event
   type the calendar does not carry makes the rule ``not_modeled`` for the attempt.
4. ``activity_requirement`` fails the first full rolling window short of its qualifying days.
5. ``payout.min_new_profit_share_of_request`` lowers the request.
6. ``consistency`` numerator and denominator windows declared separately.
7. A conflict alternative of ``absent`` removes the rule from that scenario.
8. ``commissions.components`` with a ``ComponentFeeSource``: per-component costs.
9. A session-relative ``flat_by`` follows the CME calendar's early close.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from pathlib import Path

import numpy as np
import polars as pl
import pytest
from pydantic import ValidationError

from crucible.core.errors import ConfigurationError
from crucible.data.cme_session_table import cme_session_table
from crucible.data.cme_sessions import SessionCalendar
from crucible.data.contracts import ROLL_SCHEMA
from crucible.data.exchange_fees import ParticipantProfile
from crucible.data.futures_specs import futures_spec
from crucible.data.store import ParquetDataStore
from crucible.execution.futures_sim import CostSchedule
from crucible.execution.interfaces import AccountMarks
from crucible.prop import rules as rl
from crucible.prop.attempt import (
    PAYOUT_CAP_UNKNOWN,
    _commissions_for,
    cash_estimate,
    estimate_status,
    simulate_attempt,
)
from crucible.prop.costs import (
    ComponentFeeRow,
    ComponentFeeTable,
    store_component_fees,
)
from crucible.prop.coverage import RuleCoverageRow, rule_coverage
from crucible.prop.news import NewsEvent
from crucible.prop.overlay import PropAccountOverlay
from crucible.prop.ruleset import Attribution, PropRuleset, threshold_level
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


TICK = 12_500_000
_NS = 1_000_000_000
_MIN = 60 * _NS
CALENDAR = SessionCalendar(cme_session_table(), "ES")


def _source() -> Attribution:
    return Attribution(
        url="https://example.invalid/synthetic-rules",
        quote="Synthetic rule value invented for a test, not a real firm's rule",
        snapshot_sha256="0" * 64,
        retrieved_at=dt.datetime(2024, 1, 1, tzinfo=dt.UTC),
        synthetic=True,
    )


def _ruleset(
    rules: list[dict[str, object]],
    *,
    pass_conditions: list[dict[str, object]] | None = None,
    kind: str = "evaluation",
    commissions: dict[str, object] | None = None,
    conflicts: list[dict[str, object]] | None = None,
) -> PropRuleset:
    source = _source().model_dump(mode="json")
    for rule in rules + (pass_conditions or []):
        rule.setdefault("source", source)
        rule.setdefault("evidence", "official_quote")
    raw: dict[str, object] = {
        "schema_version": 2,
        "ruleset_id": "synthetic-round-2",
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
                "phase_id": kind,
                "kind": kind,
                "starting_balance_usd": "50000",
                "rules": rules,
                "pass_conditions": pass_conditions or [],
                "fees": [],
            }
        ],
    }
    return PropRuleset.model_validate(raw)


def _marks(
    balance: str,
    *,
    bar: int = 0,
    open_ns: int = 0,
    close_ns: int = 0,
    position: int = 0,
    close_ticks: int = 20_000,
    entry_ticks: int = 20_000,
) -> AccountMarks:
    return AccountMarks(
        bar=bar,
        open_time_ns=open_ns,
        close_time_ns=close_ns,
        open_ticks=close_ticks,
        high_ticks=close_ticks,
        low_ticks=close_ticks,
        close_ticks=close_ticks,
        position=position,
        balance_micro=rl.micro(Decimal(balance)),
        cost_basis_ticks=position * entry_ticks,
        tick_micro=TICK,
    )


def _bars(
    prices: list[float], day: dt.date = dt.date(2024, 1, 8)
) -> tuple[pl.DataFrame, pl.DataFrame]:
    """One 60-minute bar per price inside the trade date's session, with a flat target."""
    ends = CALENDAR.session(day).bar_ends(3600)
    rows = {
        "event_time": [ends[index] for index in range(len(prices))],
        "open": prices,
        "high": prices,
        "low": prices,
        "close": prices,
        "contract": ["ESH4"] * len(prices),
    }
    bars = pl.DataFrame(rows)
    targets = pl.DataFrame(
        {
            "event_time": bars["event_time"],
            "target": pl.Series([1] + [1] * (len(prices) - 1), dtype=pl.Int64),
        }
    )
    return bars, targets


def _attempt(
    ruleset: PropRuleset, prices: list[float], *, day: dt.date = dt.date(2024, 1, 8), **kw: object
):
    bars, targets = _bars(prices, day)
    return simulate_attempt(
        bars=bars,
        targets=targets,
        rolls=pl.DataFrame(schema=ROLL_SCHEMA),
        spec=futures_spec("ES"),
        costs=CostSchedule(commission=Decimal("2.00")),
        ruleset=ruleset,
        start_trade_date=day,
        max_horizon_days=5,
        calendar=CALENDAR,
        execution_mode="manual",
        **kw,  # type: ignore[arg-type]
    )


# ------------------------------------------------------------------ 1. an unknown payout cap

_PAYOUT_UNKNOWN = {
    "kind": "payout",
    "rule_id": "pay",
    "buffer_usd": "0",
    "split": "0.8",
    "min_usd": "100",
    "max_usd": "unknown",
    "window": "all_time",
    "comparison": ">=",
    "action": "withdraw",
    "threshold_after_payout": "unchanged",
}


def test_an_unknown_payout_cap_pays_what_the_other_terms_allow_and_says_upper_bound() -> None:
    """A 53,000 balance from a 50,000 start with no buffer is 3,000 withdrawable.

    The cap is unknown, so it does not bind: gross = min(withdrawable 3,000, no other cap) =
    3,000.00, net = 0.8 * 3,000 = 2,400.00, and the record says ``upper_bound`` because a cap the
    sources do not give makes that the MOST the account can be paid. The same ruleset with a
    100,000 cap pays the same 3,000.00 / 2,400.00 and says ``exact``: the money is unchanged, only
    the label is.
    """
    close_ns = int(dt.datetime(2024, 1, 8, 22, 0, tzinfo=dt.UTC).timestamp()) * _NS

    def payout_bound(max_usd: str) -> tuple[list[tuple[int, int, int, str]], list[str]]:
        ruleset = _ruleset([dict(_PAYOUT_UNKNOWN, max_usd=max_usd)], kind="funded")
        overlay = PropAccountOverlay(
            ruleset=ruleset,
            phase=ruleset.phases[0],
            root="ES",
            tick_micro=TICK,
            session_close_ns=np.array([close_ns], dtype=np.int64),
            start_day=dt.date(2024, 1, 8),
            payout_policy="max_eligible",
        )
        book = _marks("53000", open_ns=close_ns - 60 * _MIN, close_ns=close_ns)
        assert overlay.begin_bar(0, book) is None
        overlay.end_bar(0, book)
        assert overlay.outcome == "running"  # a payout never changes the outcome
        return overlay.payouts, overlay.payout_bounds

    payouts, bounds = payout_bound("unknown")
    assert payouts == [(close_ns, 3_000_000_000, 2_400_000_000, "pay")]
    assert bounds == ["upper_bound"]
    exact_payouts, exact_bounds = payout_bound("100000")
    assert exact_payouts == payouts
    assert exact_bounds == ["exact"]

    rows: tuple[RuleCoverageRow, ...] = rule_coverage(_ruleset([_PAYOUT_UNKNOWN]))
    status, reasons = estimate_status(
        coverage=rows,
        verified=True,
        commissions_known=True,
        cost_assumption=None,
        news_covered=None,
        payout_cap_unknown=True,
    )
    assert status == "partial"
    assert PAYOUT_CAP_UNKNOWN in reasons
    assert cash_estimate(
        payouts_modeled=True,
        payout_cap_unknown=True,
        cost_status="complete",
        cost_assumption=None,
    ) == ("upper_bound", (PAYOUT_CAP_UNKNOWN,))


def test_an_unknown_payout_cap_leaves_the_mechanical_outcome_unchanged() -> None:
    """Prices 5,000.0 -> 5,030.0 pass a +100 target in both rulesets: only the label differs."""
    pass_conditions = [
        {
            "kind": "profit_target",
            "rule_id": "target",
            "amount_usd": "100",
            "basis": "equity",
            "evaluated": "eod",
            "comparison": ">=",
            "action": "promote_phase",
        }
    ]
    unknown = _attempt(
        _ruleset([_PAYOUT_UNKNOWN], pass_conditions=pass_conditions, kind="funded"),
        [5000.0, 5010.0, 5020.0, 5030.0],
    )
    declared = _attempt(
        _ruleset(
            [dict(_PAYOUT_UNKNOWN, max_usd="100000")],
            pass_conditions=pass_conditions,
            kind="funded",
        ),
        [5000.0, 5010.0, 5020.0, 5030.0],
    )
    assert unknown.mechanical_outcome == declared.mechanical_outcome
    assert unknown.payouts_usd == declared.payouts_usd
    assert unknown.cash_estimate_status == "upper_bound"
    assert declared.cash_estimate_status == "exact"
    assert unknown.estimate_status == "partial"
    assert any(PAYOUT_CAP_UNKNOWN in reason for reason in unknown.estimate_reasons)


def test_an_unknown_cap_is_refused_as_a_number_and_never_read_as_unlimited() -> None:
    """``unknown`` is its own value: it is not a sentinel floor, and it is not ``unlimited``."""
    rule = _ruleset([_PAYOUT_UNKNOWN]).phases[0].rules[0]
    assert rule.unknown_cap is True  # type: ignore[attr-defined]
    unlimited = _ruleset([dict(_PAYOUT_UNKNOWN, max_usd="unlimited")]).phases[0].rules[0]
    assert unlimited.unknown_cap is False  # type: ignore[attr-defined]
    books = [
        {"kind": "payout", "rule_id": "x", "max_usd": "500", "min_usd": "600"},
    ]
    with pytest.raises(ValidationError, match="above max_usd"):
        _ruleset(
            [
                dict(
                    _PAYOUT_UNKNOWN,
                    **books[0],
                    buffer_usd="0",
                    split="1",
                )
            ]
        )


# ------------------------------------------------------- 2. a lock with several triggers

_DUAL_LOCK = {
    "kind": "trailing_drawdown",
    "rule_id": "trail",
    "amount_usd": "2000",
    "mode": "intraday",
    "evaluated": "intraday",
    "basis": "equity",
    "hwm_basis": "balance",
    "comparison": "<=",
    "action": "fail",
    "lock": {
        "on": ["first_payout", "hwm"],
        "at_offset_usd": "5000",
        "locked_threshold_usd": "53000",
    },
}


def test_a_dual_trigger_lock_freezes_at_the_first_trigger_that_fires() -> None:
    """Trailing 2,000 from a 50,000 start is 48,000; the lock is 53,000.

    ``hwm`` fires when the mark reaches 50,000 + 5,000 = 55,000, ``first_payout`` at the first
    withdrawal. Payout first: the threshold moves 48,000 -> 53,000 and a later 60,000 mark cannot
    move it again. HWM first (55,200 >= 55,000): the threshold is already 53,000 when the payout
    arrives.
    """
    ruleset = _ruleset([_DUAL_LOCK])
    payout_first = rl.TrailingDrawdown(ruleset.phases[0].rules[0], 50_000_000_000, Decimal(1))
    assert payout_first.threshold == 48_000_000_000
    payout_first.on_first_payout()
    assert payout_first.threshold == 53_000_000_000
    payout_first.favorable(_marks("60000"), 20_000)
    assert payout_first.threshold == 53_000_000_000

    ruleset = _ruleset([_DUAL_LOCK])
    hwm_first = rl.TrailingDrawdown(ruleset.phases[0].rules[0], 50_000_000_000, Decimal(1))
    hwm_first.favorable(_marks("55200"), 20_000)
    assert hwm_first.hwm == 55_200_000_000
    assert hwm_first.threshold == 53_000_000_000
    hwm_first.on_first_payout()
    assert hwm_first.threshold == 53_000_000_000


def test_a_lock_trigger_list_is_a_list_and_the_hwm_parameters_stay_required() -> None:
    """``on`` is a list, never a bare string, and the hwm trigger keeps its level declaration."""
    rule = (
        _ruleset(
            [
                dict(
                    _DUAL_LOCK,
                    lock={"on": ["hwm"], "at_balance_usd": "55000", "locked_offset_usd": "3000"},
                )
            ]
        )
        .phases[0]
        .rules[0]
    )
    assert rule.lock.on == ("hwm",)  # type: ignore[attr-defined]
    with pytest.raises(ValidationError):
        _ruleset(
            [
                dict(
                    _DUAL_LOCK,
                    lock={"on": "hwm", "at_balance_usd": "55000", "locked_offset_usd": "3000"},
                )
            ]
        )
    evaluation = rl.TrailingDrawdown(rule, 50_000_000_000, Decimal(1))
    evaluation.favorable(_marks("55500"), 20_000)
    assert evaluation.threshold == 53_000_000_000  # 50,000 + 3,000
    with pytest.raises(ValidationError, match="at_balance_usd and at_offset_usd"):
        _ruleset([dict(_DUAL_LOCK, lock={"on": ["hwm"], "locked_threshold_usd": "53000"})])


def test_set_threshold_to_parses_start_plus_usd_and_zero_balance_offset() -> None:
    assert threshold_level("start") == ("start", Decimal(0))
    assert threshold_level("start_plus_usd:1250.50") == ("start_plus_usd", Decimal("1250.50"))
    assert threshold_level("zero_balance_offset:100") == ("zero_balance_offset", Decimal("100"))
    with pytest.raises(ValueError, match="not a threshold level"):
        threshold_level("trail:100")
    with pytest.raises(ValueError, match="takes no amount"):
        threshold_level("start:10")


def test_a_payout_can_set_the_threshold_to_an_explicit_level() -> None:
    """``threshold_after_payout: set_threshold`` with ``zero_balance_offset:2000``.

    The payout floor becomes 2,000.00 (so ``withdrawable = balance - (2,000 + buffer)``) and the
    phase's trailing drawdown is locked at 2,000.00: balance 53,000 with a 0 buffer is 51,000
    withdrawable and pays the 5,000 cap.
    """
    ruleset = _ruleset(
        [
            dict(
                _PAYOUT_UNKNOWN,
                max_usd="5000",
                buffer_usd="0",
                split="1",
                threshold_after_payout="set_threshold",
                set_threshold_to="zero_balance_offset:2000",
            ),
            _DUAL_LOCK,
        ],
        kind="funded",
    )
    close_ns = int(dt.datetime(2024, 1, 8, 22, 0, tzinfo=dt.UTC).timestamp()) * _NS
    overlay = PropAccountOverlay(
        ruleset=ruleset,
        phase=ruleset.phases[0],
        root="ES",
        tick_micro=TICK,
        session_close_ns=np.array([close_ns], dtype=np.int64),
        start_day=dt.date(2024, 1, 8),
        payout_policy="max_eligible",
    )
    book = _marks("53000", open_ns=close_ns - 60 * _MIN, close_ns=close_ns)
    overlay.begin_bar(0, book)
    overlay.end_bar(0, book)
    # 3,000 withdrawable: 53,000 - (50,000 + 0), capped at 5,000
    assert overlay.payouts == [(close_ns, 3_000_000_000, 3_000_000_000, "pay")]
    payout = overlay.payouts_rules[0]
    assert payout.base == 2_000_000_000
    trailing = next(rule for rule in overlay.rules if isinstance(rule, rl.TrailingDrawdown))
    assert trailing.threshold == 2_000_000_000

    raw = ruleset.model_dump(mode="python")
    raw["phases"][0]["rules"][0]["set_threshold_to"] = None
    with pytest.raises(ValidationError, match="go together"):
        PropRuleset.model_validate(raw)


# ---------------------------------------------------- 3. a news window that caps the size

_EVENT_NS = 1_704_758_400 * _NS  # 2024-01-08T18:00:00Z


def _news_rule(**overrides: object) -> dict[str, object]:
    rule: dict[str, object] = {
        "kind": "news_restriction",
        "rule_id": "news",
        "event_types": ["FOMC"],
        "instruments": ["ES"],
        "pre_minutes": 5,
        "post_minutes": 5,
        "scope": "new_entries",
        "flatten": "none",
        "effect": "contract_cap",
        "cap_contracts": "1",
        "comparison": ">=",
        "action": "block_entries",
    }
    rule.update(overrides)
    return rule


def test_a_news_contract_cap_clips_the_size_inside_the_window_and_not_outside() -> None:
    """A 5-minute pre-window around an 18:00Z FOMC release with a 1-contract cap.

    Inside (17:58-17:59) a 3-contract request is clipped to 1 (the weighted cap 1 / weight 1);
    outside (17:30-17:31) the same request is admitted whole.
    """
    event = NewsEvent("fomc-1", "FOMC", _EVENT_NS, time_known=True)
    ruleset = _ruleset([_news_rule()])
    overlay = PropAccountOverlay(
        ruleset=ruleset,
        phase=ruleset.phases[0],
        root="ES",
        tick_micro=TICK,
        session_close_ns=np.zeros(1, dtype=np.int64),
        start_day=dt.date(2024, 1, 8),
        news_events=(event,),
        news_covered=True,
    )
    inside = _marks("50000", open_ns=_EVENT_NS - 2 * _MIN, close_ns=_EVENT_NS - _MIN)
    assert overlay.admit(0, inside, 3) == 1
    resize = [record for record in overlay.events if record.kind == "resize"]
    assert [(record.requested, record.allowed) for record in resize] == [(3, 1)]

    outside = _marks("50000", open_ns=_EVENT_NS - 30 * _MIN, close_ns=_EVENT_NS - 29 * _MIN)
    assert overlay.admit(0, outside, 3) == 3


def test_a_news_event_type_the_calendar_lacks_makes_the_rule_not_modeled() -> None:
    """A rule naming PPI when the calendar carries only FOMC: reported, never \"no news\"."""
    event = NewsEvent("fomc-1", "FOMC", _EVENT_NS, time_known=True)
    ruleset = _ruleset([_news_rule(event_types=["PPI"])])
    rows = rule_coverage(
        ruleset,
        news_covered=True,
        news_unmodeled={"news": "event type(s) PPI are not in the economic calendar"},
    )
    assert [(row.modeled, row.materiality) for row in rows] == [(False, "material")]
    assert "PPI" in rows[0].description

    result = _attempt(
        ruleset,
        [5000.0, 5000.0, 5000.0, 5000.0],
        news_events=(event,),
        news_coverage=((0, 2**62),),
    )
    assert result.estimate_status == "partial"
    assert [row.modeled for row in result.rule_coverage if "news" in row.rule] == [False]
    assert any("PPI" in warning for warning in result.warnings)


# ------------------------------------------------------- 4. an activity requirement

_ACTIVITY = {
    "kind": "activity_requirement",
    "rule_id": "activity",
    "days": 2,
    "window": 3,
    "unit": "trading_days",
    "qualifies_if": {"min_trades": 1},
    "observed": "eod",
    "comparison": ">=",
    "action": "fail",
}


def _day_stats(pnl_micro: int) -> rl.DayStats:
    stats = rl.DayStats(50_000_000_000)
    stats.close_balance = 50_000_000_000 + pnl_micro
    stats.trades = 1
    return stats


def test_an_activity_requirement_fails_the_first_full_window_short_of_its_days() -> None:
    """2 qualifying calendar days in every 3-day window, a qualifying day being +50.00 or more.

    Days +100, +10, +100, +10 (in dollars): the window ending 01-09 is not full (2 days), the one
    ending 01-10 holds 2 qualifying days (08 and 10) so it passes, and the one ending 01-11
    [01-09, 01-11] holds only 01-10 = 1 < 2, so it fails.
    """
    ruleset = _ruleset(
        [
            dict(
                _ACTIVITY,
                unit="calendar_days",
                qualifies_if={"min_pnl_usd": "50"},
            )
        ]
    )
    days = {
        20240108: _day_stats(100_000_000),
        20240109: _day_stats(10_000_000),
        20240110: _day_stats(100_000_000),
        20240111: _day_stats(10_000_000),
    }
    evaluator = rl.ActivityRequirement(
        ruleset.phases[0].rules[0], 50_000_000_000, Decimal(1), days, dt.date(2024, 1, 8)
    )
    assert evaluator.violated(dt.date(2024, 1, 9)) is False
    assert evaluator.violated(dt.date(2024, 1, 10)) is False
    assert evaluator.violated(dt.date(2024, 1, 11)) is True


def test_an_activity_requirement_closes_the_account_on_the_third_session() -> None:
    """Three sessions with no trade at all: 0 qualifying days in the first full 3-day window.

    Days 1 and 2 open windows that are not full yet, so nothing happens; on day 3's close the
    window [day 1, day 3] holds 0 qualifying days against the required 2 and the account fails.
    """
    rows = [
        {
            "event_time": CALENDAR.session(day).bar_ends(3600)[-1],
            "open": 5000.0,
            "high": 5000.0,
            "low": 5000.0,
            "close": 5000.0,
            "contract": "ESH4",
        }
        for day in (dt.date(2024, 1, 8), dt.date(2024, 1, 9), dt.date(2024, 1, 10))
    ]
    bars = pl.DataFrame(rows)
    targets = pl.DataFrame(
        {
            "event_time": bars["event_time"],
            "target": pl.Series([0, 0, 0], dtype=pl.Int64),
        }
    )
    result = simulate_attempt(
        bars=bars,
        targets=targets,
        rolls=pl.DataFrame(schema=ROLL_SCHEMA),
        spec=futures_spec("ES"),
        costs=CostSchedule(commission=Decimal("2.00")),
        ruleset=_ruleset([_ACTIVITY]),
        start_trade_date=dt.date(2024, 1, 8),
        max_horizon_days=10,
        calendar=CALENDAR,
        execution_mode="manual",
    )
    assert result.outcome == "fail"
    assert result.breached_rule == "activity"
    assert [event.kind for event in result.overlay_events if event.rule_id == "activity"] == [
        "breach"
    ]


def test_an_activity_requirement_must_be_satisfiable() -> None:
    with pytest.raises(ValidationError, match="no window could ever satisfy it"):
        _ruleset([dict(_ACTIVITY, days=4, window=3)])


# -------------------------------- 5. a request bounded by the new profit since the last payout


def test_min_new_profit_share_of_request_lowers_the_request() -> None:
    """1,000.00 of new profit since the last payout and a 0.5 share allow 1,000 / 0.5 = 2,000.00.

    Balance 56,000 with a 55,000 payout base and a 1,000 buffer is 5,000 withdrawable, so without
    the share the request would be 5,000.00; 2,001.00 would need 1,000.50 of new profit.
    """
    rules = [
        dict(
            _PAYOUT_UNKNOWN,
            max_usd="unlimited",
            buffer_usd="1000",
            split="1",
            min_new_profit_share_of_request="0.5",
        )
    ]
    ruleset = _ruleset(rules, kind="funded")
    evaluator = rl.Payout(ruleset.phases[0].rules[0], 50_000_000_000, Decimal(1))
    evaluator.last_payout_balance = 55_000_000_000
    decision = evaluator.decision(
        _marks("56000"),
        {1: _day_stats(6_000_000_000)},
        trading_days=2,
        calendar_days=2,
        consistency_holds=True,
    )
    assert decision is not None
    assert decision.gross == 2_000_000_000
    assert decision.net == 2_000_000_000

    ruleset = _ruleset([dict(rules[0], min_new_profit_share_of_request=None)], kind="funded")
    unbounded = rl.Payout(ruleset.phases[0].rules[0], 50_000_000_000, Decimal(1))
    unbounded.last_payout_balance = 55_000_000_000
    wide = unbounded.decision(
        _marks("56000"),
        {1: _day_stats(6_000_000_000)},
        trading_days=2,
        calendar_days=2,
        consistency_holds=True,
    )
    assert wide is not None
    assert wide.gross == 5_000_000_000


# ------------------------------------- 6. consistency with separate numerator/denominator


def test_consistency_numerator_and_denominator_windows_are_separate() -> None:
    """Days +1,000 / +100 / +100 with a payout after day 1, a 51,200 balance and a 50,900 cycle
    opening: the best day since the payout is 100, and the current cycle's profit is 300.

    100/300 = 0.33 <= 0.4 passes; the same numerator against the days since the payout (100/200 =
    0.5) or the whole account's best day (1,000/300 and 1,000/1,200 = 0.83) do not.
    """
    days = {
        1: _day_stats(1_000_000_000),
        2: _day_stats(100_000_000),
        3: _day_stats(100_000_000),
    }

    def evaluator(**windows: object) -> rl.Consistency:
        rule = {
            "kind": "consistency",
            "rule_id": "cons",
            "max_day_share": "0.4",
            "measure": "best_day_profit/total_profit",
            "applies_to": "payout",
            "window": "all_time",
            "comparison": "<=",
            "action": "block_payout",
        }
        rule.update(windows)
        ruleset = _ruleset([rule])
        built = rl.Consistency(ruleset.phases[0].rules[0], 50_000_000_000, Decimal(1), days)
        built.last_payout_day = 1
        built.cycle_open_balance = 50_900_000_000
        return built

    split = evaluator(numerator_window="since_last_payout", denominator_window="current_cycle")
    assert split.passes(balance=51_200_000_000) is True
    coupled = evaluator(
        numerator_window="since_last_payout", denominator_window="since_last_payout"
    )
    assert coupled.passes(balance=51_200_000_000) is False
    whole = evaluator(numerator_window="all_time", denominator_window="current_cycle")
    assert whole.passes(balance=51_200_000_000) is False
    shared = evaluator()
    assert shared.passes(balance=51_200_000_000) is False


# ------------------------------------------------- 7. a conflict alternative that is absent


def test_an_absent_conflict_alternative_removes_the_rule_from_its_scenario() -> None:
    ruleset = _ruleset(
        [
            {
                "kind": "static_drawdown",
                "rule_id": "dd",
                "amount_usd": "2000",
                "basis": "equity",
                "evaluated": "intraday",
                "comparison": "<=",
                "action": "fail",
            }
        ],
        conflicts=[
            {
                "conflict_id": "dd-exists",
                "rule_id": "dd",
                "field": "amount_usd",
                "selected_value": "2000",
                "alternatives": [{"value": "absent", "source": _source().model_dump(mode="json")}],
                "selected_source": _source().model_dump(mode="json"),
                "rationale": "the newer page drops the drawdown rule altogether",
                "applicability_checked": True,
            }
        ],
    )
    generated = scenarios(ruleset)
    assert [item.scenario_id for item in generated] == ["primary", "dd-exists#0"]
    assert [rule.rule_id for rule in generated[0].ruleset.phases[0].rules] == ["dd"]
    assert generated[1].ruleset.phases[0].rules == ()
    assert generated[1].label == "sensitivity"


# --------------------------------------------- 8. per-component execution costs

_PROFILE = ParticipantProfile.from_mapping(
    {"cme_membership_status": "non_member", "nfa_assessment_eligibility": "fcm_member"}
)
"""The run's participant profile: it resolves the synthetic exchange row and the NFA row."""

_FEE_TABLE = ComponentFeeTable(
    rows=(
        ComponentFeeRow(
            root="ES",
            fee_type="exchange",
            classification_dimension="cme_membership_status",
            classification_value="non_member",
            covers=("exchange", "clearing"),
            per_side_usd=Decimal("1.27"),
            effective_from=dt.date(2024, 1, 1),
        ),
    ),
    source_sha256="1" * 64,
)
"""One synthetic row covering BOTH the exchange and the clearing fee, at 1.27 per side."""


def test_a_commission_that_excludes_a_component_adds_it_from_the_fee_table() -> None:
    """Per side: commission 2.00 plus a row covering exchange and clearing at 1.27.

    One row covers two components and is charged ONCE, so the run pays 2.00 + 1.27 = 3.27 per
    contract per side. ``unknown`` components are gaps and an all-``included`` commission keeps the
    2.00 and adds nothing; without the table, or when it has no ES row for the date, the excluded
    component is a named gap and the cash statistic is unavailable.
    """
    costs = CostSchedule(commission=Decimal("9.99"), exchange_fee=Decimal("9.99"))
    excluded = _ruleset(
        [],
        commissions={
            "status": "known",
            "components": _COMPONENTS_EXCLUDED,
            "per_side_usd": {"ES": "2.00"},
            "platform": None,
            "source": _source().model_dump(mode="json"),
        },
    )
    schedule, application = _commissions_for(
        _unknowning(excluded),
        costs,
        "ES",
        None,
        fee_source=_FEE_TABLE,
        profile=_PROFILE,
        when=dt.date(2024, 1, 8),
    )
    assert schedule.commission == Decimal("2.00")
    assert schedule.exchange_fee == Decimal("1.27")
    # one row, two components: charged once, so the clearing component adds nothing of its own
    assert application.component("clearing").status == "covered_by_row"
    assert schedule.clearing_fee == Decimal("0")
    assert schedule.regulatory_fee == Decimal("0")
    assert application.component("exchange").usd == Decimal("1.27")
    assert application.component("exchange").status == "excluded_priced"
    assert application.component("nfa").status == "unknown"
    assert application.cost_status == "unavailable"
    assert application.cost_gaps == ("nfa", "other")
    assert application.participant_profile_sha256 == _PROFILE.sha256

    # an excluded component with no participant profile cannot be priced at all: refused, by name
    with pytest.raises(ConfigurationError, match="participant profile"):
        _commissions_for(_unknowning(excluded), costs, "ES", None, when=dt.date(2024, 1, 8))
    _, blind = _commissions_for(
        _unknowning(excluded),
        costs,
        "ES",
        None,
        profile=_PROFILE,
        when=dt.date(2024, 1, 8),
    )
    assert blind.component("exchange").status == "excluded_unpriced"
    assert "no fee dataset was given" in (blind.fees_incomplete or "")

    _, uncovered = _commissions_for(
        _unknowning(excluded),
        costs,
        "ES",
        None,
        fee_source=_FEE_TABLE,
        profile=_PROFILE,
        when=dt.date(2023, 12, 1),
    )
    assert uncovered.component("exchange").usd is None
    assert "no fee row covers ES exchange on 2023-12-01" in (uncovered.fees_incomplete or "")

    included = _ruleset([])  # the helper's default: every component included
    schedule, application = _commissions_for(
        included,
        costs,
        "ES",
        None,
        fee_source=_FEE_TABLE,
        when=dt.date(2024, 1, 8),
    )
    assert schedule.commission == Decimal("2.00")
    assert schedule.exchange_fee == Decimal("0")
    assert application.cost_status == "complete"


def _unknowning(ruleset: PropRuleset) -> PropRuleset:
    """The same ruleset with only the exchange and clearing components excluded.

    The four-component helper above excludes every component; this narrows it so the arithmetic of
    one test names exactly which components it prices.
    """
    components = {
        "exchange": {"status": "excluded", "evidence": "official_quote", "text": "SYNTHETIC"},
        "clearing": {"status": "excluded", "evidence": "official_quote", "text": "SYNTHETIC"},
        "nfa": {"status": "unknown", "evidence": "not_stated", "text": "SYNTHETIC"},
        "other": {"status": "unknown", "evidence": "not_stated", "text": "SYNTHETIC"},
    }
    raw = ruleset.model_dump(mode="python")
    raw["commissions"]["components"] = components
    return PropRuleset.model_validate(raw)


def test_the_attempt_reports_an_uncovered_component_as_unavailable_cash() -> None:
    """Four flat bars, one contract: no trade, so the cash statistic is the fees alone.

    Without the fee table the attempt cannot say what the commission excludes, so the cash
    statistic is unavailable and the reason names the component; with the table the priced
    components are exact and the unknown ones keep the number unavailable.
    """
    ruleset = _unknowning(
        _ruleset(
            [],
            commissions={
                "status": "known",
                "components": _COMPONENTS_EXCLUDED,
                "per_side_usd": {"ES": "2.00"},
                "platform": None,
                "source": _source().model_dump(mode="json"),
            },
        )
    )
    # the run input the ruleset never states: without it an excluded component is refused
    with pytest.raises(ConfigurationError, match="participant profile"):
        _attempt(ruleset, [5000.0, 5000.0, 5000.0, 5000.0])
    blind = _attempt(ruleset, [5000.0, 5000.0, 5000.0, 5000.0], profile=_PROFILE)
    assert blind.cash_estimate_status == "unavailable"
    assert blind.commissions.cost_gaps == ("exchange", "clearing", "nfa", "other")
    assert blind.commissions.fees_incomplete is not None
    assert "exchange: the commission excludes it" in blind.commissions.fees_incomplete

    priced = _attempt(
        ruleset,
        [5000.0, 5000.0, 5000.0, 5000.0],
        fee_source=_FEE_TABLE,
        profile=_PROFILE,
    )
    assert priced.commissions.component("exchange").usd == Decimal("1.27")
    # nfa and other are declared unknown, so the cash number is still not available
    assert priced.cash_estimate_status == "unavailable"
    assert priced.commissions.cost_gaps == ("nfa", "other")


def test_a_fee_table_refuses_an_ambiguous_or_unsourced_row() -> None:
    row = ComponentFeeRow(
        root="ES",
        fee_type="exchange",
        classification_dimension="cme_membership_status",
        classification_value="non_member",
        covers=("exchange",),
        per_side_usd=Decimal("1.25"),
        effective_from=dt.date(2024, 1, 1),
    )
    with pytest.raises(ConfigurationError, match="overlap"):
        ComponentFeeTable(rows=(row, row), source_sha256="1" * 64)
    with pytest.raises(ConfigurationError, match="source_sha256"):
        ComponentFeeTable(rows=(row,), source_sha256="short")
    with pytest.raises(ConfigurationError, match="upper-case root"):
        ComponentFeeRow(
            root="es",
            fee_type="exchange",
            classification_dimension="cme_membership_status",
            classification_value="non_member",
            covers=("exchange",),
            per_side_usd=Decimal("1.25"),
            effective_from=dt.date(2024, 1, 1),
        )
    with pytest.raises(ConfigurationError, match="must be >= 0"):
        ComponentFeeRow(
            root="ES",
            fee_type="exchange",
            classification_dimension="cme_membership_status",
            classification_value="non_member",
            covers=("exchange",),
            per_side_usd=Decimal("-1"),
            effective_from=dt.date(2024, 1, 1),
        )
    with pytest.raises(ConfigurationError, match="does not contain its own fee_type"):
        ComponentFeeRow(
            root="ES",
            fee_type="exchange",
            classification_dimension="cme_membership_status",
            classification_value="non_member",
            covers=("clearing",),
            per_side_usd=Decimal("1.25"),
            effective_from=dt.date(2024, 1, 1),
        )


# ------------------------------------------------------ 9. the holiday early close


def test_flat_by_relative_to_the_session_end_follows_a_thanksgiving_early_close() -> None:
    """The day after US Thanksgiving 2024 closes at 12:15 Chicago = 18:15 UTC, not 16:00.

    A ``flat_by`` 60 minutes before the scheduled session end is therefore 17:15 UTC; a fixed
    16:00 Chicago clock would be an hour and 45 minutes late. The 2023 instance of the same
    holiday is an UNSOURCED window in the CME table (its published schedule was never archived),
    so the table gives it the 16:00 regime close and flags the session unverified: a firm rule
    that assumes the early close is still ``not_modeled`` for that date.
    """
    early = CALENDAR.session(dt.date(2024, 11, 29))
    assert early.verified is True
    close = dt.datetime.fromtimestamp(early.close_ns // _NS, dt.UTC)
    assert close == dt.datetime(2024, 11, 29, 18, 15, tzinfo=dt.UTC)
    assert early.close_ns == int(close.timestamp()) * _NS
    assert dt.datetime(2024, 11, 29, 17, 15, tzinfo=dt.UTC).timestamp() * _NS == (
        early.close_ns - 60 * _MIN
    )

    ruleset = _ruleset(
        [
            {
                "kind": "flat_by",
                "rule_id": "flat",
                "minutes_before_session_end": 60,
                "comparison": ">=",
                "action": "auto_liquidate",
            }
        ]
    )
    evaluator = rl.FlatBy(ruleset.phases[0].rules[0], 50_000_000_000, Decimal(1))
    window = evaluator.flat_and_reopen(early.open_ns, early.close_ns, early.close_ns)
    assert window is not None
    assert window[0] == int(dt.datetime(2024, 11, 29, 17, 15, tzinfo=dt.UTC).timestamp()) * _NS
    # the regular session that week closes at 22:00 UTC (16:00 Chicago): an hour+ later
    regular = CALENDAR.session(dt.date(2024, 12, 2))
    assert early.close_ns < regular.close_ns

    unsourced = CALENDAR.session(dt.date(2023, 11, 24))
    assert unsourced.verified is False
    assert (
        unsourced.close_ns == int(dt.datetime(2023, 11, 24, 22, 0, tzinfo=dt.UTC).timestamp()) * _NS
    )


# ------------------------------------------- 10. an unsourced session-calendar window

_FLAT_BY = {
    "kind": "flat_by",
    "rule_id": "flat",
    "minutes_before_session_end": 60,
    "comparison": ">=",
    "action": "auto_liquidate",
}


def test_an_unsourced_session_calendar_window_is_a_reported_coverage_gap() -> None:
    """2023-11-24's session opens on 2023-11-23, inside the unsourced Thanksgiving 2023 window.

    The CME table never archived that holiday's schedule, so the session is built from the regular
    week: a 16:00 Chicago close, and a 15:00 flat for a ``flat_by`` 60 minutes before the end, when
    the real day-after-Thanksgiving early close (12:15) is not in the table. The attempt must say
    so: the window is listed and the estimate is partial, never a sourced number.
    """
    result = _attempt(_ruleset([_FLAT_BY]), [5000.0], day=dt.date(2023, 11, 24))
    assert result.session_calendar_gaps == ("2023-11-22..2023-11-23",)
    assert result.estimate_status == "partial"
    assert "session calendar unsourced 2023-11-22..2023-11-23" in result.estimate_reasons
    assert any("session calendar unsourced" in warning for warning in result.warnings)
    # the regular week's close is what the session reports, and that is the flaw being reported
    session = CALENDAR.session(dt.date(2023, 11, 24))
    assert session.verified is False
    assert (
        session.close_ns - 60 * _MIN
        == int(dt.datetime(2023, 11, 24, 21, 0, tzinfo=dt.UTC).timestamp()) * _NS
    )

    sourced = _attempt(_ruleset([_FLAT_BY]), [5000.0], day=dt.date(2024, 12, 2))
    assert sourced.session_calendar_gaps == ()
    assert sourced.estimate_status == "conditional"  # unverified ruleset, no schedule gap
    assert not any("session calendar" in warning for warning in sourced.warnings)


# --------------------------- 8b. the stored fee dataset as a ComponentFeeSource

_MONEY_NS = 86_400 * _NS


def _fee_row(
    root: str,
    fee_type: str,
    amount: str,
    dimension: str,
    value: str,
    covers: str,
    source_kind: str,
) -> dict[str, object]:
    """One row of the fee contract, in the shape ``build_exchange_fees`` writes."""
    from crucible.data import exchange_fees as ef

    day = dt.date(2024, 1, 1)
    row: dict[str, object] = {
        "root": root,
        "venue": ef.VENUE_OF[root],
        "fee_type": fee_type,
        "classification_dimension": dimension,
        "classification_value": value,
        "covers": covers,
        "charge_name": None,
        "unit": ef.UNIT_PER_CONTRACT_PER_SIDE,
        "per_side_usd": amount,
        "effective_from": day,
        "effective_to": None,
        "source_kind": source_kind,
        "provided_by": "owner" if source_kind == ef.SOURCE_KIND_OWNER else None,
        "source_url": "https://example.invalid/synthetic-fees",
        "snapshot_sha256": "0" * 64,
        "quote": "SYNTHETIC TEST VALUE: a fee row invented for a test",
        "applies_quote": None,
        "distinct_from": None,
        "event_time": int(dt.datetime.combine(day, dt.time(0, 0), tzinfo=dt.UTC).timestamp()) * _NS,
        "available_at": int(dt.datetime.combine(day, dt.time(0, 0), tzinfo=dt.UTC).timestamp())
        * _NS,
        "dataset_version": ef.DATASET_VERSION,
    }
    row["record_sha256"] = ef.record_sha256(row)
    return row


def _fee_store(root: Path, *, exchange: bool):
    """A tmp store holding the fee contract: NFA rows always, exchange rows on demand."""
    from crucible.data import exchange_fees as ef
    from crucible.data.store import ParquetDataStore, build_dataset

    rows: list[dict[str, object]] = []
    for name in ef.ROOTS:
        rows.append(
            _fee_row(
                name,
                "nfa",
                "0.02",
                ef.NFA_CLASSIFICATION_DIMENSION,
                ef.NFA_CLASSIFICATION_VALUE,
                "nfa",
                ef.SOURCE_KIND_OFFICIAL,
            )
        )
        if exchange:
            rows.append(
                _fee_row(
                    name,
                    "exchange",
                    "1.25",
                    ef.EXCHANGE_CLASSIFICATION_DIMENSION,
                    ef.EXCHANGE_CLASSIFICATION_VALUE,
                    "exchange",
                    ef.SOURCE_KIND_OWNER,
                )
            )
    frame = pl.DataFrame(rows, orient="row", schema=ef.EXCHANGE_FEE_SCHEMA)
    build_dataset(
        root,
        ef.DATASET,
        frame,
        schema=ef.EXCHANGE_FEE_SCHEMA,
        sort_keys=ef.EXCHANGE_FEE_SORT_KEYS,
        source="synthetic rows written by a prop test",
    )
    return ParquetDataStore(root)


def _exchange_only_unknown_ruleset() -> PropRuleset:
    """Exchange excluded, NFA excluded, clearing and other declared unknown."""
    ruleset = _ruleset(
        [],
        commissions={
            "status": "known",
            "components": _COMPONENTS_EXCLUDED,
            "per_side_usd": {"ES": "2.00"},
            "platform": None,
            "source": _source().model_dump(mode="json"),
        },
    )
    raw = ruleset.model_dump(mode="python")
    raw["commissions"]["components"] = {
        "exchange": {"status": "excluded", "evidence": "official_quote", "text": "SYNTHETIC"},
        "clearing": {"status": "unknown", "evidence": "not_stated", "text": "SYNTHETIC"},
        "nfa": {"status": "excluded", "evidence": "official_quote", "text": "SYNTHETIC"},
        "other": {"status": "unknown", "evidence": "not_stated", "text": "SYNTHETIC"},
    }
    return PropRuleset.model_validate(raw)


def test_the_stored_fee_dataset_prices_each_component_or_says_it_is_unknown(
    tmp_path: Path,
) -> None:
    """NFA 0.02 + exchange 1.25 = 1.27 per contract per side, read from the stored dataset.

    A store holding only the NFA rows cannot price the exchange fee: the attempt reports the
    exchange component as a gap and the cash statistic is ``conditional`` only when a cost
    assumption priced it — never 0.02 charged as if it were the whole fee.
    """
    nfa_only = store_component_fees(_fee_store(tmp_path / "nfa_only", exchange=False))
    blind = _attempt(
        _exchange_only_unknown_ruleset(),
        [5000.0, 5000.0, 5000.0, 5000.0],
        fee_source=nfa_only,
        profile=_PROFILE,
    )
    assert blind.cash_estimate_status == "unavailable"
    assert blind.commissions.cost_gaps == ("exchange", "clearing", "other")
    assert blind.commissions.component("nfa").usd == Decimal("0.02")

    priced = store_component_fees(_fee_store(tmp_path / "priced", exchange=True))
    priced_attempt = _attempt(
        _exchange_only_unknown_ruleset(),
        [5000.0, 5000.0, 5000.0, 5000.0],
        fee_source=priced,
        profile=_PROFILE,
    )
    assert priced_attempt.commissions.component("exchange").usd == Decimal("1.25")
    assert priced_attempt.commissions.component("nfa").usd == Decimal("0.02")
    assert priced_attempt.commissions.cost_gaps == ("clearing", "other")
    assert priced_attempt.cash_estimate_status == "unavailable"

    # a store with no such dataset at all is refused by name, not priced at zero
    with pytest.raises(ConfigurationError, match="cannot read dataset"):
        store_component_fees(ParquetDataStore(tmp_path / "empty"))
