"""The prop-firm account overlay: the phase's rules enforced bar by bar (ADR-0106 section 3).

``PropAccountOverlay`` implements ``crucible.execution.interfaces.AccountOverlay`` for one phase
of one attempt. It holds the phase's typed rules, the phase's starting balance, the rule-day
clock and the day statistics, and answers the simulator at the fixed points of every bar: the
rule-day transition and the gap test (steps 1-2), the forced-flat window (step 6), admission
(step 3), the favourable extreme and the breach prices of the adverse walk (steps 4-5), and the
close with its end-of-day rules and pass conditions (step 8). It never reads a bar after the one
it is acting on; its state is ``Snapshottable`` so a checkpoint can resume it (ADR-0041).

Semantics, all from the ruleset and never from a firm:

- A failure threshold is a money level on equity or balance. Equity is linear in price, so its
  breach price is solved exactly and rounded against the strategy (floor for a long, ceiling for
  a short); touching the threshold is a breach.
- A hard breach closes the account; a soft breach liquidates and locks trading until the rule's
  own reset. A pass ends the phase; the attempt moves on to the next phase.
- A breach touched in a bar beats a pass in the same bar.
- A loss threshold declared ``evaluated: intraday`` is ALSO tested the instant a fill or a cost
  posting moves the basis, flat or not: a round turn that leaves the closed account past the
  threshold fails at that fill (ADR-0106, amendment of 2026-11-23).
- An end-of-day rule of day D is computed at D's last scheduled bar and its consequence is applied
  at the first bar of day D+1, before that bar's gap test; at the end of the data, day D's EOD is
  applied only when the last bar closes at the session's scheduled close, otherwise an unresolved
  attempt is censored (it is its own outcome class, never a silent pass or fail).
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from decimal import Decimal
from typing import Any, Literal

import numpy as np

from crucible.core.errors import CheckpointError, ConfigurationError
from crucible.core.types import TimestampNs
from crucible.execution.interfaces import (
    AccountMarks,
    BreachPrice,
    OverlayAction,
    OverlayEvent,
)
from crucible.prop import rules as rl
from crucible.prop.lifecycle import Lifecycle
from crucible.prop.news import NewsEvent, minute_ns
from crucible.prop.ruleset import (
    DailyLossRule,
    NewsRestrictionRule,
    Phase,
    PropRuleset,
    is_pass_condition,
)

Outcome = Literal["running", "pass", "fail", "timeout", "censored"]

_NS_PER_S = 1_000_000_000

_ZONE_LABEL: dict[str, str] = {
    "America/Chicago": "CT",
    "America/New_York": "ET",
    "America/Denver": "MT",
    "America/Los_Angeles": "PT",
}
"""A short label for the clock a rule's time is stated in, so a rejection reads as the firm
states it (``17:00 CT``). A zone not listed keeps its last path segment."""


@dataclass(frozen=True, slots=True)
class _EntryBlock:
    """One rule that refuses an entry, with the reason it gives (ADR-0106 amendment 2026-11-23).

    ``kind`` is the event kind it is recorded under: ``session_entry_block`` for a session-close
    ``flat_by`` window (the owner's name), ``news_entry_block`` for a news window and
    ``entry_blocked`` for a lock. ``freeze`` marks a rule that forbids ANY change of position
    (a news window whose scope is ``all_trading``) rather than only an increase.

    The blocking LOGIC and the rejection REASON are kept separate: the logic is
    ``PropAccountOverlay._entry_blockers``, the reason is the text built there.
    """

    kind: str
    rule_id: str
    reason: str
    freeze: bool = False


class PropAccountOverlay:
    """One phase's account, enforcing its rules inside the futures simulation (ADR-0106)."""

    def __init__(
        self,
        *,
        ruleset: PropRuleset,
        phase: Phase,
        root: str,
        tick_micro: int,
        session_close_ns: np.ndarray,
        start_day: dt.date,
        payout_policy: str = "none",
        news_events: Sequence[NewsEvent] = (),
        news_covered: bool = True,
    ) -> None:
        if tick_micro <= 0:
            msg = f"tick_micro must be positive, got {tick_micro}"
            raise ConfigurationError(msg)
        if payout_policy not in ("max_eligible", "none"):
            msg = (
                f"payout_policy = {payout_policy!r}: use max_eligible (take every eligible "
                "payout) or none (take none); whether to take a payout is the trader's choice, "
                "not a firm rule"
            )
            raise ConfigurationError(msg)
        self.payout_policy = payout_policy
        self.ruleset = ruleset
        self.phase = phase
        self.root = root
        self.tick_micro = tick_micro
        self.session_close_ns = np.asarray(session_close_ns, dtype=np.int64)
        self.start_balance = rl.micro(phase.starting_balance_usd, "starting_balance_usd")
        self.weight = ruleset.weight(root)
        self.events: list[OverlayEvent] = []
        self.outcome: Outcome = "running"
        self.breached_rule: str | None = None
        self.breach_time_ns: int | None = None
        self.pending_liquidation: BreachPrice | None = None
        """A breach found the instant a fill was booked, with a position still open: the simulator
        liquidates the rest at that price (ADR-0106, amendment of 2026-11-23)."""
        self.min_buffer: tuple[int, int, int, str] | None = None
        """``(delta_micro, bar, time_ns, rule_id)``: the smallest equity-minus-threshold seen."""
        self.days: dict[int, rl.DayStats] = {}
        self.closed_days: dict[int, rl.DayStats] = {}
        self.locked_by: str | None = None
        self.passed_at: int | None = None
        self.flat_done: dict[str, int] = {}
        self.withdrawn: int = 0
        """Total gross payout taken out of the account (micro-dollars): a withdrawal is not a
        trading loss, so the balance the rules see is the trading balance minus this."""
        self.payouts: list[tuple[int, int, int, str]] = []
        """``(time_ns, gross_micro, net_micro, rule_id)`` for every payout taken."""
        self.payout_bounds: list[str] = []
        """``exact`` or ``upper_bound`` for each payout, in the same order as ``payouts``: a cap
        the sources do not state makes the amount the most the other terms allow."""
        self.trading_days: int = 0
        """Rule-days the account has opened, for ``min_days_since_last``."""
        self.forfeited: int = 0
        """Profit forfeited to a ``daily_profit_cap`` (micro-dollars): not trading P&L."""
        self.news_events: tuple[NewsEvent, ...] = tuple(news_events)
        self.news_covered = news_covered
        self.news_flattened: set[str] = set()
        self.lifecycle = Lifecycle.for_phase(phase.kind)
        self._start_day = start_day
        self._bar = -1
        self._last_marks: AccountMarks | None = None
        clock = self._clock()
        self.reset_time: dt.time = clock[0]
        self.reset_tz: str = clock[1]
        self.day = rl.local_day(0, self.reset_time, self.reset_tz)
        self._started = False
        self.rules: list[rl.Evaluator] = []
        self.pass_conditions: list[rl.Evaluator] = []
        self.limiters: list[rl.Evaluator] = []
        self.time_limits: list[rl.TimeLimit] = []
        self.flat_rules: list[rl.FlatBy] = []
        self.daily: list[rl.DailyLoss] = []
        self.payouts_rules: list[rl.Payout] = []
        self.payout_consistency: list[rl.Consistency] = []
        self.caps: list[rl.DailyProfitCap] = []
        self.inactivity: list[rl.Inactivity] = []
        self.activity: list[rl.ActivityRequirement] = []
        self.news: list[rl.News] = []
        for rule in (*phase.rules, *phase.pass_conditions):
            evaluator = rl.build(
                rule,
                self.start_balance,
                self.weight,
                days=self.closed_days,
                start_day=start_day,
            )
            if is_pass_condition(rule):
                self.pass_conditions.append(evaluator)
            else:
                self.rules.append(evaluator)
            if isinstance(evaluator, (rl.MaxContracts, rl.ScalingPlan)):
                self.limiters.append(evaluator)
            elif isinstance(evaluator, rl.TimeLimit):
                self.time_limits.append(evaluator)
            elif isinstance(evaluator, rl.FlatBy):
                self.flat_rules.append(evaluator)
            elif isinstance(evaluator, rl.DailyLoss):
                self.daily.append(evaluator)
            elif isinstance(evaluator, rl.DailyProfitCap):
                self.caps.append(evaluator)
            elif isinstance(evaluator, rl.Inactivity):
                self.inactivity.append(evaluator)
            elif isinstance(evaluator, rl.ActivityRequirement):
                self.activity.append(evaluator)
            elif isinstance(evaluator, rl.News):
                self.news.append(evaluator)
                capped = (
                    isinstance(rule, NewsRestrictionRule)
                    and rule.effective_effect == "contract_cap"
                )
                if capped:
                    # a contract cap inside the window is a limit like max_contracts, so the
                    # smallest limit and a rejection in any limiter keep working
                    self.limiters.append(evaluator)
            elif isinstance(evaluator, rl.Payout):
                self.payouts_rules.append(evaluator)
            elif isinstance(evaluator, rl.Consistency) and evaluator.rule.applies_to == "payout":
                self.payout_consistency.append(evaluator)
        # a pass condition declared ``evaluated: eod`` is tested ONLY at the rule-day's last
        # scheduled bar (ADR-0106 section 3 step 8, ADR-0107 section 9); the intraday-declared ones
        # are tested at every bar's close. The split is derived from the rules, never serialized.
        self.eod_pass_conditions = [
            evaluator
            for evaluator in self.pass_conditions
            if rl.pass_frequency(evaluator.rule) == "eod"
        ]
        self.intraday_pass_conditions = [
            evaluator
            for evaluator in self.pass_conditions
            if rl.pass_frequency(evaluator.rule) == "intraday"
        ]

    # ------------------------------------------------------------------ identity and state

    def _clock(self) -> tuple[dt.time, str]:
        for rule in (*self.phase.rules, *self.phase.pass_conditions):
            if isinstance(rule, DailyLossRule):
                return rule.reset.time, rule.reset.tz
        return self.ruleset.reset.time, self.ruleset.reset.tz

    @property
    def closed(self) -> bool:
        return self.outcome != "running"

    @property
    def failure_rules(self) -> list[rl.Evaluator]:
        return [
            ev
            for ev in self.rules
            if isinstance(ev, (rl.StaticDrawdown, rl.TrailingDrawdown, rl.DailyLoss))
        ]

    def _record(self, kind: str, rule_id: str, marks: AccountMarks, **kw: object) -> None:
        self.events.append(
            OverlayEvent(
                kind=kind,
                bar=marks.bar,
                time_ns=marks.open_time_ns,
                rule_id=rule_id,
                requested=kw.get("requested"),  # type: ignore[arg-type]
                allowed=kw.get("allowed"),  # type: ignore[arg-type]
                note=str(kw.get("note", "")),
            )
        )

    # ------------------------------------------------------------------------ simulator hooks

    def begin_bar(self, i: int, marks: AccountMarks) -> OverlayAction | None:
        """Steps 1-2: the rule-day's resets, then the gap test at the open. An EOD-evaluated
        breach is not deferred here: it was decided at the previous close (``end_bar``)."""
        self._bar = i
        marks = self._adjusted(marks)
        self._last_marks = marks
        if self.closed:
            return None
        day = rl.local_day(marks.open_time_ns, self.reset_time, self.reset_tz)
        if not self._started or day != self.day:
            self._started = True
            self.day = day
            self._new_day(day, marks)
        gapped = self._gap_breach(marks)
        if gapped is not None:
            return self._breach(gapped, marks, at_open=True)
        return None

    def forced_flat(self, i: int, marks: AccountMarks) -> OverlayAction | None:
        """Step 6: liquidate at the open of the first bar reaching the rule's flat time."""
        marks = self._adjusted(marks)
        if self.closed:
            return None
        for evaluator in self.flat_rules:
            window = evaluator.flat_and_reopen(
                marks.open_time_ns, marks.close_time_ns, self._session_close(self._bar)
            )
            if window is None:
                continue
            flat, _ = window
            tz = evaluator.rule.tz
            day = (
                rl.local_day(marks.open_time_ns, dt.time(0, 0), tz) if tz is not None else self.day
            )
            if marks.close_time_ns < flat or self.flat_done.get(evaluator.rule_id) == day:
                continue
            self.flat_done[evaluator.rule_id] = day
            if evaluator.rule.action == "fail":
                if marks.position != 0:
                    self._fail(evaluator.rule_id, marks, marks.open_ticks)
                    return OverlayAction("close_account", evaluator.rule_id, True)
                continue
            if marks.position != 0:
                self._record("forced_flat", evaluator.rule_id, marks)
                return OverlayAction("liquidate", evaluator.rule_id, False)
        return self._news_flatten(marks)

    def admit(self, i: int, marks: AccountMarks, requested: int) -> int:
        """Step 3: the target the account allows (lock, closed account, forced-flat window,
        contract limit and scaling plan, by contract weight).

        A rule that REFUSES the entry is recorded under its own id and reason: one
        ``session_entry_block`` per session-close ``flat_by`` window, one ``news_entry_block`` per
        news window, one ``entry_blocked`` per lock, sorted by rule id. The size limit is recorded
        separately, as a ``resize`` under its own rule, and only when it is the size limit that
        changed the size (ADR-0106 amendment of 2026-11-23).
        """
        marks = self._adjusted(marks)
        if self.closed:
            return marks.position
        allowed = requested
        blocked = self._entry_blockers(marks)
        if blocked:
            for block in blocked:
                self._record(
                    block.kind,
                    block.rule_id,
                    marks,
                    requested=requested,
                    allowed=marks.position,
                    note=block.reason,
                )
            if any(block.freeze for block in blocked):
                # ``all_trading``: nothing may change the position while the window is open
                allowed = marks.position
            else:
                allowed = self._reduction(marks, requested)
        self._update_news_caps(marks)
        limit = self._contract_limit()
        if limit is not None:
            weighted = Decimal(allowed) * self.weight
            if abs(weighted) > limit:
                if self._on_excess() == "reject":
                    allowed = self._reduction(marks, 0)
                else:
                    sign = 1 if allowed > 0 else -1
                    allowed = sign * rl.allowed_contracts(limit, self.weight)
                self._record(
                    "resize",
                    self._limiting_rule(),
                    marks,
                    requested=requested,
                    allowed=allowed,
                    note="clip" if self._on_excess() == "clip" else "reject",
                )
        return allowed

    def _entry_blockers(self, marks: AccountMarks) -> list[_EntryBlock]:
        """Every rule that refuses an entry at this instant, sorted by rule id.

        The blocking LOGIC lives here and the reason text next to it; neither touches the size
        limit, which is applied afterwards and only to the size that survived the blocks.
        """
        blocks: list[_EntryBlock] = []
        if self.locked_by is not None:
            blocks.append(
                _EntryBlock(
                    "entry_blocked",
                    self.locked_by,
                    f"entry blocked: account locked by {self.locked_by} until its reset",
                )
            )
        for evaluator in self.flat_rules:
            window = evaluator.flat_and_reopen(
                marks.open_time_ns, marks.close_time_ns, self._session_close(self._bar)
            )
            if window is None:
                continue
            flat, reopen = window
            if int(marks.open_time_ns) >= reopen or int(marks.close_time_ns) < flat:
                continue
            rule = evaluator.rule
            zone = _ZONE_LABEL.get(rule.tz or "", (rule.tz or "").rsplit("/", 1)[-1])
            until = dt.datetime.fromtimestamp(reopen / _NS_PER_S, dt.UTC)
            if rule.tz is not None:
                from zoneinfo import ZoneInfo

                until = until.astimezone(ZoneInfo(rule.tz))
            blocks.append(
                _EntryBlock(
                    "session_entry_block",
                    evaluator.rule_id,
                    f"entry blocked: {evaluator.rule_id} until "
                    f"{until.strftime('%H:%M')} {zone}".rstrip(),
                )
            )
        for news in self.news:
            active = self._news_active(news, marks)
            if not active:
                continue
            if news.rule.effective_effect != "block":
                # a contract_cap window clips through the limiters; it never refuses an entry
                continue
            freeze = news.rule.scope == "all_trading"
            blocks.append(
                _EntryBlock(
                    "news_entry_block",
                    news.rule_id,
                    f"entry blocked: news window of {news.rule_id} (event {active[0]})",
                    freeze=freeze,
                )
            )
        blocks.sort(key=lambda block: (block.rule_id, block.kind))
        return blocks

    def favorable(self, i: int, marks: AccountMarks, price_ticks: int) -> None:
        """Step 4, before the adverse side: an intraday high-water mark rises first."""
        marks = self._adjusted(marks)
        if self.closed:
            return
        for evaluator in self.rules:
            evaluator.favorable(marks, price_ticks)

    def breach_prices(self, i: int, marks: AccountMarks) -> list[BreachPrice]:
        """Step 4: every active failure threshold's breach price, recomputed on demand."""
        marks = self._adjusted(marks)
        if self.closed or marks.position == 0:
            return []
        found: list[BreachPrice] = []
        for evaluator in self.rules:
            found.extend(evaluator.thresholds(marks))
        return found

    def breach_filled(
        self, i: int, marks: AccountMarks, price_ticks: int, rule_id: str, hard: bool
    ) -> None:
        """The simulator liquidated at ``price_ticks``: record the consequence."""
        self._consequence(rule_id, hard, self._adjusted(marks), price_ticks)

    def fill(
        self,
        i: int,
        marks: AccountMarks,
        quantity: int,
        price_ticks: int,
        kind: str,
        time_ns: int,
    ) -> None:
        """Step 7: every fill the simulator books (roll legs included).

        Two things happen here. The day statistics count the trade (roll legs are not new trades).
        Then every ``evaluated: intraday`` loss threshold is tested against the POST-FILL basis at
        the fill's own price: a fill moves the realized balance and its costs, so a threshold can
        be crossed with no position left to solve a breach price from (ADR-0106, amendment of
        2026-11-23). A crossing fails (or locks) the account at that instant; when a position
        remains, the rest is liquidated at the same price by the simulator.
        """
        marks = self._adjusted(marks)
        if kind not in ("roll_close", "roll_open"):
            self._day_stats(marks).trades += 1
            for evaluator in self.inactivity:
                evaluator.note_trade(self.day, self._trade_date(marks))
        if self.closed:
            return
        self._breach_after_fill(marks, price_ticks, int(time_ns))

    def take_pending_liquidation(self) -> BreachPrice | None:
        """The breach a fill just caused with a position still open, consumed once."""
        pending, self.pending_liquidation = self.pending_liquidation, None
        return pending

    def _breach_after_fill(self, marks: AccountMarks, price_ticks: int, time_ns: int) -> None:
        """Test every intraday loss threshold against the post-fill basis (flat included).

        The most adverse crossing wins: a hard rule before a soft one, then the lower threshold,
        then the rule id, so the outcome never depends on the order rules are declared in.
        """
        found: list[tuple[int, int, str, BreachPrice]] = []
        for evaluator in self.failure_rules:
            for breach in evaluator.observed(marks, price_ticks):
                threshold = getattr(evaluator, "threshold", None)
                found.append(
                    (
                        0 if breach.hard else 1,
                        -int(threshold) if threshold is not None else 0,
                        breach.rule_id,
                        breach,
                    )
                )
        if not found:
            return
        found.sort(key=lambda item: (item[0], item[1], item[2]))
        breach = found[0][3]
        self._consequence(breach.rule_id, breach.hard, marks, price_ticks, when=time_ns)
        if marks.position != 0:
            self.pending_liquidation = breach

    def _day_stats(self, marks: AccountMarks) -> rl.DayStats:
        """The current rule-day's statistics, opened with the balance it started from."""
        stats = self.days.get(self.day)
        if stats is None:
            stats = rl.DayStats(marks.balance_micro)
            self.days[self.day] = stats
        return stats

    def end_bar(self, i: int, marks: AccountMarks) -> OverlayAction | None:
        """Step 8: the close mark, the day statistics, the end-of-day rules and the passes.

        A consequence found here is executed at THIS close by the simulator (F3): an EOD-evaluated
        breach liquidates at the close, and a pass with a position still open flattens it as
        ``phase_flatten`` so the next phase starts fresh and flat. An eligible payout is taken
        here too when ``payout_policy`` allows it.
        """
        marks = self._adjusted(marks)
        self._last_marks = marks
        if self.closed:
            return None
        self._day_stats(marks).close_balance = marks.balance_micro
        self._track_buffer(marks)
        if not self._rule_day_ended(i, marks):
            return self._pass_action(marks, at_close=False)
        breaches: list[BreachPrice] = []
        for evaluator in self.rules:
            breaches.extend(evaluator.eod(marks))
        for evaluator in (*self.rules, *self.pass_conditions):
            closer = getattr(evaluator, "close_of_day", None)
            if closer is not None:
                closer(marks)
        self.closed_days[self.day] = self.days[self.day]
        if breaches:
            breach = breaches[0]
            self._consequence(breach.rule_id, breach.hard, marks, marks.close_ticks)
            kind: Literal["liquidate", "lock", "close_account"] = (
                "close_account" if breach.hard else "lock"
            )
            return OverlayAction(kind, breach.rule_id, breach.hard, marks.close_ticks)
        activity = self._activity_violation(marks)
        if activity is not None:
            return activity
        if self._check_time_limit(marks):
            return None
        cap_action = self._apply_profit_cap(i, marks)
        if cap_action is not None or self.closed:
            return cap_action
        action = self._pass_action(marks, at_close=True)
        if action is not None or self.closed:
            return action
        self._maybe_pay(marks)
        return None

    def _activity_violation(self, marks: AccountMarks) -> OverlayAction | None:
        """Step 2b: an activity requirement short of its qualifying days in a full rolling window.

        It ends the account at this close, like a hard EOD breach and before the pass conditions:
        a window that is short on the day a pass would happen beats the pass (the same pessimism
        as a breach in the bar of a pass).
        """
        if not self.activity:
            return None
        today = self._trade_date(marks)
        for evaluator in self.activity:
            if not evaluator.violated(today):
                continue
            rule_id = evaluator.rule_id
            if evaluator.rule.action == "close_account":
                self._record(
                    "close_account",
                    rule_id,
                    marks,
                    note=f"fewer than {evaluator.rule.days} qualifying days in the last "
                    f"{evaluator.rule.window} {evaluator.rule.unit}",
                )
            self._consequence(rule_id, True, marks, marks.close_ticks)
            return OverlayAction("close_account", rule_id, True, marks.close_ticks)
        return None

    def _apply_profit_cap(self, i: int, marks: AccountMarks) -> OverlayAction | None:
        """Step 8b: a per-rule-day profit cap, forfeiting the excess or promoting the phase."""
        stats = self.days.get(self.day)
        if stats is None:
            return None
        for evaluator in self.caps:
            excess = evaluator.excess(marks, stats.start_balance)
            if excess <= 0:
                continue
            if evaluator.rule.action == "promote_phase":
                self.outcome = "pass"
                self.passed_at = i
                self._record("promote_phase", evaluator.rule_id, marks)
                if self.lifecycle.state != "passed_terminal":
                    self.lifecycle.transition(
                        "passed_terminal",
                        time_ns=int(marks.close_time_ns),
                        cause=f"daily_profit_cap {evaluator.rule_id}",
                    )
                if marks.position == 0:
                    return None
                return OverlayAction("phase_flatten", evaluator.rule_id, False, marks.close_ticks)
            self.forfeited += excess
            self._record(
                "forfeit_excess",
                evaluator.rule_id,
                marks,
                note=f"forfeited {excess} micro-dollars above the daily profit cap",
            )
        return None

    def _pass_action(self, marks: AccountMarks, *, at_close: bool) -> OverlayAction | None:
        """A pass at this bar's close: flatten the position here if one is still open (F3).

        ``at_close`` says whether this bar is the rule-day's LAST scheduled bar. It decides which
        pass conditions are due: an ``evaluated: eod`` one only there, an ``evaluated: intraday``
        one at every close (``crucible.prop.rules.pass_frequency``).
        """
        if not self._check_pass(marks, at_close=at_close):
            return None
        if marks.position == 0:
            return None
        return OverlayAction("phase_flatten", "pass", False, marks.close_ticks)

    def _maybe_pay(self, marks: AccountMarks) -> None:
        """A payout at this close, when the trader takes every eligible one (P1).

        A ``payout_group`` pays at most once per close: ``max_eligible`` takes the path with the
        largest net, ``none`` takes none. The post-payout transitions of ADR-0107 section 9 step 6
        follow the withdrawal: the payout's own base, a payout-triggered trailing lock, a threshold
        ``set_threshold_to`` names, and the consistency windows' anchor.
        """
        if not self.payouts_rules or self.payout_policy != "max_eligible":
            return
        calendar_days = (self._trade_date(marks) - self._start_day).days
        best: dict[str, tuple[rl.Payout, rl.PayoutDecision]] = {}
        for evaluator in self.payouts_rules:
            since_day = evaluator.last_payout_day
            consistency = all(
                item.passes(since_day, balance=marks.balance_micro)
                for item in self.payout_consistency
            )
            decision = evaluator.decision(
                marks,
                self.closed_days,
                trading_days=self.trading_days,
                calendar_days=calendar_days,
                consistency_holds=consistency,
            )
            if decision is None:
                continue
            key = decision.payout_group or evaluator.rule_id
            current = best.get(key)
            if current is None or decision.net > current[1].net:
                best[key] = (evaluator, decision)
        if not best:
            return
        payout_day = self.day
        for evaluator, decision in best.values():
            first = evaluator.count == 0
            self.lifecycle.transition(
                "payout_pending",
                time_ns=int(marks.close_time_ns),
                cause=f"payout {decision.rule_id} eligible",
            )
            self.withdrawn += decision.gross
            evaluator.apply(
                decision,
                day=self.day,
                trading_days=self.trading_days,
                balance=marks.balance_micro - decision.gross,
            )
            self.payouts.append(
                (int(marks.close_time_ns), decision.gross, decision.net, decision.rule_id)
            )
            self.payout_bounds.append(decision.bound)
            for trailing in self.rules:
                if not isinstance(trailing, rl.TrailingDrawdown):
                    continue
                if first:
                    trailing.on_first_payout()
                if evaluator.rule.threshold_after_payout == "set_threshold":
                    trailing.lock_at(evaluator.threshold_level())
            for item in self.payout_consistency:
                item.last_payout_day = payout_day
                item.cycle_open_balance = marks.balance_micro - decision.gross
            self._record(
                "payout",
                decision.rule_id,
                marks,
                note=(
                    f"gross {decision.gross} net {decision.net} micro-dollars ({decision.bound})"
                ),
            )
            self.lifecycle.transition(
                "funded_active" if self.phase.kind == "funded" else "evaluation",
                time_ns=int(marks.close_time_ns),
                cause=f"withdrawal {decision.gross} recorded",
            )

    def finish(self, marks: AccountMarks) -> None:
        """The end of the data: a complete rule-day was already processed at its close, so an
        unresolved attempt whose data ends inside a rule-day is censored (its own class)."""
        marks = self._adjusted(marks)
        self._last_marks = marks
        if self.closed:
            return
        if self._rule_day_ended(marks.bar, marks):
            return
        self.outcome = "censored"
        self._record("censored", "attempt", marks, note="data ended inside the rule-day")
        if not self.lifecycle.terminal:
            self.lifecycle.transition(
                "censored",
                time_ns=int(marks.close_time_ns),
                cause="the data ended before the account resolved",
            )

    # ------------------------------------------------------------------------- rule machinery

    def _adjusted(self, marks: AccountMarks) -> AccountMarks:
        """The marks every rule sees: a withdrawal and a forfeited excess are not trading P&L,
        so the balance the rules test is the trading balance minus both."""
        removed = self.withdrawn + self.forfeited
        if not removed:
            return marks
        return replace(marks, balance_micro=marks.balance_micro - removed)

    def _trade_date(self, marks: AccountMarks) -> dt.date:
        return (
            dt.datetime.fromtimestamp(int(marks.open_time_ns) // 1_000_000_000, dt.UTC)
            .astimezone(_zone(self.reset_tz))
            .date()
        )

    def _new_day(self, day: int, marks: AccountMarks) -> None:
        self.trading_days += 1
        if day not in self.days:
            self.days[day] = rl.DayStats(marks.balance_micro)
        for evaluator in self.rules:
            evaluator.new_day(day, marks)
        for evaluator in self.pass_conditions:
            evaluator.new_day(day, marks)
        trade_date = self._trade_date(marks)
        for evaluator in self.inactivity:
            if evaluator.on_new_day(day, trade_date):
                self._fail(evaluator.rule_id, marks, marks.open_ticks)
                return
        if self.locked_by is not None:
            self._record("unlock", self.locked_by, marks)
            self.locked_by = None
            self.lifecycle.transition(
                "funded_active" if self.phase.kind == "funded" else "evaluation",
                time_ns=int(marks.open_time_ns),
                cause="the soft rule's reset clock reopened trading",
            )

    def _rule_day_ended(self, i: int, marks: AccountMarks) -> bool:
        """The last bar of the rule-day, known causally: its close is the session's scheduled
        close. Never inferred from a later bar (ADR-0106 section 3, step 8)."""
        if i < 0 or i >= len(self.session_close_ns):
            return False
        close = int(self.session_close_ns[i])
        return close != 0 and int(marks.close_time_ns) >= close

    def _gap_breach(self, marks: AccountMarks) -> BreachPrice | None:
        """Step 2: a threshold whose breach price the bar's open is already at or beyond."""
        breaches = self.breach_prices(marks.bar, marks)
        if marks.position > 0:
            reached = [b for b in breaches if marks.open_ticks <= b.price_ticks]
            return min(reached, key=lambda b: b.price_ticks) if reached else None
        reached = [b for b in breaches if marks.open_ticks >= b.price_ticks]
        return max(reached, key=lambda b: b.price_ticks) if reached else None

    def _breach(
        self,
        breach: BreachPrice,
        marks: AccountMarks,
        *,
        at_open: bool,
        when: int | None = None,
    ) -> OverlayAction:
        price = marks.open_ticks if at_open else breach.price_ticks
        self._consequence(breach.rule_id, breach.hard, marks, price, when=when)
        kind: Literal["liquidate", "lock", "close_account"] = (
            "close_account" if breach.hard else "lock"
        )
        return OverlayAction(kind, breach.rule_id, breach.hard, price if not at_open else None)

    def _consequence(
        self,
        rule_id: str,
        hard: bool,
        marks: AccountMarks,
        price: int,
        *,
        when: int | None = None,
    ) -> None:
        self._observe_buffer(marks, price)
        self.breach_time_ns = int(marks.close_time_ns) if when is None else int(when)
        self.breached_rule = rule_id
        if hard:
            self._fail(rule_id, marks, price, when=when)
            return
        if self.locked_by is None:
            self.locked_by = rule_id
        self._record("lock", rule_id, marks, note="soft rule: liquidate and lock until reset")
        if not self.lifecycle.terminal and self.lifecycle.state != "funded_locked_until_reset":
            self.lifecycle.transition(
                "funded_locked_until_reset",
                time_ns=self.breach_time_ns,
                cause=f"soft rule {rule_id} liquidated and locked until reset",
            )

    def _fail(
        self, rule_id: str, marks: AccountMarks, price: int, *, when: int | None = None
    ) -> None:
        if self.outcome != "running":
            return
        self.outcome = "fail"
        self.breached_rule = rule_id
        self.breach_time_ns = int(marks.close_time_ns) if when is None else int(when)
        self._record("breach", rule_id, marks, note=f"price {price} ticks")
        if not self.lifecycle.terminal:
            self.lifecycle.transition(
                "failed",
                time_ns=self.breach_time_ns,
                cause=f"hard rule {rule_id} breached",
            )

    def _check_pass(self, marks: AccountMarks, *, at_close: bool) -> bool:
        """Every pass condition DUE at this point holds: at the rule-day's close, all of them.

        An ``evaluated: eod`` target is a test of the closed trade date, so it cannot pass on an
        intraday close: a target touched inside a bar and lost again by the session's close leaves
        the account unresolved (ADR-0106 section 3 step 8, ADR-0107 section 9).
        """
        if self.closed or not self.pass_conditions:
            return False
        due = self.pass_conditions if at_close else self.intraday_pass_conditions
        if not due:
            return False
        if not all(evaluator.pass_ok(marks) for evaluator in due):
            return False
        self.outcome = "pass"
        self.passed_at = marks.bar
        self._record("pass", "attempt", marks)
        if not self.lifecycle.terminal:
            self.lifecycle.transition(
                "passed_terminal",
                time_ns=int(marks.close_time_ns),
                cause="every pass condition holds",
            )
        return True

    def _check_time_limit(self, marks: AccountMarks) -> bool:
        today = dt.datetime.fromtimestamp(
            int(marks.open_time_ns) // 1_000_000_000, dt.UTC
        ).astimezone(_zone(self.reset_tz))
        for evaluator in self.time_limits:
            if evaluator.timed_out(today.date()):
                self.outcome = "timeout"
                self._record("timeout", evaluator.rule_id, marks)
                return True
        return False

    def _observe_buffer(self, marks: AccountMarks, price_ticks: int) -> None:
        """Track the smallest basis-minus-threshold over the failure thresholds at one price."""
        for evaluator in self.failure_rules:
            threshold = getattr(evaluator, "threshold", None)
            if threshold is None:
                continue
            basis = evaluator.rule.basis
            value = rl.basis_at(marks, price_ticks, basis)
            delta = int(value) - int(threshold)
            if self.min_buffer is None or delta < self.min_buffer[0]:
                self.min_buffer = (
                    delta,
                    marks.bar,
                    int(marks.close_time_ns),
                    evaluator.rule_id,
                )

    def _track_buffer(self, marks: AccountMarks) -> None:
        """``min_buffer``: every failure threshold evaluated at the bar's conservative extreme
        (the low for a long, the high for a short, the close when flat)."""
        self._observe_buffer(
            marks, marks.adverse_ticks if marks.position != 0 else marks.close_ticks
        )

    def _contract_limit(self) -> Decimal | None:
        limits = [e.contract_limit() for e in self.limiters]
        present = [value for value in limits if value is not None]
        return min(present) if present else None

    def _limiting_rule(self) -> str:
        best: tuple[Decimal, str] | None = None
        for evaluator in self.limiters:
            value = evaluator.contract_limit()
            if value is None:
                continue
            if best is None or value < best[0]:
                best = (value, evaluator.rule_id)
        return best[1] if best is not None else "account"

    def _on_excess(self) -> str:
        """A rejection in any active limit wins: the account may never trade a size one of its
        rules refuses, even when another rule would only clip it."""
        choices = [e.on_excess() for e in self.limiters if e.contract_limit() is not None]
        return "reject" if "reject" in choices else "clip"

    def _reduction(self, marks: AccountMarks, requested: int) -> int:
        """No entry may increase exposure: only a reduction or a close is allowed."""
        if abs(requested) <= abs(marks.position) and requested * marks.position >= 0:
            return requested
        return marks.position

    def _flat_window(self, marks: AccountMarks) -> bool:
        for evaluator in self.flat_rules:
            window = evaluator.flat_and_reopen(
                marks.open_time_ns, marks.close_time_ns, self._session_close(self._bar)
            )
            if window is None:
                continue
            flat, reopen = window
            if int(marks.open_time_ns) < reopen and int(marks.close_time_ns) >= flat:
                return True
        return False

    def _session_close(self, i: int) -> int:
        if 0 <= i < len(self.session_close_ns):
            return int(self.session_close_ns[i])
        return 0

    # ------------------------------------------------------------------------------- news

    def _news_windows(self, evaluator: rl.News) -> list[tuple[int, int, str]]:
        """The restricted windows of one news rule, from the events the caller supplied.

        An attempt whose calendar coverage does not include its period passes
        ``news_covered=False`` and the rule stays ``not_modeled`` (reported), never enforced. An
        event type the calendar does not carry contributes no window: the attempt reports the rule
        as ``not_modeled`` (``crucible.prop.attempt``), never as no news.
        """
        if not self.news_covered:
            return []
        instruments = evaluator.rule.instruments
        if instruments and self.root not in instruments:
            return []
        pre = minute_ns(evaluator.rule.pre_minutes)
        post = minute_ns(evaluator.rule.post_minutes)
        out: list[tuple[int, int, str]] = []
        for event in self.news_events:
            if event.event_type not in evaluator.rule.event_types:
                continue
            if not event.time_known:
                # no invented window: the caller reports the day as a coverage gap
                continue
            out.append((event.scheduled_ns - pre, event.scheduled_ns + post, event.event_id))
        return sorted(out)

    def _news_active(self, evaluator: rl.News, marks: AccountMarks) -> list[str]:
        return [
            event_id
            for start, end, event_id in self._news_windows(evaluator)
            if int(marks.open_time_ns) <= end and int(marks.close_time_ns) >= start
        ]

    def _update_news_caps(self, marks: AccountMarks) -> None:
        """Tell every ``contract_cap`` news rule whether its window is active at this bar."""
        for evaluator in self.news:
            evaluator.cap_active = bool(self._news_active(evaluator, marks))

    def _news_blocks(self, marks: AccountMarks) -> bool:
        """Whether an active window forbids opening or increasing a position.

        Only a ``block`` window does: a ``contract_cap`` window instead clips the size through the
        limiters, so it never refuses an entry the cap allows.
        """
        for evaluator in self.news:
            if evaluator.rule.effective_effect != "block":
                continue
            if self._news_active(evaluator, marks):
                return True
        return False

    def _news_all_trading(self, marks: AccountMarks) -> bool:
        return any(
            evaluator.rule.scope == "all_trading" and self._news_active(evaluator, marks)
            for evaluator in self.news
        )

    def _news_flatten(self, marks: AccountMarks) -> OverlayAction | None:
        """Flatten at the first bar of a holding/all_trading window (``flatten: before_window``)."""
        for evaluator in self.news:
            if evaluator.rule.flatten != "before_window":
                continue
            if evaluator.rule.scope == "new_entries":
                continue
            active = self._news_active(evaluator, marks)
            if not active or marks.position == 0:
                continue
            key = f"{evaluator.rule_id}:{active[0]}"
            if key in self.news_flattened:
                continue
            self.news_flattened.add(key)
            self._record("news_flatten", evaluator.rule_id, marks, note=f"event {active[0]}")
            if evaluator.rule.action == "fail":
                self._fail(evaluator.rule_id, marks, marks.open_ticks)
                return OverlayAction("close_account", evaluator.rule_id, True)
            return OverlayAction("liquidate", evaluator.rule_id, False)
        return None

    # --------------------------------------------------------------------------- snapshotting

    def snapshot(self) -> dict[str, object]:
        """The mutable run state, built only from codec-supported values (ADR-0041)."""
        return {
            "day": self.day,
            "started": self._started,
            "outcome": self.outcome,
            "breached_rule": self.breached_rule,
            "breach_time_ns": self.breach_time_ns,
            "locked_by": self.locked_by,
            "passed_at": self.passed_at,
            "flat_done": dict(self.flat_done),
            "withdrawn": self.withdrawn,
            "forfeited": self.forfeited,
            "payouts": list(self.payouts),
            "payout_bounds": list(self.payout_bounds),
            "trading_days": self.trading_days,
            "lifecycle": self.lifecycle.snapshot(),
            "news_flattened": sorted(self.news_flattened),
            "min_buffer": self.min_buffer,
            "days": {
                str(day): [s.trades, s.start_balance, s.close_balance]
                for day, s in self.days.items()
            },
            "closed_days": {
                str(day): [s.trades, s.start_balance, s.close_balance]
                for day, s in self.closed_days.items()
            },
            "events": [
                (
                    e.kind,
                    e.bar,
                    e.time_ns,
                    e.rule_id,
                    e.requested,
                    e.allowed,
                    e.note,
                )
                for e in self.events
            ],
            "rules": [self._evaluator_state(ev) for ev in (*self.rules, *self.pass_conditions)],
        }

    def restore(self, state: Mapping[str, object]) -> None:
        # the checkpoint codec hands back plain values; every shape is checked below and a
        # malformed one raises CheckpointError instead of resuming a half-restored account
        data: dict[str, Any] = dict(state)
        try:
            self.day = int(data["day"])
            self._started = bool(data["started"])
            self.outcome = str(data["outcome"])  # type: ignore[assignment]
            raw_rule = data["breached_rule"]
            self.breached_rule = None if raw_rule is None else str(raw_rule)
            raw_breach = data["breach_time_ns"]
            self.breach_time_ns = None if raw_breach is None else int(raw_breach)
            raw_lock = data["locked_by"]
            self.locked_by = None if raw_lock is None else str(raw_lock)
            raw_passed = data["passed_at"]
            self.passed_at = None if raw_passed is None else int(raw_passed)
            self.flat_done = {str(k): int(v) for k, v in data["flat_done"].items()}
            self.withdrawn = int(data["withdrawn"])
            self.forfeited = int(data.get("forfeited", 0))
            self.lifecycle.restore(data["lifecycle"])
            self.news_flattened = {str(k) for k in data.get("news_flattened", [])}
            self.payouts = [
                (int(when), int(gross), int(net), str(rule))
                for when, gross, net, rule in data["payouts"]
            ]
            raw_bounds = data.get("payout_bounds")
            self.payout_bounds = (
                [str(bound) for bound in raw_bounds] if raw_bounds is not None else []
            )
            if self.payout_bounds and len(self.payout_bounds) != len(self.payouts):
                msg = (
                    f"prop overlay state holds {len(self.payout_bounds)} payout bounds for "
                    f"{len(self.payouts)} payouts"
                )
                raise CheckpointError(msg)
            self.trading_days = int(data["trading_days"])
            raw_buffer = data["min_buffer"]
            self.min_buffer = (
                None
                if raw_buffer is None
                else (
                    int(raw_buffer[0]),
                    int(raw_buffer[1]),
                    int(raw_buffer[2]),
                    str(raw_buffer[3]),
                )
            )
            self.days = self._restore_days(data["days"])
            self.closed_days = self._restore_days(data["closed_days"])
            self.events = [
                OverlayEvent(
                    kind=str(kind),
                    bar=int(bar),
                    time_ns=TimestampNs(int(when)),
                    rule_id=str(rule),
                    requested=None if req is None else int(req),
                    allowed=None if allowed is None else int(allowed),
                    note=str(note),
                )
                for kind, bar, when, rule, req, allowed, note in data["events"]
            ]
            evaluators = [*self.rules, *self.pass_conditions]
            saved_rules = list(data["rules"])
            if len(saved_rules) != len(evaluators):
                msg = (
                    f"prop overlay state holds {len(saved_rules)} evaluators for the phase's "
                    f"{len(evaluators)} rules: the ruleset changed under the checkpoint"
                )
                raise CheckpointError(msg)
            for evaluator, saved in zip(evaluators, saved_rules, strict=True):
                self._restore_evaluator(evaluator, saved)
        except (KeyError, TypeError, ValueError, IndexError) as exc:
            msg = f"prop overlay state is malformed: {exc}"
            raise CheckpointError(msg) from exc

    @staticmethod
    def _restore_days(raw: Any) -> dict[int, rl.DayStats]:
        out: dict[int, rl.DayStats] = {}
        for key, values in dict(raw).items():
            trades, start, close = values
            stats = rl.DayStats(int(start))
            stats.trades = int(trades)
            stats.close_balance = int(close)
            out[int(key)] = stats
        return out

    @staticmethod
    def _evaluator_state(evaluator: rl.Evaluator) -> dict[str, object]:
        state: dict[str, object] = {}
        for name in (
            "hwm",
            "locked",
            "reference",
            "prior_close",
            "amount",
            "limit",
            "next_limit",
            "trading_days",
            "base",
            "count",
            "last_payout_day",
            "last_payout_trading_day",
            "last_payout_balance",
            "peak_profit",
            "last_amount",
            "days_since_trade",
            "last_trade_day",
            "first_payout",
            "cycle_open_balance",
        ):
            if hasattr(evaluator, name):
                value = getattr(evaluator, name)
                state[name] = (
                    None if value is None else str(value) if isinstance(value, Decimal) else value
                )
        return state

    @staticmethod
    def _restore_evaluator(evaluator: rl.Evaluator, saved: Any) -> None:
        for name, value in dict(saved).items():
            if value is None:
                setattr(evaluator, name, None)
            elif name in (
                "hwm",
                "locked",
                "reference",
                "prior_close",
                "amount",
                "trading_days",
                "base",
                "count",
                "last_payout_day",
                "last_payout_trading_day",
                "last_payout_balance",
                "peak_profit",
                "last_amount",
                "days_since_trade",
                "last_trade_day",
                "first_payout",
                "cycle_open_balance",
            ):
                setattr(evaluator, name, int(value))
            else:
                setattr(evaluator, name, Decimal(str(value)))


def _zone(name: str) -> dt.tzinfo:
    from zoneinfo import ZoneInfo

    return ZoneInfo(name)
