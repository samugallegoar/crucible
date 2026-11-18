"""The Fathom contract for a futures run: `futures run --json` and `artifact show --json` emit the
same versioned document, and `--home` keeps every artifact and the trial registry in one place
(Fathom C3c, ADR-0097).

The acceptance test of this milestone: on the synthetic ES store, a run written under a temporary
Crucible home is read back byte-identically by `artifact show` (one builder, so the two can never
drift), the document validates against the registered schema, the trial registry lives under the
home's `experiments/` folder only — nothing is created in the working directory — and
`--home` + `--artifacts` is refused. The same flow on the real example config runs under ``-m
bench`` against the datasets of ``docs/data/glbx-futures-1m.md``, skipped when they are missing.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
import yaml

from crucible.cli.main import main
from crucible.experiments.artifact_id import verify_artifact
from crucible.experiments.futures_document import (
    FUTURES_DOCUMENT_SCHEMA_VERSION,
    NOT_ASSESSED_MESSAGE,
    VERDICT_REASON_CODES,
    FuturesRunDocument,
)
from tests.integration.test_futures_run_artifact import build_store, mapping

EXAMPLE = Path(__file__).resolve().parents[2] / "examples" / "futures" / "es_sma_cross.yaml"
DATASETS = ("es_1m_cont_v3", "es_1m_cont_ratio_v3", "es_1m_rolls_v3", "es_1m_raw")
RECORDED_STATISTICS = ("sharpe", "psr", "dsr", "p_value", "bootstrap", "permutation")


def _write_config(directory: Path) -> Path:
    path = directory / "futures.yaml"
    path.write_text(yaml.safe_dump(mapping()), encoding="utf-8")
    return path


def _assert_the_fathom_contract(
    document: str, home: Path, cwd: Path, store: Path | None
) -> dict[str, object]:
    """The document a reader (Fathom) gets, checked against everything the milestone promises."""
    doc = json.loads(document)
    assert doc["schema_version"] == FUTURES_DOCUMENT_SCHEMA_VERSION == 1
    assert doc["kind"] == "futures_run"
    assert doc["trial_count"] == 1
    # the null verdict, with its reason: an absence of assessment, never negative evidence
    verdict = doc["verdict"]
    assert verdict["verdict_level"] is None
    assert verdict["verdict_reason"]["code"] in VERDICT_REASON_CODES
    assert verdict["verdict_reason"]["message"] == NOT_ASSESSED_MESSAGE
    # every metric is descriptive and carries no interval
    assert doc["metrics"]
    for metric in doc["metrics"].values():
        assert metric["assessment"] == "descriptive"
        assert metric["ci_low"] is None
        assert metric["ci_high"] is None
    # the schema is the one `crucible schema --kind futures-run-document` prints
    assert FuturesRunDocument.model_validate(doc)
    assert not [
        key for key in _keys(doc) if any(term in key.lower() for term in RECORDED_STATISTICS)
    ]
    # the artifact root is the home's experiments folder, and nothing landed in the cwd
    run_dir = Path(doc["run_dir"])
    assert run_dir.parent == (home / "experiments").resolve()
    assert (home / "experiments" / "trial_registry.duckdb").is_file()
    assert not (cwd / "experiments").exists()
    assert verify_artifact(run_dir) == doc["artifact_id"]
    if store is not None:
        assert doc["datasets"]["execution"]["dataset"] == "es_1m_cont_v3"
    return doc


def _keys(value: object) -> list[str]:
    if isinstance(value, dict):
        keys = [str(key) for key in value]
        for item in value.values():
            keys.extend(_keys(item))
        return keys
    if isinstance(value, list):
        return [key for item in value for key in _keys(item)]
    return []


def test_run_and_artifact_show_emit_the_same_document_under_one_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # a working directory with nothing in it: a default `experiments/` root would show up here
    monkeypatch.chdir(tmp_path)
    home = tmp_path / "home"
    # the home's data/ folder IS the store, so --store is unnecessary with --home
    store = build_store(home / "data")
    config = _write_config(tmp_path)

    assert main(["futures", "run", "--config", str(config), "--home", str(home), "--json"]) == 0
    emitted = capsys.readouterr().out
    doc = _assert_the_fathom_contract(emitted, home, tmp_path, store)
    assert doc["window"] == {"start": "2024-03-05", "end": "2024-03-06"}

    # the same sealed directory, fetched by id: byte-identical JSON (one builder, one document)
    assert main(["artifact", "show", doc["artifact_id"], "--home", str(home), "--json"]) == 0
    assert capsys.readouterr().out == emitted

    # verify works from the home too, and the seal is the run's own
    assert main(["artifact", "verify", doc["artifact_id"], "--home", str(home), "--json"]) == 0
    verified = json.loads(capsys.readouterr().out)
    assert verified["kind"] == "verification"
    assert verified["artifact_id"] == doc["artifact_id"]

    # the human rendering says the verdict out loud instead of leaving it to the metrics
    assert main(["artifact", "show", doc["artifact_id"], "--home", str(home)]) == 0
    text = capsys.readouterr().out
    assert "Verdict: not assessed (C6/C7)" in text
    assert "not evidence of no edge" in text
    assert "net_pnl_usd:" in text


def test_the_human_run_output_states_the_verdict(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)
    home = tmp_path / "home"
    build_store(home / "data")
    config = _write_config(tmp_path)
    assert main(["futures", "run", "--config", str(config), "--home", str(home)]) == 0
    text = capsys.readouterr().out
    assert "Verdict: not assessed (C6/C7)" in text
    assert "not evidence of no edge" in text
    assert "assumed:" in text  # the approximations are still listed in full


def test_home_and_artifacts_together_are_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    home = tmp_path / "home"
    build_store(home / "data")
    config = _write_config(tmp_path)
    code = main(
        [
            "futures",
            "run",
            "--config",
            str(config),
            "--home",
            str(home),
            "--artifacts",
            str(tmp_path / "artifacts"),
            "--json",
        ]
    )
    assert code == 1
    refused = json.loads(capsys.readouterr().out)
    assert refused["error"]["code"] == "configuration_error"
    assert "pass one of --artifacts or --home" in refused["error"]["message"]
    assert not (tmp_path / "artifacts").exists()


def test_artifacts_alone_still_works(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)
    store = build_store(tmp_path / "store")
    artifacts = tmp_path / "artifacts"
    config = _write_config(tmp_path)
    args = ["futures", "run", "--config", str(config), "--store", str(store), "--json"]
    assert main([*args, "--artifacts", str(artifacts)]) == 0
    first = json.loads(capsys.readouterr().out)
    assert Path(first["run_dir"]).parent == artifacts
    # neither flag: the historical default (experiments/ under the working directory)
    assert main(args) == 0
    default = json.loads(capsys.readouterr().out)
    assert Path(default["run_dir"]).parent == tmp_path / "experiments"
    assert (tmp_path / "experiments" / "trial_registry.duckdb").is_file()
    assert (tmp_path / "experiments" / "trial_registry.duckdb").read_bytes() != b""


def test_the_data_catalog_says_which_roots_a_futures_run_can_read(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """`crucible data catalog` reports, per CME root, whether `futures run` could read the store
    (ADR-0097): calendar + contract spec + the four default v3 datasets."""
    store = build_store(tmp_path / "store")
    assert main(["data", "catalog", "--store", str(store), "--json"]) == 0
    catalog = json.loads(capsys.readouterr().out)
    support = catalog["futures_run"]
    assert support["ES"] == {"supported": True, "reasons": []}
    assert support["NQ"]["supported"] is False
    assert any("missing datasets" in reason for reason in support["NQ"]["reasons"])
    # the synthetic store holds only the ES series, so exactly one root is ready
    assert [root for root, status in support.items() if status["supported"]] == ["ES"]

    assert main(["data", "catalog", "--store", str(store)]) == 0
    text = capsys.readouterr().out
    assert "futures run ES: supported" in text
    assert "futures run NQ: not supported (missing datasets:" in text


@pytest.mark.bench
def test_the_real_example_under_a_separate_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The shipped example on the real ES datasets, under its own home (one month of minute bars).

    Run: CRUCIBLE_DATA_STORE=D:/proyectos/crucible/data/processed uv run pytest -m bench \\
        tests/integration/test_futures_fathom_contract.py
    """
    store = Path(os.environ.get("CRUCIBLE_DATA_STORE", "data/processed"))
    missing = [name for name in DATASETS if not (store / name / "data.parquet").is_file()]
    if missing:
        pytest.skip(f"{missing} not built in {store}; see docs/data/glbx-futures-1m.md")
    monkeypatch.chdir(tmp_path)
    home = tmp_path / "home"
    assert main(["futures", "run", "--config", str(EXAMPLE), "--store", str(store),
                 "--home", str(home), "--json"]) == 0  # fmt: skip
    emitted = capsys.readouterr().out
    doc = _assert_the_fathom_contract(emitted, home, tmp_path, store)
    assert doc["root"] == "ES"
    assert doc["trial_family"] == "examples-es-sma-cross"
    assert doc["window"] == {"start": "2024-03-04", "end": "2024-03-28"}
    assert doc["metrics"]["trade_dates"]["value"] == 19.0  # 2024-03-04 .. 2024-03-28, weekdays
    assert doc["verdict"]["verdict_level"] is None
    assert not [name for name in doc["metrics"] if any(t in name for t in RECORDED_STATISTICS)]

    assert main(["artifact", "show", doc["artifact_id"], "--home", str(home), "--json"]) == 0
    assert capsys.readouterr().out == emitted
    # the example's family was not counted in any other root: one home, one registry
    assert not (tmp_path / "experiments").exists()
