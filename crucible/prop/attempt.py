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

Two cost facts decide whether the cash statistic is a number at all (ADR-0107 section 10):
the commission may be unknown, and every cost component the firm charges ON TOP of it
(``exchange``, ``clearing``, ``nfa``, ``other``) must be priced by a ``ComponentFeeSource`` for the
run's participant type. A component the sources do not state is a gap. Any gap leaves
``cash_estimate_status`` ``unavailable`` unless a ``CostAssumption`` FILE covers every one of
them, which makes it ``conditional`` and never ``complete``. A payout cap the source does not
state (``unknown``) is a third case: the cash numbers are paid as the other terms allow and
labelled ``upper_bound``. An assumption file of kind ``upper_bound`` is a fourth: its amounts are
ceilings, so the attempt's ``cost_bound`` is ``upper`` and the cash statistic is labelled
``lower_bound`` (the cost can only come down, so the net cash can only rise).
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
from crucible.prop.costs import (
    PARTICIPANT_PROFILE_REASON,
    UPPER_BOUND_CASH_LABEL,
    UPPER_BOUND_COST_LABEL,
    UPPER_BOUND_KIND,
    UPPER_BOUND_REASON,
    ComponentCharge,
    ComponentFeeSource,
    ComponentFeeTable,
    CostAssumption,
    price_components,
)
from crucible.prop.coverage import (
    EvaluationStatus,
    RuleCoverageRow,
    counterfactual_application,
    coverage_warnings,
    evaluation_status,
    material_unmodeled,
    rule_coverage,
    session_calendar_gaps,
)
from crucible.prop.news import (
    Coverage,
    NewsEvent,
    coverage_covers,
    unknown_time_gaps,
)
from crucible.prop.overlay import Outcome, PropAccountOverlay
from crucible.prop.promotions import resolve_promotions
from crucible.prop.rules_schema import ComplianceRule, ExecutionMode
from crucible.prop.ruleset import PropRuleset

if TYPE_CHECKING:
    from crucible.data.cme_sessions import SessionCalendar, TradeDateSession
    from crucible.data.exchange_fees import ParticipantProfile
    from crucible.data.futures_specs import FuturesContractSpec

SEMANTICS = "high_before_low_conservative"
PAYOUT_CAP_UNKNOWN = "payout cap unknown"
"""The named reason a payout and cash statistic is an upper bound (ADR-0107 section 7)."""
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
    """One payout: when it was paid, the gross withdrawn and the trader's net share.

    ``bound`` is ``exact`` or ``upper_bound``: a payout cap the sources do not state makes the
    amount the most the other terms allow, and the record says so rather than presenting it as a
    firm number.
    """

    time_ns: int
    gross_usd: Decimal
    net_usd: Decimal
    rule_id: str
    bound: str = "exact"


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
    """The commission table the attempt used and what every cost component cost (ADR-0107 s10).

    ``components`` holds one :class:`ComponentCharge` per cost component (the commission and the
    four the firm may charge on top), ``cost_gaps`` names the components no source could price and
    ``cost_status`` is ``complete``, ``conditional`` (a cost assumption or an assumed participant
    type supplied a value) or ``unavailable``.

    ``participant_profile_sha256`` is the canonical hash of the run's participant profile: the
    profile is a RUN input, because the ruleset never states one, and using it keeps the cost
    ``conditional``. ``cost_assumption``/``cost_assumption_sha256`` name the file that priced a
    gap, ``priced_by_assumption`` lists which components it priced, and
    ``cost_assumption_kind`` says what that file claimed (``point_estimate`` or ``upper_bound``).
    """

    status: str
    per_side_usd: Decimal | None
    root: str
    source: str
    components: tuple[ComponentCharge, ...]
    cost_gaps: tuple[str, ...]
    fees_incomplete: str | None
    cost_status: str = "unavailable"
    participant_profile_sha256: str | None = None
    cost_assumption: str | None = None
    cost_assumption_sha256: str | None = None
    priced_by_assumption: tuple[str, ...] = ()
    cost_assumption_kind: str | None = None

    @property
    def cost_bound(self) -> str | None:
        """``upper`` when the cost-assumption file's amounts are ceilings, else ``None``."""
        if self.cost_assumption_kind == UPPER_BOUND_KIND:
            return UPPER_BOUND_COST_LABEL
        return None

    @property
    def priced_from_dataset(self) -> bool:
        """Whether any component was priced from the fee dataset for the run's participant type."""
        return any(item.status == "excluded_priced" for item in self.components)

    def component(self, name: str) -> ComponentCharge:
        """One component's charge: the commission, exchange, clearing, nfa or other."""
        for item in self.components:
            if item.component == name:
                return item
        msg = f"no charge recorded for component {name!r}"
        raise ConfigurationError(msg)


@dataclass(frozen=True, slots=True)
class AttemptResult:
    """One attempt: outcome, phases, breach, buffer, costs, coverage and identity (ADR-0106 s5).

    ``cost_bound`` is ``upper`` when the run's cost-assumption file states ceilings (the cost is the
    most the account can pay, the cash statistic a ``lower_bound``) and ``""`` otherwise.
    """

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
    cash_estimate_status: str
    cash_estimate_reasons: tuple[str, ...]
    cost_bound: str
    overlay_events: tuple[OverlayEvent, ...]
    rule_coverage: tuple[RuleCoverageRow, ...]
    evaluation_status: EvaluationStatus
    material_unmodeled: tuple[str, ...]
    mechanical_outcome: Outcome
    estimate_status: str
    estimate_reasons: tuple[str, ...]
    practical_eligibility: str
    practical_eligibility_conditions: tuple[str, ...]
    scenario_id: str
    commissions: CommissionApplication
    fees: FeeBreakdown
    news_covered: bool | None
    news_coverage_gaps: tuple[str, ...]
    session_calendar_gaps: tuple[str, ...]
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
    promotions_applied: tuple[str, ...] = ()
    semantics: str = SEMANTICS
    liquidation_assumptions: str = LIQUIDATION_ASSUMPTIONS


def _payout_modeled(ruleset: PropRuleset) -> bool:
    """Whether the ruleset's payouts are modeled at all: the phase carries a ``payout`` rule."""
    return any(
        rule.kind == "payout"
        for phase in ruleset.phases
        for rule in (*phase.rules, *phase.pass_conditions)
    )


def _terminal_bar(overlay: PropAccountOverlay, first: int, last: int) -> int:
    """The attempt-coordinate bar at which a phase reached its terminal event.

    A pass records the bar it happened at (``passed_at`` on the phase's own slice), and a hard
    failure or a timeout records it as the last event the overlay appended before it closed: a
    closed overlay appends nothing more, so that event is the terminal one. A phase whose data
    ends first (``censored``) or that is still running ends at the window's last bar. The phases'
    trading-day count and the fee window read this bar, never the analyst's H-day window end
    (ADR-0107, amendment of 2026-11-27, F14 and F16).
    """
    if overlay.passed_at is not None:
        return first + overlay.passed_at
    if overlay.outcome in ("fail", "timeout") and overlay.events:
        return first + overlay.events[-1].bar
    return last


def _window(
    calendar: SessionCalendar, bars: pl.DataFrame, start_trade_date: dt.date, horizon: int
) -> tuple[np.ndarray, list[dt.date | None], list[int], list[TradeDateSession]]:
    """``(session_close_ns, trade_date_of_each_bar, eligible indices, touched sessions)``.

    ``session_close_ns[i]`` is the scheduled close of the session bar ``i`` belongs to (0 when the
    bar is off schedule): the causal fact an end-of-day rule needs, never the next bar. ``touched``
    holds the sessions the eligible bars trade in, in order, so the attempt can report an unsourced
    session-calendar window it runs through (``session_calendar_gaps``).
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
    touched: list[TradeDateSession] = []
    for index in eligible:
        session_index = int(placed.session_index[index])
        if session_index < 0:
            continue
        session = placed.sessions[session_index]
        if not touched or touched[-1] is not session:
            touched.append(session)
    return close, dates, eligible, touched


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
    ruleset: PropRuleset,
    costs: CostSchedule,
    root: str,
    cost_assumption: CostAssumption | None,
    *,
    fee_source: ComponentFeeSource | None = None,
    profile: ParticipantProfile | None = None,
    when: dt.date,
) -> tuple[CostSchedule, CommissionApplication]:
    """The ruleset's commission replaces the run's fee schedule; every component is priced.

    An unknown commission is never treated as zero: the run's own schedule is kept as a labelled
    placeholder and the cost statistics stay unavailable. Each component the firm charges ON TOP of
    the commission is added from ``fee_source`` as the run's ``profile`` resolves each component's
    classification; a component the sources do not state, one the source cannot price for this root
    and date, and one whose classification the profile does not declare are named gaps. A
    ``cost_assumption`` FILE prices exactly the gaps it names for exactly this root — it may not
    override a component the ruleset includes or the dataset already priced.

    The returned ``CommissionApplication.cost_status`` is ``complete`` (nothing is missing, no
    assumption and no declared participant profile was needed), ``conditional`` (an assumption or
    the profile supplied a value) or ``unavailable`` (a gap remains). The schedule carries the
    priced amounts; a gap contributes nothing, and the caller must not present the total as
    complete.
    """
    table = ruleset.commissions
    per_side = table.per_side(root) if table.status == "known" else None
    pricing = price_components(
        components=table.components,
        commission_status=table.status,
        commission_per_side=per_side,
        root=root,
        when=when,
        costs=costs,
        fee_source=fee_source,
        profile=profile,
        assumption=cost_assumption,
    )
    gaps = pricing.gaps
    return (
        pricing.schedule,
        CommissionApplication(
            status="known" if per_side is not None else "unknown",
            per_side_usd=per_side,
            root=root,
            source=table.source.quote,
            components=pricing.charges,
            cost_gaps=gaps,
            fees_incomplete=pricing.gap_text,
            cost_status=pricing.status,
            participant_profile_sha256=None if profile is None else profile.sha256,
            cost_assumption=None if cost_assumption is None else cost_assumption.name,
            cost_assumption_sha256=None if cost_assumption is None else cost_assumption.sha256,
            priced_by_assumption=pricing.priced_by_assumption,
            cost_assumption_kind=pricing.assumption_kind,
        ),
    )


def _fees(
    ruleset: PropRuleset,
    start: dt.date,
    end: dt.date,
    *,
    passed: bool,
    resets_purchased: int,
) -> FeeBreakdown:
    """Attempt costs by kind.

    A monthly subscription is charged for every calendar month STARTED while the attempt is
    alive: from the purchase month up to and including the month of the attempt's terminal event
    (``end``, the trade date the attempt failed, passed, timed out or reached its horizon), and
    never for a month after it. An attempt that dies on its first session therefore pays one
    month, not one per month of the analyst's horizon (ADR-0107, amendment of 2026-11-27, F14).
    """
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
    session_calendar_gaps: tuple[str, ...] = (),
    fees_incomplete: str | None = None,
    payout_cap_unknown: bool = False,
    participant_profile: str | None = None,
) -> tuple[str, tuple[str, ...]]:
    """``complete|conditional|partial|unavailable`` and its reasons (ADR-0107 section 11).

    ``unavailable`` when a critical rule is unmodeled, the commission is unknown without a cost
    assumption, or a cost component has no source and no assumption; ``partial`` when a material
    rule (including an uncovered news window or a payout cap the sources do not state) is
    unmodeled; ``conditional`` when the ruleset is unverified, a cost assumption was used, or the
    run's participant profile priced the excluded components (``participant_profile`` is then the
    profile's canonical SHA-256).
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
    if fees_incomplete is not None:
        reasons.append(fees_incomplete)
    if not commissions_known and cost_assumption is None:
        reasons.append("commissions are unknown and no cost assumption was given")
    elif cost_assumption is not None:
        reasons.append(f"cost assumption {cost_assumption!r} was used")
    if participant_profile is not None:
        reasons.append(PARTICIPANT_PROFILE_REASON)
    if payout_cap_unknown:
        reasons.append(PAYOUT_CAP_UNKNOWN)
    if (
        coverage
        # a news gap is a fact about a news RULE the ruleset requested: ``news_covered`` is False
        # only when a ``news_restriction`` rule exists and the calendar does not cover the attempt.
        # A ruleset with no news rule is never gapped, and a ``not_modeled`` entry whose id
        # merely mentions news is a discretionary rule with no window, not calendar coverage
        # (ADR-0107, amendment of 2026-11-27, F15)
        and news_covered is False
        and any("news" in row.rule for row in coverage if not row.modeled)
    ):
        reasons.append("the economic calendar does not cover the attempt period")
    if news_coverage_gaps:
        reasons.append(
            "the release time is unknown for events "
            + ", ".join(news_coverage_gaps)
            + ": their whole trade date is outside news coverage"
        )
    for gap in session_calendar_gaps:
        reasons.append(f"session calendar unsourced {gap}")
    costs_gapped = fees_incomplete is not None and cost_assumption is None
    if critical or (not commissions_known and cost_assumption is None) or costs_gapped:
        return "unavailable", tuple(reasons)
    if material or news_coverage_gaps or session_calendar_gaps or payout_cap_unknown:
        return "partial", tuple(reasons)
    if not verified or cost_assumption is not None or participant_profile is not None:
        return "conditional", tuple(reasons)
    return "complete", tuple(reasons)


def cash_estimate(
    *,
    payouts_modeled: bool,
    payout_cap_unknown: bool,
    cost_status: str,
    cost_assumption: str | None,
    cost_gaps: tuple[str, ...] = (),
    participant_profile: str | None = None,
    fees_incomplete: str | None = None,
    cost_assumption_kind: str | None = None,
) -> tuple[str, tuple[str, ...]]:
    """``exact | conditional | lower_bound | upper_bound | unavailable`` for payouts and net cash.

    A cash number needs every cost the account pays, so ``cost_gaps`` decides first: ANY component
    the sources leave unpriced AFTER the cost-assumption file was applied makes the cash
    ``unavailable``, and its reason NAMES the remaining gaps. A gap a ``cost_assumption`` file did
    not price never lets the number be a bound: a ceiling on SOME of the components is not a
    ceiling on the cost, and ``lower_bound`` on the cash would claim the missing component is free
    (ADR-0107, 2026-11-24 amendment). ``complete`` costs are ``exact`` only when no assumption and
    no declared participant profile was needed; either one keeps the number ``conditional``, never
    ``complete``. A payout cap the sources do not state does not stop the number: the payouts are
    paid as the other terms allow and the statistic is an ``upper_bound``. An assumption of kind
    ``upper_bound`` that leaves NO gap makes the COST a ceiling, so the net cash is its floor: the
    statistic is ``lower_bound`` and carries :data:`UPPER_BOUND_REASON`, which wins over the cap's
    ``upper_bound`` label because it applies to every attempt of the run and the per-payout label
    still says ``upper_bound``.
    """
    reasons: list[str] = []
    upper_bound_costs = cost_assumption_kind == UPPER_BOUND_KIND
    if not payouts_modeled:
        reasons.append("the ruleset declares no payout rule, so no withdrawal is modeled")
    if cost_status == "unavailable":
        if fees_incomplete is not None:
            reasons.append(fees_incomplete)
        named = ", ".join(cost_gaps) if cost_gaps else "a component no source prices"
        if cost_assumption is None:
            reasons.append(
                f"the attempt's cost is not known ({named}), so the net cash is not a number"
            )
        else:
            reasons.append(
                f"cost assumption {cost_assumption!r} does not price {named}, so the net cash is "
                "not a number"
            )
        return "unavailable", tuple(reasons)
    if cost_assumption is not None:
        reasons.append(f"cost assumption {cost_assumption!r} was used")
    if cost_status != "unavailable" and participant_profile is not None:
        reasons.append(PARTICIPANT_PROFILE_REASON)
    if payout_cap_unknown:
        reasons.append(PAYOUT_CAP_UNKNOWN)
    if upper_bound_costs:
        reasons.append(UPPER_BOUND_REASON)
        return UPPER_BOUND_CASH_LABEL, tuple(reasons)
    if payout_cap_unknown:
        return "upper_bound", tuple(reasons)
    conditional = cost_status == "conditional" or cost_assumption is not None
    return ("conditional" if conditional else "exact"), tuple(reasons)


@dataclass(frozen=True, slots=True)
class PracticalEligibility:
    """Whether the execution mode may trade the plan, and what the trader must still meet.

    ``status`` is ``eligible``, ``eligible_conditional`` (no critical blocker, but at least one
    obligation the simulation cannot prove) or ``blocked_by_compliance`` (a critical compliance rule
    with ``action: block`` applies). ``conditions`` lists every applicable condition once, sorted;
    ``blocker`` names the rule that blocked, when one did.
    """

    status: str
    conditions: tuple[str, ...]
    blocker: str | None


def blocks_conditionally(rule: ComplianceRule) -> bool:
    """Whether a compliance rule bans this execution mode without being a critical blocker.

    ``material`` + ``action: block``: the firm states the ban, does not call it critical, and the
    simulation cannot check it. It is an obligation, so it conditions the eligibility instead of
    passing unmentioned (ADR-0107 amendment of 2026-11-24).
    """
    return rule.action == "block" and rule.materiality == "material" and rule.effect != "condition"


def blocking_condition(rule: ComplianceRule) -> str:
    """The condition text a ``material`` + ``action: block`` rule contributes, by its own id.

    ``<rule_id>: <restriction>``: the id is what a reader can look up in the ruleset and the
    restriction is the firm's own words, so a report never paraphrases the ban it lists.
    """
    return f"{rule.rule_id}: {rule.restriction.strip()}"


def practical_eligibility(
    ruleset: PropRuleset, execution_mode: ExecutionMode
) -> PracticalEligibility:
    """``eligible|eligible_conditional|blocked_by_compliance`` for the execution mode (s11).

    A critical compliance rule with ``action: block`` that applies to ``execution_mode`` wins over
    everything: the account may not be traded that way at all. Otherwise every rule that applies and
    states an obligation of the trader makes the status ``eligible_conditional``, and the conditions
    are listed (sorted, de-duplicated) rather than silently dropped: a mechanical pass under a
    condition is a CONDITIONAL valid pass, never a practically valid one.

    Two declarations state such an obligation, and neither blocks on its own:

    - ``effect: condition`` with its ``condition`` text (an obligation the firm states and the
      simulation cannot check);
    - a ``material`` rule with ``action: block``. A ban the firm treats as material is not a
      critical blocker, but it is not nothing either: the trader may trade this way only while the
      ban holds, so the rule is listed as a condition under its own id and the restriction it
      states (a high-frequency-trading ban, a rule against a high-risk strategy). Reading it as
      plain ``eligible`` claimed the simulation had cleared a rule it never looked at.
    """
    rules = ruleset.compliance_rules()
    relevant = [rule for rule in rules if execution_mode in rule.applies_to_execution]
    blocker = next(
        (rule for rule in relevant if rule.materiality == "critical" and rule.action == "block"),
        None,
    )
    if blocker is not None:
        return PracticalEligibility(
            status="blocked_by_compliance",
            conditions=(),
            blocker=blocker.rule_id,
        )
    stated = {str(rule.condition).strip() for rule in relevant if rule.effect == "condition"}
    stated.update(blocking_condition(rule) for rule in relevant if blocks_conditionally(rule))
    conditions = tuple(sorted(stated))
    return PracticalEligibility(
        status="eligible_conditional" if conditions else "eligible",
        conditions=conditions,
        blocker=None,
    )


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
    fee_source: ComponentFeeSource | None = None,
    cost_assumption: CostAssumption | None = None,
    profile: ParticipantProfile | None = None,
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

    ``profile`` also decides the PROMOTIONAL values the ruleset offers (a doubled payout cap for
    an account bought during an offer): a promotion applies only when the profile declares what it
    requires and the purchase date falls in its window, and every promotion that does not apply is
    reported by name and reason (``crucible.prop.promotions``). The ruleset's own bytes and content
    hash never change: the promoted value is a property of the run.

    ``execution_mode`` is required: a compliance rule that bans automated trading makes an
    automated strategy ``blocked_by_compliance`` even when the mechanical account passes.
    ``news_events``/``news_coverage`` are the economic calendar's rows and the covered periods;
    a news rule whose event types the calendar does not carry is ``not_modeled`` for this attempt
    (reported), and every window the calendar does carry is still enforced.
    ``fee_source`` is the ``ComponentFeeSource`` the components the firm charges ON TOP of the
    commission are priced from, resolved through the run's ``profile`` — the participant profile is
    a run input, because the ruleset never states one, and it is refused when a component is
    excluded and it is missing. Without a source, an uncovered row, a classification the profile
    does not declare, or an ``unknown`` component, that cost is a named gap and the cash statistic
    is ``unavailable`` — or ``conditional`` when ``cost_assumption`` prices every remaining gap. The
    amounts are resolved at ``start_trade_date``; a fee change inside the attempt's window is
    reported in ``warnings``, never applied silently.
    """
    if max_horizon_days < 1:
        msg = f"max_horizon_days must be >= 1, got {max_horizon_days}"
        raise ConfigurationError(msg)
    # the promotional values are a property of the RUN, never of the file: the promoted phases feed
    # the overlay, while every identity the result cites (``ruleset_sha256``, verification) is read
    # from the ruleset the file defines
    promoted_ruleset, promotions = resolve_promotions(ruleset, profile)
    close_ns, dates, eligible, touched_sessions = _window(
        calendar, bars, start_trade_date, max_horizon_days
    )
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
    news_unmodeled: dict[str, str] = {}
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
        # an event type the calendar does not carry is a declared gap, never "no news": the rule
        # that names it stays not_modeled for this attempt and is reported by name
        known_types = {event.event_type for event in news_events}
        for rule in news_rules:
            missing = [name for name in rule.event_types if name not in known_types]
            if missing:
                news_unmodeled[rule.rule_id] = (
                    f"event type(s) {', '.join(sorted(missing))} are not in the economic calendar"
                )
    coverage = rule_coverage(
        ruleset, news_covered=news_covered, news_unmodeled=news_unmodeled or None
    )
    commission_schedule, commission = _commissions_for(
        ruleset,
        costs,
        spec.root,
        cost_assumption,
        fee_source=fee_source,
        profile=profile,
        when=start_trade_date,
    )
    cost_status = commission.cost_status
    payout_cap_unknown = any(
        rule.kind == "payout" and rule.unknown_cap
        for phase in ruleset.phases
        for rule in (*phase.rules, *phase.pass_conditions)
    )
    phase_outcomes: list[PhaseOutcome] = []
    events: list[OverlayEvent] = []
    outcome: Outcome = "censored"
    breached_rule: str | None = None
    breach_time_ns: int | None = None
    buffer: tuple[int, int, int, str] | None = None
    terminal_bar: int | None = None
    payouts: list[PayoutRecord] = []
    passed_bar: int | None = None
    passed_absolute: int | None = None
    blocked_target: int | None = None
    first = window_first
    last = window_last
    for phase in promoted_ruleset.phases:
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
        terminal = _terminal_bar(overlay, first, last)
        terminal_bar = terminal
        payouts.extend(
            PayoutRecord(
                time_ns=when,
                gross_usd=Decimal(gross) / 1_000_000,
                net_usd=Decimal(net) / 1_000_000,
                rule_id=rule,
                bound=(
                    overlay.payout_bounds[index] if index < len(overlay.payout_bounds) else "exact"
                ),
            )
            for index, (when, gross, net, rule) in enumerate(overlay.payouts)
        )
        trading_days = len({day for day in dates[first : terminal + 1] if day is not None})
        phase_outcomes.append(
            PhaseOutcome(
                phase_id=phase.phase_id,
                kind=phase.kind,
                outcome=overlay.outcome,
                breached_rule=overlay.breached_rule,
                breach_time_ns=overlay.breach_time_ns,
                first_bar=first,
                # the overlay numbers bars from the phase's first bar; the artifact reports the
                # attempt's own coordinates, so the attempt offset is added
                last_bar=(first + overlay.passed_at if overlay.passed_at is not None else last),
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
        passed_absolute = first + passed_bar
        if "phase_flatten" in set(phase_result.fills["kind"].to_list()):
            # ``window_targets`` covers exactly this phase's bars, so the pass offset into the
            # overlay's slice is the index of the target that was in force at the pass
            decided = window_targets["target"].to_list()
            blocked_target = int(decided[passed_bar])
        else:
            blocked_target = None
        first = passed_absolute + 1
    if outcome == "running" and phase_outcomes:
        # the data ended before the phase resolved: right-censored at the data horizon, its own
        # class (never folded into a failure)
        outcome = "censored"
        phase_outcomes[-1] = replace(phase_outcomes[-1], outcome="censored")
    if passed_absolute is None:
        days_trading, days_calendar = None, None
    else:
        # ``dates`` spans the attempt window from its FIRST bar, and ``passed_absolute`` is an
        # index into it: a start later in the series must not measure its days from the data's
        # first bar (nor read the wrong date back)
        passed_date = dates[passed_absolute]
        assert passed_date is not None
        days_trading = len(
            {day for day in dates[window_first : passed_absolute + 1] if day is not None}
        )
        days_calendar = (passed_date - start_trade_date).days
    data_first = dates[window_first] or start_trade_date
    data_last = dates[window_last] or start_trade_date
    # the fee window ends with the attempt's terminal event (F14), never with the horizon: a start
    # that dies on its first session pays one monthly subscription, not one per month of H
    fee_end = data_last if terminal_bar is None else (dates[terminal_bar] or data_last)
    schedule_gaps = session_calendar_gaps(calendar, touched_sessions)
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
    for gap in schedule_gaps:
        warnings.append(
            f"session calendar unsourced {gap}: the CME schedule of the affected sessions was "
            "never archived, so the session-relative flat_by, the rule-day boundary and the "
            "end-of-day test are built from the regular-week regime, not from a sourced schedule"
        )
    if news_unmodeled:
        warnings.append(
            "news restrictions not modeled for this attempt: "
            + "; ".join(
                f"{rule_id} ({reason})" for rule_id, reason in sorted(news_unmodeled.items())
            )
        )
    change = (
        None
        if not isinstance(fee_source, ComponentFeeTable)
        else next(
            (
                row.effective_from
                for row in sorted(fee_source.rows, key=lambda row: row.effective_from)
                if row.root == spec.root and start_trade_date < row.effective_from <= data_last
            ),
            None,
        )
    )
    if change is not None:
        warnings.append(
            f"a per-side fee for {spec.root} changes on {change} inside the attempt, and the "
            f"schedule of {start_trade_date} is charged for the whole window"
        )
    payouts_usd = sum((record.net_usd for record in payouts), Decimal(0))
    passed = outcome == "pass"
    practical = practical_eligibility(ruleset, execution_mode)
    fee_breakdown = _fees(
        ruleset,
        start_trade_date,
        fee_end,
        passed=passed,
        resets_purchased=resets_purchased,
    )
    estimate, estimate_reasons = estimate_status(
        coverage=coverage,
        verified=ruleset.verified,
        commissions_known=commission.status == "known",
        cost_assumption=None if cost_assumption is None else cost_assumption.name,
        news_covered=news_covered,
        news_coverage_gaps=news_coverage_gaps,
        session_calendar_gaps=schedule_gaps,
        fees_incomplete=commission.fees_incomplete,
        payout_cap_unknown=payout_cap_unknown,
        participant_profile=(
            commission.participant_profile_sha256 if commission.priced_from_dataset else None
        ),
    )
    cash_status, cash_reasons = cash_estimate(
        payouts_modeled=_payout_modeled(ruleset),
        payout_cap_unknown=payout_cap_unknown,
        cost_status=cost_status,
        cost_assumption=None if cost_assumption is None else cost_assumption.name,
        cost_gaps=commission.cost_gaps,
        participant_profile=(
            commission.participant_profile_sha256 if commission.priced_from_dataset else None
        ),
        fees_incomplete=commission.fees_incomplete,
        cost_assumption_kind=commission.cost_assumption_kind,
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
        cash_estimate_status=cash_status,
        cash_estimate_reasons=cash_reasons,
        cost_bound=commission.cost_bound or "",
        overlay_events=tuple(events),
        rule_coverage=coverage,
        evaluation_status=evaluation_status(coverage),
        material_unmodeled=material_unmodeled(coverage),
        mechanical_outcome=outcome,
        estimate_status=estimate,
        estimate_reasons=estimate_reasons,
        practical_eligibility=practical.status,
        practical_eligibility_conditions=practical.conditions,
        scenario_id=scenario_id,
        news_covered=news_covered,
        news_coverage_gaps=news_coverage_gaps,
        session_calendar_gaps=schedule_gaps,
        warnings=tuple(warnings),
        ruleset_id=ruleset.ruleset_id,
        version=ruleset.version,
        ruleset_sha256=ruleset.ruleset_sha256,
        verification_status=ruleset.verification.status,
        unverified_ruleset=unverified,
        promotions_applied=promotions.applied,
        ruleset_as_of=ruleset.as_of,
        effective_from=ruleset.effective_from,
        effective_to=ruleset.effective_to,
        start_trade_date=start_trade_date,
        data_first_trade_date=data_first,
        data_last_trade_date=data_last,
        counterfactual_application=counterfactual_application(start_trade_date, ruleset),
    )
