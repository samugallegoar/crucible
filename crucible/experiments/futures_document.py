"""The futures-run document (Fathom C3c, ADR-0097): one versioned shape for a sealed run.

:func:`futures_document` builds the document from the run directory alone (``manifest.json`` plus
``metrics.json``), so ``crucible futures run --json`` and ``crucible artifact show <ART> --json``
produce the identical document by construction, and a reader (Fathom) needs no other file. The
document is versioned (``FUTURES_DOCUMENT_SCHEMA_VERSION``) and described by a JSON Schema
(``crucible schema --kind futures-run-document``).

What it says about the run's evidence, exactly:

* every metric of ``metrics.json`` is **descriptive** (``assessment: "descriptive"``) and carries
  NO confidence interval (``ci_low`` and ``ci_high`` are null). A descriptive metric with a
  non-null interval is a contract violation and refuses the document;
* the verdict is a **null verdict with a reason**: ``verdict_level`` is null and
  ``verdict_reason.code`` is ``"not_assessed"``, because Crucible computes no Sharpe, no deflated
  Sharpe, no confidence interval and no null test for futures runs before milestones C6
  (multiple-testing statistics) and C7 (robustness and prop-firm rules);
* an absence of assessment is never negative evidence: the reason's own message says so, and the
  closed ``vocabulary`` lists the levels a later milestone may assign.

Hard restriction (ADR-0095, owner): nothing here computes a statistic. It reshapes and versions
what the run already reported, and it cannot turn "not assessed" into "no edge".
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Literal, get_args

from pydantic import BaseModel, ConfigDict, Field

from crucible.core.errors import ExperimentError, InvariantViolation
from crucible.experiments.artifact_id import verify_artifact

if TYPE_CHECKING:
    from collections.abc import Mapping

FUTURES_DOCUMENT_SCHEMA_VERSION = 1
"""Version of the futures-run document (``docs/COMPATIBILITY.md`` §3: adding a key is additive;
removing, renaming or changing the meaning of one bumps this)."""

VERDICT_REASON_CODES = ("not_assessed",)
"""The closed set of verdict reason codes. ``not_assessed`` is the only one today: a futures run
has no statistical assessment before milestones C6 and C7 (ADR-0095, ADR-0097)."""

VERDICT_VOCABULARY = ("some_evidence", "not_conclusive", "no_edge_detected")
"""The verdict levels of ``crucible/product/summary.py``, in the order the product uses them. A
futures run assigns none of them today; the document lists them so a reader knows the vocabulary
without importing Crucible."""

METRIC_ASSESSMENTS = ("descriptive", "statistical")
"""The closed set of metric assessments. Every futures metric is ``descriptive``: it states what
the run did (totals, counts, a conservative drawdown), never whether the result is distinguishable
from chance."""

METRIC_UNITS = {
    "final_balance_usd": "usd",
    "final_equity_usd": "usd",
    "net_pnl_usd": "usd",
    "total_costs_usd": "usd",
    "min_equity_usd": "usd",
    "max_intraday_drawdown_usd": "usd",
    "fills": "count",
    "rolls": "count",
    "trade_dates": "trade_dates",
    "max_contracts": "contracts",
}
"""The unit of every metric a futures run reports. A metric name outside this table refuses the
document: a value with no unit cannot be read (``docs/CONVENTIONS.md`` §2)."""

METRIC_UNIT_NAMES = ("usd", "count", "contracts", "trade_dates")
"""The closed set of metric units."""

VerdictReasonCode = Literal["not_assessed"]
"""The type of a verdict reason code: the members of ``VERDICT_REASON_CODES``."""

MetricAssessment = Literal["descriptive", "statistical"]
"""The type of a metric assessment: the members of ``METRIC_ASSESSMENTS``."""

MetricUnit = Literal["usd", "count", "contracts", "trade_dates"]
"""The type of a metric unit: the members of ``METRIC_UNIT_NAMES``."""

VerdictLevel = Literal["some_evidence", "not_conclusive", "no_edge_detected"]
"""The type of a verdict level: the members of ``VERDICT_VOCABULARY``."""


def _closed_sets_agree() -> None:
    """The ``Literal`` types above and the tuples they document must name the same values.

    Called at import: a value added to one and not the other is a schema that promises a closed
    set the code does not enforce (or the reverse), so it fails here rather than in a document.
    """
    pairs = (
        (VerdictReasonCode, VERDICT_REASON_CODES, "VERDICT_REASON_CODES"),
        (MetricAssessment, METRIC_ASSESSMENTS, "METRIC_ASSESSMENTS"),
        (MetricUnit, METRIC_UNIT_NAMES, "METRIC_UNIT_NAMES"),
        (VerdictLevel, VERDICT_VOCABULARY, "VERDICT_VOCABULARY"),
    )
    for alias, values, name in pairs:
        assert get_args(alias) == values, f"{name} and its Literal type have drifted apart"
    for table, name in (
        (REASON_MESSAGES, "REASON_MESSAGES"),
        (REASON_ASSESSED_BY, "REASON_ASSESSED_BY"),
    ):
        assert tuple(table) == VERDICT_REASON_CODES, f"{name} must name every reason code"


HEADLINE_METRICS = (
    "net_pnl_usd",
    "final_equity_usd",
    "min_equity_usd",
    "max_intraday_drawdown_usd",
    "total_costs_usd",
    "fills",
)
"""The headline metrics, in reading order: what the run made, what it ended at, its worst equity,
its conservative worst drawdown, what it cost and how many fills it took."""

NOT_ASSESSED_MESSAGE = (
    "Crucible has not assessed this futures run statistically: no Sharpe, deflated Sharpe, "
    "confidence interval or null test is computed for futures runs before milestones C6 "
    "(multiple-testing statistics) and C7 (robustness and prop-firm rules). This is an absence "
    "of assessment, not evidence of no edge."
)
"""Recorded verbatim in every futures document (ADR-0095, ADR-0097). The sentence matters: a null
verdict must never be read as "no edge detected"."""

REASON_MESSAGES = {"not_assessed": NOT_ASSESSED_MESSAGE}
"""The message of each verdict reason code (one per member of ``VERDICT_REASON_CODES``)."""

REASON_ASSESSED_BY = {"not_assessed": ["C6", "C7"]}
"""The milestones whose absence leaves this reason standing."""


_closed_sets_agree()


class _Document(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FuturesDatasetDocument(_Document):
    """One dataset of the run, as its manifest records it (the run records this, never the data)."""

    dataset: str
    content_hash: str
    price_basis: Literal["raw", "adjusted"]
    adjustment: str


class FuturesWindowDocument(_Document):
    """The window the run simulated: inclusive Globex trade dates (day labels, not instants)."""

    start: str
    end: str


class FuturesFidelityDocument(_Document):
    """How finely and how expensively the run read its series (C5a).

    ``resolution``: the bar length the run simulated (``1m`` is the stored series, ``5m``/``15m`` a
    causal aggregate of it). ``cost_detail``: ``full`` charges spread and slippage,
    ``commission_only`` charges commission and fees only (OPTIMISTIC, and listed in
    ``approximations``). ``preset``: the named level that decided both fields, or null.
    ``table_version``: the version of the preset table, so a reader never reinterprets an old run.
    ``resampled``: whether the stored one-minute series was aggregated; ``dropped_off_schedule``:
    one-minute bars outside every scheduled session, not aggregated; ``partial_buckets``: buckets
    clipped by a session open or close (a run refuses one, so it is 0 in a sealed run).
    """

    resolution: Literal["1m", "5m", "15m"]
    cost_detail: Literal["full", "commission_only"]
    preset: Literal["screen", "standard", "full"] | None
    table_version: str
    resampled: bool
    dropped_off_schedule: int
    partial_buckets: int


class FuturesVerdictReasonDocument(_Document):
    """Why the verdict level is what it is: a code from ``VERDICT_REASON_CODES``, the message a
    reader must see, and the milestones whose absence leaves the reason standing."""

    code: VerdictReasonCode = Field(
        json_schema_extra={"enum": list(VERDICT_REASON_CODES)},
    )
    message: str
    assessed_by: list[str]


class FuturesVerdictDocument(_Document):
    """The null verdict: ``verdict_level`` is null exactly when a reason code is present."""

    verdict_level: None
    verdict_reason: FuturesVerdictReasonDocument
    vocabulary: list[VerdictLevel]


class FuturesMetricDocument(_Document):
    """One metric: its value, its unit and its assessment.

    Every futures metric is ``descriptive``, and a descriptive metric carries no interval: both CI
    fields are null. The document has no ``statistical`` metric today (that needs C6/C7); a later
    milestone that adds one bumps ``FUTURES_DOCUMENT_SCHEMA_VERSION`` and widens these fields.
    """

    value: float
    ci_low: None
    ci_high: None
    assessment: MetricAssessment
    unit: MetricUnit


class FuturesRunDocument(_Document):
    """A sealed futures run, as one versioned document: identity, what it assumed, the null
    verdict and every descriptive metric. Read by ``crucible futures run --json``,
    ``crucible artifact show --json`` and the MCP tools (one builder, one schema)."""

    schema_version: Literal[1]
    kind: Literal["futures_run"]
    artifact_id: str
    experiment_id: str
    run_name: str
    trial_family: str
    trial_count: int
    root: str
    window: FuturesWindowDocument
    fidelity: FuturesFidelityDocument
    run_dir: str
    datasets: dict[str, FuturesDatasetDocument]
    approximations: list[str]
    strict_execution: bool
    verdict: FuturesVerdictDocument
    headline: list[str]
    metrics: dict[str, FuturesMetricDocument]
    files: list[str]


def verdict_document(
    verdict_level: str | None = None, reason_code: str | None = "not_assessed"
) -> FuturesVerdictDocument:
    """The verdict of a futures run: a null level with a reason (ADR-0097).

    ``verdict_level`` is null EXACTLY when ``reason_code`` is present; a level from
    ``VERDICT_VOCABULARY`` without a reason, or a null level without one, is refused because
    neither can be read honestly. No futures run sets a level today.
    """
    if verdict_level is not None and verdict_level not in VERDICT_VOCABULARY:
        msg = (
            f"verdict_level {verdict_level!r} is not in the vocabulary "
            f"{list(VERDICT_VOCABULARY)}: a verdict level is one of those, or null"
        )
        raise InvariantViolation(msg)
    if (verdict_level is None) != (reason_code is not None):
        msg = (
            f"verdict_level {verdict_level!r} with reason code {reason_code!r}: a null level "
            "requires a reason code (why the run was not assessed) and a level requires none. "
            "The document refuses both mismatches: a null verdict with no reason reads as "
            "'nothing to report', which is not what an unassessed run says"
        )
        raise InvariantViolation(msg)
    if verdict_level is not None:
        msg = (
            f"the futures path assigns no verdict level (got {verdict_level!r}): no futures run "
            "is assessed statistically before milestones C6 and C7 (ADR-0095, ADR-0097). A "
            "milestone that assesses one extends this function and bumps "
            "FUTURES_DOCUMENT_SCHEMA_VERSION"
        )
        raise InvariantViolation(msg)
    assert reason_code is not None  # a null level requires it (the mismatch check above)
    message = REASON_MESSAGES.get(reason_code)
    if message is None:
        msg = (
            f"unknown verdict reason code {reason_code!r}; the closed set is "
            f"{list(VERDICT_REASON_CODES)} (ADR-0097). Add a code to VERDICT_REASON_CODES and its "
            "message, and bump FUTURES_DOCUMENT_SCHEMA_VERSION"
        )
        raise InvariantViolation(msg)
    return FuturesVerdictDocument(
        verdict_level=None,
        verdict_reason=FuturesVerdictReasonDocument(
            code=reason_code,
            message=message,
            assessed_by=list(REASON_ASSESSED_BY[reason_code]),
        ),
        vocabulary=list(VERDICT_VOCABULARY),
    )


def metric_document(name: str, entry: Mapping[str, object]) -> FuturesMetricDocument:
    """One metric of the document: its value, its unit and its descriptive assessment.

    ``entry`` is the metric as ``metrics.json`` writes it (``value``, ``ci_low``, ``ci_high``).
    Every futures metric is descriptive (the run computes no statistical metric), and a
    descriptive metric must have null intervals: a non-null one is refused rather than shipped,
    because it would read as a claim the run never made.
    """
    unit = METRIC_UNITS.get(name)
    if unit is None:
        msg = (
            f"metric {name!r} of the run has no unit in METRIC_UNITS: a value with no unit cannot "
            "be read. Add it to METRIC_UNITS (and to the document's schema) before shipping it"
        )
        raise InvariantViolation(msg)
    assessment: MetricAssessment = "descriptive"
    if entry.get("ci_low") is not None or entry.get("ci_high") is not None:
        msg = (
            f"metric {name!r} is descriptive but carries an interval "
            f"(ci_low={entry.get('ci_low')!r}, ci_high={entry.get('ci_high')!r}): a descriptive "
            "metric states what the run did, and an interval here would read as a statistical "
            "claim the futures path does not make (AGENTS.md §9, ADR-0095)"
        )
        raise InvariantViolation(msg)
    value = entry.get("value")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        msg = (
            f"metric {name!r} has value {value!r}, which is not a number: metrics.json writes "
            "each metric as {'value': <number>, 'ci_low': null, 'ci_high': null}"
        )
        raise InvariantViolation(msg)
    return FuturesMetricDocument(
        value=float(value),
        ci_low=None,
        ci_high=None,
        assessment=assessment,
        unit=unit,
    )


def _read_json(path: Path) -> dict[str, object]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        msg = (
            f"cannot read {path} ({exc}): the directory is not a finished futures run. Point at "
            "a run directory under the artifacts root, or run `crucible futures run` again"
        )
        raise ExperimentError(msg).at(path=str(path)) from exc
    if not isinstance(raw, dict):
        msg = f"{path} does not hold a JSON object; it is not a Crucible manifest or metrics file"
        raise ExperimentError(msg).at(path=str(path))
    return {str(key): value for key, value in raw.items()}


def _text(manifest: Mapping[str, object], key: str, where: Path) -> str:
    value = manifest.get(key)
    if not isinstance(value, str):
        msg = (
            f"the manifest of {where.name} has no {key!r}: the directory is not a futures run "
            "written by `crucible futures run` (ADR-0095)"
        )
        raise ExperimentError(msg).at(path=str(where), key=key)
    return value


def _datasets(manifest: Mapping[str, object], where: Path) -> dict[str, FuturesDatasetDocument]:
    raw = manifest.get("datasets")
    if not isinstance(raw, dict) or not raw:
        msg = (
            f"the manifest of {where.name} records no datasets: the futures document reports the "
            "four datasets of the run, so a manifest without them cannot be read"
        )
        raise ExperimentError(msg).at(path=str(where), key="datasets")
    out: dict[str, FuturesDatasetDocument] = {}
    for role in sorted(raw):
        entry = raw[role]
        if not isinstance(entry, dict):
            msg = f"the manifest's datasets[{role!r}] is not an object; it is a DatasetRef"
            raise ExperimentError(msg).at(path=str(where), key=f"datasets.{role}")
        out[role] = FuturesDatasetDocument.model_validate(entry)
    return out


DEFAULT_FIDELITY: dict[str, object] = {
    "resolution": "1m",
    "cost_detail": "full",
    "preset": None,
    "table_version": "1",
    "resampled": False,
    "dropped_off_schedule": 0,
    "partial_buckets": 0,
}
"""The fidelity block of a run that recorded none: a manifest written before C5a simulated the
stored one-minute series with the full cost model, so it reads as ``1m`` + ``full`` rather than
failing (adding the key is additive, ``FUTURES_DOCUMENT_SCHEMA_VERSION`` stays 1)."""


def _fidelity(manifest: Mapping[str, object], where: Path) -> FuturesFidelityDocument:
    """The manifest's ``fidelity`` block, or the pre-C5a default when it recorded none."""
    raw = manifest.get("fidelity", DEFAULT_FIDELITY)
    if not isinstance(raw, dict):
        msg = (
            f"the manifest of {where.name} records fidelity={raw!r}: the fidelity block is an "
            "object {resolution, cost_detail, preset, table_version, resampled, "
            "dropped_off_schedule, partial_buckets}"
        )
        raise ExperimentError(msg).at(path=str(where), key="fidelity")
    return FuturesFidelityDocument.model_validate(raw)


def _strings(manifest: Mapping[str, object], key: str, where: Path) -> list[str]:
    value = manifest.get(key)
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        msg = (
            f"the manifest of {where.name} has no {key!r} list of strings: the futures document "
            "reports the run's assumptions and result files verbatim"
        )
        raise ExperimentError(msg).at(path=str(where), key=key)
    return [str(item) for item in value]


def futures_document(run_dir: Path) -> dict[str, object]:
    """The futures-run document for the sealed run in ``run_dir`` (ADR-0097).

    Built from the directory alone (``manifest.json`` + ``metrics.json``), so a freshly finished
    run and the same artifact fetched by id give the identical document. Refuses a directory that
    is not a futures run or whose seal does not verify (``verify_artifact`` runs first: an edited
    artifact is never described as if it were the run).

    Timing: a read of a sealed artifact, after the fact; nothing here reads the clock or computes
    a statistic (the restriction of ADR-0095).
    """
    verify_artifact(run_dir)
    manifest = _read_json(run_dir / "manifest.json")
    kind = manifest.get("kind")
    if kind != "futures_run":
        msg = (
            f"{run_dir.name} is not a futures run: its manifest says kind={kind!r}. The futures "
            "document describes a run of `crucible futures run` (ADR-0095); use `crucible "
            "artifact show` for an equity run"
        )
        raise ExperimentError(msg).at(path=str(run_dir), kind=str(kind))
    metrics_raw = _read_json(run_dir / "metrics.json")
    window = manifest.get("window")
    if not isinstance(window, dict):
        msg = f"the manifest of {run_dir.name} records no window {{start, end}}"
        raise ExperimentError(msg).at(path=str(run_dir), key="window")
    trial_count = manifest.get("trial_count")
    if isinstance(trial_count, bool) or not isinstance(trial_count, int):
        msg = (
            f"the manifest of {run_dir.name} records trial_count={trial_count!r}: the document "
            "reports the family's trial count as an integer (ADR-0008)"
        )
        raise ExperimentError(msg).at(path=str(run_dir), key="trial_count")
    strict_execution = manifest.get("strict_execution")
    if not isinstance(strict_execution, bool):
        msg = (
            f"the manifest of {run_dir.name} records strict_execution={strict_execution!r}: the "
            "document reports whether the run refused off-schedule fills as a boolean"
        )
        raise ExperimentError(msg).at(path=str(run_dir), key="strict_execution")
    metrics: dict[str, FuturesMetricDocument] = {}
    for name in sorted(metrics_raw):
        entry = metrics_raw[name]
        if not isinstance(entry, dict):
            msg = (
                f"the run's metrics.json entry {name!r} is not an object: every metric is "
                "{'value': <number>, 'ci_low': null, 'ci_high': null}"
            )
            raise ExperimentError(msg).at(path=str(run_dir / "metrics.json"), metric=name)
        metrics[name] = metric_document(name, entry)
    missing = [name for name in HEADLINE_METRICS if name not in metrics]
    if missing:
        msg = (
            f"the run's metrics.json lacks the headline metric(s) {missing}: a futures document "
            "always reports the headline set"
        )
        raise ExperimentError(msg).at(path=str(run_dir / "metrics.json"), missing=missing)
    document = FuturesRunDocument(
        schema_version=FUTURES_DOCUMENT_SCHEMA_VERSION,
        kind="futures_run",
        artifact_id=_text(manifest, "artifact_id", run_dir),
        experiment_id=_text(manifest, "experiment_id", run_dir),
        run_name=_text(manifest, "run_name", run_dir),
        trial_family=_text(manifest, "trial_family", run_dir),
        trial_count=trial_count,
        root=_text(manifest, "root", run_dir),
        window=FuturesWindowDocument(
            start=str(window.get("start", "")), end=str(window.get("end", ""))
        ),
        fidelity=_fidelity(manifest, run_dir),
        run_dir=Path(run_dir).resolve().as_posix(),
        datasets=_datasets(manifest, run_dir),
        approximations=_strings(manifest, "approximations", run_dir),
        strict_execution=strict_execution,
        verdict=verdict_document(),
        headline=list(HEADLINE_METRICS),
        metrics=metrics,
        files=_strings(manifest, "files", run_dir),
    )
    dumped: dict[str, object] = document.model_dump(mode="json")
    return dumped


def futures_document_json_schema() -> dict[str, object]:
    """JSON Schema (draft 2020-12) of the futures-run document, generated from the models above.

    ``verdict_level`` is typed null, ``verdict_reason.code`` and ``assessment`` are enums of their
    closed sets, and the metric intervals are typed null (every metric is descriptive), so a
    consumer that validates before reading cannot accept a document that claims an interval.
    """
    schema: dict[str, object] = FuturesRunDocument.model_json_schema()
    return schema


__all__ = [
    "DEFAULT_FIDELITY",
    "FUTURES_DOCUMENT_SCHEMA_VERSION",
    "HEADLINE_METRICS",
    "METRIC_ASSESSMENTS",
    "METRIC_UNITS",
    "METRIC_UNIT_NAMES",
    "NOT_ASSESSED_MESSAGE",
    "VERDICT_REASON_CODES",
    "VERDICT_VOCABULARY",
    "FuturesRunDocument",
    "futures_document",
    "futures_document_json_schema",
    "metric_document",
    "verdict_document",
]
