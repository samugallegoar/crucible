"""The XFA scaling-plan ladder: balance tiers, the boundary reading and the excess clip.

The firm's table (an image, transcribed) reads COLUMNS of account balance against contracts:
"Below $1,500 -> 2 Lots", "$1,500 - $2,000 -> 3 Lots", "Above $2,000 -> 5 Lots" for the $50K
account. The owner's delegated decision of 2026-11-23 reads a balance exactly ON a printed
boundary as the LOWER tier, the conservative direction, so the rungs are ``min_balance_usd`` with
``comparison: '>'`` (strictly above $1,500 is the 3-lot rung) and the first rung carries no
threshold at all: it is the floor, which is why a zero or negative balance still has a size.

Every expected number is written out as arithmetic in the test.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest
from pydantic import ValidationError

from crucible.execution.interfaces import AccountMarks
from crucible.prop import rules as rl
from crucible.prop.rules_schema import ScalingPlanRule, ScalingStep
from crucible.prop.ruleset import Attribution

TICK = 12_500_000  # $12.50 per tick in micro-dollars
SOURCE = Attribution(
    url="https://example.invalid/synthetic-rules",
    quote="Synthetic rule value invented for a test, not a real firm's rule",
    snapshot_sha256="0" * 64,
    retrieved_at=dt.datetime(2024, 1, 1, tzinfo=dt.UTC),
    synthetic=True,
)

# The $50K XFA ladder exactly as the image prints it, read through its boundary decision.
STEPS = (
    ScalingStep(max_contracts=Decimal("2")),
    ScalingStep(min_balance_usd=Decimal("1500"), max_contracts=Decimal("3")),
    ScalingStep(min_balance_usd=Decimal("2000"), max_contracts=Decimal("5")),
)


def ladder(comparison: str = ">", steps: tuple[ScalingStep, ...] = STEPS) -> ScalingPlanRule:
    return ScalingPlanRule(
        rule_id="xfa_max_contracts",
        steps=steps,
        evaluated="eod",
        basis="balance",
        comparison=comparison,  # type: ignore[arg-type]
        action="clip",
        source=SOURCE,
        evidence="assumption",
        assumption={
            "name": "synthetic",
            "rationale": "a test value",
            "assumption_kind": "owner_decision",
        },
    )


def close(balance: str, *, position: int = 0, entry_ticks: int = 0) -> AccountMarks:
    """A flat book whose end-of-day close marks the balance (equity == balance when flat)."""
    return AccountMarks(
        bar=0,
        open_time_ns=0,
        close_time_ns=0,
        open_ticks=0,
        high_ticks=0,
        low_ticks=0,
        close_ticks=0,
        position=position,
        balance_micro=rl.micro(Decimal(balance)),
        cost_basis_ticks=position * entry_ticks,
        tick_micro=TICK,
    )


def evaluator(rule: ScalingPlanRule | None = None) -> rl.ScalingPlan:
    plan = rule or ladder()
    built = rl.build(plan, rl.micro(Decimal("0")), Decimal("1"))
    assert isinstance(built, rl.ScalingPlan)
    return built


def test_the_xfa_starts_at_zero_so_its_first_day_uses_the_floor_rung() -> None:
    """The page says the XFA starts at a $0 balance; 0 is below 1,500, so day one is 2 lots."""
    plan = evaluator()
    assert plan.contract_limit() == Decimal("2")


def test_a_balance_exactly_on_the_boundary_is_the_lower_tier() -> None:
    """1,500.00 -> 2 lots (the "below $1,500" column); 1,500.01 -> 3 (strictly above it)."""
    plan = evaluator()
    plan.close_of_day(close("1500.00"))
    plan.new_day(1, close("1500.00"))
    assert plan.contract_limit() == Decimal("2")
    plan.close_of_day(close("1500.01"))
    plan.new_day(2, close("1500.01"))
    assert plan.contract_limit() == Decimal("3")


def test_two_thousand_is_also_the_lower_tier_and_above_it_the_largest_rung() -> None:
    """2,000.00 -> 3 lots ("$1,500 - $2,000"); 2,000.01 -> 5 ("above $2,000")."""
    plan = evaluator()
    plan.close_of_day(close("2000.00"))
    plan.new_day(1, close("2000.00"))
    assert plan.contract_limit() == Decimal("3")
    plan.close_of_day(close("2000.01"))
    plan.new_day(2, close("2000.01"))
    assert plan.contract_limit() == Decimal("5")


def test_the_same_ladder_read_inclusively_puts_the_boundary_in_the_upper_rung() -> None:
    """The declaration decides: comparison '>=' is the other reading of the same table.

    It is the reading the owner REJECTED for Topstep (decision 1), and the engine must not choose
    it for the file: 1,500.00 is 3 lots under '>=' and 2 under '>'.
    """
    plan = evaluator(ladder(">="))
    plan.close_of_day(close("1500.00"))
    plan.new_day(1, close("1500.00"))
    assert plan.contract_limit() == Decimal("3")


def test_a_negative_balance_keeps_the_floor_tier() -> None:
    """-250.00 is below the first threshold, so the floor rung (2 lots) applies, never zero."""
    plan = evaluator()
    plan.close_of_day(close("-250.00"))
    plan.new_day(1, close("-250.00"))
    assert plan.contract_limit() == Decimal("2")


def test_the_tier_holds_for_the_whole_session_and_changes_only_at_the_next_one() -> None:
    """A close below 2,000 chooses 3 lots; the limit rises at the NEXT rule-day, never inside one.

    Day 1 closes at 1,800.00 (between the two boundaries) -> day 2 is 3 lots. Day 2 closes at
    2,400.00 -> day 3 is 5. Between those closes ``contract_limit`` does not move, because
    nothing but ``new_day`` assigns ``limit``.
    """
    plan = evaluator()
    plan.close_of_day(close("1800.00"))
    plan.new_day(1, close("1800.00"))
    assert plan.contract_limit() == Decimal("3")
    # ...the account trades up inside day 2; the limit does not follow the equity
    plan.close_of_day(close("2400.00"))
    assert plan.contract_limit() == Decimal("3")
    plan.new_day(2, close("2400.00"))
    assert plan.contract_limit() == Decimal("5")


def test_a_profit_ladder_keeps_its_own_reading_and_its_floor() -> None:
    """The original form: profit since the start, ``>=``, and a balance below the first rung
    gets no contracts at all (no floor rung is declared in that form)."""
    steps = (
        ScalingStep(min_profit_usd=Decimal("1000"), max_contracts=Decimal("2")),
        ScalingStep(min_profit_usd=Decimal("2000"), max_contracts=Decimal("4")),
    )
    rule = ScalingPlanRule(
        rule_id="profit_ladder",
        steps=steps,
        evaluated="eod",
        basis="balance",
        comparison="<=",
        action="clip",
        source=SOURCE,
    )
    plan = rl.build(rule, rl.micro(Decimal("50000")), Decimal("1"))
    assert isinstance(plan, rl.ScalingPlan)
    assert plan.contract_limit() == Decimal("0")
    plan.close_of_day(close("51000"))
    plan.new_day(1, close("51000"))
    assert plan.contract_limit() == Decimal("2")
    plan.close_of_day(close("52000"))
    plan.new_day(2, close("52000"))
    assert plan.contract_limit() == Decimal("4")


def test_a_balance_ladder_refuses_an_intraday_or_equity_or_falling_reading() -> None:
    """Refuse, do not warn: a balance ladder is read at ONE close on ONE quantity."""
    for override, needle in (
        ({"evaluated": "intraday"}, "evaluated: eod"),
        ({"basis": "equity"}, "basis is"),
        ({"comparison": "<="}, "cannot read a balance ladder"),
    ):
        raw = {
            "rule_id": "xfa",
            "steps": STEPS,
            "evaluated": "eod",
            "basis": "balance",
            "comparison": ">",
            "action": "clip",
            "source": SOURCE,
            **override,
        }
        with pytest.raises(ValidationError, match=needle):
            ScalingPlanRule.model_validate(raw)


def test_a_ladder_cannot_mix_the_two_quantities_or_gap_the_floor() -> None:
    """One ladder is read against one quantity, and only the FIRST rung may omit its threshold."""
    with pytest.raises(ValidationError, match="mix"):
        ScalingPlanRule.model_validate(
            {
                "rule_id": "mixed",
                "steps": (
                    ScalingStep(min_profit_usd=Decimal("0"), max_contracts=Decimal("1")),
                    ScalingStep(min_balance_usd=Decimal("1500"), max_contracts=Decimal("2")),
                ),
                "evaluated": "eod",
                "basis": "balance",
                "comparison": ">",
                "action": "clip",
                "source": SOURCE,
            }
        )
    with pytest.raises(ValidationError, match="FLOOR rung"):
        ScalingPlanRule.model_validate(
            {
                "rule_id": "gap",
                "steps": (
                    ScalingStep(min_balance_usd=Decimal("500"), max_contracts=Decimal("1")),
                    ScalingStep(max_contracts=Decimal("2")),
                    ScalingStep(min_balance_usd=Decimal("2000"), max_contracts=Decimal("3")),
                ),
                "evaluated": "eod",
                "basis": "balance",
                "comparison": ">",
                "action": "clip",
                "source": SOURCE,
            }
        )
    with pytest.raises(ValidationError, match="sorted"):
        ScalingPlanRule.model_validate(
            {
                "rule_id": "unsorted",
                "steps": (
                    ScalingStep(max_contracts=Decimal("2")),
                    ScalingStep(min_balance_usd=Decimal("2000"), max_contracts=Decimal("3")),
                    ScalingStep(min_balance_usd=Decimal("1500"), max_contracts=Decimal("4")),
                ),
                "evaluated": "eod",
                "basis": "balance",
                "comparison": ">",
                "action": "clip",
                "source": SOURCE,
            }
        )
