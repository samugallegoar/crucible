"""Prop-firm rules: one evaluator per rule kind, in integer micro-dollars and ticks (ADR-0106).

Every evaluator answers the same four questions, and nothing else:

- ``new_day(day, marks)``: the rule-day changed, so reset (the daily-loss reference, the scaling
  limit for the coming day, the lock). ``day`` is a sortable integer for the rule's own clock.
- ``favorable(marks, price_ticks)``: the bar's favourable extreme, applied before the adverse side
  (``high_before_low_conservative``), so an intraday high-water mark rises first.
- ``thresholds(marks)`` / ``eod(marks)``: the failure thresholds active intrabar and at the
  rule-day close, as ``BreachPrice`` rows already rounded against the strategy.
- ``pass_ok(marks)``: whether a pass condition holds.

A threshold is a money level on a declared basis (``equity`` or ``balance``). Equity is linear in
price with slope ``position * tick_value``, so the price at which a threshold is touched is solved
exactly in integers: a long breaches at the LARGEST tick whose equity is ``<=`` the threshold
(floor), a short at the SMALLEST (ceiling). Touching the threshold is a breach.

Hand-computed arithmetic (ticks, micro-dollars): a long of 1 contract bought at 5000.00 ticks with
a $2,500 drawdown from a $50,000 start has threshold ``50_000_000_000 - 2_500_000_000``
micro-dollars; the breach price is ``(threshold - balance + basis * tick) / (qty * tick)`` ticks
with ``basis = 5000`` and ``tick = 12_500_000`` micro-dollars.
"""

from __future__ import annotations

import datetime as dt
from decimal import ROUND_HALF_UP, Decimal
from typing import TYPE_CHECKING, Any

from crucible.core.errors import ConfigurationError
from crucible.execution.interfaces import AccountMarks, BreachPrice

if TYPE_CHECKING:
    from crucible.prop.ruleset import (
        ComplianceRule,
        ConsistencyRule,
        DailyLossRule,
        DailyProfitCapRule,
        FlatByRule,
        InactivityRule,
        MaxContractsRule,
        MinTradingDaysRule,
        NewsRestrictionRule,
        PayoutRule,
        ProfitTargetRule,
        ScalingPlanRule,
        StaticDrawdownRule,
        TimeLimitRule,
        TrailingDrawdownRule,
    )

_MICRO = 1_000_000
_NS_PER_S = 1_000_000_000
_UTC = dt.UTC


def micro(amount: Decimal, what: str = "amount") -> int:
    """Exact micro-dollars: money is never a float in this package."""
    scaled = amount * _MICRO
    if scaled != scaled.to_integral_value():
        msg = f"{what} = {amount} has more than 6 decimals; money is kept in exact micro-dollars"
        raise ConfigurationError(msg)
    return int(scaled)


def breach_price(marks: AccountMarks, threshold_micro: int) -> int | None:
    """The tick price at which equity touches ``threshold_micro``, rounded against the strategy.

    Long: the largest tick ``p`` with ``equity(p) <= T`` (floor). Short: the smallest tick ``p``
    with ``equity(p) <= T`` (ceiling). None when flat, where equity cannot move. Exact integers:
    ``equity(p) = balance + (q*p - basis) * tick_value <= T`` is ``q*p*tick <= (T - balance) +
    basis*tick``, solved with floor/ceil division of integers.
    """
    q = marks.position
    if q == 0:
        return None
    value = marks.tick_micro
    numerator = (threshold_micro - marks.balance_micro) + marks.cost_basis_ticks * value
    denominator = q * value
    if denominator > 0:
        return numerator // denominator
    return -(numerator // -denominator)


def equity_at(marks: AccountMarks, price_ticks: int) -> int:
    return marks.equity_micro(price_ticks)


def basis_at(marks: AccountMarks, price_ticks: int, basis: str) -> int:
    """A rule's basis at a price: ``equity`` marks the book, ``balance`` is the realized ledger."""
    return marks.balance_micro if basis == "balance" else marks.equity_micro(price_ticks)


def local_day(instant_ns: int, rule_day: dt.time, tz: str) -> int:
    """The rule-day of an instant: the local date after subtracting the reset time in ``tz``,
    as a sortable integer (``YYYYMMDD``)."""
    from zoneinfo import ZoneInfo

    seconds = instant_ns // _NS_PER_S
    local = dt.datetime.fromtimestamp(seconds, _UTC).astimezone(ZoneInfo(tz))
    shifted = local - dt.timedelta(hours=rule_day.hour, minutes=rule_day.minute)
    return shifted.year * 10_000 + shifted.month * 100 + shifted.day


def day_instant_ns(day: int, clock: dt.time, tz: str) -> int:
    """UTC ns of ``clock`` on rule-day ``day`` (a ``YYYYMMDD`` integer) in ``tz``."""
    from zoneinfo import ZoneInfo

    date = dt.date(day // 10_000, (day // 100) % 100, day % 100)
    local = dt.datetime.combine(date, clock).replace(tzinfo=ZoneInfo(tz))
    return int(local.timestamp()) * _NS_PER_S


class DayStats:
    """One rule-day's trading record: fills and balance change, for the minimum-days and
    consistency rules."""

    __slots__ = ("close_balance", "start_balance", "trades")

    def __init__(self, start_balance: int) -> None:
        self.trades = 0
        self.start_balance = start_balance
        self.close_balance = start_balance

    @property
    def pnl(self) -> int:
        return self.close_balance - self.start_balance


class Evaluator:
    """Base evaluator: a rule, the phase's starting balance and the contract weight."""

    def __init__(self, rule: Any, start_micro: int, weight: Decimal) -> None:
        # the rule kinds are a discriminated union; each subclass narrows this annotation
        self.rule: Any = rule
        self.start_micro = start_micro
        self.weight = weight

    @property
    def rule_id(self) -> str:
        return str(self.rule.rule_id)

    @property
    def kind(self) -> str:
        return str(self.rule.kind)

    def new_day(self, day: int, marks: AccountMarks) -> None:
        """The rule-day changed."""

    def favorable(self, marks: AccountMarks, price_ticks: int) -> None:
        """The bar's favourable extreme."""

    def thresholds(self, marks: AccountMarks) -> list[BreachPrice]:
        """Failure thresholds active inside the bar."""
        return []

    def eod(self, marks: AccountMarks) -> list[BreachPrice]:
        """Failure thresholds evaluated at the rule-day close."""
        return []

    def pass_ok(self, marks: AccountMarks) -> bool:
        """Whether this pass condition holds now."""
        return True

    def contract_limit(self) -> Decimal | None:
        """The weighted contract limit this rule imposes today, or None."""
        return None

    def on_excess(self) -> str:
        return "clip"


class ProfitTarget(Evaluator):
    """Pass condition: the basis reaches ``starting_balance + amount``."""

    rule: ProfitTargetRule

    @property
    def threshold(self) -> int:
        return self.start_micro + micro(self.rule.amount_usd, "profit_target.amount_usd")

    def pass_ok(self, marks: AccountMarks) -> bool:
        if self.rule.require_flat and marks.position != 0:
            return False
        if self.rule.basis == "balance":
            return marks.balance_micro >= self.threshold
        if self.rule.evaluated == "intraday":
            best = max(marks.close_ticks, marks.favorable_ticks)
            return marks.equity_micro(best) >= self.threshold
        return marks.equity_micro(marks.close_ticks) >= self.threshold


class StaticDrawdown(Evaluator):
    """Threshold ``starting_balance - amount``; it never trails."""

    rule: StaticDrawdownRule

    @property
    def threshold(self) -> int:
        return self.start_micro - micro(self.rule.amount_usd, "static_drawdown.amount_usd")

    def thresholds(self, marks: AccountMarks) -> list[BreachPrice]:
        if self.rule.evaluated != "intraday" or self.rule.basis == "balance":
            return []
        price = breach_price(marks, self.threshold)
        return [] if price is None else [BreachPrice(price, self.rule_id, True)]

    def eod(self, marks: AccountMarks) -> list[BreachPrice]:
        # an EOD-evaluated threshold is only tested at the rule-day's close; a balance basis only
        # moves on fills, so its check belongs to the close even when declared intraday
        if self.rule.evaluated == "intraday" and self.rule.basis == "equity":
            return []
        value = basis_at(marks, marks.close_ticks, self.rule.basis)
        return (
            [BreachPrice(marks.close_ticks, self.rule_id, True)] if value <= self.threshold else []
        )


class TrailingDrawdown(Evaluator):
    """Threshold ``hwm - amount``, with the mark's basis separate from the tested basis.

    ``mode`` moves the high-water mark (intraday: the favourable extreme; EOD: the rule-day
    close) from ``mark_basis``; ``evaluated`` tests the threshold on ``basis``. A lock freezes
    the threshold, either when the mark reaches a level (``lock.on: hwm``) or on the first payout
    (``lock.on: first_payout``), which the overlay signals.
    """

    rule: TrailingDrawdownRule

    def __init__(self, rule: TrailingDrawdownRule, start_micro: int, weight: Decimal) -> None:
        super().__init__(rule, start_micro, weight)
        self.hwm = start_micro
        self.locked: int | None = None
        self.first_payout: bool = False

    @property
    def threshold(self) -> int:
        if self.locked is not None:
            return self.locked
        amount = micro(self.rule.amount_usd, "trailing_drawdown.amount_usd")
        return self.hwm - amount

    def _observe(self, marks: AccountMarks, price_ticks: int) -> None:
        value = basis_at(marks, price_ticks, self.rule.mark_basis)
        self.hwm = max(self.hwm, value)
        self._apply_lock()

    def _locked_value(self) -> int:
        lock = self.rule.lock
        assert lock is not None
        absolute = lock.locked_threshold_usd
        locked_offset = lock.locked_offset_usd
        if absolute is not None:
            return micro(absolute, "lock.locked_threshold_usd")
        return self.start_micro + micro(
            locked_offset if locked_offset is not None else Decimal(0),
            "lock.locked_offset_usd",
        )

    def _apply_lock(self) -> None:
        lock = self.rule.lock
        if lock is None or self.locked is not None or lock.on != "hwm":
            return
        balance = lock.at_balance_usd
        offset = lock.at_offset_usd
        trigger = (
            micro(balance, "lock.at_balance_usd")
            if balance is not None
            else self.start_micro
            + micro(offset if offset is not None else Decimal(0), "lock.at_offset_usd")
        )
        if self.hwm < trigger:
            return
        self.locked = self._locked_value()

    def on_first_payout(self) -> None:
        """The first withdrawal happened: a payout-triggered lock freezes the threshold now."""
        self.first_payout = True
        lock = self.rule.lock
        if lock is None or lock.on != "first_payout" or self.locked is not None:
            return
        self.locked = self._locked_value()

    def new_day(self, day: int, marks: AccountMarks) -> None:
        return None

    def favorable(self, marks: AccountMarks, price_ticks: int) -> None:
        if self.rule.mode == "intraday":
            self._observe(marks, price_ticks)

    def thresholds(self, marks: AccountMarks) -> list[BreachPrice]:
        # the mark's own update timing (mode) is independent of when the threshold is tested
        if self.rule.evaluated != "intraday" or self.rule.basis == "balance":
            return []
        price = breach_price(marks, self.threshold)
        return [] if price is None else [BreachPrice(price, self.rule_id, True)]

    def eod(self, marks: AccountMarks) -> list[BreachPrice]:
        if self.rule.mode == "eod":
            self._observe(marks, marks.close_ticks)
        if self.rule.evaluated == "intraday" and self.rule.basis == "equity":
            return []
        value = basis_at(marks, marks.close_ticks, self.rule.basis)
        return (
            [BreachPrice(marks.close_ticks, self.rule_id, True)] if value <= self.threshold else []
        )


class DailyLoss(Evaluator):
    """Threshold ``reference - amount`` (or a percentage of the reference), reset at the rule's
    own clock. Soft: liquidate and lock until the reset. Hard: fail."""

    rule: DailyLossRule

    def __init__(self, rule: DailyLossRule, start_micro: int, weight: Decimal) -> None:
        super().__init__(rule, start_micro, weight)
        self.reference = start_micro
        self.prior_close = start_micro
        self.amount = 0
        self.peak_profit = 0
        self.last_amount = 0

    @property
    def threshold(self) -> int:
        return self.reference - self.amount

    @property
    def hard(self) -> bool:
        return self.rule.action == "fail"

    def _tier_amount(self, balance_micro: int) -> int:
        tiers = self.rule.amount_by_balance_tier or ()
        chosen = tiers[0]
        for tier in tiers:
            if balance_micro >= micro(tier.min_balance_usd, "daily_loss.tier.min_balance_usd"):
                chosen = tier
        return micro(chosen.amount_usd, "daily_loss.tier.amount_usd")

    def _ratchet_amount(self, marks: AccountMarks) -> int:
        value = basis_at(marks, marks.close_ticks, self.rule.basis)
        self.peak_profit = max(self.peak_profit, value - self.start_micro)
        pct = self.rule.pct_of_peak_profit
        assert pct is not None
        amount = int(
            (Decimal(self.peak_profit) * pct / 100).to_integral_value(rounding=ROUND_HALF_UP)
        )
        if self.rule.non_decreasing:
            self.last_amount = max(self.last_amount, amount)
            return self.last_amount
        return amount

    def _recompute(self, marks: AccountMarks) -> None:
        if self.rule.amount_by_balance_tier is not None:
            self.amount = self._tier_amount(marks.balance_micro)
        elif self.rule.pct_of_peak_profit is not None:
            self.amount = self._ratchet_amount(marks)
        elif self.rule.amount_usd is not None:
            self.amount = micro(self.rule.amount_usd, "daily_loss.amount_usd")
        else:
            pct = self.rule.pct_of_reference
            assert pct is not None
            self.amount = int(
                (Decimal(self.reference) * pct / 100).to_integral_value(rounding=ROUND_HALF_UP)
            )

    def new_day(self, day: int, marks: AccountMarks) -> None:
        if self.rule.reference == "day_start_balance":
            self.reference = marks.balance_micro
        elif self.rule.reference == "day_start_equity":
            self.reference = marks.equity_micro(marks.open_ticks)
        else:
            self.reference = self.prior_close
        self._recompute(marks)

    def favorable(self, marks: AccountMarks, price_ticks: int) -> None:
        if self.rule.pct_of_peak_profit is not None:
            self._recompute(marks)

    def close_of_day(self, marks: AccountMarks) -> None:
        self.prior_close = marks.balance_micro

    def thresholds(self, marks: AccountMarks) -> list[BreachPrice]:
        if self.rule.evaluated != "intraday" or self.rule.basis == "balance":
            return []
        price = breach_price(marks, self.threshold)
        return [] if price is None else [BreachPrice(price, self.rule_id, self.hard)]

    def eod(self, marks: AccountMarks) -> list[BreachPrice]:
        if self.rule.evaluated == "intraday" and self.rule.basis == "equity":
            return []
        value = basis_at(marks, marks.close_ticks, self.rule.basis)
        if value <= self.threshold:
            return [BreachPrice(marks.close_ticks, self.rule_id, self.hard)]
        return []


def allowed_contracts(limit: Decimal, weight: Decimal) -> int:
    """Whole contracts whose total weight does not exceed ``limit`` (floor; never rounds an
    account into a larger limit than the ruleset grants)."""
    return int((limit / weight).to_integral_value(rounding="ROUND_FLOOR"))


class MaxContracts(Evaluator):
    """Admission limit by contract weight (or per contract), clipped or rejected."""

    rule: MaxContractsRule

    def contract_limit(self) -> Decimal:
        if self.rule.per_instrument is not None:
            return Decimal(self.rule.per_instrument) * self.weight
        assert self.rule.limit is not None
        return self.rule.limit

    def on_excess(self) -> str:
        return self.rule.action


class ScalingPlan(Evaluator):
    """The weighted contract limit for the next rule-day, from the rule-day's end-of-day basis."""

    rule: ScalingPlanRule

    def __init__(self, rule: ScalingPlanRule, start_micro: int, weight: Decimal) -> None:
        super().__init__(rule, start_micro, weight)
        limits = [step.max_contracts for step in rule.steps]
        self.limit = limits[0] if rule.steps[0].min_profit_usd <= 0 else Decimal(0)
        self.next_limit = self.limit

    def close_of_day(self, marks: AccountMarks) -> None:
        profit = basis_at(marks, marks.close_ticks, self.rule.basis) - self.start_micro
        chosen = Decimal(0)
        for step in self.rule.steps:
            if profit >= micro(step.min_profit_usd, "scaling_plan.min_profit_usd"):
                chosen = step.max_contracts
        self.next_limit = chosen

    def new_day(self, day: int, marks: AccountMarks) -> None:
        self.limit = self.next_limit

    def contract_limit(self) -> Decimal:
        return self.limit

    def on_excess(self) -> str:
        return self.rule.action


class FlatBy(Evaluator):
    """A forced-flat clock: an absolute time, or a distance before the session's scheduled end.

    The session-relative form is what makes a holiday early close come from the CME calendar
    instead of a guessed clock time (ADR-0107, vocabulary added in C7b).
    """

    rule: FlatByRule

    def flat_and_reopen(
        self, open_ns: int, close_ns: int, session_close_ns: int = 0
    ) -> tuple[int, int] | None:
        """``(flat_instant_ns, reopen_instant_ns)`` for this bar, or None without a clock."""
        rule = self.rule
        if rule.minutes_before_session_end is not None:
            if session_close_ns <= 0:
                return None
            flat = int(session_close_ns) - rule.minutes_before_session_end * 60 * _NS_PER_S
        else:
            assert rule.time is not None
            assert rule.tz is not None
            day = local_day(open_ns, dt.time(0, 0), rule.tz)
            flat = day_instant_ns(day, rule.time, rule.tz)
        if rule.reopen is not None and rule.tz is not None:
            day = local_day(open_ns, dt.time(0, 0), rule.tz)
            reopen = day_instant_ns(day, rule.reopen, rule.tz)
            if reopen <= flat:
                reopen += 24 * 60 * 60 * _NS_PER_S
        else:
            # a session-relative close has no clock time zone to place a reopen clock in: the
            # forced-flat window is the bar that reaches the flat instant (a firm that states a
            # reopen also states a fixed clock)
            reopen = flat
        return flat, reopen


class MinTradingDays(Evaluator):
    """Pass condition: enough rule-days satisfy the declared day test, in the declared unit."""

    rule: MinTradingDaysRule

    def __init__(
        self, rule: MinTradingDaysRule, start_micro: int, weight: Decimal, days: dict[int, DayStats]
    ) -> None:
        super().__init__(rule, start_micro, weight)
        self.days = days

    def pass_ok(self, marks: AccountMarks) -> bool:
        return self.passes()

    def _counts(self, stats: DayStats) -> bool:
        predicate = self.rule.day_counts_if
        counts = True
        if predicate.min_trades is not None:
            counts = counts and stats.trades >= predicate.min_trades
        if predicate.min_abs_pnl_usd is not None:
            limit = micro(predicate.min_abs_pnl_usd, "min_abs_pnl")
            counts = counts and abs(stats.pnl) >= limit
        if predicate.min_pnl_usd is not None:
            limit = micro(predicate.min_pnl_usd, "min_pnl")
            counts = counts and stats.pnl >= limit
        if self.rule.unit == "winning_days":
            counts = counts and stats.pnl > 0
        return counts

    def passes(self) -> bool:
        return sum(1 for stats in self.days.values() if self._counts(stats)) >= self.rule.days


def consistency_ok(
    rule: ConsistencyRule, days: dict[int, DayStats], since_day: int | None = None
) -> bool:
    """``best_day_profit/total_profit <= max_day_share`` over the declared window.

    A total profit of zero or less satisfies nothing (there is no share of nothing). A payout
    window with ``since_last_payout`` counts only rule-days after the last withdrawal.
    """
    if rule.window == "since_last_payout" and since_day is not None:
        profits = [stats.pnl for day, stats in days.items() if day > since_day]
    else:
        profits = [stats.pnl for stats in days.values()]
    total = sum(profits)
    if total <= 0:
        return False
    share = Decimal(max(profits)) / Decimal(total)
    return share <= rule.max_day_share


class Consistency(Evaluator):
    """The best day's share of total profit is at most ``max_day_share``."""

    rule: ConsistencyRule

    def __init__(
        self,
        rule: ConsistencyRule,
        start_micro: int,
        weight: Decimal,
        days: dict[int, DayStats],
    ) -> None:
        super().__init__(rule, start_micro, weight)
        self.days = days
        self.last_payout_day: int | None = None

    def pass_ok(self, marks: AccountMarks) -> bool:
        # a payout condition never gates the phase pass (it is checked at payout time instead)
        if self.rule.applies_to != "pass":
            return True
        return self.passes()

    def passes(self, since_day: int | None = None) -> bool:
        anchor = self.last_payout_day if since_day is None else since_day
        return consistency_ok(self.rule, self.days, anchor)


class PayoutDecision:
    """One payout the trader takes: ``gross`` withdrawn, ``net`` to the trader, its group."""

    __slots__ = ("gross", "net", "payout_group", "payout_index", "reason", "rule_id")

    def __init__(
        self,
        gross: int,
        net: int,
        rule_id: str,
        *,
        payout_group: str | None = None,
        payout_index: int = 0,
        reason: str = "",
    ) -> None:
        self.gross = gross
        self.net = net
        self.rule_id = rule_id
        self.payout_group = payout_group
        self.payout_index = payout_index
        self.reason = reason


class Payout(Evaluator):
    """Payout eligibility, evaluated at a rule-day's close (ADR-0106 section 4).

    ``withdrawable = balance - (base + buffer_usd)``. The gross is the smallest of the declared
    caps (``max_usd`` or ``unlimited``, ``max_usd_by_payout`` for this payout index,
    ``max_pct_of_balance``, ``max_share_of_withdrawable``) and ``withdrawable``; a payout happens
    only when that gross is at least ``min_usd`` and every gate (trading days since the last
    withdrawal, profitable/traded days in the declared window, the profit gates, the first-payout
    calendar gate, the consistency rule) holds.

    Whether an eligible payout is taken is the trader's choice (``payout_policy``), never a firm
    rule; ``payout_group`` limits a close to at most one payout from the group.
    """

    rule: PayoutRule

    def __init__(self, rule: PayoutRule, start_micro: int, weight: Decimal) -> None:
        super().__init__(rule, start_micro, weight)
        self.base = start_micro
        self.count = 0
        self.last_payout_day: int | None = None
        self.last_payout_trading_day: int | None = None
        self.last_payout_balance = start_micro

    def _window_days(self, days: dict[int, DayStats]) -> list[DayStats]:
        if self.rule.window == "since_last_payout" and self.last_payout_day is not None:
            return [stats for day, stats in days.items() if day > self.last_payout_day]
        return list(days.values())

    def profitable_days(self, days: dict[int, DayStats]) -> int:
        floor = micro(self.rule.min_day_profit_usd, "payout.min_day_profit_usd")
        return sum(1 for stats in self._window_days(days) if stats.pnl >= floor)

    def traded_days(self, days: dict[int, DayStats]) -> int:
        return sum(1 for stats in self._window_days(days) if stats.trades > 0)

    def _cap(self, balance: int, withdrawable: int) -> int:
        rule = self.rule
        cap = withdrawable if rule.max_usd == "unlimited" else micro(rule.max_usd, "payout.max_usd")
        if rule.max_usd_by_payout:
            caps = rule.max_usd_by_payout
            index = min(self.count, len(caps) - 1)
            cap = min(cap, micro(caps[index], f"payout.max_usd_by_payout[{index}]"))
        if rule.max_pct_of_balance is not None:
            cap = min(
                cap,
                int(
                    (Decimal(balance) * rule.max_pct_of_balance / 100).to_integral_value(
                        rounding=ROUND_HALF_UP
                    )
                ),
            )
        if rule.max_share_of_withdrawable is not None:
            cap = min(
                cap,
                int(
                    (Decimal(withdrawable) * rule.max_share_of_withdrawable).to_integral_value(
                        rounding=ROUND_HALF_UP
                    )
                ),
            )
        return cap

    def decision(
        self,
        marks: AccountMarks,
        days: dict[int, DayStats],
        *,
        trading_days: int,
        calendar_days: int,
        consistency_holds: bool,
    ) -> PayoutDecision | None:
        """The payout this close allows, or None. ``marks.balance_micro`` is the balance the
        payout is computed from (already net of earlier withdrawals)."""
        rule = self.rule
        if rule.max_payouts is not None and self.count >= rule.max_payouts:
            return None
        since = (
            trading_days
            if self.last_payout_trading_day is None
            else trading_days - self.last_payout_trading_day
        )
        if since < rule.min_days_since_last:
            return None
        if (
            rule.first_payout_after_calendar_days is not None
            and self.count == 0
            and calendar_days < rule.first_payout_after_calendar_days
        ):
            return None
        if self.profitable_days(days) < rule.min_profitable_days:
            return None
        if self.traded_days(days) < rule.min_traded_days:
            return None
        profit_since = marks.balance_micro - self.last_payout_balance
        if profit_since < micro(rule.min_profit_since_last_usd, "min_profit_since_last_usd"):
            return None
        if rule.cycle_goal_usd is not None and profit_since < micro(
            rule.cycle_goal_usd, "payout.cycle_goal_usd"
        ):
            return None
        if not consistency_holds:
            return None
        buffer = micro(rule.buffer_usd, "payout.buffer_usd")
        withdrawable = marks.balance_micro - (self.base + buffer)
        if withdrawable <= 0:
            return None
        gross = min(self._cap(marks.balance_micro, withdrawable), withdrawable)
        if gross < micro(rule.min_usd, "payout.min_usd"):
            return None
        net = int((Decimal(gross) * rule.split).to_integral_value(rounding=ROUND_HALF_UP))
        return PayoutDecision(
            gross,
            net,
            self.rule_id,
            payout_group=rule.payout_group,
            payout_index=self.count + 1,
            reason=f"withdrawable {withdrawable} micro-dollars",
        )

    def apply(self, decision: PayoutDecision, *, day: int, trading_days: int, balance: int) -> None:
        """Record the payout: the balance has already fallen by ``gross``; update the base."""
        self.count += 1
        self.last_payout_day = day
        self.last_payout_trading_day = trading_days
        self.last_payout_balance = balance
        if self.rule.threshold_after_payout == "trail_from_new_balance":
            self.base = balance
        elif self.rule.threshold_after_payout == "reset_to_start":
            self.base = self.start_micro


class DailyProfitCap(Evaluator):
    """A per-rule-day profit ceiling: forfeit the excess or promote the phase (ADR-0107)."""

    rule: DailyProfitCapRule

    def excess(self, marks: AccountMarks, day_start: int) -> int:
        value = basis_at(marks, marks.close_ticks, self.rule.basis)
        cap = micro(self.rule.amount_usd, "daily_profit_cap.amount_usd")
        return max(0, (value - day_start) - cap)


class Inactivity(Evaluator):
    """A maximum gap between trading days, in the declared unit (ADR-0107)."""

    rule: InactivityRule

    def __init__(self, rule: InactivityRule, start_micro: int, weight: Decimal) -> None:
        super().__init__(rule, start_micro, weight)
        self.last_trade_day: int | None = None
        self.last_trade_date: dt.date | None = None
        self.days_since_trade = 0

    def note_trade(self, day: int, trade_date: dt.date) -> None:
        self.last_trade_day = day
        self.last_trade_date = trade_date
        self.days_since_trade = 0

    def on_new_day(self, day: int, trade_date: dt.date) -> bool:
        """Whether the gap is now exceeded (``True`` is a breach of this rule)."""
        self.days_since_trade += 1
        if self.rule.unit == "calendar_days":
            anchor = self.last_trade_date
            gap = (trade_date - anchor).days if anchor is not None else self.days_since_trade
        else:
            gap = self.days_since_trade
        return gap > self.rule.max_gap


class News(Evaluator):
    """A news restriction: the overlay owns the event calendar and the coverage record."""

    rule: NewsRestrictionRule


class Compliance(Evaluator):
    """A conduct restriction: practical eligibility, never a mechanical account effect."""

    rule: ComplianceRule


class TimeLimit(Evaluator):
    """A phase without a pass within the limit times out."""

    rule: TimeLimitRule

    def __init__(
        self,
        rule: TimeLimitRule,
        start_micro: int,
        weight: Decimal,
        start_day: dt.date,
    ) -> None:
        super().__init__(rule, start_micro, weight)
        self.start_day = start_day
        self.trading_days = 0

    def new_day(self, day: int, marks: AccountMarks) -> None:
        self.trading_days += 1

    def timed_out(self, today: dt.date) -> bool:
        """The limit is exhausted without a pass: the day count reached it."""
        if self.rule.max_calendar_days is not None:
            return (today - self.start_day).days >= self.rule.max_calendar_days
        assert self.rule.max_trading_days is not None
        return self.trading_days >= self.rule.max_trading_days


class Fee(Evaluator):
    """Attempt cost accounting only; it never touches the trading ledger."""


def build(
    rule: Any,
    start_micro: int,
    weight: Decimal,
    *,
    days: dict[int, DayStats] | None = None,
    start_day: dt.date | None = None,
) -> Evaluator:
    """The evaluator for one typed rule. A kind without an evaluator is refused (ADR-0106: a
    rule the engine cannot express goes to ``not_modeled``, it is never approximated)."""
    from crucible.prop import ruleset as rs

    kind = str(rule.kind)
    if isinstance(rule, rs.ProfitTargetRule):
        return ProfitTarget(rule, start_micro, weight)
    if isinstance(rule, rs.StaticDrawdownRule):
        return StaticDrawdown(rule, start_micro, weight)
    if isinstance(rule, rs.TrailingDrawdownRule):
        return TrailingDrawdown(rule, start_micro, weight)
    if isinstance(rule, rs.DailyLossRule):
        return DailyLoss(rule, start_micro, weight)
    if isinstance(rule, rs.MaxContractsRule):
        return MaxContracts(rule, start_micro, weight)
    if isinstance(rule, rs.ScalingPlanRule):
        return ScalingPlan(rule, start_micro, weight)
    if isinstance(rule, rs.FlatByRule):
        return FlatBy(rule, start_micro, weight)
    if isinstance(rule, rs.MinTradingDaysRule):
        assert days is not None
        return MinTradingDays(rule, start_micro, weight, days)
    if isinstance(rule, rs.ConsistencyRule):
        assert days is not None
        return Consistency(rule, start_micro, weight, days)
    if isinstance(rule, rs.PayoutRule):
        return Payout(rule, start_micro, weight)
    if isinstance(rule, rs.TimeLimitRule):
        assert start_day is not None
        return TimeLimit(rule, start_micro, weight, start_day)
    if isinstance(rule, rs.FeeRule):
        return Fee(rule, start_micro, weight)
    if isinstance(rule, rs.DailyProfitCapRule):
        return DailyProfitCap(rule, start_micro, weight)
    if isinstance(rule, rs.InactivityRule):
        return Inactivity(rule, start_micro, weight)
    if isinstance(rule, rs.NewsRestrictionRule):
        return News(rule, start_micro, weight)
    if isinstance(rule, rs.ComplianceRule):
        return Compliance(rule, start_micro, weight)
    msg = (
        f"rule kind {kind!r} has no evaluator in crucible.prop.rules: a rule the engine cannot "
        "express must be listed in the ruleset's not_modeled, never approximated"
    )
    raise ConfigurationError(msg)
