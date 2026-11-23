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
from decimal import ROUND_FLOOR, ROUND_HALF_UP, Decimal
from typing import TYPE_CHECKING, Any, Literal

from crucible.core.errors import ConfigurationError
from crucible.execution.interfaces import AccountMarks, BreachPrice

if TYPE_CHECKING:
    from crucible.prop.ruleset import (
        ActivityRequirementRule,
        ComplianceRule,
        ConsistencyRule,
        DailyLossRule,
        DailyProfitCapRule,
        DayCountsIf,
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


def day_counts(stats: DayStats, predicate: DayCountsIf) -> bool:
    """Whether a rule-day satisfies the declared day predicate (trades and/or P&L).

    ``min_abs_pnl_usd`` counts a day that moved either way, ``min_pnl_usd`` a day that ended at
    least that far up; a firm states one or the other, never both.
    """
    counts = True
    if predicate.min_trades is not None:
        counts = counts and stats.trades >= predicate.min_trades
    if predicate.min_abs_pnl_usd is not None:
        counts = counts and abs(stats.pnl) >= micro(predicate.min_abs_pnl_usd, "min_abs_pnl")
    if predicate.min_pnl_usd is not None:
        counts = counts and stats.pnl >= micro(predicate.min_pnl_usd, "min_pnl")
    return counts


def pass_frequency(rule: object) -> Literal["intraday", "eod"]:
    """When a pass condition is tested: at every bar's close, or only at the rule-day's end.

    ADR-0106 section 3 step 8 and ADR-0107 section 9 put the pass conditions at the rule-day's
    close, after the threshold tests. A firm that states ``evaluated: eod`` means exactly that: its
    target is tested on the CLOSED figure of the trade date and never on an intraday close, so a
    target touched inside a bar and lost again by the close does not pass. ``evaluated: intraday``
    is tested at every bar's close, and a touch counts at the bar's favourable extreme. A pass
    condition that declares no frequency (``min_trading_days``, ``consistency``) is tested at every
    close as well: those rules read the CLOSED rule-days, so a test before a day closes simply
    restates the previous answer. ``on_request`` has no channel in a simulation and is treated the
    same way (it is never promoted to a rule-day-only test either).
    """
    return "eod" if getattr(rule, "evaluated", None) == "eod" else "intraday"


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

    def observed(self, marks: AccountMarks, price_ticks: int) -> list[BreachPrice]:
        """A threshold the account is ALREADY past at ``price_ticks`` (ADR-0106 amendment).

        Tested by the overlay immediately after every fill and every cost posting, flat or not:
        a fill moves the realized balance and with it the basis a loss threshold is measured on, so
        a threshold can be crossed with no position left to solve a breach price from. Only an
        ``evaluated: intraday`` threshold is tested this way; an EOD-evaluated one is still tested
        at the rule-day's close alone.
        """
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

    def observed(self, marks: AccountMarks, price_ticks: int) -> list[BreachPrice]:
        if self.rule.evaluated != "intraday":
            return []
        value = basis_at(marks, price_ticks, self.rule.basis)
        return [BreachPrice(price_ticks, self.rule_id, True)] if value <= self.threshold else []

    def eod(self, marks: AccountMarks) -> list[BreachPrice]:
        # an EOD-evaluated threshold is only tested at the rule-day's close; a balance basis only
        # moves on fills, so its close check stays even when declared intraday
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
        if lock is None or self.locked is not None or "hwm" not in lock.on:
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
        if lock is None or "first_payout" not in lock.on or self.locked is not None:
            return
        self.locked = self._locked_value()

    def lock_at(self, level_micro: int) -> None:
        """Freeze the threshold at an explicit level (a payout's ``threshold_after_payout``).

        Used by ``payout.threshold_after_payout: set_threshold``: after the withdrawal the firm
        states the level the threshold sits at instead of letting it trail.
        """
        self.locked = int(level_micro)

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

    def observed(self, marks: AccountMarks, price_ticks: int) -> list[BreachPrice]:
        if self.rule.evaluated != "intraday":
            return []
        value = basis_at(marks, price_ticks, self.rule.basis)
        return [BreachPrice(price_ticks, self.rule_id, True)] if value <= self.threshold else []

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

    def observed(self, marks: AccountMarks, price_ticks: int) -> list[BreachPrice]:
        if self.rule.evaluated != "intraday":
            return []
        value = basis_at(marks, price_ticks, self.rule.basis)
        return (
            [BreachPrice(price_ticks, self.rule_id, self.hard)] if value <= self.threshold else []
        )

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
        elif rule.minutes_before_session_end is not None:
            # a session-relative close: no entry from the flat instant until the scheduled
            # session close (the next session's open is after it), so a strategy cannot re-enter
            # in the minutes between the firm's flat time and the session end
            reopen = int(session_close_ns)
        else:
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
        counts = day_counts(stats, self.rule.day_counts_if)
        if self.rule.unit == "winning_days":
            counts = counts and stats.pnl > 0
        return counts

    def passes(self) -> bool:
        return sum(1 for stats in self.days.values() if self._counts(stats)) >= self.rule.days


def consistency_ok(
    rule: ConsistencyRule,
    days: dict[int, DayStats],
    since_day: int | None = None,
    *,
    cycle_profit: int | None = None,
) -> bool:
    """``best_day_profit/total_profit <= max_day_share`` over the two declared windows.

    The numerator's window (which day is the best) and the denominator's (which profit it is
    shared with) are separate: ``all_time`` every rule-day, ``since_last_payout`` the rule-days
    after the previous withdrawal, and ``current_cycle`` the profit of the payout cycle measured
    from the balance the cycle opened at (``cycle_profit``; absent it falls back to the rule-days
    since the last payout). A total profit of zero or less satisfies nothing (there is no share of
    nothing).
    """
    if rule.best_day_window == "since_last_payout" and since_day is not None:
        numerator = [stats.pnl for day, stats in days.items() if day > since_day]
    else:
        numerator = [stats.pnl for stats in days.values()]
    if rule.profit_window == "all_time":
        total = sum(stats.pnl for stats in days.values())
    elif rule.profit_window == "current_cycle" and cycle_profit is not None:
        total = int(cycle_profit)
    elif since_day is not None:
        total = sum(stats.pnl for day, stats in days.items() if day > since_day)
    else:
        total = sum(stats.pnl for stats in days.values())
    if not numerator or total <= 0:
        return False
    share = Decimal(max(numerator)) / Decimal(total)
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
        self.cycle_open_balance: int | None = None
        """The balance the current payout cycle opened at (after the last withdrawal), for a
        ``current_cycle`` denominator; None means the cycle opened at the phase's start."""

    def pass_ok(self, marks: AccountMarks) -> bool:
        # a payout condition never gates the phase pass (it is checked at payout time instead)
        if self.rule.applies_to != "pass":
            return True
        return self.passes(balance=marks.balance_micro)

    def passes(self, since_day: int | None = None, *, balance: int | None = None) -> bool:
        anchor = self.last_payout_day if since_day is None else since_day
        cycle = None if balance is None else self.cycle_profit(balance)
        return consistency_ok(self.rule, self.days, anchor, cycle_profit=cycle)

    def cycle_profit(self, balance: int) -> int:
        """The current payout cycle's profit: the balance less the balance the cycle opened at."""
        opening = self.start_micro if self.cycle_open_balance is None else self.cycle_open_balance
        return int(balance) - int(opening)


class PayoutDecision:
    """One payout the trader takes: ``gross`` withdrawn, ``net`` to the trader, its group.

    ``bound`` is ``exact`` or ``upper_bound``: a cap the sources do not state makes the amount the
    most the other terms allow, never an unlimited one (ADR-0107 section 7).
    """

    __slots__ = ("bound", "gross", "net", "payout_group", "payout_index", "reason", "rule_id")

    def __init__(
        self,
        gross: int,
        net: int,
        rule_id: str,
        *,
        payout_group: str | None = None,
        payout_index: int = 0,
        reason: str = "",
        bound: str = "exact",
    ) -> None:
        self.gross = gross
        self.net = net
        self.rule_id = rule_id
        self.payout_group = payout_group
        self.payout_index = payout_index
        self.reason = reason
        self.bound = bound


class Payout(Evaluator):
    """Payout eligibility, evaluated at a rule-day's close (ADR-0106 section 4).

    ``withdrawable = balance - (base + buffer_usd)``. The gross is the smallest of the declared
    caps (``max_usd`` or ``unlimited``, ``max_usd_by_payout`` for this payout index,
    ``max_pct_of_balance``, ``max_share_of_withdrawable``, ``min_new_profit_share_of_request``)
    and ``withdrawable``; a payout happens only when that gross is at least ``min_usd`` and every
    gate (trading days since the last withdrawal, profitable/traded days in the declared window,
    the profit gates, the first-payout calendar gate, the consistency rule) holds.

    A cap the source does not state is ``unknown``: it does not bind (the payout is what the other
    terms allow) and the decision is labelled ``upper_bound``. It is never read as ``unlimited``.

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
        # ``unlimited`` and ``unknown`` do not bind arithmetically; only ``unknown`` is labelled
        cap = withdrawable
        if isinstance(rule.max_usd, Decimal):
            cap = min(cap, micro(rule.max_usd, "payout.max_usd"))
        if rule.max_usd_by_payout:
            caps = rule.max_usd_by_payout
            index = min(self.count, len(caps) - 1)
            declared = caps[index]
            if isinstance(declared, Decimal):
                cap = min(cap, micro(declared, f"payout.max_usd_by_payout[{index}]"))
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
        cap = self._cap(marks.balance_micro, withdrawable)
        share = rule.min_new_profit_share_of_request
        if share is not None:
            # a request of X needs new profit >= share * X: the largest X that satisfies it
            cap = min(
                cap,
                int((Decimal(profit_since) / share).to_integral_value(rounding=ROUND_FLOOR)),
            )
        gross = min(cap, withdrawable)
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
            bound="upper_bound" if rule.unknown_cap else "exact",
        )

    def threshold_level(self) -> int:
        """The explicit level ``threshold_after_payout: set_threshold`` sets, in micro-dollars.

        ``start`` is the phase's starting balance, ``start_plus_usd`` that balance plus a fixed
        amount, ``zero_balance_offset`` an absolute level above a zero balance.
        """
        from crucible.prop.rules_schema import threshold_level

        declared = self.rule.set_threshold_to
        if declared is None:
            msg = (
                f"payout {self.rule_id}: threshold_after_payout is not set_threshold, so it has no "
                "explicit level to set"
            )
            raise ConfigurationError(msg)
        kind, amount = threshold_level(declared)
        if kind == "start":
            return self.start_micro
        value = micro(amount, f"payout.set_threshold_to[{kind}]")
        return self.start_micro + value if kind == "start_plus_usd" else value

    def apply(self, decision: PayoutDecision, *, day: int, trading_days: int, balance: int) -> None:
        """Record the payout: the balance has already fallen by ``gross``; update the base."""
        self.count += 1
        self.last_payout_day = day
        self.last_payout_trading_day = trading_days
        self.last_payout_balance = balance
        if self.rule.threshold_after_payout == "trail_from_new_balance":
            self.base = balance
        elif self.rule.threshold_after_payout in ("reset_to_start", "set_threshold"):
            self.base = (
                self.start_micro
                if self.rule.threshold_after_payout == "reset_to_start"
                else self.threshold_level()
            )


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
    """A news restriction: the overlay owns the event calendar and the coverage record.

    With ``effect: contract_cap`` an active window also clips the admitted size to
    ``cap_contracts`` (a contract WEIGHT); the overlay sets ``cap_active`` per bar, because only
    it knows the calendar windows.
    """

    rule: NewsRestrictionRule

    def __init__(self, rule: NewsRestrictionRule, start_micro: int, weight: Decimal) -> None:
        super().__init__(rule, start_micro, weight)
        self.cap_active: bool = False

    def contract_limit(self) -> Decimal | None:
        if self.rule.effective_effect != "contract_cap" or not self.cap_active:
            return None
        assert self.rule.cap_contracts is not None
        return self.rule.cap_contracts

    def on_excess(self) -> str:
        return "clip"


class ActivityRequirement(Evaluator):
    """At least ``days`` qualifying rule-days in EVERY rolling window of ``window`` days.

    The window is the one ending at the rule-day being closed, and it is tested only once it is
    full: for ``calendar_days`` from the phase's start to the day, for ``trading_days`` the last
    ``window`` closed rule-days. Days come from the overlay's closed rule-days, so a window is
    judged on complete days only (never on the day in progress).
    """

    rule: ActivityRequirementRule

    def __init__(
        self,
        rule: ActivityRequirementRule,
        start_micro: int,
        weight: Decimal,
        days: dict[int, DayStats],
        start_day: dt.date,
    ) -> None:
        super().__init__(rule, start_micro, weight)
        self.days = days
        self.start_day = start_day

    def _window(self, today: dt.date) -> list[DayStats]:
        ordered = sorted(self.days.items())
        if self.rule.unit == "trading_days":
            if len(ordered) < self.rule.window:
                return []
            return [stats for _, stats in ordered[-self.rule.window :]]
        low = today - dt.timedelta(days=self.rule.window - 1)
        return [stats for day, stats in ordered if low <= rule_date(day) <= today]

    def full(self, today: dt.date) -> bool:
        """Whether a whole window has elapsed, so its count can be judged."""
        if self.rule.unit == "trading_days":
            return len(self.days) >= self.rule.window
        return (today - self.start_day).days + 1 >= self.rule.window

    def violated(self, today: dt.date) -> bool:
        """Whether the window ending at ``today`` holds fewer than the required qualifying days."""
        if not self.full(today):
            return False
        qualifying = sum(
            1 for stats in self._window(today) if day_counts(stats, self.rule.qualifies_if)
        )
        return qualifying < self.rule.days


def rule_date(day: int) -> dt.date:
    """The calendar date of a rule-day integer (``YYYYMMDD``, as ``local_day`` returns)."""
    return dt.date(day // 10_000, (day // 100) % 100, day % 100)


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
    if isinstance(rule, rs.ActivityRequirementRule):
        assert days is not None
        assert start_day is not None
        return ActivityRequirement(rule, start_micro, weight, days, start_day)
    if isinstance(rule, rs.NewsRestrictionRule):
        return News(rule, start_micro, weight)
    if isinstance(rule, rs.ComplianceRule):
        return Compliance(rule, start_micro, weight)
    msg = (
        f"rule kind {kind!r} has no evaluator in crucible.prop.rules: a rule the engine cannot "
        "express must be listed in the ruleset's not_modeled, never approximated"
    )
    raise ConfigurationError(msg)
