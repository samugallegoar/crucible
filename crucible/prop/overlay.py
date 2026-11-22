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
- An end-of-day rule of day D is computed at D's last scheduled bar and its consequence is applied
  at the first bar of day D+1, before that bar's gap test; at the end of the data, day D's EOD is
  applied only when the last bar closes at the session's scheduled close, otherwise an unresolved
  attempt is censored (it is its own outcome class, never a silent pass or fail).
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Mapping
from dataclasses import replace
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
from crucible.prop.ruleset import (
    DEFAULT_RESET_TIME,
    DEFAULT_RESET_TZ,
    DailyLossRule,
    Phase,
    PropRuleset,
    is_pass_condition,
)

Outcome = Literal["running", "pass", "fail", "timeout", "censored"]


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
        self.trading_days: int = 0
        """Rule-days the account has opened, for ``min_days_since_last``."""
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
            elif isinstance(evaluator, rl.Payout):
                self.payouts_rules.append(evaluator)
            elif isinstance(evaluator, rl.Consistency) and evaluator.rule.applies_to == "payout":
                self.payout_consistency.append(evaluator)

    # ------------------------------------------------------------------ identity and state

    def _clock(self) -> tuple[dt.time, str]:
        for rule in (*self.phase.rules, *self.phase.pass_conditions):
            if isinstance(rule, DailyLossRule):
                return rule.reset.time, rule.reset.tz
        return DEFAULT_RESET_TIME, DEFAULT_RESET_TZ

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
            window = evaluator.flat_and_reopen(marks.open_time_ns, marks.close_time_ns)
            if window is None:
                continue
            flat, _ = window
            day = rl.local_day(marks.open_time_ns, dt.time(0, 0), evaluator.rule.tz)
            if marks.close_time_ns < flat or self.flat_done.get(evaluator.rule_id) == day:
                continue
            self.flat_done[evaluator.rule_id] = day
            if evaluator.rule.consequence == "fail":
                if marks.position != 0:
                    self._fail(evaluator.rule_id, marks, marks.open_ticks)
                    return OverlayAction("close_account", evaluator.rule_id, True)
                continue
            if marks.position != 0:
                self._record("forced_flat", evaluator.rule_id, marks)
                return OverlayAction("liquidate", evaluator.rule_id, False)
        return None

    def admit(self, i: int, marks: AccountMarks, requested: int) -> int:
        """Step 3: the target the account allows (lock, closed account, forced-flat window,
        contract limit and scaling plan, by contract weight)."""
        marks = self._adjusted(marks)
        if self.closed:
            return marks.position
        allowed = requested
        if self.locked_by is not None or self._flat_window(marks):
            allowed = self._reduction(marks, requested)
        limit = self._contract_limit()
        if limit is not None:
            weighted = Decimal(allowed) * self.weight
            if abs(weighted) > limit:
                if self._on_excess() == "reject":
                    allowed = self._reduction(marks, 0)
                else:
                    sign = 1 if allowed > 0 else -1
                    allowed = sign * rl.allowed_contracts(limit, self.weight)
        if allowed != requested:
            self._record(
                "resize",
                self._limiting_rule(),
                marks,
                requested=requested,
                allowed=allowed,
                note="clip" if self._on_excess() == "clip" else "reject",
            )
        return allowed

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

    def fill(self, i: int, marks: AccountMarks, quantity: int, price_ticks: int, kind: str) -> None:
        """Every fill the simulator books, for the day statistics (trades per rule-day)."""
        if kind in ("roll_close", "roll_open"):
            return
        self._day_stats(marks).trades += 1

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
            return self._pass_action(marks)
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
        if self._check_time_limit(marks):
            return None
        action = self._pass_action(marks)
        if action is not None or self.closed:
            return action
        self._maybe_pay(marks)
        return None

    def _pass_action(self, marks: AccountMarks) -> OverlayAction | None:
        """A pass at this bar's close: flatten the position here if one is still open (F3)."""
        if not self._check_pass(marks):
            return None
        if marks.position == 0:
            return None
        return OverlayAction("phase_flatten", "pass", False, marks.close_ticks)

    def _maybe_pay(self, marks: AccountMarks) -> None:
        """A payout at this close, when the trader takes every eligible one (P1)."""
        if not self.payouts_rules or self.payout_policy != "max_eligible":
            return
        consistency = all(evaluator.passes() for evaluator in self.payout_consistency)
        for evaluator in self.payouts_rules:
            decision = evaluator.decision(
                marks,
                self.closed_days,
                trading_days=self.trading_days,
                consistency_holds=consistency,
            )
            if decision is None:
                continue
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
            self._record(
                "payout",
                decision.rule_id,
                marks,
                note=f"gross {decision.gross} net {decision.net} micro-dollars",
            )
            return

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

    # ------------------------------------------------------------------------- rule machinery

    def _adjusted(self, marks: AccountMarks) -> AccountMarks:
        """The marks every rule sees: gross payouts are withdrawals, not trading losses, so the
        balance the rules test is the trading balance minus what the trader took out."""
        if not self.withdrawn:
            return marks
        return replace(marks, balance_micro=marks.balance_micro - self.withdrawn)

    def _new_day(self, day: int, marks: AccountMarks) -> None:
        self.trading_days += 1
        if day not in self.days:
            self.days[day] = rl.DayStats(marks.balance_micro)
        for evaluator in self.rules:
            evaluator.new_day(day, marks)
        for evaluator in self.pass_conditions:
            evaluator.new_day(day, marks)
        if self.locked_by is not None:
            self._record("unlock", self.locked_by, marks)
            self.locked_by = None

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

    def _fail(
        self, rule_id: str, marks: AccountMarks, price: int, *, when: int | None = None
    ) -> None:
        if self.outcome != "running":
            return
        self.outcome = "fail"
        self.breached_rule = rule_id
        self.breach_time_ns = int(marks.close_time_ns) if when is None else int(when)
        self._record("breach", rule_id, marks, note=f"price {price} ticks")

    def _check_pass(self, marks: AccountMarks) -> bool:
        if self.closed or not self.pass_conditions:
            return False
        if not all(evaluator.pass_ok(marks) for evaluator in self.pass_conditions):
            return False
        self.outcome = "pass"
        self.passed_at = marks.bar
        self._record("pass", "attempt", marks)
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
            window = evaluator.flat_and_reopen(marks.open_time_ns, marks.close_time_ns)
            if window is None:
                continue
            flat, reopen = window
            if int(marks.open_time_ns) < reopen and int(marks.close_time_ns) >= flat:
                return True
        return False

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
            "payouts": list(self.payouts),
            "trading_days": self.trading_days,
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
            self.payouts = [
                (int(when), int(gross), int(net), str(rule))
                for when, gross, net, rule in data["payouts"]
            ]
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
            ):
                setattr(evaluator, name, int(value))
            else:
                setattr(evaluator, name, Decimal(str(value)))


def _zone(name: str) -> dt.tzinfo:
    from zoneinfo import ZoneInfo

    return ZoneInfo(name)
