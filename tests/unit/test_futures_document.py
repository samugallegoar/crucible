"""The futures-run document: one versioned shape, a null verdict with a reason, descriptive metrics
(Fathom C3c, ADR-0097).

The run is the synthetic ES run of ``tests/integration/test_futures_run_artifact.py`` (two Globex
trade dates, one contract switch): what is under test is the document built from its sealed
directory — the keys and the version, the null verdict, the descriptive-only metrics with null
intervals, the refusals (a non-futures manifest, a tampered seal, a metric that claims an
interval) and the registered schema.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import cast

import pytest

from crucible.core.errors import ExperimentError, InvariantViolation
from crucible.experiments.artifact_id import read_seal, seal_artifact
from crucible.experiments.futures_document import (
    FUTURES_DOCUMENT_SCHEMA_VERSION,
    HEADLINE_METRICS,
    METRIC_ASSESSMENTS,
    METRIC_UNIT_NAMES,
    METRIC_UNITS,
    NOT_ASSESSED_MESSAGE,
    REASON_ASSESSED_BY,
    VERDICT_REASON_CODES,
    VERDICT_VOCABULARY,
    FuturesRunDocument,
    futures_document,
    futures_document_json_schema,
    metric_document,
    verdict_document,
)
from crucible.experiments.futures_run import run_futures
from tests.integration.test_futures_run_artifact import build_store, config

DOCUMENT_KEYS = {
    "schema_version",
    "kind",
    "artifact_id",
    "experiment_id",
    "run_name",
    "trial_family",
    "trial_count",
    "root",
    "window",
    "run_dir",
    "datasets",
    "approximations",
    "strict_execution",
    "verdict",
    "headline",
    "metrics",
    "files",
}
"""The document's keys, exactly (an added or renamed key fails the test with the schema)."""


@pytest.fixture(scope="module")
def run_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """One sealed synthetic futures run (its own store and artifacts root)."""
    root = tmp_path_factory.mktemp("document")
    store = build_store(root / "store")
    result = run_futures(config(), store_root=store, artifacts_root=root / "artifacts")
    return result.run_dir


def _copy(run_dir: Path, target: Path) -> Path:
    shutil.copytree(run_dir, target)
    return target


def _tampered_metrics(run_dir: Path, target: Path) -> Path:
    """A copy with an interval added to a descriptive metric, re-sealed (a plausible edit)."""
    copy = _copy(run_dir, target)
    metrics = json.loads((copy / "metrics.json").read_text(encoding="utf-8"))
    metrics["net_pnl_usd"]["ci_low"] = -10.0
    metrics["net_pnl_usd"]["ci_high"] = 10.0
    (copy / "metrics.json").write_text(json.dumps(metrics, sort_keys=True), encoding="utf-8")
    seal_artifact(copy)
    return copy


def _relabelled(run_dir: Path, target: Path) -> Path:
    """A copy whose manifest says it is an equity run, re-sealed so only the kind is wrong."""
    copy = _copy(run_dir, target)
    manifest = json.loads((copy / "manifest.json").read_text(encoding="utf-8"))
    manifest["kind"] = "run"
    (copy / "manifest.json").write_text(json.dumps(manifest, sort_keys=True), encoding="utf-8")
    seal_artifact(copy)
    return copy


def _keys(value: object) -> list[str]:
    """Every key of every object in the document (recursively)."""
    if isinstance(value, dict):
        keys = [str(key) for key in value]
        for item in value.values():
            keys.extend(_keys(item))
        return keys
    if isinstance(value, list):
        return [key for item in value for key in _keys(item)]
    return []


def _statistical(key: str) -> bool:
    lowered = key.lower()
    terms = ("sharpe", "psr", "dsr", "p_value", "p-value", "bootstrap", "permutation")
    return any(term in lowered for term in terms)


# ---------------------------------------------------------------------------------------------
# the shape


def test_the_document_has_the_versioned_shape(run_dir: Path) -> None:
    doc = futures_document(run_dir)
    datasets = cast("dict[str, dict[str, object]]", doc["datasets"])
    assert set(doc) == DOCUMENT_KEYS
    assert doc["schema_version"] == FUTURES_DOCUMENT_SCHEMA_VERSION == 1
    assert doc["kind"] == "futures_run"
    assert str(doc["artifact_id"]).startswith("ART-")
    assert doc["experiment_id"] == run_dir.name
    assert str(doc["experiment_id"]).startswith("FUT-")
    assert doc["run_name"] == "es-sma-demo"
    assert doc["trial_family"] == "es-intraday-sma"
    assert doc["trial_count"] == 1
    assert doc["root"] == "ES"
    assert doc["window"] == {"start": "2024-03-05", "end": "2024-03-06"}
    assert doc["run_dir"] == run_dir.resolve().as_posix()
    assert "/" in str(doc["run_dir"])  # posix-style, even on Windows
    assert "\\" not in str(doc["run_dir"])
    assert sorted(datasets) == ["execution", "raw", "rolls", "signal"]
    assert set(datasets["execution"]) == {
        "dataset",
        "content_hash",
        "price_basis",
        "adjustment",
    }
    assert doc["strict_execution"] is True
    files = cast("list[str]", doc["files"])
    assert files == sorted(files)
    assert "metrics.json" in files
    assert cast("list[str]", doc["approximations"])  # uncalibrated costs are recorded
    assert doc["headline"] == list(HEADLINE_METRICS)


# ---------------------------------------------------------------------------------------------
# the verdict: null, with a reason


def test_the_verdict_is_null_with_a_reason(run_dir: Path) -> None:
    verdict = cast("dict[str, object]", futures_document(run_dir)["verdict"])
    assert verdict["verdict_level"] is None  # no level: the run is not assessed
    assert verdict["vocabulary"] == list(VERDICT_VOCABULARY)
    reason = cast("dict[str, object]", verdict["verdict_reason"])
    assert reason["code"] == "not_assessed"
    assert reason["code"] in VERDICT_REASON_CODES
    assert reason["assessed_by"] == REASON_ASSESSED_BY["not_assessed"] == ["C6", "C7"]
    assert reason["message"] == NOT_ASSESSED_MESSAGE
    assert "absence of assessment, not evidence of no edge" in str(reason["message"])
    # the hard restriction: no key of the document names a statistical result (ADR-0095)
    assert not [key for key in _keys(futures_document(run_dir)) if _statistical(key)]


def test_a_verdict_level_without_its_reason_is_refused() -> None:
    assert verdict_document().verdict_level is None  # the futures verdict: null + a reason
    assert verdict_document(None, "not_assessed").verdict_level is None
    with pytest.raises(InvariantViolation, match="reason code"):
        verdict_document("not_conclusive", "not_assessed")  # a level next to a reason
    with pytest.raises(InvariantViolation, match="reason code"):
        verdict_document(None, None)  # a null level with nothing to explain it
    with pytest.raises(InvariantViolation, match="verdict level"):
        verdict_document("not_conclusive", None)  # the futures path assigns no level
    with pytest.raises(InvariantViolation, match="vocabulary"):
        verdict_document("probably_fine", None)
    with pytest.raises(InvariantViolation, match="reason code"):
        verdict_document(None, "unheard_of")


# ---------------------------------------------------------------------------------------------
# the metrics: descriptive, no intervals


def test_every_metric_is_descriptive_with_null_intervals(run_dir: Path) -> None:
    metrics = cast("dict[str, dict[str, object]]", futures_document(run_dir)["metrics"])
    assert set(metrics) == set(METRIC_UNITS)
    for name, metric in metrics.items():
        assert metric["assessment"] == "descriptive"
        assert metric["assessment"] in METRIC_ASSESSMENTS
        assert metric["ci_low"] is None
        assert metric["ci_high"] is None
        assert metric["unit"] == METRIC_UNITS[name]
        assert metric["unit"] in METRIC_UNIT_NAMES
        assert isinstance(metric["value"], float)
    for name in HEADLINE_METRICS:
        assert name in metrics


def test_a_descriptive_metric_may_not_claim_an_interval() -> None:
    with pytest.raises(InvariantViolation, match="descriptive but carries an interval"):
        metric_document("net_pnl_usd", {"value": 1.0, "ci_low": -1.0, "ci_high": 3.0})
    with pytest.raises(InvariantViolation, match="no unit"):
        metric_document("not_a_metric", {"value": 1.0, "ci_low": None, "ci_high": None})
    with pytest.raises(InvariantViolation, match="not a number"):
        metric_document("fills", {"value": "4", "ci_low": None, "ci_high": None})
    metric = metric_document("fills", {"value": 4, "ci_low": None, "ci_high": None})
    assert metric.value == 4.0
    assert metric.assessment == "descriptive"
    assert metric.unit == "count"


def test_a_tampered_metrics_file_is_refused_by_the_builder(run_dir: Path, tmp_path: Path) -> None:
    tampered = _tampered_metrics(run_dir, tmp_path / "with_interval")
    with pytest.raises(InvariantViolation, match="descriptive but carries an interval"):
        futures_document(tampered)


# ---------------------------------------------------------------------------------------------
# the refusals


def test_a_non_futures_manifest_is_refused(run_dir: Path, tmp_path: Path) -> None:
    equity = _relabelled(run_dir, tmp_path / "equity")
    with pytest.raises(ExperimentError, match="not a futures run"):
        futures_document(equity)


def test_a_tampered_seal_is_refused(run_dir: Path, tmp_path: Path) -> None:
    edited = _copy(run_dir, tmp_path / "edited")
    metrics = json.loads((edited / "metrics.json").read_text(encoding="utf-8"))
    metrics["net_pnl_usd"]["value"] = 1_000_000.0  # an edit after the seal
    (edited / "metrics.json").write_text(json.dumps(metrics, sort_keys=True), encoding="utf-8")
    assert read_seal(edited) is not None  # it still carries the old seal
    with pytest.raises(ExperimentError, match="does not match its artifact_id"):
        futures_document(edited)


def test_a_directory_without_a_manifest_is_refused(tmp_path: Path) -> None:
    empty = tmp_path / "not_a_run"
    empty.mkdir()
    with pytest.raises(ExperimentError, match="not a finished"):
        futures_document(empty)


# ---------------------------------------------------------------------------------------------
# the schema


def test_the_registered_schema_describes_the_document(run_dir: Path) -> None:
    from crucible.experiments.contracts import OUTPUT_SCHEMAS, output_json_schema

    assert "futures-run-document" in OUTPUT_SCHEMAS
    schema = output_json_schema("futures-run-document")
    assert schema == futures_document_json_schema() == FuturesRunDocument.model_json_schema()
    assert schema["title"] == "FuturesRunDocument"
    assert set(cast("dict[str, object]", schema["properties"])) == DOCUMENT_KEYS
    assert sorted(cast("list[str]", schema["required"])) == sorted(DOCUMENT_KEYS)
    definitions = cast("dict[str, dict[str, object]]", schema["$defs"])
    verdict = cast(
        "dict[str, dict[str, object]]", definitions["FuturesVerdictDocument"]["properties"]
    )
    assert verdict["verdict_level"]["type"] == "null"
    reason = cast(
        "dict[str, dict[str, object]]",
        definitions["FuturesVerdictReasonDocument"]["properties"],
    )
    assert reason["code"]["enum"] == list(VERDICT_REASON_CODES)
    metric = cast(
        "dict[str, dict[str, object]]", definitions["FuturesMetricDocument"]["properties"]
    )
    assert metric["assessment"]["enum"] == list(METRIC_ASSESSMENTS)
    assert metric["unit"]["enum"] == list(METRIC_UNIT_NAMES)
    assert metric["ci_low"]["type"] == "null"
    assert metric["ci_high"]["type"] == "null"
    assert definitions["FuturesMetricDocument"]["additionalProperties"] is False

    # the document is exactly what the schema's model accepts (jsonschema is not a dependency,
    # so the model the schema is generated from is the validator)
    assert FuturesRunDocument.model_validate(futures_document(run_dir))
