"""Batch evaluation of N strategy expressions on ONE futures-run base (Fathom C5a).

A batch is a base futures config plus an ordered list of DSL expressions (ADR-0096/0098). Every
candidate runs with the base's data, window, contracts, costs, execution, session and fidelity, and
only ``strategy`` (the expression and its parameter bindings) and ``run.name`` change -- so the
comparison conditions are identical across candidates by construction, not by convention.

Two identities keep the batch honest:

- ``batch_id`` = ``BAT-`` + the SHA-256 of the base config and the ORDERED candidate list, so the
  same submission is the same batch and re-running it is a reproduction, not a new search;
- the run id of each candidate is the futures run id (``FUT-...``, ADR-0095), so a candidate whose
  run was already computed is ``cached`` and reuses that run rather than computing it again.

Trial accounting: a batch SUBMITS every candidate and COMPUTES one run per distinct
parameterization (canonicalized and bound, ``crucible.dsl.identity.parameterization_id``). The
submissions are recorded in the registry's ``submissions`` table (one row per submitted candidate,
in submission order, with its ``CND-`` candidate id) and each computed run registers its trial as
any futures run does. Since C6a (ADR-0103) ``batch.json`` reports the family's
``submission_count``, ``unique_candidate_count`` and ``total_trials``: a submission is an EVENT, a
candidate is counted once however many windows or folds it was evaluated on, and ``total_trials``
is what a deflation divides by.

What this module does NOT do (ADR-0095, ADR-0103): compute or rank a statistic. Each candidate
reports the five descriptive metrics of its run (totals and counts) with null intervals, PLUS the
``statistics`` block its run recorded (C6a) copied verbatim, and ``verdict`` is null with the
``robustness_not_assessed`` reason of ADR-0097 (robustness is C7). Candidates are listed in
SUBMISSION order, never sorted by a metric.

Units: money in USD (as ``metrics.json`` reports it), counts in contracts and fills, times UTC ns.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from crucible.core.canonical import canonical_json
from crucible.core.errors import ConfigurationError, ExperimentError
from crucible.experiments.artifact_id import read_seal, verify_artifact
from crucible.experiments.futures_config import (
    FuturesRunConfig,
    candidate_id,
    futures_config_hash,
    load_futures_config,
    parse_futures_config,
)
from crucible.experiments.futures_document import metric_document, verdict_document
from crucible.experiments.futures_run import futures_run_id, run_futures
from crucible.experiments.futures_stats import STATISTICS_METRICS
from crucible.validation.trial_registry import DuckDBTrialRegistry

BATCH_SCHEMA_VERSION = 1
"""Version of ``batch.json`` (``docs/COMPATIBILITY.md`` §3: adding a key is additive)."""

BATCH_ID_PREFIX = "BAT-"
"""Prefix of a batch id."""

BATCH_ID_HEX = 16
"""Hex digits of the SHA-256 kept in the batch id (64 bits, as every other id in the project)."""

BATCH_STATUSES = ("computed", "cached")
"""What happened to a candidate: its run was simulated now, or an identical run already existed
(another candidate of this batch with the same parameterization, or a sealed run of the same
config and datasets)."""

CANDIDATE_METRICS = (
    "net_pnl_usd",
    "total_costs_usd",
    "fills",
    "max_intraday_drawdown_usd",
    "min_equity_usd",
)
"""The descriptive metrics a batch reports per candidate, in reading order: what the run made, what
it cost, how many fills it took, its conservative worst drawdown and its worst equity. Every one is
``descriptive`` with null intervals; nothing here ranks candidates (AGENTS.md §9)."""

REGISTRY_FILE = "trial_registry.duckdb"
"""The trial registry's file name under the artifacts root (ADR-0008)."""

RANKING_NOTE = (
    "candidates are listed in submission order, never sorted by a metric: C5 reports what each run "
    "did, and ordering them by a statistic would be a claim this milestone does not make"
)
"""Recorded in ``batch.json`` so a reader knows the list order is the submission's."""


class _StrictModel(BaseModel):
    """A batch file is a small contract: a typo or an extra key is an error, not a knob."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class FuturesBatchCandidateFile(_StrictModel):
    """One candidate: a name, an expression and (optionally) the bindings of its parameters.

    Only these three keys are accepted: the data, window, contracts, costs, execution, session and
    fidelity of a batch come from its base config, so a candidate cannot change the conditions it
    is compared under (passing one is refused, not ignored).
    """

    name: str = Field(
        min_length=1,
        description="Candidate name, unique within the batch; it becomes <base run name>/<name>.",
    )
    expression: str = Field(
        min_length=1,
        description="A DSL expression (ADR-0096/0098): a condition (true is long) or a "
        "scale-invariant score whose sign sets the side.",
    )
    params: dict[str, object] = Field(
        default_factory=dict,
        description="Bindings of the expression's `$` parameters by name (without `$`); they are "
        "applied before the candidate's parameterization id is computed, so two spellings of the "
        "same values are one candidate.",
    )


class FuturesBatchFile(_StrictModel):
    """The batch file: a base futures-run config and the ordered candidates to run on it."""

    kind: Literal["futures_batch"] = Field(
        default="futures_batch", description="File kind discriminator (a futures batch)."
    )
    base: str = Field(
        min_length=1,
        description="Path to a futures-run YAML, relative to this file's directory. Its strategy "
        "section is REPLACED per candidate; everything else is shared.",
    )
    candidates: list[FuturesBatchCandidateFile] = Field(
        min_length=1, description="The candidates, in submission order (kept, never sorted)."
    )


@dataclass(frozen=True, slots=True)
class BatchCandidate:
    """One validated candidate: its position in the submission and what to bind."""

    position: int
    name: str
    expression: str
    params: dict[str, object]


@dataclass(frozen=True, slots=True)
class FuturesBatch:
    """A loaded batch: the file's path, the base config it resolved and its candidates."""

    path: Path
    base: FuturesRunConfig
    candidates: tuple[BatchCandidate, ...]


@dataclass(frozen=True, slots=True)
class BatchResult:
    """What a finished batch hands back: where its ``batch.json`` is, its id and the document."""

    batch_dir: Path
    batch_id: str
    document: dict[str, object]


def _validation_message(exc: ValidationError, where: Path) -> str:
    problems = "; ".join(
        f"{'.'.join(str(part) for part in error['loc']) or '(root)'}: {error['msg']}"
        for error in exc.errors()
    )
    return (
        f"the futures batch file {where} is invalid: {problems}. A candidate takes exactly name, "
        "expression and params; everything else (data, window, contracts, costs, execution, "
        "session, fidelity) comes from the base config"
    )


def load_futures_batch(path: Path) -> FuturesBatch:
    """Load and validate a batch file, resolving its base config against the file's directory.

    Refuses a file that is not a batch, a candidate with a key other than name/expression/params,
    a duplicate candidate name, and a base that is not a valid futures-run config.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        msg = f"cannot read the futures batch file {path}: {exc}"
        raise ConfigurationError(msg) from exc
    try:
        raw = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        msg = f"the futures batch file {path} is not valid YAML: {exc}"
        raise ConfigurationError(msg) from exc
    if not isinstance(raw, dict):
        msg = f"the futures batch file {path} did not parse to a mapping"
        raise ConfigurationError(msg)
    try:
        parsed = FuturesBatchFile.model_validate(raw)
    except ValidationError as exc:
        raise ConfigurationError(_validation_message(exc, path)) from exc
    names = [candidate.name for candidate in parsed.candidates]
    duplicates = sorted({name for name in names if names.count(name) > 1})
    if duplicates:
        msg = (
            f"the futures batch file {path} names the candidate(s) {duplicates} more than once: a "
            "candidate name identifies its run (<base>/<name>), so two candidates cannot share "
            "one"
        )
        raise ConfigurationError(msg)
    base_path = Path(parsed.base)
    if not base_path.is_absolute():
        base_path = path.parent / base_path
    base = load_futures_config(base_path)
    candidates = tuple(
        BatchCandidate(
            position=position,
            name=candidate.name,
            expression=candidate.expression,
            params=dict(candidate.params),
        )
        for position, candidate in enumerate(parsed.candidates)
    )
    return FuturesBatch(path=path, base=base, candidates=candidates)


def futures_batch_json_schema() -> dict[str, object]:
    """The JSON Schema of the batch file (``crucible schema --kind futures-batch``)."""
    return FuturesBatchFile.model_json_schema()


def batch_id(base: FuturesRunConfig, candidates: tuple[BatchCandidate, ...]) -> str:
    """``BAT-`` + the SHA-256 of the base config and the ORDERED candidates (their order is part of
    the submission, so the same candidates in another order are another batch)."""
    basis = {
        "base": base.model_dump(mode="json"),
        "candidates": [
            {
                "name": candidate.name,
                "expression": candidate.expression,
                "params": candidate.params,
            }
            for candidate in candidates
        ],
    }
    return (
        BATCH_ID_PREFIX
        + hashlib.sha256(canonical_json(basis).encode("utf-8")).hexdigest()[:BATCH_ID_HEX]
    )


def candidate_config(base: FuturesRunConfig, candidate: BatchCandidate) -> FuturesRunConfig:
    """The base config with ONLY ``strategy`` and ``run.name`` replaced for this candidate.

    Every other field is the base's (re-parsed, so the derived objects -- cost schedule, execution
    policy, session policy, compiled expression -- are built and checked as usual).

    The dump is ``exclude_unset``: a field the base left at its default must stay unset in the
    candidate too, or re-validation would see every default as an explicit setting (which the
    config refuses where it matters, e.g. a non-zero spread under ``commission_only``).
    """
    raw = base.model_dump(mode="json", exclude_unset=True)
    raw["strategy"] = {"expression": candidate.expression, "params": candidate.params}
    raw["run"] = {**raw["run"], "name": f"{base.run.name}/{candidate.name}"}
    return parse_futures_config(raw)


def _cached_run(run_dir: Path) -> tuple[str, dict[str, object]]:
    """The artifact id and metrics of an already sealed run directory (verifying its seal first)."""
    verify_artifact(run_dir)
    seal = read_seal(run_dir)
    if seal is None:
        msg = (
            f"{run_dir} holds a futures run without a seal: the batch refuses to reuse a directory "
            "it cannot verify. Re-run it with overwrite=true"
        )
        raise ExperimentError(msg).at(path=str(run_dir))
    try:
        metrics = json.loads((run_dir / "metrics.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        msg = f"cannot read the metrics of the existing run {run_dir}: {exc}"
        raise ExperimentError(msg).at(path=str(run_dir / "metrics.json")) from exc
    if not isinstance(metrics, dict):
        msg = f"the metrics of the existing run {run_dir} are not a JSON object"
        raise ExperimentError(msg).at(path=str(run_dir / "metrics.json"))
    return seal.artifact_id, {str(key): value for key, value in metrics.items()}


def _candidate_document(
    candidate: BatchCandidate,
    status: str,
    run_id: str,
    artifact_id: str,
    structure_id: str,
    parameterization_id: str,
    candidate_identity: str,
    metrics: dict[str, object],
) -> dict[str, object]:
    """One candidate's row of ``batch.json``: its identity, its descriptive metrics and its
    statistics (C6a).

    ``statistics`` is the run's own C6a report (per-period and annualized Sharpe, mean daily
    return, PSR, DSR, mean IC with their intervals and reasons), copied from its sealed
    ``metrics.json``: a cached candidate has no numbers of its own and reports the ones the run it
    reuses computed. Nothing here ranks the candidates (AGENTS.md §9).
    """
    reported: dict[str, object] = {}
    for name in CANDIDATE_METRICS:
        entry = metrics.get(name)
        if not isinstance(entry, dict):
            msg = (
                f"the run {run_id} (candidate {candidate.name!r}) has no {name!r} metric: a batch "
                "reports the same five descriptive metrics for every candidate"
            )
            raise ExperimentError(msg).at(key=name)
        reported[name] = metric_document(name, entry).model_dump(mode="json")
    statistics: dict[str, object] = {}
    for name in STATISTICS_METRICS:
        entry = metrics.get(name)
        if not isinstance(entry, dict):
            msg = (
                f"the run {run_id} (candidate {candidate.name!r}) has no {name!r} statistic: since "
                "C6a every futures run reports its statistics in metrics.json (ADR-0103). Re-run "
                "the candidate with `crucible futures run`"
            )
            raise ExperimentError(msg).at(key=name)
        statistics[name] = metric_document(name, entry).model_dump(mode="json")
    return {
        "position": candidate.position,
        "name": candidate.name,
        "status": status,
        "run_id": run_id,
        "artifact_id": artifact_id,
        "structure_id": structure_id,
        "parameterization_id": parameterization_id,
        "candidate_id": candidate_identity,
        "metrics": reported,
        "statistics": statistics,
    }


def run_futures_batch(
    batch: FuturesBatch | Path | str,
    *,
    store_root: Path,
    artifacts_root: Path,
    overwrite: bool = False,
) -> BatchResult:
    """Run every candidate of ``batch`` on one base config and write ``<artifacts>/<batch_id>/``.

    ``batch``: a loaded :class:`FuturesBatch`, or the path of a batch file to load. ``store_root``:
    the ParquetDataStore root (shared by every candidate). ``artifacts_root``: where the run
    directories, the shared ``trial_registry.duckdb`` and the batch directory live. ``overwrite``:
    re-simulate a run whose directory already exists instead of reusing it (a reproduction keeps
    the same run and artifact ids).

    Timing: a candidate's decision reads only bars that had closed by the bar it decides at, exactly
    as a single futures run (the batch adds no data access). Determinism: the batch id, the run ids
    and ``batch.json`` (sorted keys) are pure functions of the batch file, the base config and the
    datasets.
    """
    loaded = load_futures_batch(Path(batch)) if isinstance(batch, str | Path) else batch
    base = loaded.base
    identifier = batch_id(base, loaded.candidates)
    registry = DuckDBTrialRegistry(artifacts_root / REGISTRY_FILE)
    computed: dict[str, tuple[str, str, dict[str, object]]] = {}
    """``parameterization_id -> (run_id, artifact_id, metrics)``: what computed it."""
    rows: list[dict[str, object]] = []
    for candidate in loaded.candidates:
        config = candidate_config(base, candidate)
        compiled = config.strategy.compiled_signal(config.signal.input)
        key = compiled.parameterization_id
        reused = computed.get(key)
        if reused is not None:
            run_id, artifact_id, metrics = reused
            status = "cached"
        else:
            run_id = futures_run_id(config, store_root=store_root)
            run_dir = artifacts_root / run_id
            if not overwrite and run_dir.is_dir():
                artifact_id, metrics = _cached_run(run_dir)
                status = "cached"
            else:
                result = run_futures(
                    config,
                    store_root=store_root,
                    artifacts_root=artifacts_root,
                    overwrite=overwrite,
                )
                run_id = result.run_id
                artifact_id = result.artifact_id
                artifact_id, metrics = _cached_run(result.run_dir)
                status = "computed"
            computed[key] = (run_id, artifact_id, metrics)
        registry.record_submission(
            identifier,
            candidate.position,
            config.run.family,
            run_id,
            compiled.structure_id,
            compiled.parameterization_id,
            candidate.name,
            status,
            candidate_id=candidate_id(config),
        )
        rows.append(
            _candidate_document(
                candidate,
                status,
                run_id,
                artifact_id,
                compiled.structure_id,
                compiled.parameterization_id,
                candidate_id(config),
                metrics,
            )
        )
    document: dict[str, object] = {
        "schema_version": BATCH_SCHEMA_VERSION,
        "kind": "futures_batch",
        "batch_id": identifier,
        "family": base.run.family,
        "base_config_hash": futures_config_hash(base),
        "fidelity": base.fidelity.record(),
        "candidates": rows,
        "submitted": len(rows),
        "distinct_runs": len({str(row["run_id"]) for row in rows}),
        "trials": {
            "submission_count": registry.submission_count(base.run.family),
            "unique_candidate_count": registry.unique_candidate_count(base.run.family),
            "total_trials": registry.total_trials(base.run.family),
        },
        "verdict": verdict_document().model_dump(mode="json"),
        "ordering": RANKING_NOTE,
    }
    batch_dir = artifacts_root / identifier
    batch_dir.mkdir(parents=True, exist_ok=True)
    (batch_dir / "batch.json").write_text(
        json.dumps(document, sort_keys=True, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    return BatchResult(batch_dir=batch_dir, batch_id=identifier, document=document)


__all__ = [
    "BATCH_ID_PREFIX",
    "BATCH_SCHEMA_VERSION",
    "BATCH_STATUSES",
    "CANDIDATE_METRICS",
    "RANKING_NOTE",
    "REGISTRY_FILE",
    "BatchCandidate",
    "BatchResult",
    "FuturesBatch",
    "FuturesBatchCandidateFile",
    "FuturesBatchFile",
    "batch_id",
    "candidate_config",
    "futures_batch_json_schema",
    "load_futures_batch",
    "run_futures_batch",
]
