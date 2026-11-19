"""Effective trials of a futures family, the supplementary DSR and PBO panels (C6b, ADR-0104).

C6a deflates every futures Sharpe by the family's ``total_trials``: its count of DISTINCT
candidates (ADR-0103). That count overstates the number of independent hypotheses, because two
variants that differ only in a window length are not two bets. This module estimates the effective
number of trials from the candidates' DAILY RETURN correlations
(``crucible.validation.effective_trials``), reports it beside the primary deflation -- never in
place of it -- and computes the probability of backtest overfitting (PBO) for a valid candidate
panel.

Four rules of ADR-0104 shape everything here:

1. **One series per candidate.** A candidate is represented by its daily returns (ADR-0103
   decision 1), from its REPRESENTATIVE run: the one with the most observations, a tie going to the
   earliest recorded -- ``DuckDBTrialRegistry.candidate_trials``, the same rule the primary DSR's
   candidate Sharpes use.
2. **The pairwise correlation follows C5c** (ADR-0102): an INNER join on trade dates (nothing
   filled), only between candidates whose comparison keys agree, at least
   ``min_overlap_trade_dates`` shared dates (default 20, never below 10), never for a constant
   series. The rules are C5c's own functions (``futures_compare.daily_correlation``,
   ``comparison_key``/``key_diff``), so a correlation here is the correlation a comparison would
   report. Correlation is computed on the runs' daily P&L, and Pearson of the daily returns equals
   Pearson of the daily P&L: a return is ``P&L / initial_capital`` and the family shares one
   capital, so dividing both series by the same constant leaves the coefficient unchanged. That is
   why the estimator can reuse the C5c series without a second copy of the returns.
3. **No pair, no estimate.** A pair without a valid correlation (too little overlap, incompatible
   keys, a constant series, a missing or unverified artifact) makes the estimate ``unavailable``
   with the reasons. A missing correlation is NEVER replaced by 0 or 1.
4. **The estimate is supplementary.** ``dsr`` stays the primary result deflated by
   ``total_trials`` (byte-identical to C6a); ``dsr_effective_trials`` sits next to it under a
   ``supplementary`` key, carries the threshold and the candidate ids it used, and feeds no verdict
   (``verdict_level`` stays null with ``robustness_not_assessed``).

PBO (ADR-0015, ADR-0070) needs a panel of trials over the SAME periods, so it is only computed on
a valid one: the batch window's candidate returns, or (walk-forward) a separate full-window panel
of one run per distinct candidate. The selected out-of-sample path is never a PBO input.

Timing: everything here reads finished, sealed artifacts and the registry; nothing simulates and
nothing reads the clock. Determinism: candidate order, pair order, the matrix and the cluster tie
rule are all sorted, so two calls over the same artifacts give the same report, and the trials id
is a pure function of the family, the representative runs and the options.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from dataclasses import dataclass, replace
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Literal

import numpy as np
from pydantic import BaseModel, ConfigDict, Field

from crucible.core.canonical import canonical_json
from crucible.core.errors import ConfigurationError, CrucibleError, InvariantViolation
from crucible.experiments.futures_compare import (
    DEFAULT_MIN_OVERLAP_TRADE_DATES,
    MIN_OVERLAP_FLOOR,
    _DailyPnl,
    comparison_key,
    daily_correlation,
    key_diff,
    load_member,
)
from crucible.experiments.futures_document import verdict_document
from crucible.validation.dsr import deflated_sharpe_ratio_over_effective_trials
from crucible.validation.effective_trials import (
    DEFAULT_RHO_THRESHOLD,
    EffectiveTrialsResult,
    estimate_effective_trials,
    unavailable_effective_trials,
)
from crucible.validation.pbo import probability_of_backtest_overfitting
from crucible.validation.splits import CombinatorialPurgedCVSplitter
from crucible.validation.trial_registry import DuckDBTrialRegistry

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from numpy.typing import NDArray

    from crucible.experiments.futures_compare import Member
    from crucible.validation.trial_registry import CandidateTrial
EFT_ID_PREFIX = "EFT-"
"""Prefix of an effective-trials report id."""

EFT_ID_HEX = 16
"""Hex digits of the SHA-256 kept in the report id (64 bits, as every other id in the project)."""

TRIALS_SCHEMA_VERSION = 1
"""Version of ``trials.json`` (``docs/COMPATIBILITY.md`` §3: adding a key is additive)."""

TRIALS_FILE = "trials.json"
"""The file a trials report writes under its directory."""

REGISTRY_FILE = "trial_registry.duckdb"
"""The trial registry's file name under the artifacts root (ADR-0008)."""

DEFAULT_PBO_GROUPS = 8
"""The CSCV group count PBO uses unless the batch or walk-forward file says otherwise (even)."""

MIN_PBO_GROUPS = 4
"""Fewest CSCV groups that can be split symmetrically: ``n_test_groups == n_groups // 2`` with
``n_groups >= 3`` (``CombinatorialPurgedCVSplitter``), so an even count of at least 4."""

PAIR_STATUSES: tuple[PairStatus, ...] = (
    "ok",
    "insufficient_overlap",
    "incompatible",
    "constant_series",
    "unverified",
    "missing",
)
"""What a pair did. The first four are C5c's own statuses (ADR-0102); ``unverified`` and
``missing`` say the representative artifact of one member could not be read at all."""

CandidateStatus = Literal["ok", "unverified", "missing"]
"""Whether a candidate's representative artifact could be read: ``ok``, or why not."""

PairStatus = Literal[
    "ok",
    "insufficient_overlap",
    "incompatible",
    "constant_series",
    "unverified",
    "missing",
]
"""A pair's status: a value, or the reason there is none (ADR-0102's vocabulary plus the two
reasons a whole artifact is unreadable)."""

OVERLAP_RULE = (
    "Pearson correlation of the two runs' daily series over the trade dates BOTH have (an inner "
    "join: a date one member lacks is never filled with zero), on at least min_overlap_trade_dates "
    "shared trade dates; Pearson of the daily returns equals Pearson of the daily P&L because a "
    "return is P&L / initial_capital and the family shares one capital"
)
"""Recorded in every report: what a pair's ``rho`` is."""

KEY_RULE = (
    "only candidates whose comparison keys agree are correlated (simulator version, fidelity, "
    "execution, session and signal input); a pair whose keys differ is incompatible and no value "
    "is computed"
)
"""Recorded in every report: which pairs may be correlated at all (ADR-0102 decision 4)."""

UNAVAILABLE_RULE = (
    "a pair without a valid correlation makes the estimate unavailable, with its reason: a missing "
    "coefficient is never replaced by 0 or 1"
)
"""Recorded in every report: the rule that keeps the estimate honest (ADR-0104 decision 2)."""

SUPPLEMENTARY_DSR_METHOD = (
    "deflated_sharpe_ratio with N = the effective number of trials, keeping the primary DSR's "
    "per-period Sharpe and the SAME cross-trial dispersion (the family's distinct candidate "
    "Sharpes): only N changes (ADR-0104 decision 4). SUPPLEMENTARY: the primary dsr is deflated by "
    "total_trials and is the conservative reading; this one never feeds a verdict"
)
"""Recorded in every ``dsr_effective_trials`` entry."""

PBO_METHOD = (
    "CSCV (Bailey, Borwein, Lopez de Prado & Zhu 2015): the period axis of the aligned candidate "
    "panel is cut into n_groups contiguous groups, every combination of n_groups/2 groups is the "
    "out-of-sample set, the in-sample winner is selected by its partition Sharpe and its "
    "out-of-sample rank decides overfit (embargo 0, nothing purged)"
)
"""Recorded in every ``pbo`` block."""

PBO_TIE_RULE = (
    "ties are resolved by expectation under uniform random tie-breaking: a split counts as overfit "
    "when 2 * rank <= N + 1 on the integer out-of-sample rank, so a panel of identical trials "
    "reports (N + 1) / (2 N), never 1.0"
)
"""Recorded in every ``pbo`` block (ADR-0070)."""

PBO_PANEL_RULE = (
    "PBO needs a panel of at least two DISTINCT candidates over an IDENTICAL set of trade dates; "
    "nothing is filled, so a candidate whose dates differ makes PBO unavailable"
)
"""Recorded in every ``pbo`` block."""


class _StrictModel(BaseModel):
    """A report document is a contract: a typo or an extra key is an error, not a knob."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class TrialsCountsDocument(_StrictModel):
    """The family's counts at the moment the report was written (ADR-0103 decision 4)."""

    submission_count: int
    unique_candidate_count: int
    total_trials: int


class TrialsCandidateDocument(_StrictModel):
    """One candidate: the representative run the correlation and the Sharpe come from."""

    candidate_id: str
    run_id: str
    n_obs: int | None
    sharpe_per_period: float | None


class TrialsPairDocument(_StrictModel):
    """One pair's correlation: its status, the overlapping trade dates and the value when there is
    one. ``rho`` is null exactly when the status is not ``ok``, and ``detail`` says why."""

    a: str
    b: str
    status: Literal[
        "ok",
        "insufficient_overlap",
        "incompatible",
        "constant_series",
        "unverified",
        "missing",
    ]
    overlap: int | None
    rho: float | None
    differing_keys: list[str] = Field(default_factory=list)
    detail: str | None = None


class TrialsEstimatorDocument(_StrictModel):
    """The estimate and how it was made (ADR-0104 decision 3).

    ``assessment`` is ``estimator`` and never a probability: the count depends on the threshold,
    which is why the report also carries the sensitivity table. ``method`` records the linkage, the
    distance formula, the threshold rule, the overlap and key rules and the candidate ids.
    """

    assessment: Literal["estimator"]
    note: str
    status: Literal["ok", "unavailable"]
    effective_trials: int | None
    threshold: float
    clusters: list[list[str]]
    reasons: list[str]
    method: dict[str, object]


class TrialsSensitivityDocument(_StrictModel):
    """One row of the threshold sensitivity table: the cluster count and the clusters."""

    effective_trials: int
    clusters: list[list[str]]


class FuturesTrialsDocument(_StrictModel):
    """``trials.json``: the effective-trials report of one futures family (ADR-0104 decision 5)."""

    schema_version: Literal[1]
    kind: Literal["futures_trials"]
    trials_id: str
    family: str
    counts: TrialsCountsDocument
    candidates: list[TrialsCandidateDocument]
    pairs: list[TrialsPairDocument]
    estimator: TrialsEstimatorDocument
    sensitivity: dict[str, TrialsSensitivityDocument]
    verdict: dict[str, object]


@dataclass(frozen=True, slots=True)
class DailySeries:
    """The part of an artifact a correlation reads: its id and its daily P&L by trade date.

    ``Member`` satisfies this shape, so a correlation here is C5c's function; the run that is being
    written at the moment passes its in-memory series through it (it has no seal yet, so it cannot
    be loaded from disk).
    """

    member_id: str
    net: Mapping[dt.date, Decimal]


@dataclass(frozen=True, slots=True)
class OwnerSeries:
    """The artifact being written: its representative run, its daily series and its comparison key.

    A run computes its own supplementary reading BEFORE it is sealed, so it cannot be read back
    from disk (an unsealed directory has no artifact id and no verification). It hands its own
    series in instead, and the estimate treats it exactly like every other candidate.
    """

    run_id: str
    candidate_id: str
    series: DailySeries
    key: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class CandidateSeries:
    """One candidate of the report: its representative run, its series and why it may be absent."""

    candidate_id: str
    run_id: str
    n_obs: int | None
    sharpe: float | None
    series: _DailyPnl | None
    key: Mapping[str, object] | None
    reason: str | None
    status: CandidateStatus = "ok"

    @property
    def usable(self) -> bool:
        """Whether the candidate's series and key could be read, so it can be correlated."""
        return self.series is not None


@dataclass(frozen=True, slots=True)
class PairResult:
    """One pair's outcome."""

    a: str
    b: str
    status: PairStatus
    overlap: int | None
    rho: float | None
    differing_keys: tuple[str, ...] = ()
    detail: str | None = None


@dataclass(frozen=True, slots=True)
class FuturesTrialsReport:
    """A family's effective-trials report: the counts, the candidates, the pairs and the estimate.

    ``document`` is the ``trials.json`` body, built through :class:`FuturesTrialsDocument`, so the
    file and the schema cannot drift. ``trial_sharpes`` is the family's per-candidate Sharpe list,
    the same one the primary DSR is computed with: the supplementary reading changes N alone.
    """

    family: str
    trials_id: str
    counts: Mapping[str, int]
    candidates: tuple[CandidateSeries, ...]
    pairs: tuple[PairResult, ...]
    estimator: EffectiveTrialsResult
    trial_sharpes: tuple[float, ...]
    document: dict[str, object]

    @property
    def candidate_ids(self) -> tuple[str, ...]:
        """The candidate ids the estimate covers, sorted."""
        return tuple(candidate.candidate_id for candidate in self.candidates)

    @property
    def effective_trials(self) -> int | None:
        """The estimate, when it could be made."""
        return self.estimator.effective_trials


@dataclass(frozen=True, slots=True)
class TrialsResult:
    """What a finished trials report hands back: where ``trials.json`` is, its id and the report."""

    trials_dir: Path
    trials_id: str
    report: FuturesTrialsReport

    @property
    def document(self) -> dict[str, object]:
        """The ``trials.json`` body this report wrote."""
        return self.report.document


# ---------------------------------------------------------------------------------------------
# a. one series per candidate


def _reason_for(
    entry: CandidateTrial, artifacts_root: Path
) -> tuple[Member | None, CandidateStatus, str | None]:
    """The representative run's daily series, or why it cannot be read (ADR-0104 decision 1).

    A missing directory, an unreadable or unverifiable artifact and a run id that is not a futures
    run all give no series and a reason naming the candidate's run: the estimate is then
    ``unavailable`` rather than computed over a shorter list.
    """
    directory = artifacts_root / entry.experiment_id
    if not directory.is_dir():
        return (
            None,
            "missing",
            f"the representative run {entry.experiment_id} of candidate {entry.candidate_id} is "
            f"not under {artifacts_root}: the estimate reads sealed artifacts, so a missing run "
            "makes it unavailable rather than smaller",
        )
    try:
        member = load_member(artifacts_root, entry.experiment_id)
    except ConfigurationError as exc:
        return (
            None,
            "missing",
            f"the representative run {entry.experiment_id} of candidate {entry.candidate_id} is "
            f"not a futures-run artifact ({exc}): a row recorded before C6a names an experiment "
            "that cannot be correlated",
        )
    if not member.verified:
        return (
            None,
            "unverified",
            f"the representative run {entry.experiment_id} of candidate {entry.candidate_id} does "
            f"not verify ({member.detail}): an artifact whose seal fails is never read as if it "
            "were sound",
        )
    return member, "ok", None


def _candidate_series(
    entries: Sequence[CandidateTrial], *, artifacts_root: Path, owner: OwnerSeries | None
) -> tuple[CandidateSeries, ...]:
    """Every candidate's representative series, in candidate-id order."""
    out: list[CandidateSeries] = []
    for entry in entries:
        if owner is not None and entry.experiment_id == owner.run_id:
            out.append(
                CandidateSeries(
                    candidate_id=entry.candidate_id,
                    run_id=entry.experiment_id,
                    n_obs=len(owner.series.net) or entry.n_obs,
                    sharpe=entry.sharpe,
                    series=owner.series,
                    key=dict(owner.key),
                    reason=None,
                )
            )
            continue
        member, status, reason = _reason_for(entry, artifacts_root)
        out.append(
            CandidateSeries(
                candidate_id=entry.candidate_id,
                run_id=entry.experiment_id,
                n_obs=entry.n_obs if member is None else len(member.net),
                sharpe=entry.sharpe,
                series=None if member is None else DailySeries(member.member_id, member.net),
                key=None if member is None else comparison_key(member),
                reason=reason,
                status=status,
            )
        )
    return tuple(out)


# ---------------------------------------------------------------------------------------------
# b. the pairwise correlations


def _pair(a: CandidateSeries, b: CandidateSeries, *, min_overlap: int) -> PairResult:
    """One pair's correlation, following the C5c rules (ADR-0102, ADR-0104 decision 2)."""
    for side in (a, b):
        if side.series is None:
            return PairResult(
                a=a.candidate_id,
                b=b.candidate_id,
                status=side.status if side.status != "ok" else "unverified",
                overlap=None,
                rho=None,
                detail=side.reason,
            )
    assert a.key is not None  # a usable candidate always has a key
    assert b.key is not None
    assert a.series is not None
    assert b.series is not None
    differing = tuple(key_diff(a.key, b.key))
    if differing:
        return PairResult(
            a=a.candidate_id,
            b=b.candidate_id,
            status="incompatible",
            overlap=None,
            rho=None,
            differing_keys=differing,
            detail=(
                "the two candidates were not simulated under the same execution, session, fidelity "
                "or signal input, so their series are not comparable: " + ", ".join(differing)
            ),
        )
    result = daily_correlation(a.series, b.series, min_overlap=min_overlap)
    detail = None
    if result.status == "insufficient_overlap":
        detail = (
            f"{result.overlap_trade_dates} overlapping trade date(s) over at least "
            f"{min_overlap} required: too few for a coefficient, and a missing one is never "
            "replaced by 0"
        )
    elif result.status == "constant_series":
        detail = (
            "a series is constant over the overlap, so the correlation is undefined (a flat run "
            "that never held a position is not an uncorrelated one)"
        )
    return PairResult(
        a=a.candidate_id,
        b=b.candidate_id,
        status=result.status,
        overlap=result.overlap_trade_dates,
        rho=result.value,
        detail=detail,
    )


def _pairs(candidates: Sequence[CandidateSeries], *, min_overlap: int) -> tuple[PairResult, ...]:
    """Every unordered pair, in candidate-id order (deterministic and complete)."""
    out: list[PairResult] = []
    for left in range(len(candidates)):
        for right in range(left + 1, len(candidates)):
            out.append(_pair(candidates[left], candidates[right], min_overlap=min_overlap))
    return tuple(out)


def _matrix(ids: Sequence[str], pairs: Sequence[PairResult]) -> NDArray[np.float64] | None:
    """The correlation matrix, or None when any pair has no value (never a filled-in matrix)."""
    position = {name: index for index, name in enumerate(ids)}
    matrix = np.eye(len(ids), dtype=np.float64)
    for pair in pairs:
        if pair.status != "ok" or pair.rho is None:
            return None
        matrix[position[pair.a], position[pair.b]] = pair.rho
        matrix[position[pair.b], position[pair.a]] = pair.rho
    return matrix


def _futures_method(method: Mapping[str, object], *, min_overlap: int) -> dict[str, object]:
    """The estimator's method record plus the rules THIS report applied to the correlations.

    The overlap floor, the inner-join rule, the pair-compatibility rule and the "no pair, no
    estimate" rule are the futures report's (ADR-0102, ADR-0104 decisions 2 and 3), not the
    estimator's, so they are added here and travel with every record -- available or not.
    """
    return {
        **dict(method),
        "min_overlap_trade_dates": min_overlap,
        "overlap_rule": OVERLAP_RULE,
        "key_rule": KEY_RULE,
        "unavailable_rule": UNAVAILABLE_RULE,
    }


def _estimate(
    candidates: Sequence[CandidateSeries],
    pairs: Sequence[PairResult],
    *,
    rho_threshold: float,
    min_overlap: int,
) -> EffectiveTrialsResult:
    """The estimate, or the reasons it cannot be made (ADR-0104 decisions 2 and 3)."""
    ids = [candidate.candidate_id for candidate in candidates]
    reasons = [f"{pair.a} / {pair.b}: {pair.detail}" for pair in pairs if pair.status != "ok"]
    if not candidates:
        reasons.append(
            "the family has no recorded candidate: an effective count needs at least one, and it "
            "is never invented"
        )
    matrix = _matrix(ids, pairs) if not reasons else None
    if matrix is None or reasons:
        return unavailable_effective_trials(
            ids, reasons, rho_threshold=rho_threshold, min_overlap_trade_dates=min_overlap
        )
    return estimate_effective_trials(ids, matrix, rho_threshold=rho_threshold)


# ---------------------------------------------------------------------------------------------
# c. the report


def trials_id(
    family: str,
    candidates: Sequence[CandidateSeries],
    *,
    rho_threshold: float,
    min_overlap_trade_dates: int,
) -> str:
    """``EFT-`` + the SHA-256 of the family, the representative runs and the options.

    The candidate ids and their representative run ids are hashed in sorted order: the id names
    the exact candidate set and the exact pair of options the report was computed with, so another
    threshold or another representative run is another report, never an overwrite.
    """
    basis = {
        "family": family,
        "candidates": [
            {"candidate_id": candidate.candidate_id, "run_id": candidate.run_id}
            for candidate in candidates
        ],
        "options": {
            "rho_threshold": rho_threshold,
            "min_overlap_trade_dates": min_overlap_trade_dates,
        },
    }
    return (
        EFT_ID_PREFIX
        + hashlib.sha256(canonical_json(basis).encode("utf-8")).hexdigest()[:EFT_ID_HEX]
    )


def _check_min_overlap(min_overlap_trade_dates: int) -> int:
    """Refuse an overlap floor the C5c rule forbids (less than :data:`MIN_OVERLAP_FLOOR`)."""
    if min_overlap_trade_dates < MIN_OVERLAP_FLOOR:
        msg = (
            f"min_overlap_trade_dates = {min_overlap_trade_dates}: a correlation needs at least "
            f"{MIN_OVERLAP_FLOOR} overlapping trade dates (ADR-0102), and the policy is never "
            "relaxed below the floor"
        )
        raise ConfigurationError(msg)
    return min_overlap_trade_dates


def _document(
    report: FuturesTrialsReport,
) -> dict[str, object]:
    """``trials.json``'s body, through the document model so the schema cannot drift."""
    document = FuturesTrialsDocument(
        schema_version=TRIALS_SCHEMA_VERSION,
        kind="futures_trials",
        trials_id=report.trials_id,
        family=report.family,
        counts=TrialsCountsDocument(**dict(report.counts)),
        candidates=[
            TrialsCandidateDocument(
                candidate_id=candidate.candidate_id,
                run_id=candidate.run_id,
                n_obs=candidate.n_obs,
                sharpe_per_period=candidate.sharpe,
            )
            for candidate in report.candidates
        ],
        pairs=[
            TrialsPairDocument(
                a=pair.a,
                b=pair.b,
                status=pair.status,
                overlap=pair.overlap,
                rho=pair.rho,
                differing_keys=list(pair.differing_keys),
                detail=pair.detail,
            )
            for pair in report.pairs
        ],
        estimator=TrialsEstimatorDocument.model_validate(report.estimator.record()),
        sensitivity={
            key: TrialsSensitivityDocument.model_validate(entry)
            for key, entry in report.estimator.sensitivity.items()
        },
        verdict=verdict_document().model_dump(mode="json"),
    )
    return document.model_dump(mode="json")


def futures_effective_trials(
    family: str,
    *,
    artifacts_root: Path,
    rho_threshold: float = DEFAULT_RHO_THRESHOLD,
    min_overlap_trade_dates: int = DEFAULT_MIN_OVERLAP_TRADE_DATES,
    owner: OwnerSeries | None = None,
) -> FuturesTrialsReport:
    """The effective-trials report of ``family``, without writing anything (ADR-0104 decision 5).

    ``family`` names the trial family (``ExperimentHeader.family``); ``artifacts_root`` holds the
    sealed runs, their shared ``trial_registry.duckdb`` and where a report would be written.
    ``rho_threshold`` is the estimator's ``rho*``, ``min_overlap_trade_dates`` the C5c overlap floor
    (default 20, refused below 10). ``owner`` is the artifact being written right now, whose
    in-memory series stands in for its own unsealed run; a reader of finished artifacts passes
    nothing.

    Refuses nothing about the candidates' correlations: a pair without a valid coefficient is
    reported and makes the estimate unavailable. It refuses an overlap floor below the C5c floor
    and a threshold that is not a correlation.
    """
    _check_min_overlap(min_overlap_trade_dates)
    registry = DuckDBTrialRegistry(artifacts_root / REGISTRY_FILE)
    entries = registry.candidate_trials(family)
    candidates = _candidate_series(entries, artifacts_root=artifacts_root, owner=owner)
    pairs = _pairs(candidates, min_overlap=min_overlap_trade_dates)
    estimate = _estimate(
        candidates, pairs, rho_threshold=rho_threshold, min_overlap=min_overlap_trade_dates
    )
    estimator = replace(
        estimate, method=_futures_method(estimate.method, min_overlap=min_overlap_trade_dates)
    )
    if estimator.available and estimator.effective_trials is not None:
        count = estimator.effective_trials
        if count > len(candidates):
            msg = (
                f"the estimate is {count} effective trial(s) over {len(candidates)} "
                "candidate(s): the count can never exceed the candidates it clusters"
            )
            raise InvariantViolation(msg)
    report = FuturesTrialsReport(
        family=family,
        trials_id=trials_id(
            family,
            candidates,
            rho_threshold=rho_threshold,
            min_overlap_trade_dates=min_overlap_trade_dates,
        ),
        counts={
            "submission_count": registry.submission_count(family),
            "unique_candidate_count": registry.unique_candidate_count(family),
            "total_trials": registry.total_trials(family),
        },
        candidates=candidates,
        pairs=pairs,
        estimator=estimator,
        trial_sharpes=tuple(
            candidate.sharpe for candidate in candidates if candidate.sharpe is not None
        ),
        document={},
    )
    return replace(report, document=_document(report))


def run_futures_trials(
    family: str,
    *,
    artifacts_root: Path,
    rho_threshold: float = DEFAULT_RHO_THRESHOLD,
    min_overlap_trade_dates: int = DEFAULT_MIN_OVERLAP_TRADE_DATES,
) -> TrialsResult:
    """Compute the report and write ``<artifacts>/<EFT-ID>/trials.json`` (ADR-0104 decision 5).

    The file is JSON with sorted keys and a newline, like every other Crucible document, so two
    runs over the same artifacts are byte-identical. Nothing is simulated and no trial is recorded:
    a trials report reads the family, it does not extend it.
    """
    report = futures_effective_trials(
        family,
        artifacts_root=artifacts_root,
        rho_threshold=rho_threshold,
        min_overlap_trade_dates=min_overlap_trade_dates,
    )
    directory = artifacts_root / report.trials_id
    directory.mkdir(parents=True, exist_ok=True)
    (directory / TRIALS_FILE).write_text(
        json.dumps(report.document, sort_keys=True, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    return TrialsResult(trials_dir=directory, trials_id=report.trials_id, report=report)


def futures_trials_json_schema() -> dict[str, object]:
    """The JSON Schema of ``trials.json`` (``crucible schema --kind futures-trials``)."""
    return FuturesTrialsDocument.model_json_schema()


# ---------------------------------------------------------------------------------------------
# d. the supplementary reading of the primary DSR


def supplementary_dsr(
    returns: NDArray[np.float64],
    *,
    report: FuturesTrialsReport,
) -> dict[str, object]:
    """``dsr_effective_trials``: the primary DSR's series and dispersion with N replaced.

    ``returns`` is the series the primary ``dsr`` was computed on (the run's daily returns, or the
    walk-forward's OOS chain), ``report`` the family's estimate at write time. The value uses the
    family's own candidate Sharpes (``report.trial_sharpes``) for the cross-trial dispersion, so it
    differs from the primary reading in ``N`` alone (ADR-0104 decision 4).

    Null with a reason when the estimate is unavailable, when the family has fewer than two
    candidate Sharpes (there is no dispersion to keep) or when the series itself cannot be scored:
    a missing number always says why. It is ``assessment: "inferential"`` with no interval, it
    records the threshold, the effective count and the candidate ids it used, and it never feeds a
    verdict.
    """
    effective = report.effective_trials
    entry: dict[str, object] = {
        "value": None,
        "ci_low": None,
        "ci_high": None,
        "assessment": "inferential",
        "unit": "probability",
        "method": SUPPLEMENTARY_DSR_METHOD,
        "reason": None,
        "threshold": report.estimator.threshold,
        "effective_trials": effective,
        "candidate_ids": list(report.candidate_ids),
    }
    if effective is None:
        entry["reason"] = (
            "the effective number of trials is unavailable for this family ("
            + "; ".join(report.estimator.reasons)
            + "), so there is no supplementary reading: the primary dsr already reports the "
            "conservative deflation over total_trials"
        )
        return entry
    if len(report.trial_sharpes) < 2:
        entry["reason"] = (
            "the supplementary DSR keeps the primary DSR's cross-trial dispersion, which needs at "
            f"least 2 distinct candidate Sharpe ratios; this family has {len(report.trial_sharpes)}"
        )
        return entry
    try:
        result = deflated_sharpe_ratio_over_effective_trials(
            returns, report.trial_sharpes, effective
        )
    except CrucibleError as exc:  # a refused series is null with its reason, never a zero
        entry["reason"] = str(exc)
        return entry
    entry["value"] = result.dsr
    return entry


def supplementary_block(
    returns: NDArray[np.float64], *, report: FuturesTrialsReport
) -> dict[str, object]:
    """The ``supplementary`` block a document carries next to its primary ``dsr``."""
    return {"dsr_effective_trials": supplementary_dsr(returns, report=report)}


# ---------------------------------------------------------------------------------------------
# e. PBO on a valid panel


@dataclass(frozen=True, slots=True)
class PanelSeries:
    """One candidate's column of a PBO panel: its trade dates and its daily returns, aligned."""

    candidate_id: str
    trade_dates: tuple[dt.date, ...]
    returns: NDArray[np.float64]
    source: str = ""
    """Where the series came from (a run id, or the walk-forward's full-window panel run)."""


@dataclass(frozen=True, slots=True)
class PboOutcome:
    """A PBO block: the probability, how it was split, and why it is null when it is."""

    value: float | None
    n_groups: int
    n_combinations: int | None
    n_candidates: int
    n_observations: int | None
    reason: str | None
    differing_dates: tuple[str, ...] = ()

    def record(self) -> dict[str, object]:
        """The ``pbo`` block as a document writes it."""
        return {
            "value": self.value,
            "n_groups": self.n_groups,
            "n_combinations": self.n_combinations,
            "n_candidates": self.n_candidates,
            "n_observations": self.n_observations,
            "assessment": "inferential",
            "method": PBO_METHOD,
            "tie_rule": PBO_TIE_RULE,
            "reason": self.reason,
        }


def _differing_dates(panel: Sequence[PanelSeries]) -> list[str]:
    """The trade dates the candidates do not all share, in date order (a bounded sample)."""
    common = set(panel[0].trade_dates)
    for entry in panel[1:]:
        common &= set(entry.trade_dates)
    differing = sorted({day for entry in panel for day in entry.trade_dates if day not in common})
    return [day.isoformat() for day in differing[:10]]


def pbo_on_panel(panel: Sequence[PanelSeries], *, n_groups: int = DEFAULT_PBO_GROUPS) -> PboOutcome:
    """The probability of backtest overfitting of a candidate panel (ADR-0104 decision 6).

    The panel must hold at least two DISTINCT candidates over an IDENTICAL set of trade dates;
    nothing is filled, nothing is dropped. A candidate whose dates differ, a panel with fewer than
    two candidates, fewer observations than ``n_groups`` or a non-even/countable group count makes
    PBO ``unavailable`` with a reason (never a number): a PBO over an unaligned panel would compare
    a candidate's Tuesday with another's Wednesday.
    """
    if n_groups % 2 != 0 or n_groups < MIN_PBO_GROUPS:
        msg = (
            f"n_groups = {n_groups}: CSCV needs an even group count of at least {MIN_PBO_GROUPS} "
            "(n_test_groups == n_groups // 2, and the splitter needs at least 3 groups). The "
            "default is 8"
        )
        raise ConfigurationError(msg)
    distinct = {entry.candidate_id: entry for entry in panel}
    if len(distinct) < 2 or len(distinct) != len(panel):
        return PboOutcome(
            value=None,
            n_groups=n_groups,
            n_combinations=None,
            n_candidates=len(distinct),
            n_observations=None,
            reason=(
                f"PBO needs at least 2 distinct candidates over the same periods; this panel has "
                f"{len(distinct)}. {PBO_PANEL_RULE}"
            ),
        )
    ordered = [distinct[key] for key in sorted(distinct)]
    dates = [entry.trade_dates for entry in ordered]
    if any(set(day_set) != set(dates[0]) for day_set in dates[1:]):
        return PboOutcome(
            value=None,
            n_groups=n_groups,
            n_combinations=None,
            n_candidates=len(ordered),
            n_observations=None,
            reason=(
                "the candidates do not share one set of trade dates, so the panel is not "
                f"comparable and PBO is unavailable. Dates not shared by every candidate: "
                f"{_differing_dates(ordered)}. {PBO_PANEL_RULE}"
            ),
            differing_dates=tuple(_differing_dates(ordered)),
        )
    lengths = {len(entry.trade_dates) for entry in ordered}
    if len(lengths) != 1:
        return PboOutcome(
            value=None,
            n_groups=n_groups,
            n_combinations=None,
            n_candidates=len(ordered),
            n_observations=min(lengths),
            reason=(
                "the candidates' series have different lengths after alignment, so the panel "
                "cannot be built without filling values. " + PBO_PANEL_RULE
            ),
        )
    observations = lengths.pop()
    if observations < n_groups:
        return PboOutcome(
            value=None,
            n_groups=n_groups,
            n_combinations=None,
            n_candidates=len(ordered),
            n_observations=observations,
            reason=(
                f"PBO needs at least n_groups = {n_groups} observations to split, and this panel "
                f"has {observations}. Use fewer groups or a longer window"
            ),
        )
    matrix = np.vstack([np.asarray(entry.returns, dtype=np.float64) for entry in ordered])
    result = probability_of_backtest_overfitting(
        matrix, CombinatorialPurgedCVSplitter(n_groups, n_test_groups=n_groups // 2, embargo=0)
    )
    return PboOutcome(
        value=result.pbo,
        n_groups=n_groups,
        n_combinations=result.n_combinations,
        n_candidates=result.n_trials,
        n_observations=observations,
        reason=None,
    )


__all__ = [
    "DEFAULT_PBO_GROUPS",
    "EFT_ID_HEX",
    "EFT_ID_PREFIX",
    "KEY_RULE",
    "MIN_OVERLAP_FLOOR",
    "MIN_PBO_GROUPS",
    "OVERLAP_RULE",
    "PAIR_STATUSES",
    "PBO_METHOD",
    "PBO_PANEL_RULE",
    "PBO_TIE_RULE",
    "REGISTRY_FILE",
    "SUPPLEMENTARY_DSR_METHOD",
    "TRIALS_FILE",
    "TRIALS_SCHEMA_VERSION",
    "UNAVAILABLE_RULE",
    "CandidateSeries",
    "DailySeries",
    "FuturesTrialsDocument",
    "FuturesTrialsReport",
    "OwnerSeries",
    "PairResult",
    "PanelSeries",
    "PboOutcome",
    "TrialsResult",
    "futures_effective_trials",
    "futures_trials_json_schema",
    "pbo_on_panel",
    "run_futures_trials",
    "supplementary_block",
    "supplementary_dsr",
    "trials_id",
]
