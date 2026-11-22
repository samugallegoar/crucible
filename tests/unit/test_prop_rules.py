"""Prop-firm rule evaluators (ADR-0106 section 4): the integer arithmetic, hand-computed.

Every expected value here is written out as arithmetic in the test. Money is micro-dollars and
prices are integer ticks of the ES contract (tick 0.25, $12.50 per tick) unless stated otherwise.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest
from pydantic import ValidationError

from crucible.core.errors import ConfigurationError
from crucible.execution.interfaces import AccountMarks
from crucible.prop import rules as rl
from crucible.prop.ruleset import (
    Attribution,
    ConsistencyRule,
    DailyLossRule,
    DayCountsIf,
    MaxContractsRule,
    MinTradingDaysRule,
    ResetClock,
    StaticDrawdownRule,
    TrailingDrawdownRule,
    TrailingLock,
)

TICK = 12_500_000  # $12.50 per tick in micro-dollars
SOURCE = Attribution(
    url="https://example.invalid/synthetic-rules",
    quote="Synthetic rule value invented for a test, not a real firm's rule",
    snapshot_sha256="0" * 64,
    retrieved_at=dt.datetime(2024, 1, 1, tzinfo=dt.UTC),
    synthetic=True,
)


def marks(
    position: int,
    balance: str,
    entry_ticks: int,
    *,
    open_ticks: int = 20_000,
    high_ticks: int = 20_000,
    low_ticks: int = 20_000,
    close_ticks: int = 20_000,
) -> AccountMarks:
    """A 1-lot (or signed n-lot) book marked at the given prices, in micro-dollars."""
    return AccountMarks(
        bar=0,
        open_time_ns=0,
        close_time_ns=0,
        open_ticks=open_ticks,
        high_ticks=high_ticks,
        low_ticks=low_ticks,
        close_ticks=close_ticks,
        position=position,
        balance_micro=rl.micro(Decimal(balance)),
        cost_basis_ticks=position * entry_ticks,
        tick_micro=TICK,
    )


def test_breach_price_long_is_the_largest_tick_below_the_threshold() -> None:
    """Long 1 at 5,000.00 with balance 49,979.25, threshold 47,500.00.

    equity(p) = 49,979.25 + (p - 5,000) * 50 <= 47,500  =>  p <= 4,950.415, and the largest tick
    at or below that is 4,950.25 = 19,801 ticks. Equity there is 47,491.75, at 4,950.50 it is
    47,504.25 > 47,500.
    """
    book = marks(1, "49979.25", 20_000)
    assert rl.breach_price(book, 47_500_000_000) == 19_801
    assert book.equity_micro(19_801) == 47_491_750_000
    assert book.equity_micro(19_802) == 47_504_250_000


def test_breach_price_short_is_the_smallest_tick_above_the_threshold() -> None:
    """Short 1 at 5,000.00 (20,000 ticks) with balance 49,979.25, threshold 47,500.00.

    equity(p) = 49,979.25 + (20,000 - p) * 12.50 <= 47,500  =>  p >= 20,198.34 ticks, and the
    smallest tick at or above that is 20,198.50 = 20,199 ticks. Equity there is 47,491.75; at
    20,198.00 it is 47,504.25 > 47,500.
    """
    book = marks(-1, "49979.25", 20_000)
    assert rl.breach_price(book, 47_500_000_000) == 20_199
    assert book.equity_micro(20_199) == 47_491_750_000
    assert book.equity_micro(20_198) == 47_504_250_000


def test_breach_price_is_undefined_when_flat() -> None:
    """Equity cannot move without a position, so there is no price that breaches."""
    assert rl.breach_price(marks(0, "50000", 0), 1) is None


def test_static_drawdown_threshold_and_flat_balance_basis() -> None:
    rule = StaticDrawdownRule(
        rule_id="dd",
        amount_usd=Decimal("2500"),
        basis="balance",
        evaluated="intraday",
        comparison="<=",
        action="fail",
        source=SOURCE,
    )
    evaluator = rl.build(rule, 50_000_000_000, Decimal(1))
    assert isinstance(evaluator, rl.StaticDrawdown)
    assert evaluator.threshold == 47_500_000_000
    # a balance basis has no intrabar breach price: the check is at the close
    assert evaluator.thresholds(marks(1, "47000", 20_000)) == []
    breaches = evaluator.eod(marks(1, "47000", 20_000, close_ticks=19_000))
    assert [(b.rule_id, b.hard) for b in breaches] == [("dd", True)]


def test_daily_loss_percentage_rounds_half_up_on_the_reference() -> None:
    """2.5% of 50,000.00 is 1,250.00 micro-rounded exactly; threshold 48,750.00."""
    rule = DailyLossRule(
        rule_id="daily",
        pct_of_reference=Decimal("2.5"),
        reference="day_start_balance",
        basis="equity",
        evaluated="intraday",
        comparison="<=",
        action="soft_lock_until_reset",
        reset=ResetClock(time=dt.time(17, 0), tz="America/Chicago"),
        source=SOURCE,
    )
    evaluator = rl.build(rule, 50_000_000_000, Decimal(1))
    assert isinstance(evaluator, rl.DailyLoss)
    book = marks(1, "50000", 20_000, open_ticks=20_000)
    evaluator.new_day(1, book)
    assert evaluator.reference == 50_000_000_000
    assert evaluator.amount == 1_250_000_000
    assert evaluator.threshold == 48_750_000_000
    assert evaluator.hard is False


def test_trailing_lock_freezes_the_threshold_once_the_hwm_reaches_it() -> None:
    """Trailing intraday 2,500 with a lock at a 51,000.00 hwm and a 49,000.00 threshold.

    A favourable equity of 51,029.25 (the high 5,021.00 on a 1-lot entered at 5,000.00 with
    balance 49,979.25) engages the lock, so the threshold is 49,000.00 and the breach price is
    4,980.25. Unlocked it would be 51,029.25 - 2,500 = 48,529.25 (breach 4,971.00).
    """
    rule = TrailingDrawdownRule(
        rule_id="trail",
        amount_usd=Decimal("2500"),
        mode="intraday",
        evaluated="intraday",
        basis="equity",
        hwm_basis="equity",
        comparison="<=",
        action="fail",
        lock=TrailingLock(
            on="hwm",
            at_balance_usd=Decimal("51000"),
            locked_threshold_usd=Decimal("49000"),
        ),
        source=SOURCE,
    )
    evaluator = rl.build(rule, 50_000_000_000, Decimal(1))
    assert isinstance(evaluator, rl.TrailingDrawdown)
    before = marks(1, "49979.25", 20_000, high_ticks=20_084, low_ticks=19_820)
    evaluator.favorable(before, 20_084)  # equity 51,979.25 > 51,000: the lock engages
    assert evaluator.locked == 49_000_000_000
    assert [b.price_ticks for b in evaluator.thresholds(before)] == [19_921]
    never = rl.TrailingDrawdown(
        TrailingDrawdownRule(
            rule_id="trail",
            amount_usd=Decimal("2500"),
            mode="intraday",
            evaluated="intraday",
            basis="equity",
            hwm_basis="equity",
            comparison="<=",
            action="fail",
            source=SOURCE,
        ),
        50_000_000_000,
        Decimal(1),
    )
    never.favorable(before, 20_084)
    assert never.threshold == 51_029_250_000 - 2_500_000_000
    assert [b.price_ticks for b in never.thresholds(before)] == [19_884]


def test_weighted_contract_limits_floor_to_whole_contracts() -> None:
    """2 minis of weight 1 allow 2; 2 minis of weight 0.1 allow 20 micros; 1 of weight 0.3
    allows 3 (3 * 0.3 = 0.9 <= 1, 4 * 0.3 = 1.2 > 1)."""
    assert rl.allowed_contracts(Decimal(2), Decimal(1)) == 2
    assert rl.allowed_contracts(Decimal(2), Decimal("0.1")) == 20
    assert rl.allowed_contracts(Decimal(1), Decimal("0.3")) == 3
    per_instrument = MaxContractsRule(
        rule_id="c",
        per_instrument=3,
        comparison="<=",
        action="clip",
        source=SOURCE,
    )
    evaluator = rl.build(per_instrument, 0, Decimal("0.1"))
    assert isinstance(evaluator, rl.MaxContracts)
    assert evaluator.contract_limit() == Decimal("0.3")


def test_rule_day_comes_from_the_reset_clock_in_its_zone() -> None:
    """A 17:00 America/Chicago reset: 2024-01-08 16:00 Chicago is the 2024-01-07 rule-day and
    2024-01-08 17:01 Chicago is the 2024-01-08 rule-day."""
    utc = dt.UTC
    sixteen = int(dt.datetime(2024, 1, 8, 22, 0, tzinfo=utc).timestamp()) * 1_000_000_000
    seventeen = int(dt.datetime(2024, 1, 8, 23, 1, tzinfo=utc).timestamp()) * 1_000_000_000
    clock = dt.time(17, 0)
    assert rl.local_day(sixteen, clock, "America/Chicago") == 20_240_107
    assert rl.local_day(seventeen, clock, "America/Chicago") == 20_240_108
    # the flat-by clock of that rule-day is 17:00 Chicago = 23:00 UTC in January
    assert rl.day_instant_ns(20_240_108, clock, "America/Chicago") == seventeen - 60 * 1_000_000_000


def test_consistency_is_the_best_days_share_of_total_profit() -> None:
    """458.50 and 458.50: the best share is 458.50 / 917.00 = 0.5, inside 0.8. A single day of
    917.00 is a share of 1.0 and outside it, and a loss-making total satisfies nothing."""
    rule = ConsistencyRule(
        rule_id="c",
        max_day_share=Decimal("0.8"),
        measure="best_day_profit/total_profit",
        applies_to="pass",
        window="all_time",
        comparison="<=",
        action="promote_phase",
        source=SOURCE,
    )
    two_days = {1: rl.DayStats(0), 2: rl.DayStats(0)}
    two_days[1].close_balance = 458_500_000
    two_days[2].close_balance = 458_500_000
    assert rl.consistency_ok(rule, two_days) is True
    one_day = {1: rl.DayStats(0)}
    one_day[1].close_balance = 917_000_000
    assert rl.consistency_ok(rule, one_day) is False
    losing = {1: rl.DayStats(0), 2: rl.DayStats(0)}
    losing[1].close_balance = -100_000_000
    losing[2].close_balance = 50_000_000
    assert rl.consistency_ok(rule, losing) is False


def test_min_trading_days_counts_only_days_that_satisfy_the_day_test() -> None:
    """Two days are required; a day counts when it has at least one trade."""
    rule = MinTradingDaysRule(
        rule_id="days",
        days=2,
        unit="trading_days",
        day_counts_if=DayCountsIf(min_trades=1),
        comparison=">=",
        action="promote_phase",
        source=SOURCE,
    )
    days = {1: rl.DayStats(0), 2: rl.DayStats(0), 3: rl.DayStats(0)}
    days[1].trades = 1
    days[2].trades = 0
    days[3].trades = 2
    evaluator = rl.build(rule, 0, Decimal(1), days=days)
    assert isinstance(evaluator, rl.MinTradingDays)
    assert evaluator.passes() is True  # days 1 and 3 count, day 2 does not
    days[3].trades = 0
    assert evaluator.passes() is False


def test_a_rule_kind_without_an_evaluator_is_refused() -> None:
    """ADR-0106: a rule the engine cannot express goes to ``not_modeled``, never approximated."""

    class Payout:
        kind = "payout"
        rule_id = "payout"

    with pytest.raises(ConfigurationError):
        rl.build(Payout(), 0, Decimal(1))


# --------------------------------------------- F2: evaluated is a separate, required declaration


def test_an_eod_evaluated_static_drawdown_has_no_intrabar_breach_price() -> None:
    """``evaluated: eod``: no price test exists inside the bar; only the close basis is checked.

    Equity at 4,955.00 would be 47,729.25... above the 47,500.00 threshold, but the price test is
    not even asked for: ``thresholds`` is empty and the close below it is what breaches.
    """
    rule = StaticDrawdownRule(
        rule_id="dd",
        amount_usd=Decimal("2500"),
        basis="equity",
        evaluated="eod",
        comparison="<=",
        action="fail",
        source=SOURCE,
    )
    evaluator = rl.build(rule, 50_000_000_000, Decimal(1))
    book = marks(1, "49979.25", 20_000, high_ticks=20_100, low_ticks=19_820, close_ticks=19_720)
    assert evaluator.thresholds(book) == []
    assert [b.price_ticks for b in evaluator.eod(book)] == [19_720]
    assert evaluator.eod(marks(1, "49979.25", 20_000, close_ticks=20_040)) == []


def test_an_eod_evaluated_daily_loss_is_only_tested_at_the_close() -> None:
    """Daily loss 1,000.00 evaluated at the close: no intrabar price, a breach at the close.

    The day's reference is the balance at its start, 49,979.25, so the threshold is
    49,979.25 - 1,000.00 = 48,979.25 and the close at 4,980.00 gives exactly that.
    """
    rule = DailyLossRule(
        rule_id="daily",
        amount_usd=Decimal("1000"),
        reference="day_start_balance",
        basis="equity",
        evaluated="eod",
        comparison="<=",
        action="fail",
        reset=ResetClock(time=dt.time(17, 0), tz="America/Chicago"),
        source=SOURCE,
    )
    evaluator = rl.build(rule, 50_000_000_000, Decimal(1))
    book = marks(1, "49979.25", 20_000, high_ticks=20_040, close_ticks=19_920)
    evaluator.new_day(1, book)
    assert evaluator.threshold == 48_979_250_000
    assert evaluator.thresholds(book) == []
    assert [(b.price_ticks, b.hard) for b in evaluator.eod(book)] == [(19_920, True)]


def test_eod_mode_trailing_with_intraday_evaluation_tests_the_threshold_intrabar() -> None:
    """``mode: eod`` moves the mark at the close; ``evaluated: intraday`` still tests the
    threshold on every bar, so the breach price exists (the previous behaviour stays expressible).

    HWM 50,000.00 (the close raised it to equity 51,029.25 above, but the capital base is a floor),
    threshold 47,500.00, breach price 4,950.25 = 19,801 ticks on a 1-lot entered at 20,000 ticks.
    """
    rule = TrailingDrawdownRule(
        rule_id="trail",
        amount_usd=Decimal("2500"),
        mode="eod",
        evaluated="intraday",
        basis="equity",
        hwm_basis="equity",
        comparison="<=",
        action="fail",
        source=SOURCE,
    )
    evaluator = rl.build(rule, 50_000_000_000, Decimal(1))
    book = marks(1, "49979.25", 20_000, low_ticks=19_820)
    assert [b.price_ticks for b in evaluator.thresholds(book)] == [19_801]
    assert evaluator.eod(book) == []


def test_evaluated_is_required_on_every_threshold_rule() -> None:
    """A firm declares when its threshold is tested: the model refuses to guess."""
    with pytest.raises(ValidationError):
        StaticDrawdownRule(rule_id="dd", amount_usd=Decimal("2500"), source=SOURCE)
    with pytest.raises(ValidationError):
        TrailingDrawdownRule(rule_id="trail", amount_usd=Decimal("2500"), mode="eod", source=SOURCE)
    with pytest.raises(ValidationError):
        DailyLossRule(rule_id="daily", amount_usd=Decimal("1000"), source=SOURCE)
