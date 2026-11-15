"""``crucible artifact``, ``--detail`` and the published schemas, end to end (ADR-0084)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from crucible.cli.main import main
from crucible.experiments.artifacts import MANIFEST_FIELDS, manifest_keys
from crucible.experiments.contracts import (
    ErrorDocument,
    RunDocument,
    VerificationDocument,
    manifest_json_schema,
)
from examples.momentum.build_data import build_all
from examples.trend_demo.build_data import build_all as build_trend_data


@pytest.fixture(scope="module")
def store(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("data")
    build_all(path)
    return path


@pytest.fixture(scope="module")
def run_root(tmp_path_factory: pytest.TempPathFactory, store: Path) -> Path:
    """One finished event-driven run, shared by the read-only tests (tests that edit copy it)."""
    root = tmp_path_factory.mktemp("runs")
    config = tmp_path_factory.mktemp("cfg") / "c.yaml"
    raw = yaml.safe_load(Path("examples/momentum/config.yaml").read_text(encoding="utf-8"))
    raw["data"]["store"] = str(store)
    config.write_text(yaml.safe_dump(raw), encoding="utf-8")
    assert main(["run", str(config), "--artifacts", str(root)]) == 0
    return root


def _json(capsys: pytest.CaptureFixture[str]) -> dict[str, object]:
    doc: dict[str, object] = json.loads(capsys.readouterr().out)
    return doc


def _only_run(root: Path) -> Path:
    runs = [p for p in root.iterdir() if (p / "manifest.json").is_file()]
    assert len(runs) == 1
    return runs[0]


def _artifact_id(root: Path) -> str:
    manifest = json.loads((_only_run(root) / "manifest.json").read_text(encoding="utf-8"))
    return str(manifest["artifact_id"])


def _conforms(manifest: dict[str, object], schema: dict[str, object]) -> None:
    """A minimal JSON Schema check for the manifest schema: required, no extras, types."""
    properties = schema["properties"]
    assert isinstance(properties, dict)
    required = schema["required"]
    assert isinstance(required, list)
    assert set(required) <= set(manifest), set(required) - set(manifest)
    assert set(manifest) <= set(properties), set(manifest) - set(properties)
    py = {"integer": int, "number": (int, float), "string": str, "boolean": bool, "object": dict}
    for key, value in manifest.items():
        spec = properties[key]
        assert isinstance(spec, dict)
        options = spec.get("anyOf", [spec])
        assert any(
            (opt["type"] == "null" and value is None)
            or (opt["type"] == "array" and isinstance(value, list))
            or (opt["type"] in py and isinstance(value, py[opt["type"]]))
            for opt in options
        ), (key, value)


# ------------------------------------------------------------- compact and detailed


def test_run_json_is_compact_by_default(
    run_root: Path, store: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = tmp_path / "c.yaml"
    raw = yaml.safe_load(Path("examples/momentum/config.yaml").read_text(encoding="utf-8"))
    raw["data"]["store"] = str(store)
    config.write_text(yaml.safe_dump(raw), encoding="utf-8")
    assert main(["run", str(config), "--artifacts", str(tmp_path / "r"), "--json"]) == 0
    doc = _json(capsys)
    parsed = RunDocument.model_validate(doc)
    assert parsed.artifact_id is not None
    assert parsed.artifact_id.startswith("ART-")
    assert parsed.detail is None
    assert "detail" not in doc


def test_detail_adds_the_full_manifest_and_the_files(
    run_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    artifact = _artifact_id(run_root)
    assert main(["artifact", "show", artifact, "--artifacts", str(run_root), "--json"]) == 0
    compact_text = capsys.readouterr().out
    assert (
        main(["artifact", "show", artifact, "--artifacts", str(run_root), "--detail", "--json"])
        == 0
    )
    detailed_text = capsys.readouterr().out
    detailed = RunDocument.model_validate(json.loads(detailed_text))
    assert detailed.detail is not None
    assert detailed.detail.manifest["artifact_id"] == artifact
    assert {f.name for f in detailed.detail.files} >= {"manifest.json", "metrics.json"}
    assert len(detailed_text) > 3 * len(compact_text)


def test_the_compact_document_stays_small(
    run_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Fathom pays per byte: the default document is a summary, not the artifact."""
    assert (
        main(["artifact", "show", _artifact_id(run_root), "--artifacts", str(run_root), "--json"])
        == 0
    )
    assert len(capsys.readouterr().out) < 4000


# ------------------------------------------------------------------ lookup by id


def test_show_by_artifact_id_equals_the_document_the_run_printed(
    store: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = tmp_path / "c.yaml"
    raw = yaml.safe_load(Path("examples/momentum/config.yaml").read_text(encoding="utf-8"))
    raw["data"]["store"] = str(store)
    config.write_text(yaml.safe_dump(raw), encoding="utf-8")
    root = tmp_path / "r"
    assert main(["run", str(config), "--artifacts", str(root), "--json"]) == 0
    from_run = _json(capsys)
    assert main(["artifact", "show", str(from_run["artifact_id"]), "--artifacts", str(root)]) == 0
    capsys.readouterr()
    assert (
        main(["artifact", "show", str(from_run["artifact_id"]), "--artifacts", str(root), "--json"])
        == 0
    )
    assert _json(capsys) == from_run


def test_show_accepts_the_experiment_id_too(
    run_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    experiment = _only_run(run_root).name
    assert main(["artifact", "show", experiment, "--artifacts", str(run_root), "--json"]) == 0
    assert RunDocument.model_validate(_json(capsys)).experiment_id == experiment


# ------------------------------------------------------------------- verification


def test_verify_an_intact_artifact(run_root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    artifact = _artifact_id(run_root)
    assert main(["artifact", "verify", artifact, "--artifacts", str(run_root), "--json"]) == 0
    doc = VerificationDocument.model_validate(_json(capsys))
    assert doc.artifact_id == artifact


def test_verify_an_edited_artifact_prints_a_structured_error(
    run_root: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    copy = tmp_path / "copy"
    source = _only_run(run_root)
    target = copy / source.name
    target.mkdir(parents=True)
    for file in source.iterdir():
        if file.is_file():
            (target / file.name).write_bytes(file.read_bytes())
    artifact = _artifact_id(copy)
    metrics = target / "metrics.json"
    metrics.write_text(metrics.read_text(encoding="utf-8") + " ", encoding="utf-8")
    assert main(["artifact", "verify", artifact, "--artifacts", str(copy), "--json"]) == 1
    error = ErrorDocument.model_validate(_json(capsys)).error
    assert error.code == "experiment_error"
    assert error.type == "ExperimentError"
    assert "does not match its artifact_id" in error.message
    assert error.location["command"] == "artifact"
    assert error.location["artifact_id"] == artifact


def test_an_unknown_artifact_is_a_structured_error(
    run_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["artifact", "show", "ART-nope", "--artifacts", str(run_root), "--json"]) == 1
    error = ErrorDocument.model_validate(_json(capsys)).error
    assert error.code == "experiment_error"
    assert error.location == {
        "root": str(run_root),
        "artifact_id": "ART-nope",
        "command": "artifact",
    }
    assert "--artifacts root" in error.message  # the message says how to fix it


# --------------------------------------------------------------------- schemas


@pytest.mark.parametrize("kind", ["run", "verification", "error", "manifest"])
def test_each_output_schema_prints_one_json_object(
    kind: str, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["schema", "--kind", kind]) == 0
    schema = _json(capsys)
    assert schema["type"] == "object"
    assert "properties" in schema


def test_the_manifest_schema_covers_every_declared_field(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["schema", "--kind", "manifest"]) == 0
    schema = _json(capsys)
    assert set(schema["properties"]) == set(MANIFEST_FIELDS)  # type: ignore[arg-type]
    assert schema["additionalProperties"] is False


def test_a_real_manifest_conforms_to_the_published_schema(
    run_root: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    manifest = json.loads((_only_run(run_root) / "manifest.json").read_text(encoding="utf-8"))
    _conforms(manifest, manifest_json_schema())
    assert set(manifest) == manifest_keys("event-driven")
    # and a vectorized one
    trend = tmp_path / "trend"
    build_trend_data(trend)
    raw = yaml.safe_load(
        Path("examples/trend_demo/config_vectorized.yaml").read_text(encoding="utf-8")
    )
    raw["data"]["store"] = str(trend)
    config = tmp_path / "v.yaml"
    config.write_text(yaml.safe_dump(raw), encoding="utf-8")
    assert main(["run-vectorized", str(config), "--artifacts", str(tmp_path / "v"), "--json"]) == 0
    doc = RunDocument.model_validate(_json(capsys))
    vectorized = json.loads((Path(doc.artifacts) / "manifest.json").read_text(encoding="utf-8"))
    _conforms(vectorized, manifest_json_schema())
    assert doc.artifact_id == vectorized["artifact_id"]


def test_a_schema_for_an_unknown_kind_is_refused_by_the_parser(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit):
        main(["schema", "--kind", "nope"])
    assert "invalid choice" in capsys.readouterr().err
