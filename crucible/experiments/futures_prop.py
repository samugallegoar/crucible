"""Prop evaluation over one futures run: the attempt sequence, censoring and pass probability.

A prop evaluation answers one question about an existing candidate: *if this strategy were traded on
this futures run under one firm's ruleset, how often would an attempt starting on trade date ``d``
pass, and how little would that number know?* It simulates nothing new about the strategy — the
signal is causal and independent of the account, so ``import_prepared_run`` prepares the bars,
targets, rolls and raw per-contract bars ONCE (ADR-0095, ADR-0107 section 4) and every attempt
replays a slice of them through ``simulate_attempt``.

What this module enforces (ADR-0107 sections 4, 5, 6, 10, 11 and 12):

- **Start dates.** Every Globex trade date of the run's window with at least one on-schedule bar is
  a start. An attempt begins at the open of that trade date.
- **The horizon.** ``horizon_trading_days`` (``H``) is the analyst's horizon, in TRADING days, and
  it is required. It is converted to a calendar-day window per start with the CME session calendar
  (a start before a holiday spans more calendar days for the same H trade dates), and it is refused
  when it is shorter than any phase's own time limit (a ``max_calendar_days`` limit is converted per
  start, because a firm limit that could never fire inside the horizon makes the horizon a lie).
- **Outcome classes.** ``pass`` (every evaluation phase passed), ``fail`` (a hard rule was
  breached), ``timeout`` (the firm's own time limit ended a phase), ``horizon`` (H was reached
  unresolved) and ``censored`` (the data ended before ``d + H`` and before resolution). ``horizon``
  and ``censored`` are separate classes; neither is folded into a failure or a pass. The funded
  phase's outcome is DESCRIPTIVE: it is reported for the starts whose evaluation passed and never
  turns such a start into a non-pass (ADR-0107 section 4).
- **Pass probability.** ``p = passes / complete starts`` where a complete start is one whose
  horizon fits in the data (``d + H <= last date``); ``p_low = passes / all starts`` (censored
  counted as failures) and ``p_high = (passes + censored) / all starts`` (censored as passes) sit
  beside it. The interval is a SEEDED circular block bootstrap over the complete starts in date
  order with a block of ``max(H, ceil(sqrt(n)))`` trade dates — one block therefore always covers
  the starts whose attempts can overlap (``futures_stats.circular_block_bootstrap``, ADR-0103
  decision 5) — and with fewer than two blocks it is ``unavailable`` with its reason, never a
  narrower invention. ``effective_independent_attempts = n / H`` states how little independent
  information overlapping starts carry.
- **Status, never a verdict.** The number is named ``pass_probability`` only when nothing
  qualifies it: every rule modeled, the ruleset verified, the costs known, the calendar covered and
  the data inside the ruleset's effective period. Otherwise it is ``conditional_pass_probability``
  with ``definitive: false`` and every reason. ``practical_eligibility`` is judged for the
  EXECUTION MODE: a mechanical pass under a critical compliance blocker is never reported as a
  practically valid pass. There is no threshold and no verdict.
- **Not a submission.** A prop evaluation evaluates an existing candidate. It never records a
  trial, so it changes neither ``submission_count`` nor ``total_trials`` (ADR-0107 section 6); the
  manifest links it to the candidate id and the trial family instead.

The artifact is ``<artifacts>/PRP-<16hex>/``: ``attempts.parquet`` (one row per scenario and
start), ``summary.json`` (the statistics, the bootstrap record and the coverage), ``ruleset.yaml``
(the exact bytes used) and ``manifest.json`` with the seal. ``PRP-`` is a pure function of the
inputs — the run's id basis, the ruleset's content hash, H, the execution mode, the payout policy,
the cost assumption, whether scenarios were simulated and the two auxiliary datasets' content
hashes — so the same inputs reproduce byte-identical files and the same directory (ADR-0079,
ADR-0084). The bootstrap seed is ``bootstrap_seed(evaluation_id, statistic)``, which is why the id
is computed before the simulation starts.

Timing: a pure function of its arguments; nothing reads the wall clock except the artifact seal's
``created_at``. Money is USD ``Decimal`` throughout; times are UTC int64 nanoseconds; ``trade_date``
is a Globex day label. Market data past 2024-12-31 is refused by the vault guard, never by weakening
it (ADR-0105).
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import shutil
from dataclasses import asdict, dataclass
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Final, Literal

import numpy as np
import polars as pl
from pydantic import BaseModel, ConfigDict

from crucible.core.errors import ConfigurationError, CrucibleError, DataQualityError
from crucible.core.types import DatasetId
from crucible.data.econ_events import (
    EVENT_TYPES,
    load_econ_events,
)
from crucible.data.econ_events import (
    Coverage as EconCalendarCoverage,
)
from crucible.data.econ_events import (
    coverage as econ_calendar_coverage,
)
from crucible.data.exchange_fees import ParticipantProfile
from crucible.data.store import ParquetDataStore
from crucible.data.vault import refuse_protected_window
from crucible.experiments.artifact_id import read_seal, seal_artifact, write_manifest
from crucible.experiments.futures_config import (
    FuturesRunConfig,
    candidate_id,
    futures_config_hash,
)
from crucible.experiments.futures_run import (
    RUN_ID_HEX,
    RUN_ID_PREFIX,
    import_prepared_run,
    run_id_basis,
    write_result_parquet,
)
from crucible.experiments.futures_run import (
    SCHEMA_VERSION as RUN_SCHEMA_VERSION,
)
from crucible.experiments.futures_stats import (
    BOOTSTRAP_RNG,
    block_length,
    bootstrap_seed,
    circular_block_bootstrap,
    percentile_interval,
)
from crucible.prop.attempt import AttemptResult, practical_eligibility, simulate_attempt
from crucible.prop.costs import (
    CostAssumption,
    load_cost_assumption,
    store_component_fees,
)
from crucible.prop.coverage import (
    EvaluationStatus,
    evaluation_status,
    rule_coverage,
)
from crucible.prop.news import Coverage, NewsEvent
from crucible.prop.promotions import resolve_promotions
from crucible.prop.ruleset import PropRuleset, load_ruleset
from crucible.prop.scenarios import (
    PRIMARY_SCENARIO_ID,
    RulesetScenario,
)
from crucible.prop.scenarios import (
    scenarios as scenario_list,
)

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence

    from numpy.typing import NDArray

    from crucible.data.cme_sessions import SessionCalendar
    from crucible.experiments.futures_run import _Prepared
    from crucible.experiments.futures_signals import DatasetRef
    from crucible.prop.rules_schema import ExecutionMode

EVALUATION_PREFIX: Final = "PRP-"
EVALUATION_ID_HEX: Final = 16
"""Hex digits of the SHA-256 kept in the directory name (64 bits, like a run id)."""

SCHEMA_VERSION: Final = 1
"""Version of this artifact layout: its file set, its attempt columns and its summary fields."""

EVALUATION_VERSION: Final = "prop-evaluation:2"
"""The semantics of a prop evaluation, in the evaluation id: a change to how an attempt is
classified or to how an interval is built is a new version, never a silent re-reading of an old
id."""

KIND: Final[Literal["prop_evaluation"]] = "prop_evaluation"

RESULT_FILES: Final = ("attempts.parquet", "summary.json", "ruleset.yaml")
"""The result files of a prop evaluation (the seal's digest covers these; ADR-0084)."""

OUTCOMES: Final = ("pass", "fail", "timeout", "horizon", "censored")
"""The five classes of ADR-0107 section 4, in report order."""

EXECUTION_MODES: Final = ("automated", "manual")
PAYOUT_POLICIES: Final = ("max_eligible", "none")
SCENARIO_MODES: Final = ("primary", "all")

PASS_PROBABILITY: Final = "pass_probability"
CONDITIONAL_PASS_PROBABILITY: Final = "conditional_pass_probability"
"""The two names of the same number: the second is used whenever anything qualifies it, so a
conditional number can never be read as a definitive one (ADR-0107 section 5)."""

BLOCK_LENGTH_POLICY: Final = "max(horizon_trading_days, ceil(sqrt(n)))"
"""ADR-0107 section 5: a block is at least H trade dates long, so it always covers the starts whose
attempts can overlap, and grows to ``ceil(sqrt(n))`` when the sequence is longer than that."""

STATISTICS: Final = ("pass_probability", "mean_net_cash_usd")
"""The two bootstrapped statistics: the pass rate and the mean net cash per attempt."""

CashStatus = Literal["exact", "conditional", "upper_bound", "unavailable"]
EligibilityStatus = Literal["eligible", "eligible_conditional", "blocked_by_compliance", "unknown"]
"""``unknown`` is never produced by the ruleset: it is reserved for a caller that cannot judge."""

_CASH_VALUES: dict[str, CashStatus] = {
    "exact": "exact",
    "conditional": "conditional",
    "upper_bound": "upper_bound",
    "unavailable": "unavailable",
}
_CASH_RANK: dict[str, int] = {name: rank for rank, name in enumerate(_CASH_VALUES)}

_ELIGIBILITY_VALUES: dict[str, EligibilityStatus] = {
    "eligible": "eligible",
    "eligible_conditional": "eligible_conditional",
    "blocked_by_compliance": "blocked_by_compliance",
    "unknown": "unknown",
}
"""The only eligibility labels a summary may carry, so a new one cannot slip in unreported."""

_ESTIMATE_RANK: dict[str, int] = {
    "complete": 0,
    "conditional": 1,
    "partial": 2,
    "unavailable": 3,
}
"""How bad an attempt's ``estimate_status`` is, for the worst-of-the-starts label."""

_NS_PER_DAY = 86_400 * 1_000_000_000
"""Nanoseconds in one calendar day (the day label an attempt window is measured in)."""

PROP_ATTEMPTS_SCHEMA: dict[str, pl.DataType] = {
    "scenario_id": pl.String(),  # primary, or <conflict_id>#<index> for a sensitivity scenario
    "scenario_label": pl.String(),  # official_primary | alternative_sensitivity
    "start_trade_date": pl.Date(),  # Globex trade date the attempt started at (a day label)
    "outcome": pl.String(),  # pass | fail | timeout | horizon | censored (ADR-0107 section 4)
    "complete": pl.Boolean(),  # true when d + H fits in the data (the start is never censored)
    "horizon_end_trade_date": pl.Date(),  # nullable: the H-th trade date of the horizon
    "horizon_trading_days": pl.Int64(),  # H, the analyst's horizon in TRADING days
    "phase_outcomes": pl.String(),  # "<phase_id>:<outcome>" per phase, joined by ';'
    "breached_rule": pl.String(),  # nullable: the rule id of the first hard breach
    "breach_time_ns": pl.Int64(),  # nullable: UTC ns of that breach
    "days_to_pass_trading": pl.Int64(),  # nullable: trading days from the start to the pass
    "days_to_pass_calendar": pl.Int64(),  # nullable: calendar days from the start to the pass
    "min_buffer_usd": pl.Decimal(38, 6),  # nullable: USD, the smallest basis-minus-threshold
    "payouts_usd": pl.Decimal(38, 6),  # USD; the trader's net payouts over the attempt
    "payout_bound": pl.String(),  # exact | upper_bound | exact+upper_bound | '' (none paid)
    "fees_evaluation_usd": pl.Decimal(38, 6),  # USD; evaluation-kind fees of the attempt
    "fees_activation_usd": pl.Decimal(38, 6),  # USD; activation fees (charged only on a pass)
    "fees_monthly_usd": pl.Decimal(38, 6),  # USD; monthly fees, per started calendar month
    "fees_reset_usd": pl.Decimal(38, 6),  # USD; reset fees bought by the attempt policy
    "fees_usd": pl.Decimal(38, 6),  # USD; every fee of the attempt, the four kinds above
    "net_cash_usd": pl.Decimal(38, 6),  # USD; payouts_usd - fees_usd (see cash_estimate_status)
    "cash_estimate_status": pl.String(),  # exact | conditional | upper_bound | unavailable
    "commission_usd": pl.Decimal(38, 6),  # nullable: USD per side the firm's commission charges
    "commission_status": pl.String(),  # known | unknown | assumption (never read as zero)
    "exchange_usd": pl.Decimal(38, 6),  # nullable: USD per side added for the exchange fee
    "exchange_status": pl.String(),  # included|excluded_priced|excluded_unpriced|unknown|assumption
    "clearing_usd": pl.Decimal(38, 6),  # nullable: USD per side added for the clearing fee
    "clearing_status": pl.String(),  # included|excluded_priced|excluded_unpriced|unknown|assumption
    "nfa_usd": pl.Decimal(38, 6),  # nullable: USD per side added for the NFA assessment
    "nfa_status": pl.String(),  # included|excluded_priced|excluded_unpriced|unknown|assumption
    "other_usd": pl.Decimal(38, 6),  # nullable: USD per side added for any other per-side charge
    "other_status": pl.String(),  # included|excluded_priced|excluded_unpriced|unknown|assumption
    "cost_status": pl.String(),  # complete | conditional | unavailable (see cost_gaps)
    "cost_gaps": pl.String(),  # components no source could price, joined by ';' ('' when none)
    "cost_assumption_sha256": pl.String(),  # nullable: SHA-256 of the cost-assumption file used
    "participant_profile_sha256": pl.String(),  # nullable: canonical sha256 of the run's profile
    "coverage_gap_count": pl.Int64(),  # news and session-calendar coverage gaps of the attempt
    "coverage_gaps": pl.String(),  # the gaps themselves, joined by ';' ('' when none)
    "estimate_status": pl.String(),  # complete | conditional | partial | unavailable
    "estimate_reasons": pl.String(),  # why the estimate is not complete, joined by ';'
    "practical_eligibility": pl.String(),  # eligible | eligible_conditional | blocked | unknown
    "practical_eligibility_conditions": pl.String(),  # what the trader must meet, ";"-joined
    "unverified_ruleset": pl.Boolean(),  # true when the ruleset has no matching verification
    "counterfactual_application": pl.Boolean(),  # data starts before the ruleset's effective_from
    "promotions_applied": pl.String(),  # promotions used, "<id>:<rule>:<field>=<v>", ";"-joined
}
"""``attempts.parquet``: one row per (scenario, start), sorted by scenario then start date."""

_SOURCE_NOTE = (
    "Every number in summary.json is a property of the simulated attempt sequence, not an "
    "assessment of the strategy: there is no threshold and no verdict (C7e). Market data is "
    "strictly before 2025-01-01, so a current ruleset applied to it is a counterfactual "
    "application, and a ruleset stays unverified until the owner confirms it (ADR-0107)."
)
"""Recorded verbatim in the summary and the manifest."""


# ---------------------------------------------------------------------------------------------
# a. the summary document


class _Strict(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class PropInterval(_Strict):
    """A percentile interval, or the reason it is not a number."""

    status: Literal["available", "unavailable"]
    low: float | None
    high: float | None
    reason: str | None


class PropBounds(_Strict):
    """The censoring bounds over ALL starts (ADR-0107 section 5)."""

    low: float | None
    high: float | None


class PropBootstrapRecord(_Strict):
    """Exactly how one interval was made, so it can be reproduced."""

    rng: str
    seed: int
    block_length_policy: str
    block_length: int
    resamples: int
    confidence: float
    observations: int


class PropProbability(_Strict):
    """The pass probability under its honest name, with its interval, bounds and reasons."""

    field: Literal["pass_probability", "conditional_pass_probability"]
    value: float | None
    interval: PropInterval
    bounds: PropBounds
    passes: int
    passes_complete: int
    complete_starts: int
    all_starts: int
    censored: int
    effective_independent_attempts: float | None
    evaluation_status: str
    definitive: bool
    reasons: list[str]


class PropCash(_Strict):
    """The mean net cash per attempt: payouts minus fees, and what the number is worth."""

    status: Literal["exact", "conditional", "upper_bound", "unavailable"]
    mean_net_cash_usd: str | None
    interval: PropInterval
    reasons: list[str]


class PropFunded(_Strict):
    """Descriptive funded-phase outcomes of the starts whose evaluation passed (no probability)."""

    passing_starts: int
    no_funded_phase: int
    survived: int
    breached: int
    unresolved: int
    payouts_made: int
    payout_total_usd: str
    payout_gross_usd: str
    fees_usd: str
    mean_net_cash_usd: str | None


class PropPracticalEligibility(_Strict):
    """Practical eligibility for the exact execution mode, and the passes it allows.

    ``eligible_conditional`` means no critical blocker applies but at least one compliance
    obligation the SIMULATION cannot prove does: ``conditions`` lists every one of them. A
    mechanical pass under a condition is counted in ``conditionally_valid_passes`` and NEVER in
    ``practically_valid_passes`` (ADR-0107 section 11, amended 2026-11-23).
    """

    execution_mode: str
    status: Literal["eligible", "eligible_conditional", "blocked_by_compliance", "unknown"]
    conditions: list[str]
    mechanical_passes: int
    practically_valid_passes: int
    conditionally_valid_passes: int
    reason: str | None


class PropUnmodeledRule(_Strict):
    """One declared unmodeled firm rule, its materiality and the fact that would change it."""

    rule: str
    materiality: str
    becomes_immaterial_if: str | None


class PropScenarioSummary(_Strict):
    """One scenario: its counts, its probability, its cash, its funded phase and its labels."""

    scenario_id: str
    ruleset_scenario_label: Literal["official", "sensitivity"]
    scenario_label: Literal["official_primary", "alternative_sensitivity"]
    conflict_id: str | None
    rationale: str
    starts: int
    complete_starts: int
    counts: dict[str, int]
    probability: PropProbability
    cash: PropCash
    funded: PropFunded
    bootstrap: dict[str, PropBootstrapRecord]
    coverage_gap_starts: int
    estimate_status: str
    estimate_reasons: list[str]
    practical_eligibility: PropPracticalEligibility
    unmodeled_rules: list[PropUnmodeledRule]
    cost_components: list[PropCostComponents]
    warnings: list[str]


class PropCostAssumption(_Strict):
    """The cost-assumption file a run used: its identity, and what it priced (ADR-0107 s10)."""

    name: str
    sha256: str
    provided_by: str
    status: str
    description: str
    evidence: str
    source_path: str
    roots: list[str]
    unused_roots: list[str]
    priced_components: list[str]
    remaining_gaps: list[str]


class PropCostComponents(_Strict):
    """The per-component cost status of one root: declared, and how the attempts priced it."""

    root: str
    participant_profile_sha256: str | None
    components: dict[str, str]
    cost_status: str
    gaps: list[str]


class PropNewsCoverage(_Strict):
    """What the economic calendar covered for the event types the rules name (ADR-0107 s12)."""

    dataset: str
    content_hash: str | None
    event_types: list[str]
    events_in_window: int
    unknown_time_events: list[str]
    covered_intervals: list[list[int]]
    gaps: list[dict[str, object]]


class PropRulesetReference(_Strict):
    """The ruleset the evaluation used, and the status the owner gave it."""

    ruleset_id: str
    version: int
    ruleset_sha256: str
    verification_status: str
    unverified: bool
    as_of: str
    effective_from: str
    effective_to: str | None
    file: str


class PropEvaluationSummary(_Strict):
    """``summary.json``: the statistics, the bootstrap record and the coverage of one evaluation."""

    schema_version: Literal[1]
    kind: Literal["prop_evaluation"]
    evaluation_id: str
    run_id: str
    candidate_id: str
    trial_family: str
    root: str
    window: dict[str, str]
    horizon_trading_days: int
    execution_mode: str
    payout_policy: str
    cost_assumption: PropCostAssumption | None
    cost_components: list[PropCostComponents]
    promotions_applied: list[str]
    promotions_not_applied: list[str]
    participant_profile: dict[str, str] | None
    participant_profile_sha256: str | None
    scenarios_requested: Literal["primary", "all"]
    start_dates: dict[str, object]
    ruleset: PropRulesetReference
    news: PropNewsCoverage
    exchange_fees: dict[str, str] | None
    scenarios: list[PropScenarioSummary]
    not_a_submission: bool
    source_note: str


def prop_evaluation_json_schema() -> dict[str, object]:
    """The JSON Schema of ``summary.json`` (``crucible schema --kind prop-evaluation``)."""
    return PropEvaluationSummary.model_json_schema()


# ---------------------------------------------------------------------------------------------
# b. horizon, start dates and the outcome classes


@dataclass(frozen=True, slots=True)
class _EvaluationPlan:
    """The calendar arithmetic a run's window implies, before anything is simulated.

    ``start_dates`` are the trade dates an attempt may start on; ``horizon_end`` maps each to the
    trade date its H-th trading day falls on (``None`` when the calendar has fewer than H trade
    dates left). ``calendar_days`` is the window length ``simulate_attempt`` needs for that start: H
    trade dates measured on the CALENDAR, not on the data, because the data may end inside the
    horizon and the attempt must then be censored, not silently shortened.
    """

    trade_dates: tuple[dt.date, ...]
    start_dates: tuple[dt.date, ...]
    horizon_end: Mapping[dt.date, dt.date | None]
    calendar_days: Mapping[dt.date, int]

    def is_complete(self, start: dt.date) -> bool:
        """Whether the start's H trade dates fit in the data (``d + H <= last date``)."""
        end = self.horizon_end[start]
        return end is not None and end <= self.trade_dates[-1]


def _start_dates(prepared: _Prepared) -> tuple[dt.date, ...]:
    """Every trade date of the window whose first scheduled bar is tradable (ADR-0107 section 4).

    A date without an on-schedule bar cannot be a start: an attempt begins at the OPEN of its trade
    date, and a date the series reaches only off schedule (outside every scheduled Globex segment)
    has no open for the account to trade from.
    """
    dates = prepared.bars.trade_dates.cast(pl.Date).to_list()
    flags = prepared.bars.on_schedule.to_list()
    selected: list[dt.date] = []
    for day, on_schedule in zip(dates, flags, strict=True):
        if on_schedule and isinstance(day, dt.date) and day not in selected:
            selected.append(day)
    if not selected:
        msg = (
            "no bar of the prepared window is on the CME schedule, so no trade date can start an "
            "attempt: check the session calendar and the execution dataset's timestamps"
        )
        raise DataQualityError(msg)
    return tuple(selected)


def _evaluation_plan(
    prepared: _Prepared, calendar: SessionCalendar, horizon_trading_days: int
) -> _EvaluationPlan:
    """The start dates of the window and, for each, the horizon end and the calendar-day window."""
    dates = prepared.bars.trade_dates.cast(pl.Date).to_list()
    trade_dates = tuple(dict.fromkeys(day for day in dates if isinstance(day, dt.date)))
    if not trade_dates:
        msg = "the prepared window holds no trade date: nothing can start an attempt"
        raise DataQualityError(msg)
    horizon_end: dict[dt.date, dt.date | None] = {}
    calendar_days: dict[dt.date, int] = {}
    for start in _start_dates(prepared):
        end = _nth_trade_date(calendar, start, horizon_trading_days)
        horizon_end[start] = end
        calendar_days[start] = (trade_dates[-1] - start).days if end is None else (end - start).days
    return _EvaluationPlan(
        trade_dates=trade_dates,
        start_dates=tuple(sorted(horizon_end)),
        horizon_end=horizon_end,
        calendar_days=calendar_days,
    )


def _nth_trade_date(
    calendar: SessionCalendar, start: dt.date, horizon_trading_days: int
) -> dt.date | None:
    """The ``horizon_trading_days``-th Globex trade date counting ``start`` as the first, or None.

    Read from the SESSION CALENDAR (never from the data): the horizon is the analyst's H trade
    dates, and whether the data covers them decides whether a start is complete, not how long the
    attempt is allowed to run.
    """
    if horizon_trading_days < 1:
        msg = f"horizon_trading_days must be >= 1, got {horizon_trading_days}"
        raise ConfigurationError(msg)
    # four calendar days per trade date is generous for a five-session week, plus the closures a
    # holiday week adds; ask the calendar for that range and count its trade dates
    limit = min(calendar.last, start + dt.timedelta(days=4 * horizon_trading_days + 14))
    sessions = calendar.sessions(start, limit)
    if len(sessions) < horizon_trading_days:
        return None
    return sessions[horizon_trading_days - 1].trade_date


def classify_attempt(attempt: AttemptResult, *, complete: bool) -> str:
    """One attempt's class, from its phases (ADR-0107 section 4).

    ``pass`` requires EVERY evaluation phase to have passed — the funded phase's own outcome is
    descriptive and never turns a passed evaluation into something else. A hard breach in an
    evaluation phase is ``fail``; the firm's own time limit is ``timeout``; an attempt the horizon
    (or the data) ended unresolved is ``horizon`` when its H trade dates fit in the data and
    ``censored`` when they do not.
    """
    phases = [phase for phase in attempt.phase_outcomes if phase.kind == "evaluation"]
    if not phases:
        phases = list(attempt.phase_outcomes)
    if any(phase.outcome == "fail" for phase in phases):
        return "fail"
    if phases and all(phase.outcome == "pass" for phase in phases):
        return "pass"
    if any(phase.outcome == "timeout" for phase in phases):
        return "timeout"
    return "horizon" if complete else "censored"


# ---------------------------------------------------------------------------------------------
# c. statistics and the bootstrap


def prop_block_length(n: int, horizon_trading_days: int) -> int:
    """``max(H, ceil(sqrt(n)))``: a block always spans the starts whose attempts can overlap."""
    if n < 1:
        msg = f"a bootstrap block length needs at least one observation; got n={n}"
        raise ConfigurationError(msg)
    return max(horizon_trading_days, block_length(n))


def _mean(values: NDArray[np.float64]) -> float:
    return float(np.mean(values))


def _interval_document(
    values: NDArray[np.float64],
    *,
    evaluation_id: str,
    statistic_name: str,
    horizon_trading_days: int,
    resamples: int,
    confidence: float,
    what: str,
) -> tuple[PropInterval, PropBootstrapRecord | None]:
    """The seeded circular block bootstrap interval of one statistic, and how it was made.

    Fewer than two blocks (``n < 2 * block``) makes the interval ``unavailable`` with its reason:
    one block resampled twice is the same block, so there is no dispersion to report.
    """
    n = len(values)
    if n == 0:
        return (
            PropInterval(
                status="unavailable",
                low=None,
                high=None,
                reason=f"there is no complete start to resample the {what} from",
            ),
            None,
        )
    block = prop_block_length(n, horizon_trading_days)
    record = PropBootstrapRecord(
        rng=BOOTSTRAP_RNG,
        seed=bootstrap_seed(evaluation_id, statistic_name),
        block_length_policy=BLOCK_LENGTH_POLICY,
        block_length=block,
        resamples=resamples,
        confidence=confidence,
        observations=n,
    )
    if n < 2 * block:
        return (
            PropInterval(
                status="unavailable",
                low=None,
                high=None,
                reason=(
                    f"{n} complete start(s) is fewer than two blocks of {block} trade dates "
                    f"(H = {horizon_trading_days}), so the {what} has no dispersion to report"
                ),
            ),
            record,
        )
    samples = circular_block_bootstrap(
        values,
        _mean,
        rng=np.random.Generator(np.random.PCG64(record.seed)),
        resamples=resamples,
        length=block,
    )
    low, high = percentile_interval(samples, confidence)
    return PropInterval(status="available", low=low, high=high, reason=None), record


def _ratio(numerator: int, denominator: int) -> float | None:
    return None if denominator == 0 else numerator / denominator


def _mean_money(values: Sequence[Decimal]) -> Decimal | None:
    """The exact mean of a list of USD ``Decimal`` amounts, at the micro-dollar, or ``None``."""
    if not values:
        return None
    total = sum(values, Decimal(0))
    return (total / len(values)).quantize(Decimal("0.000001"))


# ---------------------------------------------------------------------------------------------
# d. the news calendar and the coverage it implies


def calendar_event_types(rulesets: Iterable[PropRuleset]) -> tuple[str, ...]:
    """The event types the rules' news restrictions name, sorted and de-duplicated."""
    names: set[str] = set()
    for ruleset in rulesets:
        for rule in ruleset.news_rules():
            names.update(rule.event_types)
    return tuple(sorted(names))


def covered_intervals(
    coverage: EconCalendarCoverage, event_types: Sequence[str]
) -> tuple[tuple[int, int], ...]:
    """The instants at which EVERY named event type is covered, as half-open intervals.

    A type's coverage runs from its first event to its last, minus the periods the dataset declares
    as gaps; the intervals reported here are their intersection, because a news rule is only
    modeled when the calendar would have carried an event of every type the rule names. An empty
    result means the period is not covered at all, which is ``not_modeled`` and reported.
    """
    per_type: list[list[tuple[int, int]]] = []
    for event_type in event_types:
        spans = [span for span in coverage.spans if span.event_type == event_type]
        if not spans:
            return ()
        intervals = [
            (min(span.first_event for span in spans), max(span.last_event for span in spans))
        ]
        for gap in coverage.gaps_of(event_type):
            intervals = _subtract(intervals, gap.start_at, gap.end_at)
        per_type.append(intervals)
    if not per_type:
        return ()
    out = per_type[0]
    for intervals in per_type[1:]:
        out = _intersect(out, intervals)
    return tuple(out)


def _subtract(intervals: list[tuple[int, int]], low: int, high: int) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    for start, end in intervals:
        if high <= start or end <= low:
            out.append((start, end))
            continue
        if start < low:
            out.append((start, min(end, low)))
        if high < end:
            out.append((max(start, high), end))
    return [(start, end) for start, end in out if start < end]


def _intersect(left: list[tuple[int, int]], right: list[tuple[int, int]]) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    for a_low, a_high in left:
        for b_low, b_high in right:
            low, high = max(a_low, b_low), min(a_high, b_high)
            if low < high:
                out.append((low, high))
    return sorted(out)


def _news_events(
    store: ParquetDataStore, dataset: str, event_types: Sequence[str], start_ns: int, end_ns: int
) -> tuple[NewsEvent, ...]:
    """The calendar rows of ``event_types`` in ``[start_ns, end_ns)``, ``time_known`` passed
    through.

    An event type the dataset does not carry is not requested here (the request would be refused)
    and stays absent from the result, which is how ``simulate_attempt`` reports it: the rule naming
    it is ``not_modeled`` for the attempt, never "no news".
    """
    wanted = [name for name in event_types if name in EVENT_TYPES]
    if not wanted:
        return ()
    frame = load_econ_events(store, wanted, start_ns, end_ns, dataset=DatasetId(dataset))
    return tuple(
        NewsEvent(
            event_id=str(row["event_id"]),
            event_type=str(row["event_type"]),
            scheduled_ns=int(row["event_time"]),
            time_known=bool(row["time_known"]),
        )
        for row in frame.iter_rows(named=True)
    )


def _calendar_gaps(
    coverage: EconCalendarCoverage, event_types: Sequence[str], start_ns: int, end_ns: int
) -> list[dict[str, object]]:
    """The dataset's declared gaps that overlap the evaluation window, for the artifact."""
    wanted = set(event_types)
    rows: list[dict[str, object]] = []
    for gap in coverage.gaps:
        if gap.event_type not in wanted:
            continue
        if gap.end_at <= start_ns or end_ns <= gap.start_at:
            continue
        rows.append(
            {
                "event_type": gap.event_type,
                "start_at": gap.start_at,
                "end_at": gap.end_at,
                "periods": gap.periods,
                "reason": gap.reason,
            }
        )
    return rows


# ---------------------------------------------------------------------------------------------
# e. one scenario


@dataclass(frozen=True, slots=True)
class _Classified:
    """One (scenario, start): the raw attempt plus the evaluation's own class and horizon."""

    scenario: RulesetScenario
    start: dt.date
    horizon_end: dt.date | None
    complete: bool
    outcome: str
    attempt: AttemptResult


def _scenario_label(
    scenario: RulesetScenario,
) -> Literal["official_primary", "alternative_sensitivity"]:
    """``official_primary`` or ``alternative_sensitivity`` — never a bare ``official``."""
    return "official_primary" if scenario.is_primary else "alternative_sensitivity"


def _estimate_label(classifications: Iterable[_Classified]) -> tuple[str, list[str]]:
    """The worst ``estimate_status`` of the scenario's attempts and every distinct reason."""
    status = "complete"
    reasons: set[str] = set()
    for item in classifications:
        current = item.attempt.estimate_status
        if _ESTIMATE_RANK.get(current, 0) > _ESTIMATE_RANK[status]:
            status = current
        reasons.update(item.attempt.estimate_reasons)
    return status, sorted(reasons)


def _probability_reasons(
    *,
    status: EvaluationStatus,
    material_unmodeled: Sequence[str],
    verified: bool,
    cost_assumption: str | None,
    news_gap_starts: int,
    session_gaps: Sequence[str],
    counterfactual_starts: int,
    cash_status: CashStatus,
    cash_reasons: Sequence[str],
    blocked_execution_mode: str | None,
) -> list[str]:
    """Every reason the pass probability is not definitive (ADR-0107 sections 5, 11 and 12)."""
    reasons: list[str] = []
    if status == "blocked":
        reasons.append(
            "a critical rule is not modeled, so the probability is not definitive (blocked)"
            if not material_unmodeled
            else "critical rules are not modeled: "
            + ", ".join(sorted(material_unmodeled))
            + " (blocked)"
        )
    elif status == "conditional_on_modeled_rules":
        reasons.append(
            "material rules are not modeled: " + ", ".join(sorted(material_unmodeled))
            if material_unmodeled
            else "the ruleset declares material values it cannot model"
        )
    if not verified:
        reasons.append("the ruleset is unverified: only the owner can confirm it")
    if cost_assumption is not None:
        reasons.append(f"a cost assumption {cost_assumption!r} was used")
    if cash_status == "unavailable":
        reasons.append(
            "the cost of the attempt is unknown, so the cash statistic is unavailable: "
            + "; ".join(cash_reasons)
        )
    if news_gap_starts:
        reasons.append(
            f"the economic calendar does not cover {news_gap_starts} start(s) of the window"
        )
    if session_gaps:
        reasons.append(
            "the attempt trades through an unsourced CME session-calendar window: "
            + ", ".join(sorted(set(session_gaps)))
        )
    if counterfactual_starts:
        reasons.append(
            f"{counterfactual_starts} start(s) apply a ruleset that took effect after the data "
            "(a counterfactual application)"
        )
    if blocked_execution_mode is not None:
        reasons.append(
            f"practical eligibility is blocked_by_compliance for {blocked_execution_mode} "
            "execution, so no pass is a practically valid pass"
        )
    return reasons


def _funded_document(passing: Sequence[_Classified]) -> PropFunded:
    """The funded phase's outcomes over the passing starts: descriptive only (ADR-0107 s4)."""
    survived = breached = unresolved = no_funded = 0
    payouts_made = 0
    net_total = Decimal(0)
    gross_total = Decimal(0)
    fees_total = Decimal(0)
    for item in passing:
        funded = [phase for phase in item.attempt.phase_outcomes if phase.kind == "funded"]
        if not funded:
            no_funded += 1
        elif any(phase.outcome == "fail" for phase in funded):
            breached += 1
        elif all(phase.outcome == "pass" for phase in funded):
            survived += 1
        else:
            unresolved += 1
        payouts_made += len(item.attempt.payouts)
        net_total += item.attempt.payouts_usd
        gross_total += sum((record.gross_usd for record in item.attempt.payouts), Decimal(0))
        fees_total += item.attempt.fees_usd
    mean = _mean_money([item.attempt.net_cash_usd for item in passing])
    return PropFunded(
        passing_starts=len(passing),
        no_funded_phase=no_funded,
        survived=survived,
        breached=breached,
        unresolved=unresolved,
        payouts_made=payouts_made,
        payout_total_usd=str(net_total),
        payout_gross_usd=str(gross_total),
        fees_usd=str(fees_total),
        mean_net_cash_usd=None if mean is None else str(mean),
    )


def _cost_components_document(
    classifications: Sequence[_Classified],
) -> list[PropCostComponents]:
    """The per-component cost status of each root the attempts priced (ADR-0107 section 10).

    One entry per root, listing the five components (``commission`` plus ``exchange``,
    ``clearing``, ``nfa``, ``other``) with the status the attempt recorded, and the gaps that
    remained. A component priced differently by different starts is ``mixed``: the table reports
    the disagreement instead of picking one.
    """
    seen: dict[str, dict[str, set[str]]] = {}
    gaps: dict[str, set[str]] = {}
    statuses: dict[str, set[str]] = {}
    participant: dict[str, str | None] = {}
    for item in classifications:
        application = item.attempt.commissions
        root = application.root
        entries = seen.setdefault(root, {})
        for charge in application.components:
            entries.setdefault(charge.component, set()).add(charge.status)
        gaps.setdefault(root, set()).update(application.cost_gaps)
        statuses.setdefault(root, set()).add(application.cost_status)
        if application.participant_profile_sha256 is not None:
            participant[root] = application.participant_profile_sha256
    document: list[PropCostComponents] = []
    for root in sorted(seen):
        components = {
            name: (next(iter(values)) if len(values) == 1 else "mixed")
            for name, values in seen[root].items()
        }
        cost_statuses = statuses.get(root, set())
        document.append(
            PropCostComponents(
                root=root,
                participant_profile_sha256=participant.get(root),
                components=components,
                cost_status=(next(iter(cost_statuses)) if len(cost_statuses) == 1 else "mixed"),
                gaps=sorted(gaps.get(root, set())),
            )
        )
    return document


def _eligibility_reason(
    *,
    ruleset: PropRuleset,
    execution_mode: str,
    status: EligibilityStatus,
    conditions: tuple[str, ...],
) -> str | None:
    """Why the execution mode is not plainly eligible, in one sentence (ADR-0107 section 11).

    ``blocked_by_compliance`` and ``eligible_conditional`` answer different questions: the first
    says the account may not be traded this way at all, the second says it may, but only while the
    trader keeps every listed obligation, which the simulation cannot prove.
    """
    if status == "blocked_by_compliance":
        return (
            f"{execution_mode} execution is blocked by a critical compliance rule of "
            f"{ruleset.ruleset_id} v{ruleset.version}: a mechanically successful attempt under a "
            "compliance blocker is never a practically valid pass (ADR-0107 section 11)"
        )
    if status == "eligible_conditional":
        return (
            f"{execution_mode} execution is eligible only under {len(conditions)} condition(s) "
            f"the simulation cannot prove, listed in this block; a mechanical pass is a "
            "conditionally valid pass, never a practically valid one, and meeting them is the "
            "trader's responsibility, not something the ruleset's authorization guarantees "
            "(ADR-0107 section 11)"
        )
    return None


def _scenario_summary(
    scenario: RulesetScenario,
    classifications: Sequence[_Classified],
    *,
    evaluation_id: str,
    horizon_trading_days: int,
    execution_mode: ExecutionMode,
    cost_assumption: str | None,
    resamples: int,
    confidence: float,
) -> PropScenarioSummary:
    """One scenario's statistics, bootstrap records, funded descriptives and labels."""
    counts = dict.fromkeys(OUTCOMES, 0)
    for item in classifications:
        counts[item.outcome] += 1
    all_starts = len(classifications)
    complete = [item for item in classifications if item.complete]
    passes_all = counts["pass"]
    passes_complete = sum(1 for item in complete if item.outcome == "pass")
    censored = counts["censored"]

    indicator = np.array(
        [1.0 if item.outcome == "pass" else 0.0 for item in complete], dtype=np.float64
    )
    interval, pass_record = _interval_document(
        indicator,
        evaluation_id=evaluation_id,
        statistic_name=PASS_PROBABILITY,
        horizon_trading_days=horizon_trading_days,
        resamples=resamples,
        confidence=confidence,
        what="pass probability",
    )
    records: dict[str, PropBootstrapRecord] = {}
    if pass_record is not None:
        records[PASS_PROBABILITY] = pass_record

    cash_status: CashStatus = "exact"
    cash_reasons: set[str] = set()
    for item in complete:
        current = item.attempt.cash_estimate_status
        if _CASH_RANK.get(current, 0) > _CASH_RANK[cash_status]:
            cash_status = _CASH_VALUES.get(current, "unavailable")
        cash_reasons.update(item.attempt.cash_estimate_reasons)
    cash_values = np.array(
        [float(item.attempt.net_cash_usd) for item in complete], dtype=np.float64
    )
    cash_interval, cash_record = _interval_document(
        cash_values,
        evaluation_id=evaluation_id,
        statistic_name="mean_net_cash_usd",
        horizon_trading_days=horizon_trading_days,
        resamples=resamples,
        confidence=confidence,
        what="mean net cash per attempt",
    )
    if cash_record is not None:
        records["mean_net_cash_usd"] = cash_record
    # the mean money is exact (Decimal), not a float: an attempt-level cash number is USD to the
    # micro-dollar, and a mean that drifts in the 15th digit is a number nobody can reconcile
    mean_cash = _mean_money([item.attempt.net_cash_usd for item in complete])
    cash_reasons_sorted = sorted(cash_reasons)
    if cash_status == "unavailable":
        # a number never travels beside an unavailable status: the mean of an incomplete cost is
        # not the mean net cash, it is a smaller number wearing its name
        mean_cash = None
        cash_interval = PropInterval(
            status="unavailable",
            low=None,
            high=None,
            reason="the net cash per attempt is not a number: " + "; ".join(cash_reasons_sorted),
        )

    coverage = rule_coverage(scenario.ruleset)
    status = evaluation_status(coverage)
    material = tuple(
        row.rule for row in coverage if not row.modeled and row.materiality != "immaterial"
    )
    news_gap_starts = sum(1 for item in classifications if item.attempt.news_coverage_gaps)
    session_gaps = [gap for item in classifications for gap in item.attempt.session_calendar_gaps]
    counterfactual_starts = sum(
        1 for item in classifications if item.attempt.counterfactual_application
    )
    raw_eligibility = practical_eligibility(scenario.ruleset, execution_mode)
    eligibility: EligibilityStatus = _ELIGIBILITY_VALUES.get(raw_eligibility.status, "unknown")
    blocked = eligibility == "blocked_by_compliance"
    conditional = eligibility == "eligible_conditional"
    reasons = _probability_reasons(
        status=status,
        material_unmodeled=material,
        verified=scenario.ruleset.verified,
        cost_assumption=cost_assumption,
        news_gap_starts=news_gap_starts,
        session_gaps=session_gaps,
        counterfactual_starts=counterfactual_starts,
        cash_status=cash_status,
        cash_reasons=cash_reasons_sorted,
        blocked_execution_mode=execution_mode if blocked else None,
    )
    definitive = not reasons
    probability = PropProbability(
        field=PASS_PROBABILITY if definitive else CONDITIONAL_PASS_PROBABILITY,
        value=_ratio(passes_complete, len(complete)),
        interval=interval,
        bounds=PropBounds(
            low=_ratio(passes_all, all_starts),
            high=_ratio(passes_all + censored, all_starts),
        ),
        passes=passes_all,
        passes_complete=passes_complete,
        complete_starts=len(complete),
        all_starts=all_starts,
        censored=censored,
        effective_independent_attempts=(
            None if not complete else len(complete) / horizon_trading_days
        ),
        evaluation_status=status,
        definitive=definitive,
        reasons=reasons,
    )
    estimate_status, estimate_reasons = _estimate_label(classifications)
    warnings: set[str] = set()
    for item in classifications:
        warnings.update(item.attempt.warnings)
    passing = [item for item in classifications if item.outcome == "pass"]
    return PropScenarioSummary(
        scenario_id=scenario.scenario_id,
        ruleset_scenario_label=scenario.label,
        scenario_label=_scenario_label(scenario),
        conflict_id=scenario.conflict_id,
        rationale=scenario.rationale,
        starts=all_starts,
        complete_starts=len(complete),
        counts=counts,
        probability=probability,
        cash=PropCash(
            status=cash_status,
            mean_net_cash_usd=None if mean_cash is None else str(mean_cash),
            interval=cash_interval,
            reasons=cash_reasons_sorted,
        ),
        funded=_funded_document(passing),
        bootstrap=records,
        coverage_gap_starts=sum(
            1
            for item in classifications
            if item.attempt.news_coverage_gaps or item.attempt.session_calendar_gaps
        ),
        estimate_status=estimate_status,
        estimate_reasons=estimate_reasons,
        cost_components=_cost_components_document(classifications),
        practical_eligibility=PropPracticalEligibility(
            execution_mode=execution_mode,
            status=eligibility,
            conditions=list(raw_eligibility.conditions),
            mechanical_passes=passes_all,
            practically_valid_passes=0 if (blocked or conditional) else passes_all,
            conditionally_valid_passes=passes_all if conditional else 0,
            reason=_eligibility_reason(
                ruleset=scenario.ruleset,
                execution_mode=execution_mode,
                status=eligibility,
                conditions=raw_eligibility.conditions,
            ),
        ),
        unmodeled_rules=[
            PropUnmodeledRule(
                rule=entry.rule,
                materiality=entry.materiality,
                becomes_immaterial_if=entry.becomes_immaterial_if,
            )
            for entry in sorted(scenario.ruleset.not_modeled, key=lambda entry: entry.rule)
        ],
        warnings=sorted(warnings),
    )


# ---------------------------------------------------------------------------------------------
# f. the attempt rows


def _attempt_row(item: _Classified, horizon_trading_days: int) -> dict[str, object]:
    """One ``attempts.parquet`` row: the attempt, its class and its coverage."""
    attempt = item.attempt
    application = attempt.commissions
    gaps = [*attempt.news_coverage_gaps, *attempt.session_calendar_gaps]
    return {
        "scenario_id": item.scenario.scenario_id,
        "scenario_label": _scenario_label(item.scenario),
        "start_trade_date": item.start,
        "outcome": item.outcome,
        "complete": item.complete,
        "horizon_end_trade_date": item.horizon_end,
        "horizon_trading_days": horizon_trading_days,
        "phase_outcomes": ";".join(
            f"{phase.phase_id}:{phase.outcome}" for phase in attempt.phase_outcomes
        ),
        "breached_rule": attempt.breached_rule,
        "breach_time_ns": attempt.breach_time_ns,
        "days_to_pass_trading": attempt.days_to_pass_trading,
        "days_to_pass_calendar": attempt.days_to_pass_calendar,
        "min_buffer_usd": attempt.min_buffer_usd,
        "payouts_usd": attempt.payouts_usd,
        "payout_bound": "+".join(sorted({record.bound for record in attempt.payouts})),
        "fees_evaluation_usd": attempt.fees.evaluation_usd,
        "fees_activation_usd": attempt.fees.activation_usd,
        "fees_monthly_usd": attempt.fees.monthly_usd,
        "fees_reset_usd": attempt.fees.reset_usd,
        "fees_usd": attempt.fees.total_usd,
        "net_cash_usd": attempt.net_cash_usd,
        "cash_estimate_status": attempt.cash_estimate_status,
        "commission_usd": application.component("commission").usd,
        "commission_status": application.component("commission").status,
        "exchange_usd": application.component("exchange").usd,
        "exchange_status": application.component("exchange").status,
        "clearing_usd": application.component("clearing").usd,
        "clearing_status": application.component("clearing").status,
        "nfa_usd": application.component("nfa").usd,
        "nfa_status": application.component("nfa").status,
        "other_usd": application.component("other").usd,
        "other_status": application.component("other").status,
        "cost_status": application.cost_status,
        "cost_gaps": ";".join(application.cost_gaps),
        "cost_assumption_sha256": application.cost_assumption_sha256,
        "participant_profile_sha256": application.participant_profile_sha256,
        "coverage_gap_count": len(gaps),
        "coverage_gaps": ";".join(gaps),
        "estimate_status": attempt.estimate_status,
        "estimate_reasons": ";".join(attempt.estimate_reasons),
        "practical_eligibility": attempt.practical_eligibility,
        "practical_eligibility_conditions": ";".join(attempt.practical_eligibility_conditions),
        "unverified_ruleset": attempt.unverified_ruleset,
        "counterfactual_application": attempt.counterfactual_application,
        "promotions_applied": ";".join(attempt.promotions_applied),
    }


def attempts_frame(
    classifications: Sequence[_Classified], horizon_trading_days: int
) -> pl.DataFrame:
    """``attempts.parquet``: one row per (scenario, start), sorted by scenario then start date."""
    rows = [
        _attempt_row(item, horizon_trading_days)
        for item in sorted(
            classifications, key=lambda item: (item.scenario.scenario_id, item.start)
        )
    ]
    return pl.DataFrame(rows, schema=PROP_ATTEMPTS_SCHEMA, strict=True)


# ---------------------------------------------------------------------------------------------
# g. the evaluation


@dataclass(frozen=True, slots=True)
class PropEvaluationResult:
    """What a finished evaluation hands back. ``summary`` is the ``summary.json`` document."""

    evaluation_dir: Path
    evaluation_id: str
    artifact_id: str
    summary: dict[str, object]


def _scenario_mode(value: str) -> Literal["primary", "all"]:
    """The scenario selection as its literal type; anything else is refused by name."""
    if value == "primary":
        return "primary"
    if value == "all":
        return "all"
    msg = (
        f"scenarios {value!r} is not one of {list(SCENARIO_MODES)}: 'primary' simulates the "
        "selected ruleset only and 'all' adds every sensitivity scenario of its conflicts"
    )
    raise ConfigurationError(msg)


def _refuse_options(
    *,
    horizon_trading_days: int,
    execution_mode: str,
    payout_policy: str,
    scenarios_requested: str,
) -> None:
    """Refuse anything that would make the evaluation mean something other than what it says."""
    if horizon_trading_days < 1:
        msg = (
            f"horizon_trading_days must be >= 1, got {horizon_trading_days}: an attempt has to "
            "run at least one trade date"
        )
        raise ConfigurationError(msg)
    if execution_mode not in EXECUTION_MODES:
        msg = (
            f"execution_mode {execution_mode!r} is not one of {list(EXECUTION_MODES)}: practical "
            "eligibility depends on how the strategy is executed, so the mode is required"
        )
        raise ConfigurationError(msg)
    if payout_policy not in PAYOUT_POLICIES:
        msg = (
            f"payout_policy {payout_policy!r} is not one of {list(PAYOUT_POLICIES)}: taking a "
            "payout is the trader's choice, and the attempt records which one was simulated"
        )
        raise ConfigurationError(msg)
    if scenarios_requested not in SCENARIO_MODES:
        _scenario_mode(scenarios_requested)


def _first_trade_date_at_or_after(calendar: SessionCalendar, day: dt.date) -> dt.date:
    """The first Globex trade date at or after ``day``; ``day`` itself past the calendar's end."""
    cursor = day
    while cursor <= calendar.last:
        if calendar.is_trade_date(cursor):
            return cursor
        cursor += dt.timedelta(days=1)
    return day


def _refuse_horizon(
    ruleset: PropRuleset,
    plan: _EvaluationPlan,
    horizon_trading_days: int,
    calendar: SessionCalendar,
) -> None:
    """Refuse an H shorter than any phase's own time limit (ADR-0107 section 4).

    A trading-day limit is compared directly. A CALENDAR-day limit is converted per start with the
    session calendar: the phase ends on the first rule-day at or after ``d + C``, so H has to reach
    that trade date or the firm's limit could never fire inside the horizon.
    """
    for phase in ruleset.phases:
        # a limit is declared on the phase or, in the schema-version-2 vocabulary, by a
        # ``time_limit`` rule of it: both end a phase, and H has to be able to see it happen
        rules = [
            rule for rule in (*phase.rules, *phase.pass_conditions) if rule.kind == "time_limit"
        ]
        trading_limits = [phase.max_trading_days, *(rule.max_trading_days for rule in rules)]
        calendar_limits = [phase.max_calendar_days, *(rule.max_calendar_days for rule in rules)]
        for limit in trading_limits:
            if limit is None or limit <= horizon_trading_days:
                continue
            msg = (
                f"horizon_trading_days = {horizon_trading_days} is shorter than phase "
                f"{phase.phase_id!r}'s trading-day limit {limit}: the firm's own limit could never "
                "end the phase inside the horizon. Raise the horizon to at least "
                f"{limit}"
            )
            raise ConfigurationError(msg)
        for days in (limit for limit in calendar_limits if limit is not None):
            for start in plan.start_dates:
                end = plan.horizon_end[start]
                limit_day = start + dt.timedelta(days=days)
                if end is not None and limit_day <= end:
                    continue
                reached = _first_trade_date_at_or_after(calendar, limit_day)
                msg = (
                    f"horizon_trading_days = {horizon_trading_days} is shorter than phase "
                    f"{phase.phase_id!r}'s calendar-day limit {days}: from {start} that limit is "
                    f"reached on {reached}, and H trade dates end on "
                    f"{end if end is not None else 'past the window'}. Raise the horizon so the "
                    "firm's own limit can fire inside it"
                )
                raise ConfigurationError(msg)


def evaluation_basis(
    *,
    run_basis: str,
    ruleset_sha256: str,
    horizon_trading_days: int,
    execution_mode: str,
    payout_policy: str,
    cost_assumption: CostAssumption | None,
    scenarios_requested: str,
    news_dataset: str,
    news_hash: str,
    exchange_fees_dataset: str,
    exchange_fees_hash: str,
    participant_profile_sha256: str | None = None,
) -> str:
    """The text the evaluation id hashes: every input that can change a number or a label."""
    return "|".join(
        [
            run_basis,
            ruleset_sha256,
            f"horizon={horizon_trading_days}",
            f"execution_mode={execution_mode}",
            f"payout_policy={payout_policy}",
            f"cost_assumption={cost_assumption.name if cost_assumption else ''}"
            f":{cost_assumption.sha256 if cost_assumption else ''}",
            f"participant_profile={participant_profile_sha256 or ''}",
            f"scenarios={scenarios_requested}",
            f"news={news_dataset}:{news_hash}",
            f"exchange_fees={exchange_fees_dataset}:{exchange_fees_hash}",
            EVALUATION_VERSION,
        ]
    )


def evaluation_id_of(basis: str) -> str:
    """``PRP-`` + the truncated SHA-256 of the basis."""
    digest = hashlib.sha256(basis.encode("utf-8")).hexdigest()[:EVALUATION_ID_HEX]
    return f"{EVALUATION_PREFIX}{digest}"


def _content_hash(store: ParquetDataStore, dataset: str) -> str | None:
    """A dataset's content hash, or ``None`` when the store does not hold it (never a guess)."""
    try:
        return store.manifest(DatasetId(dataset)).content_hash
    except (CrucibleError, KeyError, OSError):
        return None


def _needs_exchange_fees(rulesets: Iterable[PropRuleset]) -> bool:
    """Whether any scenario's commission declares a component the firm charges ON TOP of it."""
    return any(bool(ruleset.commissions.excluded_components) for ruleset in rulesets)


def _refuse_missing_profile(
    rulesets: Iterable[PropRuleset], *, selected: PropRuleset, value: ParticipantProfile | None
) -> None:
    """Refuse a missing participant profile when a ruleset prices a component on top.

    The profile is a RUN input because a ruleset never states one, and every fee row states the
    classification it is written for: without a profile an ``excluded`` component cannot be priced
    at all, so the run stops here instead of reporting every attempt as a gap.
    """
    excluded = sorted(
        {name for ruleset in rulesets for name in ruleset.commissions.excluded_components}
    )
    if excluded and value is None:
        msg = (
            f"ruleset {selected.ruleset_id} v{selected.version} declares {excluded} charged on top "
            "of the commission, so the run needs a participant profile (--participant-profile "
            "FILE), e.g. 'cme_membership_status: non_member' and "
            "'nfa_assessment_eligibility: fcm_member': each fee row states the classification it "
            "is written for and the ruleset never states one"
        )
        raise ConfigurationError(msg)


def _replace(directory: Path, overwrite: bool) -> None:
    """Create the evaluation directory, or replace it (keeping the previous seal's time)."""
    if directory.exists():
        if not overwrite:
            msg = (
                f"evaluation directory {directory} already exists: these inputs were already "
                "evaluated. Pass overwrite=True to re-run it (a reproduction keeps the same "
                "artifact id, and nothing is recorded as a trial either way)"
            )
            raise ConfigurationError(msg)
        shutil.rmtree(directory)
    directory.mkdir(parents=True, exist_ok=True)


def _midnight_ns(day: dt.date) -> int:
    """UTC nanoseconds at 00:00 of ``day`` (a day boundary, never an instant in a session)."""
    return int(dt.datetime.combine(day, dt.time(0, 0), tzinfo=dt.UTC).timestamp()) * 1_000_000_000


def _session_table_hash(calendar: SessionCalendar) -> str:
    """The session calendar's table hash (the run id's own calendar input)."""
    from crucible.data.cme_sessions import table_summary

    return str(table_summary(calendar.table)["sha256"])


def _ref_document(ref: DatasetRef) -> dict[str, object]:
    """One dataset reference as JSON-ready values."""
    return dict(asdict(ref))


def run_prop_evaluation(
    config: FuturesRunConfig,
    *,
    ruleset_path: str | Path,
    horizon_trading_days: int,
    execution_mode: ExecutionMode,
    payout_policy: str = "max_eligible",
    cost_assumption: str | Path | None = None,
    participant_profile: ParticipantProfile | None = None,
    scenarios: str = "primary",
    news_dataset: str = "econ_events_v2",
    exchange_fees_dataset: str = "exchange_fees_v1",
    store_root: Path,
    artifacts_root: Path,
    home: Path | None = None,
    overwrite: bool = False,
) -> PropEvaluationResult:
    """Evaluate one ruleset over one futures run's attempt sequence and seal the artifact.

    ``config``/``store_root`` are the run (the signal is prepared once, exactly as ``run_futures``
    prepares it). ``ruleset_path`` is one v2 ruleset file; its exact bytes are copied into the
    artifact and its content hash locks the evaluation id. ``horizon_trading_days`` (H) is the
    analyst's horizon, refused when it is shorter than any phase's own limit. ``execution_mode`` is
    required because practical eligibility depends on it, and ``payout_policy`` is the trader's
    choice between taking every eligible payout and none. ``cost_assumption`` is the PATH of a
    cost-assumption YAML file (``crucible.prop.costs.load_cost_assumption``): the user's explicit,
    unverified statement that prices the exact cost gaps it names, without which the cash statistics
    are ``unavailable``. ``participant_profile`` is the run's declaration of who its account is — a
    flat mapping from classification dimension to value
    (``crucible.data.exchange_fees.ParticipantProfile``), e.g.
    ``{cme_membership_status: non_member, nfa_assessment_eligibility: fcm_member}``. Each fee row
    names the one dimension it needs, so a component the firm charges on top of the commission is
    required-resolvable through the profile: it is required as soon as a component is declared
    ``excluded``, and the profile that priced anything is recorded by its canonical SHA-256 in the
    manifest, the summary and every attempts row.

    ``scenarios``: ``primary`` evaluates the selected ruleset only; ``all`` adds one full
    sensitivity scenario per conflict alternative (ADR-0107 section 7), reported beside the
    primary, never instead of it. ``news_dataset``/``exchange_fees_dataset`` name the versioned
    datasets the rules read (the economic calendar and the exchange/regulatory fee table); their
    content hashes join the evaluation id, and a fee table is only read when a commission excludes
    the fees. ``home``: the Crucible home whose vault declaration is honored (``None``: no home
    declaration — the store's own declaration always is, and the data layer refuses a protected
    read regardless).

    Timing: a pure function of the inputs; the only clock read is the seal's ``created_at``.
    Pessimism: fills come from ``simulate_futures`` inside ``simulate_attempt``, a censored attempt
    is its own class, and an uncovered news window or an unmodeled rule is reported rather than
    assumed away. A prop evaluation is NOT a submission: no trial is recorded.
    """
    _refuse_options(
        horizon_trading_days=horizon_trading_days,
        execution_mode=execution_mode,
        payout_policy=payout_policy,
        scenarios_requested=scenarios,
    )
    refuse_protected_window(
        root=config.root,
        start=config.window.start,
        end=config.window.end,
        store_root=store_root,
        home=home,
        what=f"the prop evaluation of {config.run.name!r}",
    )
    prepared = import_prepared_run(config, store_root)
    calendar = prepared.calendar
    plan = _evaluation_plan(prepared, calendar, horizon_trading_days)
    ruleset_file = Path(ruleset_path)
    ruleset_bytes = ruleset_file.read_bytes()
    ruleset = load_ruleset(ruleset_file)
    roots = {instrument.root for instrument in ruleset.instruments}
    if config.root not in roots:
        msg = (
            f"ruleset {ruleset.ruleset_id} v{ruleset.version} does not trade {config.root}: its "
            f"instruments are {sorted(roots)}. The attempt would apply one root's rules to "
            "another root's bars"
        )
        raise ConfigurationError(msg)
    chosen = scenario_list(ruleset)
    if scenarios == "primary":
        chosen = [item for item in chosen if item.is_primary]
    if not chosen or chosen[0].scenario_id != PRIMARY_SCENARIO_ID:
        msg = "the scenario list must start with the primary scenario"
        raise DataQualityError(msg)
    _refuse_horizon(ruleset, plan, horizon_trading_days, calendar)

    # the auxiliary datasets: the calendar is always read (its coverage labels every attempt); the
    # fee table only when a component is charged on top of the commission
    assumption = None if cost_assumption is None else load_cost_assumption(Path(cost_assumption))
    store = ParquetDataStore(store_root)
    calendar_coverage = econ_calendar_coverage(store, dataset=DatasetId(news_dataset))
    event_types = calendar_event_types(item.ruleset for item in chosen)
    start_ns = _midnight_ns(config.window.start)
    end_ns = _midnight_ns(plan.trade_dates[-1]) + _NS_PER_DAY
    news_events = _news_events(store, news_dataset, event_types, start_ns, end_ns)
    news_coverage: Coverage = covered_intervals(calendar_coverage, event_types)
    news_gaps = _calendar_gaps(calendar_coverage, event_types, start_ns, end_ns)
    fee_source = None
    if _needs_exchange_fees(item.ruleset for item in chosen):
        fee_source = store_component_fees(store, dataset=exchange_fees_dataset)
    fees_hash = _content_hash(store, exchange_fees_dataset) if fee_source is not None else None
    news_hash = _content_hash(store, news_dataset)
    _refuse_missing_profile(
        (item.ruleset for item in chosen), selected=chosen[0].ruleset, value=participant_profile
    )

    run_basis = run_id_basis(config, prepared.refs, _session_table_hash(calendar))
    run_id = f"{RUN_ID_PREFIX}{hashlib.sha256(run_basis.encode('utf-8')).hexdigest()[:RUN_ID_HEX]}"
    basis = evaluation_basis(
        run_basis=run_basis,
        ruleset_sha256=ruleset.ruleset_sha256,
        horizon_trading_days=horizon_trading_days,
        execution_mode=execution_mode,
        payout_policy=payout_policy,
        cost_assumption=assumption,
        scenarios_requested=scenarios,
        news_dataset=news_dataset,
        news_hash=news_hash or "",
        exchange_fees_dataset=exchange_fees_dataset,
        exchange_fees_hash=fees_hash or "",
        participant_profile_sha256=(
            None if participant_profile is None else participant_profile.sha256
        ),
    )
    evaluation_id = evaluation_id_of(basis)
    evaluation_dir = artifacts_root / evaluation_id
    prior = read_seal(evaluation_dir) if evaluation_dir.is_dir() else None

    bars = prepared.bars.execution.with_columns(prepared.bars.on_schedule)
    classifications: list[_Classified] = []
    for scenario in chosen:
        for start in plan.start_dates:
            attempt = simulate_attempt(
                bars=bars,
                targets=prepared.targets,
                rolls=prepared.rolls,
                spec=prepared.spec,
                costs=config.cost_schedule(),
                ruleset=scenario.ruleset,
                start_trade_date=start,
                max_horizon_days=plan.calendar_days[start],
                calendar=calendar,
                raw=prepared.raw,
                policy=config.execution_policy(),
                payout_policy=payout_policy,
                execution_mode=execution_mode,
                news_events=news_events,
                news_coverage=news_coverage,
                fee_source=fee_source,
                cost_assumption=assumption,
                profile=participant_profile,
                scenario_id=scenario.scenario_id,
            )
            classifications.append(
                _Classified(
                    scenario=scenario,
                    start=start,
                    horizon_end=plan.horizon_end[start],
                    complete=plan.is_complete(start),
                    outcome=classify_attempt(attempt, complete=plan.is_complete(start)),
                    attempt=attempt,
                )
            )

    summaries = [
        _scenario_summary(
            scenario,
            [item for item in classifications if item.scenario.scenario_id == scenario.scenario_id],
            evaluation_id=evaluation_id,
            horizon_trading_days=horizon_trading_days,
            execution_mode=execution_mode,
            cost_assumption=None if assumption is None else assumption.name,
            resamples=config.statistics.resamples,
            confidence=config.statistics.confidence,
        )
        for scenario in chosen
    ]
    summary = PropEvaluationSummary(
        schema_version=SCHEMA_VERSION,
        kind=KIND,
        evaluation_id=evaluation_id,
        run_id=run_id,
        candidate_id=candidate_id(config),
        trial_family=config.run.family,
        root=config.root,
        window={
            "start": config.window.start.isoformat(),
            "end": config.window.end.isoformat(),
            "last_trade_date": plan.trade_dates[-1].isoformat(),
        },
        horizon_trading_days=horizon_trading_days,
        execution_mode=execution_mode,
        payout_policy=payout_policy,
        cost_assumption=(
            None
            if assumption is None
            else PropCostAssumption(
                name=assumption.name,
                sha256=assumption.sha256,
                provided_by=assumption.provided_by,
                status=assumption.status,
                description=assumption.description,
                evidence=assumption.evidence,
                source_path=assumption.source_path,
                roots=list(assumption.roots),
                unused_roots=list(assumption.unused_roots(sorted(roots))),
                priced_components=sorted(
                    {
                        charge.component
                        for item in classifications
                        for charge in item.attempt.commissions.components
                        if charge.status == "assumption"
                    }
                ),
                remaining_gaps=sorted(
                    {gap for item in classifications for gap in item.attempt.commissions.cost_gaps}
                ),
            )
        ),
        cost_components=_cost_components_document(classifications),
        promotions_applied=sorted(
            {entry for item in classifications for entry in item.attempt.promotions_applied}
        ),
        promotions_not_applied=sorted(
            {
                reason
                for scenario in chosen
                for reason in resolve_promotions(scenario.ruleset, participant_profile)[
                    1
                ].not_applied
            }
        ),
        participant_profile=(
            None if participant_profile is None else participant_profile.as_mapping()
        ),
        participant_profile_sha256=(
            None if participant_profile is None else participant_profile.sha256
        ),
        scenarios_requested=_scenario_mode(scenarios),
        start_dates={
            "count": len(plan.start_dates),
            "first": plan.start_dates[0].isoformat(),
            "last": plan.start_dates[-1].isoformat(),
            "last_trade_date": plan.trade_dates[-1].isoformat(),
        },
        ruleset=PropRulesetReference(
            ruleset_id=ruleset.ruleset_id,
            version=ruleset.version,
            ruleset_sha256=ruleset.ruleset_sha256,
            verification_status=ruleset.verification.status,
            unverified=not ruleset.verified,
            as_of=ruleset.as_of.isoformat(),
            effective_from=ruleset.effective_from.isoformat(),
            effective_to=(
                None if ruleset.effective_to is None else ruleset.effective_to.isoformat()
            ),
            file=ruleset_file.name,
        ),
        news=PropNewsCoverage(
            dataset=news_dataset,
            content_hash=news_hash,
            event_types=list(event_types),
            events_in_window=len(news_events),
            unknown_time_events=sorted(
                event.event_id for event in news_events if not event.time_known
            ),
            covered_intervals=[[low, high] for low, high in news_coverage],
            gaps=news_gaps,
        ),
        exchange_fees=(
            None
            if fee_source is None
            else {
                "dataset": exchange_fees_dataset,
                "content_hash": fees_hash or "",
            }
        ),
        scenarios=summaries,
        not_a_submission=True,
        source_note=_SOURCE_NOTE,
    )

    frame = attempts_frame(classifications, horizon_trading_days)
    _replace(evaluation_dir, overwrite)
    write_result_parquet(frame, evaluation_dir / "attempts.parquet")
    payload = summary.model_dump(mode="json")
    (evaluation_dir / "summary.json").write_text(
        json.dumps(payload, sort_keys=True, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    (evaluation_dir / "ruleset.yaml").write_bytes(ruleset_bytes)
    manifest: dict[str, object] = {
        "kind": KIND,
        "schema_version": SCHEMA_VERSION,
        "evaluation_id": evaluation_id,
        "evaluation_basis": basis,
        "evaluation_version": EVALUATION_VERSION,
        "run_id": run_id,
        "run_id_basis": run_basis,
        "run_schema_version": RUN_SCHEMA_VERSION,
        "config_hash": futures_config_hash(config),
        "candidate_id": candidate_id(config),
        "trial_family": config.run.family,
        "run_name": config.run.name,
        "root": config.root,
        "window": summary.window,
        "datasets": {role: _ref_document(prepared.refs[role]) for role in sorted(prepared.refs)},
        "horizon": {
            "trading_days": horizon_trading_days,
            "calendar_days": "converted per start date with the CME session calendar",
            "block_length_policy": BLOCK_LENGTH_POLICY,
        },
        "execution_mode": execution_mode,
        "payout_policy": payout_policy,
        "cost_assumption": (
            None if assumption is None else summary.model_dump(mode="json")["cost_assumption"]
        ),
        "cost_components": summary.model_dump(mode="json")["cost_components"],
        "promotions_applied": summary.model_dump(mode="json")["promotions_applied"],
        "promotions_not_applied": summary.model_dump(mode="json")["promotions_not_applied"],
        "participant_profile": summary.model_dump(mode="json")["participant_profile"],
        "participant_profile_sha256": summary.model_dump(mode="json")["participant_profile_sha256"],
        "scenarios_requested": scenarios,
        "ruleset": {
            "file": ruleset_file.name,
            "ruleset_id": ruleset.ruleset_id,
            "version": ruleset.version,
            "ruleset_sha256": ruleset.ruleset_sha256,
            "verification_status": ruleset.verification.status,
            "unverified": not ruleset.verified,
            "as_of": ruleset.as_of.isoformat(),
            "effective_from": ruleset.effective_from.isoformat(),
            "effective_to": (
                None if ruleset.effective_to is None else ruleset.effective_to.isoformat()
            ),
        },
        "news": {
            "dataset": news_dataset,
            "content_hash": news_hash,
            "event_types": list(event_types),
        },
        "exchange_fees": summary.exchange_fees,
        "start_dates": summary.start_dates,
        "attempts": frame.height,
        "bootstrap": {
            "statistics": list(STATISTICS),
            "block_length_policy": BLOCK_LENGTH_POLICY,
            "rng": BOOTSTRAP_RNG,
            "seeds": {name: bootstrap_seed(evaluation_id, name) for name in STATISTICS},
        },
        "files": sorted(RESULT_FILES),
        "trial_recorded": False,
        "not_a_submission": (
            "a prop evaluation evaluates an existing candidate: it records no trial and changes "
            "neither submission_count nor total_trials (ADR-0107 section 6)"
        ),
        "source_note": _SOURCE_NOTE,
    }
    write_manifest(evaluation_dir, manifest)
    artifact_id = seal_artifact(evaluation_dir, prior=prior)
    return PropEvaluationResult(
        evaluation_dir=evaluation_dir,
        evaluation_id=evaluation_id,
        artifact_id=artifact_id,
        summary=payload,
    )


__all__ = [
    "BLOCK_LENGTH_POLICY",
    "CONDITIONAL_PASS_PROBABILITY",
    "EVALUATION_PREFIX",
    "EVALUATION_VERSION",
    "KIND",
    "OUTCOMES",
    "PASS_PROBABILITY",
    "PROP_ATTEMPTS_SCHEMA",
    "RESULT_FILES",
    "SCHEMA_VERSION",
    "PropEvaluationResult",
    "PropEvaluationSummary",
    "PropScenarioSummary",
    "attempts_frame",
    "calendar_event_types",
    "classify_attempt",
    "covered_intervals",
    "evaluation_basis",
    "evaluation_id_of",
    "prop_block_length",
    "prop_evaluation_json_schema",
    "run_prop_evaluation",
]
