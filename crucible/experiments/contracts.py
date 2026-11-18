"""The versioned documents Crucible prints about a run (ADR-0084), and their JSON Schemas.

One builder, :func:`run_document`, produces the run document for the CLI (``crucible run --json``,
``crucible artifact show``) and therefore for the MCP tools, which relay the CLI's document: there
is a single shape and a single schema. Two sizes, because the consumer pays per byte:

* **compact** (default): ids, where the artifact is, the headline manifest fields that must travel
  together (AGENTS.md §9) and every metric with its confidence interval;
* **detailed** (``detail=True``): adds the full manifest and the artifact's file inventory.

``OUTPUT_SCHEMA_VERSION`` follows ``docs/COMPATIBILITY.md`` §3: adding a key is additive; removing,
renaming or changing the meaning of one bumps it. The schemas below are generated from the models
here and from ``artifacts.MANIFEST_FIELDS``, so they cannot drift from the code.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict

from crucible.experiments.artifacts import MANIFEST_FIELDS, SCHEMA_VERSION
from crucible.experiments.futures_document import futures_document_json_schema

if TYPE_CHECKING:
    from pathlib import Path

OUTPUT_SCHEMA_VERSION = 1
"""Version of the run, verification and error documents."""

HEADLINE_MANIFEST_KEYS = (
    "config_hash",
    "contamination",
    "contamination_reason",
    "dsr",
    "dsr_benchmark_sharpe",
    "dsr_error",
    "mode",
    "pbo",
    "realism_level",
    "runtime",
    "seed",
    "trial_count",
    "trial_family",
)
"""The set that travels together in the compact document: CI-bearing metrics (separate key), trial
count, DSR/PBO and the realism level, plus what identifies the run (AGENTS.md §9)."""


class _Document(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MetricDocument(_Document):
    """One metric: the value and its bootstrap interval (null when the metric has none)."""

    value: float | None
    ci_low: float | None
    ci_high: float | None


class FileEntry(_Document):
    """One file of the artifact directory (detailed documents only)."""

    name: str
    bytes: int


class RunDetail(_Document):
    """What ``detail=True`` adds: the full manifest and the file inventory."""

    manifest: dict[str, object]
    files: list[FileEntry]


class RunDocument(_Document):
    """A finished run, compact or detailed. ``artifact_id`` is null only for a run written before
    the artifact contract (``crucible artifact verify`` says so)."""

    schema_version: Literal[1]
    kind: Literal["run"]
    artifact_id: str | None
    experiment_id: str
    artifacts: str
    report: str | None
    manifest: dict[str, object]
    metrics: dict[str, MetricDocument]
    detail: RunDetail | None = None


class VerificationDocument(_Document):
    """``crucible artifact verify`` on an intact artifact (a mismatch is an error document)."""

    schema_version: Literal[1]
    kind: Literal["verification"]
    artifact_id: str
    verified: Literal[True]
    results_digest: str


class ErrorBody(_Document):
    """What a refusal says: ``code`` is stable (branch on it), ``message`` is actionable text,
    ``location`` says where it arose (command, path, symbol, timestamp, order id...)."""

    schema_version: Literal[1]
    code: str
    type: str
    message: str
    location: dict[str, object]


class ErrorDocument(_Document):
    """The ``--json`` form of a refusal: ``{"error": {...}}`` on stdout, exit code 1."""

    error: ErrorBody


def _read_json(path: Path) -> dict[str, object]:
    loaded: dict[str, object] = json.loads(path.read_text(encoding="utf-8"))
    return loaded


def run_document(
    run_dir: Path, *, detail: bool = False, report: Path | None = None
) -> dict[str, object]:
    """The run document for the artifact in ``run_dir`` (compact unless ``detail``).

    Read from disk, so a freshly finished run and an old one fetched by id give the same document.
    ``report`` overrides the report path; by default ``report.html`` in the directory when present.
    """
    manifest = _read_json(run_dir / "manifest.json")
    metrics = _read_json(run_dir / "metrics.json")
    report_path = report if report is not None else run_dir / "report.html"
    doc: dict[str, object] = {
        "schema_version": OUTPUT_SCHEMA_VERSION,
        "kind": "run",
        "artifact_id": manifest.get("artifact_id"),
        "experiment_id": manifest["experiment_id"],
        "artifacts": str(run_dir),
        "report": str(report_path) if report_path.is_file() else None,
        "manifest": {key: manifest.get(key) for key in HEADLINE_MANIFEST_KEYS},
        "metrics": {name: metrics[name] for name in sorted(metrics)},
    }
    if detail:
        doc["detail"] = {
            "manifest": manifest,
            "files": [
                {"name": path.name, "bytes": path.stat().st_size}
                for path in sorted(run_dir.iterdir())
                if path.is_file()
            ],
        }
    return doc


def verification_document(artifact_id: str, run_dir: Path) -> dict[str, object]:
    """The document for an artifact that passed ``verify_artifact``."""
    manifest = _read_json(run_dir / "manifest.json")
    return {
        "schema_version": OUTPUT_SCHEMA_VERSION,
        "kind": "verification",
        "artifact_id": artifact_id,
        "verified": True,
        "results_digest": manifest["results_digest"],
    }


def manifest_json_schema() -> dict[str, object]:
    """JSON Schema of ``manifest.json``, generated from ``artifacts.MANIFEST_FIELDS``.

    ``required`` lists the keys every run writes; keys that exist only on one runner or only after a
    later step (``factor_regression``) are optional here. ``additionalProperties`` is false: a key
    not declared in ``MANIFEST_FIELDS`` is a drift the schema refuses.
    """
    json_types = {"integer", "number", "string", "boolean", "object", "array<string>"}
    properties: dict[str, object] = {}
    required: list[str] = []
    for key, field in MANIFEST_FIELDS.items():
        base: dict[str, object] = (
            {"type": "array", "items": {"type": "string"}}
            if field.type == "array<string>"
            else {"type": field.type}
        )
        if field.type not in json_types:
            msg = f"MANIFEST_FIELDS[{key!r}] has the non-JSON type {field.type!r}"
            raise ValueError(msg)
        properties[key] = {
            **({"anyOf": [base, {"type": "null"}]} if field.nullable else base),
            "description": field.description,
        }
        if not field.optional and field.paths == "both":
            required.append(key)
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "Crucible run manifest",
        "description": (
            f"manifest.json of a run, artifact schema_version {SCHEMA_VERSION} "
            "(docs/COMPATIBILITY.md §3)."
        ),
        "type": "object",
        "properties": properties,
        "required": sorted(required),
        "additionalProperties": False,
    }


OUTPUT_SCHEMAS = ("run", "verification", "error", "manifest", "futures-run-document")
"""The ``crucible schema --kind`` values this module serves. ``futures-run`` is the futures-run
CONFIG (``futures_config.futures_config_json_schema``); ``futures-run-document`` is the JSON Schema
of the document a sealed futures run prints (ADR-0097, ``futures_document``)."""


def output_json_schema(kind: str) -> dict[str, object]:
    """The JSON Schema for ``kind`` (one of ``OUTPUT_SCHEMAS``)."""
    if kind == "run":
        return RunDocument.model_json_schema()
    if kind == "verification":
        return VerificationDocument.model_json_schema()
    if kind == "error":
        return ErrorDocument.model_json_schema()
    if kind == "manifest":
        return manifest_json_schema()
    if kind == "futures-run-document":
        return futures_document_json_schema()
    msg = f"unknown output schema {kind!r}; choose one of {', '.join(OUTPUT_SCHEMAS)}"
    raise ValueError(msg)
