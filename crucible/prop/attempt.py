"""One prop-firm attempt from one start trade date, inside the futures simulation (ADR-0106).

``simulate_attempt`` runs the phases of a ruleset in order over one window of one continuous
futures series. Each phase is a ``PropAccountOverlay`` handed to ``simulate_futures``, so a
breach, a lock or a resize changes the path the simulation takes from then on (never a
post-processed score of a path the account could not have traded). A phase that passes ends its
account; the next phase starts a fresh account with its own starting balance at the next eligible
open, where the previous phase's position is flattened.

Outcome is one of ``pass``, ``fail``, ``timeout`` or ``censored``. ``censored`` is its own class:
the data ended before the attempt resolved (the last rule-day is incomplete per the calendar), and
it is never folded into a failure rate.

A payout is a withdrawal recorded apart from trading P&L (ADR-0106 section 4): the funded phase's
``payout`` rule decides eligibility at each close and ``payout_policy`` decides whether the trader
takes it. ``payouts_usd`` is the trader's net share, ``net_cash_usd`` is that minus the fees, and
``payouts`` lists every payout with its gross and net. There is no pass probability and no verdict
in this stage.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from dataclasses import dataclass, replace
from decimal import Decimal
from typing import TYPE_CHECKING

import numpy as np
import polars as pl

from crucible.core.errors import ConfigurationError, DataQualityError
from crucible.data.cme_sessions import assign_bars, trade_date_of
from crucible.execution.futures_sim import (
    CostSchedule,
    ExecutionPolicy,
    simulate_futures,
)
from crucible.execution.interfaces import OverlayEvent
from crucible.prop import rules as rl
from crucible.prop.coverage import (
    EvaluationStatus,
    RuleCoverageRow,
    counterfactual_application,
    coverage_warnings,
    evaluation_status,
    material_unmodeled,
    rule_coverage,
)
from crucible.prop.news import (
    Coverage,
    NewsEvent,
    coverage_covers,
    unknown_time_gaps,
)
from crucible.prop.overlay import Outcome, PropAccountOverlay
from crucible.prop.rules_schema import ExecutionMode
from crucible.prop.ruleset import PropRuleset

if TYPE_CHECKING:
    from crucible.data.cme_sessions import SessionCalendar
    from crucible.data.futures_specs import FuturesContractSpec

SEMANTICS = "high_before_low_conservative"
LIQUIDATION_ASSUMPTIONS = (
    "a breach liquidates the whole position as a market order at its breach price (floor for a "
    "long, ceiling for a short) or at the open when the bar gapped past it, paying the bar's open "
    "spread and slippage plus liquidation_extra_slippage_ticks against the strategy; a target "
    "never fills in a bar where a stop or a breach price is touched"
)


@dataclass(frozen=True, slots=True)
class PhaseOutcome:
    """What one phase did: its outcome, breach, window and size."""

    phase_id: str
    kind: str
    outcome: Outcome
    breached_rule: str | None
    breach_time_ns: int | None
    first_bar: int
    last_bar: int
    trading_days: int


@dataclass(frozen=True, slots=True)
class PayoutRecord:
    """One payout: when it was paid, the gross withdrawn and the trader's net share."""

    time_ns: int
    gross_usd: Decimal
    net_usd: Decimal
    rule_id: str


@dataclass(frozen=True, slots=True)
class FeeBreakdown:
    """Attempt costs, broken out so a monthly or reset fee is never hidden in a total."""

    evaluation_usd: Decimal
    activation_usd: Decimal
    monthly_usd: Decimal
    reset_usd: Decimal
    total_usd: Decimal


@dataclass(frozen=True, slots=True)
class CommissionApplication:
    """The commission table the attempt used, and whether it is known (ADR-0107 section 10)."""

    status: str
    per_side_usd: Decimal | None
    root: str
    source: str
    cost_assumption: str | None


@dataclass(frozen=True, slots=True)
class AttemptResult:
    """One attempt: outcome, phases, breach, buffer, costs, coverage and identity (ADR-0106 s5)."""

    outcome: Outcome
    phase_outcomes: tuple[PhaseOutcome, ...]
    breached_rule: str | None
    breach_time_ns: int | None
    days_to_pass_trading: int | None
    days_to_pass_calendar: int | None
    min_buffer_usd: Decimal | None
    min_buffer_bar: int | None
    min_buffer_time_ns: int | None
    min_buffer_rule: str | None
    fees_usd: Decimal
    payouts_usd: Decimal
    payouts: tuple[PayoutRecord, ...]
    payout_policy: str
    payout_modeled: bool
    net_cash_usd: Decimal
    overlay_events: tuple[OverlayEvent, ...]
    rule_coverage: tuple[RuleCoverageRow, ...]
    evaluation_status: EvaluationStatus
    material_unmodeled: tuple[str, ...]
    mechanical_outcome: Outcome
    estimate_status: str
    estimate_reasons: tuple[str, ...]
    practical_eligibility: str
    scenario_id: str
    commissions: CommissionApplication
    fees: FeeBreakdown
    news_covered: bool | None
    news_coverage_gaps: tuple[str, ...]
    warnings: tuple[str, ...]
    ruleset_id: str
    version: int
    ruleset_sha256: str
    verification_status: str
    unverified_ruleset: bool
    ruleset_as_of: dt.date
    effective_from: dt.date
    effective_to: dt.date | None
    start_trade_date: dt.date
    data_first_trade_date: dt.date
    data_last_trade_date: dt.date
    counterfactual_application: bool
    semantics: str = SEMANTICS
    liquidation_assumptions: str = LIQUIDATION_ASSUMPTIONS


def _payout_modeled(ruleset: PropRuleset) -> bool:
    """Whether the ruleset's payouts are modeled at all: the phase carries a ``payout`` rule."""
    return any(
        rule.kind == "payout"
        for phase in ruleset.phases
        for rule in (*phase.rules, *phase.pass_conditions)
    )


def _window(
    calendar: SessionCalendar, bars: pl.DataFrame, start_trade_date: dt.date, horizon: int
) -> tuple[np.ndarray, list[dt.date | None], list[int]]:
    """``(session_close_ns, trade_date_of_each_bar, eligible bar indices)`` for the bars.

    ``session_close_ns[i]`` is the scheduled close of the session bar ``i`` belongs to (0 when the
    bar is off schedule): the causal fact an end-of-day rule needs, never the next bar.
    """
    ends = bars["event_time"].to_numpy().astype(np.int64)
    placed = assign_bars(calendar, ends)
    close = np.zeros(len(ends), dtype=np.int64)
    for index, session_index in enumerate(placed.session_index.tolist()):
        if session_index >= 0:
            close[index] = placed.sessions[session_index].close_ns
    dates: list[dt.date | None] = trade_date_of(calendar, ends)
    limit = start_trade_date + dt.timedelta(days=horizon)
    eligible = [
        i for i, day in enumerate(dates) if day is not None and start_trade_date <= day <= limit
    ]
    return close, dates, eligible


def _trade_date(dates: list[dt.date | None], i: int) -> dt.date:
    """The trade date of bar ``i``; a bar outside every scheduled session has none, and a rule
    day cannot be assigned to it."""
    day = dates[i]
    if day is None:
        msg = f"bar {i} is outside every scheduled session, so it has no trade date"
        raise DataQualityError(msg)
    return day


def _slice(
    bars: pl.DataFrame,
    targets: pl.DataFrame,
    rolls: pl.DataFrame,
    first: int,
    last: int,
) -> tuple[pl.DataFrame, pl.DataFrame, pl.DataFrame]:
    """The bars, targets and rolls of ``[first, last]``; a roll before the window is dropped and
    its contract simply starts the window."""
    window = bars[first : last + 1]
    if window.height == 0:
        msg = f"no bars in the attempt window [{first}, {last}]"
        raise DataQualityError(msg)
    start_time = int(window["event_time"][0])
    kept = targets.filter(pl.col("event_time") >= start_time).head(window.height)
    if kept.height != window.height:
        msg = (
            f"targets do not cover the attempt window: {kept.height} rows for {window.height} "
            "bars (targets must hold exactly one value per bar)"
        )
        raise ConfigurationError(msg)
    kept_rolls = rolls.filter(pl.col("event_time") >= start_time)
    return window, kept, kept_rolls


def _commissions_for(
    ruleset: PropRuleset, costs: CostSchedule, root: str, cost_assumption: str | None
) -> tuple[CostSchedule, CommissionApplication, bool]:
    """The ruleset's commission table replaces the run's fee schedule (spread/slippage stay).

    An unknown commission is never treated as zero: without an explicit named assumption the
    run's own schedule is kept as a labelled placeholder and ``cost_stats_available`` is false.
    """
    table = ruleset.commissions
    per_side = table.per_side(root) if table.status == "known" else None
    if per_side is not None:
        schedule = replace(
            costs,
            commission=per_side,
            exchange_fee=Decimal(0),
            clearing_fee=Decimal(0),
            regulatory_fee=Decimal(0),
        )
        return (
            schedule,
            CommissionApplication(
                status="known",
                per_side_usd=per_side,
                root=root,
                source=table.source.quote,
                cost_assumption=None,
            ),
            True,
        )
    available = cost_assumption is not None
    return (
        costs,
        CommissionApplication(
            status="unknown",
            per_side_usd=None,
            root=root,
            source=table.source.quote,
            cost_assumption=cost_assumption,
        ),
        available,
    )


def _fees(
    ruleset: PropRuleset,
    start: dt.date,
    end: dt.date,
    *,
    passed: bool,
    resets_purchased: int,
) -> FeeBreakdown:
    """Attempt costs by kind. A monthly fee is charged per STARTED calendar month of the attempt."""
    months = max(1, (end.year - start.year) * 12 + (end.month - start.month) + 1)
    evaluation = activation = monthly = reset = Decimal(0)
    for phase in ruleset.phases:
        for fee in phase.fees:
            if fee.fee_kind == "monthly":
                monthly += fee.amount_usd * months
            elif fee.fee_kind == "reset":
                reset += fee.amount_usd * resets_purchased
            elif fee.fee_kind == "activation":
                if passed:
                    activation += fee.amount_usd
            else:
                evaluation += fee.amount_usd
    return FeeBreakdown(
        evaluation_usd=evaluation,
        activation_usd=activation,
        monthly_usd=monthly,
        reset_usd=reset,
        total_usd=evaluation + activation + monthly + reset,
    )


def estimate_status(
    *,
    coverage: tuple[RuleCoverageRow, ...],
    verified: bool,
    commissions_known: bool,
    cost_assumption: str | None,
    news_covered: bool | None,
    news_coverage_gaps: tuple[str, ...] = (),
) -> tuple[str, tuple[str, ...]]:
    """``complete|conditional|partial|unavailable`` and its reasons (ADR-0107 section 11).

    ``unavailable`` when a critical rule is unmodeled or the commissions are unknown without a
    named assumption; ``partial`` when a material rule (including an uncovered news window) is
    unmodeled; ``conditional`` when the ruleset is unverified or a cost assumption was used.
    """
    reasons: list[str] = []
    critical = [row.rule for row in coverage if not row.modeled and row.materiality == "critical"]
    material = [row.rule for row in coverage if not row.modeled and row.materiality == "material"]
    for rule in critical:
        reasons.append(f"unmodeled critical rule {rule}")
    for rule in material:
        reasons.append(f"unmodeled material rule {rule}")
    if not verified:
        reasons.append("the ruleset is unverified")
    if not commissions_known and cost_assumption is None:
        reasons.append("commissions are unknown and no cost assumption was given")
    elif cost_assumption is not None:
        reasons.append(f"cost assumption {cost_assumption!r} was used")
    if (
        coverage
        and news_covered is not True
        and any("news" in row.rule for row in coverage if not row.modeled)
    ):
        reasons.append("the economic calendar does not cover the attempt period")
    if news_coverage_gaps:
        reasons.append(
            "the release time is unknown for events "
            + ", ".join(news_coverage_gaps)
            + ": their whole trade date is outside news coverage"
        )
    if critical or (not commissions_known and cost_assumption is None):
        return "unavailable", tuple(reasons)
    if material or news_coverage_gaps:
        return "partial", tuple(reasons)
    if not verified or cost_assumption is not None:
        return "conditional", tuple(reasons)
    return "complete", tuple(reasons)


def practical_eligibility(ruleset: PropRuleset, execution_mode: ExecutionMode) -> str:
    """``eligible|blocked_by_compliance|unknown`` for the exact execution mode (ADR-0107 s11)."""
    rules = ruleset.compliance_rules()
    if not rules:
        return "eligible"
    relevant = [rule for rule in rules if execution_mode in rule.applies_to_execution]
    if any(rule.materiality == "critical" and rule.action == "block" for rule in relevant):
        return "blocked_by_compliance"
    return "eligible"


def simulate_attempt(
    *,
    bars: pl.DataFrame,
    targets: pl.DataFrame,
    rolls: pl.DataFrame,
    spec: FuturesContractSpec,
    costs: CostSchedule,
    ruleset: PropRuleset,
    start_trade_date: dt.date,
    max_horizon_days: int,
    calendar: SessionCalendar,
    raw: pl.DataFrame | None = None,
    policy: ExecutionPolicy | None = None,
    liquidation_extra_slippage_ticks: int = 0,
    payout_policy: str = "none",
    execution_mode: ExecutionMode,
    news_events: Sequence[NewsEvent] | None = None,
    news_coverage: Coverage | None = None,
    cost_assumption: str | None = None,
    resets_purchased: int = 0,
    scenario_id: str = "primary",
) -> AttemptResult:
    """Run ``ruleset``'s phases from ``start_trade_date`` over ``max_horizon_days`` calendar days.

    ``bars``/``targets``/``rolls``/``spec``/``costs``/``raw`` are the futures run's (ADR-0095).
    ``calendar`` supplies the scheduled session ends that decide when a rule-day is complete.
    ``liquidation_extra_slippage_ticks`` is stress-test input (C7c): adverse ticks a liquidation
    pays on top of the bar's open (or close) costs, charged as money so the fill stays inside its
    bar. ``payout_policy`` is the trader's choice, not a firm rule: ``max_eligible`` takes every
    eligible payout the funded phase's ``payout`` rule allows, ``none`` takes none; the choice is
    recorded on the result.

    A phase that passes with a position still open flattens it at that bar's close (a
    ``phase_flatten`` fill in the passing phase). The next phase starts a fresh, flat account at the
    next bar with the require-signal-reset re-entry block in force at the decided target in force,
    so the strategy re-enters only after its decided target changes.

    ``execution_mode`` is required: a compliance rule that bans automated trading makes an
    automated strategy ``blocked_by_compliance`` even when the mechanical account passes.
    ``news_events``/``news_coverage`` are the economic calendar's rows and the covered periods;
    a news rule without coverage is ``not_modeled`` for this attempt.
    """
    if max_horizon_days < 1:
        msg = f"max_horizon_days must be >= 1, got {max_horizon_days}"
        raise ConfigurationError(msg)
    close_ns, dates, eligible = _window(calendar, bars, start_trade_date, max_horizon_days)
    if not eligible:
        msg = (
            f"no bar of the series falls in the attempt window "
            f"[{start_trade_date}, {start_trade_date + dt.timedelta(days=max_horizon_days)}]"
        )
        raise DataQualityError(msg)
    window_first, window_last = eligible[0], eligible[-1]
    tick_micro = rl.micro(spec.tick_value, "tick_value")
    news_rules = ruleset.news_rules()
    news_events = tuple(news_events or ())
    news_covered: bool | None = None
    news_coverage_gaps: tuple[str, ...] = ()
    if news_rules:
        start_ns = int(bars["event_time"][window_first])
        end_date = dates[window_last] or start_trade_date
        end_ns = (
            int(
                dt.datetime.combine(
                    end_date + dt.timedelta(days=1), dt.time(0, 0), tzinfo=dt.UTC
                ).timestamp()
            )
            * 1_000_000_000
        )
        news_coverage_gaps = unknown_time_gaps(news_events, start_ns, end_ns)
        # an unknown-time event is a gap for ITS date only: the known windows stay enforced
        news_covered = coverage_covers(news_coverage, start_ns, end_ns)
        if not news_events:
            news_covered = False
    coverage = rule_coverage(ruleset, news_covered=news_covered)
    commission_schedule, commission, _cost_stats_available = _commissions_for(
        ruleset, costs, spec.root, cost_assumption
    )
    phase_outcomes: list[PhaseOutcome] = []
    events: list[OverlayEvent] = []
    outcome: Outcome = "censored"
    breached_rule: str | None = None
    breach_time_ns: int | None = None
    buffer: tuple[int, int, int, str] | None = None
    payouts: list[PayoutRecord] = []
    passed_bar: int | None = None
    blocked_target: int | None = None
    first = window_first
    last = window_last
    for phase in ruleset.phases:
        if first > last:
            outcome = "censored"
            break
        window, window_targets, window_rolls = _slice(bars, targets, rolls, first, last)
        sliced_close = close_ns[first : last + 1]
        overlay = PropAccountOverlay(
            ruleset=ruleset,
            phase=phase,
            root=spec.root,
            tick_micro=tick_micro,
            session_close_ns=sliced_close,
            start_day=_trade_date(dates, first),
            payout_policy=payout_policy,
            news_events=news_events,
            news_covered=news_covered is not False,
        )
        phase_result = simulate_futures(
            bars=window,
            targets=window_targets,
            rolls=window_rolls,
            spec=spec,
            costs=commission_schedule,
            initial_capital=phase.starting_balance_usd,
            policy=policy,
            raw=raw,
            account=overlay,
            liquidation_extra_slippage_ticks=liquidation_extra_slippage_ticks,
            initial_blocked_target=blocked_target,
        )
        events.extend(overlay.events)
        payouts.extend(
            PayoutRecord(
                time_ns=when,
                gross_usd=Decimal(gross) / 1_000_000,
                net_usd=Decimal(net) / 1_000_000,
                rule_id=rule,
            )
            for when, gross, net, rule in overlay.payouts
        )
        trading_days = len({day for day in dates[first : last + 1] if day is not None})
        phase_outcomes.append(
            PhaseOutcome(
                phase_id=phase.phase_id,
                kind=phase.kind,
                outcome=overlay.outcome,
                breached_rule=overlay.breached_rule,
                breach_time_ns=overlay.breach_time_ns,
                first_bar=first,
                last_bar=overlay.passed_at if overlay.passed_at is not None else last,
                trading_days=trading_days,
            )
        )
        if overlay.min_buffer is not None and (buffer is None or overlay.min_buffer[0] < buffer[0]):
            buffer = overlay.min_buffer
        outcome = overlay.outcome
        breached_rule, breach_time_ns = overlay.breached_rule, overlay.breach_time_ns
        if outcome != "pass":
            break
        passed_bar = overlay.passed_at
        if passed_bar is None:
            msg = (
                f"phase {phase.phase_id} reports a pass without the bar it happened at: the "
                "attempt cannot start the next phase without it"
            )
            raise DataQualityError(msg)
        # the passing phase flattened at its close: the next account starts flat and re-enters
        # only after the strategy's decided target changes (signal reset, ADR-0090)
        if "phase_flatten" in set(phase_result.fills["kind"].to_list()):
            decided = window_targets["target"].to_list()
            blocked_target = int(decided[passed_bar - first])
        else:
            blocked_target = None
        first = passed_bar + 1
    if outcome == "running" and phase_outcomes:
        # the data ended before the phase resolved: right-censored at the data horizon, its own
        # class (never folded into a failure)
        outcome = "censored"
        phase_outcomes[-1] = replace(phase_outcomes[-1], outcome="censored")
    if passed_bar is None:
        days_trading, days_calendar = None, None
    else:
        passed_date = dates[passed_bar]
        assert passed_date is not None
        days_trading = len({day for day in dates[window_first : passed_bar + 1] if day is not None})
        days_calendar = (passed_date - start_trade_date).days
    data_first = dates[window_first] or start_trade_date
    data_last = dates[window_last] or start_trade_date
    unverified = not ruleset.verified
    warnings = list(coverage_warnings(coverage, ruleset))
    if news_coverage_gaps:
        warnings.append(
            "news coverage gap: the release time is unknown for "
            + ", ".join(news_coverage_gaps)
            + "; their whole trade date is not modeled, while every timed event is still enforced"
        )
    if counterfactual_application(start_trade_date, ruleset):
        warnings.append(
            f"the data window starts {start_trade_date}, before the ruleset's effective_from "
            f"{ruleset.effective_from}: a counterfactual application"
        )
    payouts_usd = sum((record.net_usd for record in payouts), Decimal(0))
    passed = outcome == "pass"
    fee_breakdown = _fees(
        ruleset,
        start_trade_date,
        data_last,
        passed=passed,
        resets_purchased=resets_purchased,
    )
    estimate, estimate_reasons = estimate_status(
        coverage=coverage,
        verified=ruleset.verified,
        commissions_known=commission.status == "known",
        cost_assumption=cost_assumption,
        news_covered=news_covered,
        news_coverage_gaps=news_coverage_gaps,
    )
    return AttemptResult(
        outcome=outcome,
        phase_outcomes=tuple(phase_outcomes),
        breached_rule=breached_rule,
        breach_time_ns=breach_time_ns,
        days_to_pass_trading=days_trading,
        days_to_pass_calendar=days_calendar,
        min_buffer_usd=None if buffer is None else Decimal(buffer[0]) / 1_000_000,
        min_buffer_bar=None if buffer is None else buffer[1],
        min_buffer_time_ns=None if buffer is None else buffer[2],
        min_buffer_rule=None if buffer is None else buffer[3],
        fees_usd=fee_breakdown.total_usd,
        fees=fee_breakdown,
        commissions=commission,
        payouts_usd=payouts_usd,
        payouts=tuple(payouts),
        payout_policy=payout_policy,
        payout_modeled=_payout_modeled(ruleset),
        net_cash_usd=payouts_usd - fee_breakdown.total_usd,
        overlay_events=tuple(events),
        rule_coverage=coverage,
        evaluation_status=evaluation_status(coverage),
        material_unmodeled=material_unmodeled(coverage),
        mechanical_outcome=outcome,
        estimate_status=estimate,
        estimate_reasons=estimate_reasons,
        practical_eligibility=practical_eligibility(ruleset, execution_mode),
        scenario_id=scenario_id,
        news_covered=news_covered,
        news_coverage_gaps=news_coverage_gaps,
        warnings=tuple(warnings),
        ruleset_id=ruleset.ruleset_id,
        version=ruleset.version,
        ruleset_sha256=ruleset.ruleset_sha256,
        verification_status=ruleset.verification.status,
        unverified_ruleset=unverified,
        ruleset_as_of=ruleset.as_of,
        effective_from=ruleset.effective_from,
        effective_to=ruleset.effective_to,
        start_trade_date=start_trade_date,
        data_first_trade_date=data_first,
        data_last_trade_date=data_last,
        counterfactual_application=counterfactual_application(start_trade_date, ruleset),
    )
