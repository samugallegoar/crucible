"""Prop-firm payouts (ADR-0106 section 4, C7a part 2), hand-computed.

A payout is a withdrawal recorded apart from trading P&L: the funded phase's ``payout`` rule
decides eligibility at each rule-day's close, and whether the trader takes an eligible payout is
``payout_policy`` -- the trader's choice, never a firm rule.

The synthetic fixture is a 50,000.00 funded account with a 1,000.00 buffer, an 80% split, a
100.00 minimum and a 2,000.00 cap. Every expected number below is written out as arithmetic.
"""

from __future__ import annotations

import datetime as dt
import hashlib
from decimal import Decimal
from pathlib import Path

import numpy as np
import polars as pl
import pytest
import yaml

from crucible.core.errors import ConfigurationError
from crucible.data.cme_session_table import cme_session_table
from crucible.data.cme_sessions import SessionCalendar
from crucible.data.contracts import ROLL_SCHEMA
from crucible.data.futures_specs import futures_spec
from crucible.execution.futures_sim import CostSchedule
from crucible.execution.interfaces import AccountMarks
from crucible.prop.attempt import simulate_attempt
from crucible.prop.overlay import PropAccountOverlay
from crucible.prop.ruleset import PropRuleset, load_ruleset

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "prop"
_NS = 1_000_000_000
_MIN = 60 * _NS
_T0 = int(dt.datetime(2024, 1, 8, 15, 1, tzinfo=dt.UTC).timestamp()) * _NS
ES = futures_spec("ES")
COSTS = CostSchedule(commission=Decimal("2.00"))
CALENDAR = SessionCalendar(cme_session_table(), "ES")


def _payout_ruleset(**fields: object) -> PropRuleset:
    raw = yaml.safe_load((FIXTURES / "synthetic_p_payout.yaml").read_text(encoding="utf-8"))
    raw["phases"][0]["rules"][0].update(fields)
    return PropRuleset.model_validate(raw)


def _with_payout_consistency(**fields: object) -> PropRuleset:
    raw = yaml.safe_load((FIXTURES / "synthetic_p_payout.yaml").read_text(encoding="utf-8"))
    raw["phases"][0]["rules"].append(
        {
            "kind": "consistency",
            "rule_id": "consistency",
            "max_day_share": "0.5",
            "applies_to": "payout",
            "source": {
                "url": "https://example.invalid/synthetic-rules",
                "quote": "Synthetic rule value invented for a test, not a real firm's rule",
                "snapshot_sha256": "0" * 64,
                "retrieved_at": "2024-01-01T00:00:00Z",
                "synthetic": True,
            },
        }
    )
    raw["phases"][0]["rules"][0].update(fields)
    return PropRuleset.model_validate(raw)


def _twenty_five_thousand() -> PropRuleset:
    """The payout fixture re-based on a 25,000.00 account (the fixture's own 50,000.00 start)."""
    raw = yaml.safe_load((FIXTURES / "synthetic_p_payout.yaml").read_text(encoding="utf-8"))
    raw["account_size_usd"] = "25000"
    raw["phases"][0]["starting_balance_usd"] = "25000"
    return PropRuleset.model_validate(raw)


def _marks(bar: int, balance: str, *, open_ns: int, close_ns: int) -> AccountMarks:
    return AccountMarks(
        bar=bar,
        open_time_ns=open_ns,
        close_time_ns=close_ns,
        open_ticks=20_000,
        high_ticks=20_000,
        low_ticks=20_000,
        close_ticks=20_000,
        position=0,
        balance_micro=int(Decimal(balance) * 1_000_000),
        cost_basis_ticks=0,
        tick_micro=12_500_000,
    )


def _drive(
    ruleset: PropRuleset,
    days: list[tuple[str, str, int]],
    *,
    payout_policy: str = "max_eligible",
) -> PropAccountOverlay:
    """Drive one overlay over ``days``, each a rule-day of its own: ``(open balance, close
    balance, trades)``. One bar per day, at 17:01 Chicago, closing at the session end."""
    n = len(days)
    close_ns = np.zeros(n, dtype=np.int64)
    overlay = PropAccountOverlay(
        ruleset=ruleset,
        phase=ruleset.phases[0],
        root="ES",
        tick_micro=12_500_000,
        session_close_ns=close_ns,
        start_day=dt.date(2024, 1, 7),
        payout_policy=payout_policy,
    )
    for bar, (opening, closing, trades) in enumerate(days):
        open_ns = _T0 + bar * 24 * 60 * _MIN
        close_ns[bar] = open_ns + _MIN
        sheet = _marks(bar, opening, open_ns=open_ns, close_ns=open_ns + _MIN)
        assert overlay.begin_bar(bar, sheet) is None
        for _ in range(trades):
            overlay.fill(bar, sheet, 1, 20_000, "signal")
        end = _marks(bar, closing, open_ns=open_ns, close_ns=open_ns + _MIN)
        action = overlay.end_bar(bar, end)
        if action is not None or overlay.closed:
            break
    last = bar
    overlay.finish(
        _marks(
            last,
            days[last][1],
            open_ns=_T0 + last * 24 * 60 * _MIN,
            close_ns=_T0 + last * 24 * 60 * _MIN + _MIN,
        )
    )
    return overlay


def test_an_eligible_payout_withdraws_the_capped_gross_and_pays_the_split() -> None:
    """Close balance 53,000.00: withdrawable = 53,000 - (50,000 + 1,000) = 2,000.00, the cap
    (2,000.00) binds at exactly 2,000.00, and the trader receives 0.8 * 2,000.00 = 1,600.00. The
    account keeps 53,000 - 2,000 = 51,000.00.
    """
    overlay = _drive(_payout_ruleset(), [("50000", "53000", 1)])
    assert len(overlay.payouts) == 1
    _when, gross, net, rule = overlay.payouts[0]
    assert (gross, net, rule) == (2_000_000_000, 1_600_000_000, "payout")
    assert overlay.withdrawn == 2_000_000_000
    assert overlay.outcome == "running"


def test_the_buffer_blocks_a_payout() -> None:
    """51,000.00 is only 1,000.00 above the starting balance, exactly the buffer, and 50,500.00
    is below it: withdrawable 0.00 and -500.00, so no payout on either day."""
    overlay = _drive(_payout_ruleset(), [("50000", "51000", 1), ("51000", "50500", 1)])
    assert overlay.payouts == []
    assert overlay.withdrawn == 0


def test_the_max_usd_cap_limits_a_large_payout() -> None:
    """Withdrawable 58,000 - 51,000 = 7,000.00 but the cap is 500.00: gross 500.00, net 400.00."""
    overlay = _drive(_payout_ruleset(max_usd="500"), [("50000", "58000", 1)])
    assert [(gross, net) for _when, gross, net, _rule in overlay.payouts] == [
        (500_000_000, 400_000_000)
    ]


def test_the_payout_consistency_rule_blocks_the_payout() -> None:
    """Day 1 makes 3,000.00 of the 3,500.00 total: the best day's share is 3000/3500 = 0.857,
    above 0.5, so day 2 pays nothing -- and day 1's own share is 3000/3000 = 1.0, above it too."""
    overlay = _drive(_with_payout_consistency(), [("50000", "53000", 1), ("53000", "53500", 1)])
    assert overlay.payouts == []


def test_threshold_after_payout_unchanged_needs_the_buffer_earned_again() -> None:
    """``unchanged`` keeps the 50,000.00 base: day 2's trading balance 55,000.00 is 53,000.00
    after the 2,000.00 withdrawal, so withdrawable = 53,000 - 51,000 = 2,000.00 again and the
    second payout is another 2,000.00 (net 1,600.00)."""
    overlay = _drive(
        _payout_ruleset(threshold_after_payout="unchanged"),
        [("50000", "53000", 1), ("53000", "55000", 1)],
    )
    assert [gross for _when, gross, _net, _rule in overlay.payouts] == [
        2_000_000_000,
        2_000_000_000,
    ]
    assert overlay.withdrawn == 4_000_000_000


def test_threshold_after_payout_trail_from_new_balance_rebuilds_the_buffer() -> None:
    """``trail_from_new_balance`` moves the base to the post-payout 51,000.00: day 2's adjusted
    balance 53,000.00 gives withdrawable = 53,000 - (51,000 + 1,000) = 1,000.00, so the second
    payout is 1,000.00 (net 800.00)."""
    overlay = _drive(
        _payout_ruleset(threshold_after_payout="trail_from_new_balance"),
        [("50000", "53000", 1), ("53000", "55000", 1)],
    )
    assert [gross for _when, gross, _net, _rule in overlay.payouts] == [
        2_000_000_000,
        1_000_000_000,
    ]
    assert [net for _when, _gross, net, _rule in overlay.payouts] == [
        1_600_000_000,
        800_000_000,
    ]


def test_max_payouts_stops_after_the_declared_number() -> None:
    """``max_payouts: 1``: day 1 pays 2,000.00 and day 2, though eligible for another 2,000.00,
    pays nothing."""
    overlay = _drive(
        _payout_ruleset(max_payouts=1),
        [("50000", "53000", 1), ("53000", "55000", 1)],
    )
    assert len(overlay.payouts) == 1


def test_min_days_since_last_delays_the_first_payout() -> None:
    """``min_days_since_last: 2``: on rule-day 1 only 1 trading day has opened (1 < 2), on
    rule-day 2 two have (2 >= 2), so the first payout falls on day 2: 2,000.00 gross."""
    overlay = _drive(
        _payout_ruleset(min_days_since_last=2),
        [("50000", "53000", 1), ("53000", "53000", 1)],
    )
    assert len(overlay.payouts) == 1
    assert overlay.payouts[0][0] == _T0 + 1 * 24 * 60 * _MIN + _MIN


def test_min_profitable_days_needs_that_many_profitable_days() -> None:
    """``min_profitable_days: 2``: day 1 has one profitable day, day 2 has two, so the payout is
    on day 2 (2,000.00 gross)."""
    overlay = _drive(
        _payout_ruleset(min_profitable_days=2),
        [("50000", "53000", 1), ("53000", "53000", 1)],
    )
    assert len(overlay.payouts) == 1
    assert overlay.payouts[0][:3] == (
        _T0 + 1 * 24 * 60 * _MIN + _MIN,
        2_000_000_000,
        1_600_000_000,
    )


def test_payout_policy_none_takes_no_payout() -> None:
    """The same eligible close with ``payout_policy="none"``: taking it is the trader's choice."""
    overlay = _drive(_payout_ruleset(), [("50000", "53000", 1)], payout_policy="none")
    assert overlay.payouts == []
    assert overlay.withdrawn == 0


def test_an_unknown_payout_policy_is_refused() -> None:
    with pytest.raises(ConfigurationError):
        PropAccountOverlay(
            ruleset=_payout_ruleset(),
            phase=_payout_ruleset().phases[0],
            root="ES",
            tick_micro=12_500_000,
            session_close_ns=np.zeros(1, dtype=np.int64),
            start_day=dt.date(2024, 1, 7),
            payout_policy="always",
        )


def test_a_payout_shrinks_the_balance_the_failure_rules_test() -> None:
    """The withdrawal is not a trading loss but it does leave the account.

    A 3,000.00 drawdown on the same funded account: after a 2,000.00 payout from 53,000.00 the
    account holds 51,000.00, and the next close at 50,000.00 (adjusted 48,000.00... ) is below the
    47,000.00 threshold? No: threshold = 50,000 - 3,000 = 47,000.00, so 48,000.00 is above it.
    A second close at 49,000.00 (adjusted 47,000.00) touches it exactly and fails at that close.
    """
    ruleset = _payout_ruleset()
    raw = ruleset.model_dump(mode="json")
    raw["phases"][0]["rules"] = []
    raw["phases"][0]["rules"].append(
        {
            "kind": "payout",
            "rule_id": "payout",
            "buffer_usd": "1000",
            "split": "0.8",
            "min_usd": "100",
            "max_usd": "2000",
            "min_profitable_days": "1",
            "source": {
                "url": "https://example.invalid/synthetic-rules",
                "quote": "Synthetic rule value invented for a test",
                "snapshot_sha256": "0" * 64,
                "retrieved_at": "2024-01-01T00:00:00Z",
                "synthetic": True,
            },
        }
    )
    raw["phases"][0]["rules"].append(
        {
            "kind": "static_drawdown",
            "rule_id": "max_drawdown",
            "amount_usd": "3000",
            "basis": "balance",
            "evaluated": "eod",
            "source": {
                "url": "https://example.invalid/synthetic-rules",
                "quote": "Synthetic rule value invented for a test",
                "snapshot_sha256": "0" * 64,
                "retrieved_at": "2024-01-01T00:00:00Z",
                "synthetic": True,
            },
        }
    )
    funded = PropRuleset.model_validate(raw)
    overlay = _drive(funded, [("50000", "53000", 1), ("53000", "49000", 1)])
    assert overlay.withdrawn == 2_000_000_000
    # adjusted balance = 49,000 - 2,000 = 47,000, exactly the 50,000 - 3,000 threshold
    assert overlay.outcome == "fail"
    assert overlay.breached_rule == "max_drawdown"


def test_the_attempt_records_payouts_and_the_traders_choice() -> None:
    """End to end: 1 contract bought at 2,500.00 and sold at 2,600.00 before the session close.

    Balance = 25,000 - 20.75 + 100 * 50 - 20.75 = 29,958.50; withdrawable =
    29,958.50 - (25,000 + 1,000) = 3,958.50, so gross = min(2,000, 3,958.50) = 2,000.00 and the
    trader receives 1,600.00.
    ``net_cash_usd`` = 1,600.00 - 0.00 fees. With ``payout_policy="none"`` nothing is paid, and
    the result still says the ruleset models payouts.
    """
    first = CALENDAR.session(dt.date(2024, 1, 8)).bar_ends(60)
    rows = [
        {
            "event_time": first[0],
            "open": 2500.0,
            "high": 2500.0,
            "low": 2500.0,
            "close": 2500.0,
            "contract": "ESH4",
        },
        {
            "event_time": first[1],
            "open": 2500.0,
            "high": 2600.0,
            "low": 2500.0,
            "close": 2600.0,
            "contract": "ESH4",
        },
        {
            "event_time": first[-1],
            "open": 2600.0,
            "high": 2600.0,
            "low": 2600.0,
            "close": 2600.0,
            "contract": "ESH4",
        },
    ]
    bars = pl.DataFrame(rows)
    targets = pl.DataFrame(
        {"event_time": bars["event_time"], "target": pl.Series([1, 0, 0], dtype=pl.Int64)}
    )
    common = {
        "bars": bars,
        "targets": targets,
        "rolls": pl.DataFrame(schema=ROLL_SCHEMA),
        "spec": ES,
        "costs": COSTS,
        "ruleset": _twenty_five_thousand(),
        "start_trade_date": dt.date(2024, 1, 8),
        "max_horizon_days": 5,
        "calendar": CALENDAR,
    }
    paid = simulate_attempt(**common, payout_policy="max_eligible")
    assert paid.payouts_usd == Decimal("1600")
    assert paid.net_cash_usd == Decimal("1600")
    assert paid.payout_modeled is True
    assert paid.payout_policy == "max_eligible"
    assert [(p.gross_usd, p.net_usd, p.rule_id) for p in paid.payouts] == [
        (Decimal("2000"), Decimal("1600"), "payout")
    ]
    unpaid = simulate_attempt(**common, payout_policy="none")
    assert unpaid.payouts_usd == Decimal(0)
    assert unpaid.payouts == ()
    assert unpaid.payout_modeled is True
    assert unpaid.payout_policy == "none"


def test_the_ruleset_hash_covers_the_payout_terms() -> None:
    """A ruleset is data: changing the split changes the content hash, so a version is immutable."""
    base = load_ruleset(FIXTURES / "synthetic_p_payout.yaml")
    edited = _payout_ruleset(split="0.9")
    assert base.ruleset_sha256 != edited.ruleset_sha256
    assert len(hashlib.sha256(base.ruleset_sha256.encode()).hexdigest()) == 64
