"""``crucible futures run|check``, ``crucible schema --kind futures-run`` and the MCP tools
(Fathom C3b, ADR-0095).

The store is the synthetic ES store of ``tests/integration/test_futures_run_artifact.py`` (two
Globex trade dates, one contract switch): what is under test here is the CLI's plumbing — the JSON
document, the refusal path, the config check and the schema kind — and the validity of the shipped
example config on every run. The example is *run* only under ``-m bench``, against the real
datasets of ``docs/data/glbx-futures-1m.md``, and skipped when they are missing.
"""

from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path

import polars as pl
import pytest
import yaml

from crucible.cli.main import main
from crucible.experiments.artifact_id import verify_artifact
from crucible.experiments.futures_config import (
    canonical_futures_yaml,
    futures_config_hash,
    load_futures_config,
)
from tests.integration.test_futures_run_artifact import FAMILY, build_store, mapping

EXAMPLE = Path("examples/futures/es_sma_cross.yaml")
DATASETS = ("es_1m_cont_v3", "es_1m_cont_ratio_v3", "es_1m_rolls_v3", "es_1m_raw")
RUN_KEYS = {
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
"""The futures-run document's keys (ADR-0097); its own shape is tested in
tests/unit/test_futures_document.py."""


def _write_config(directory: Path, **overrides: object) -> Path:
    """The synthetic store's config, as the YAML file the CLI reads."""
    path = directory / "futures.yaml"
    path.write_text(yaml.safe_dump(mapping(**overrides)), encoding="utf-8")
    return path


@pytest.fixture(scope="module")
def store(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return build_store(tmp_path_factory.mktemp("store") / "store")


def _run_args(config: Path, store: Path, artifacts: Path) -> list[str]:
    return [
        "futures",
        "run",
        "--config",
        str(config),
        "--store",
        str(store),
        "--artifacts",
        str(artifacts),
        "--json",
    ]


# ---------------------------------------------------------------------------------------------
# futures run


def test_run_json_writes_a_sealed_artifact_that_verifies(
    store: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = _write_config(tmp_path)
    artifacts = tmp_path / "artifacts"
    assert main(_run_args(config, store, artifacts)) == 0
    doc = json.loads(capsys.readouterr().out)  # stdout is exactly one JSON document
    assert set(doc) == RUN_KEYS
    assert doc["kind"] == "futures_run"
    assert doc["schema_version"] == 1
    assert doc["experiment_id"].startswith("FUT-")
    assert doc["artifact_id"].startswith("ART-")
    run_dir = Path(doc["run_dir"])
    assert run_dir.is_dir()
    assert run_dir.name == doc["experiment_id"]
    assert run_dir.parent == artifacts
    assert doc["trial_family"] == FAMILY
    assert doc["trial_count"] == 1
    assert doc["metrics"]["fills"]["value"] == 4.0
    assert doc["metrics"]["trade_dates"]["value"] == 2.0
    assert doc["verdict"]["verdict_level"] is None  # not assessed: no statistic is claimed
    assert doc["approximations"]  # uncalibrated costs are recorded, not hidden

    # the real shape of `artifact verify`: an id, and the root it was written under
    assert (
        main(["artifact", "verify", doc["artifact_id"], "--artifacts", str(artifacts), "--json"])
        == 0
    )
    verified = json.loads(capsys.readouterr().out)
    assert verified["verified"] is True
    assert verified["artifact_id"] == doc["artifact_id"]
    assert verify_artifact(run_dir) == doc["artifact_id"]

    # `artifact show` describes the same directory with the same document (ADR-0097)
    assert (
        main(["artifact", "show", doc["artifact_id"], "--artifacts", str(artifacts), "--json"]) == 0
    )
    assert json.loads(capsys.readouterr().out) == doc


def test_a_second_identical_run_is_refused_unless_overwrite(
    store: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = _write_config(tmp_path)
    artifacts = tmp_path / "artifacts"
    args = _run_args(config, store, artifacts)
    assert main(args) == 0
    first = json.loads(capsys.readouterr().out)

    assert main(args) == 1
    refused = json.loads(capsys.readouterr().out)
    assert refused["error"]["code"] == "configuration_error"
    assert "already exists" in refused["error"]["message"]
    assert refused["error"]["location"]["command"] == "futures"

    assert main([*args, "--overwrite"]) == 0
    again = json.loads(capsys.readouterr().out)
    assert again["experiment_id"] == first["experiment_id"]
    assert again["artifact_id"] == first["artifact_id"]
    assert again["trial_count"] == 1  # a reproduction is not a second trial


def test_run_prints_the_headline_and_the_approximations(
    store: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = _write_config(tmp_path)
    artifacts = tmp_path / "artifacts"
    assert main(["futures", "run", "--config", str(config), "--store", str(store),
                 "--artifacts", str(artifacts)]) == 0  # fmt: skip
    text = capsys.readouterr().out
    assert "run:          FUT-" in text
    assert "artifact:     ART-" in text
    assert f"family {FAMILY}" in text
    assert "bars:         10" in text
    assert "Verdict: not assessed (C6/C7)" in text
    assert "assumed:" in text
    assert f"run dir:      {artifacts}" in text


# ---------------------------------------------------------------------------------------------
# futures check and the schema kind


def test_check_reports_the_config_hash_and_the_canonical_config(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = _write_config(tmp_path)
    expected_hash = futures_config_hash(load_futures_config(config))

    assert main(["futures", "check", "--config", str(config), "--json"]) == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc["kind"] == "futures_run_config"
    assert doc["config_hash"] == expected_hash
    assert doc["config"]["kind"] == "futures_run"
    assert doc["config"]["datasets"] == {
        "execution": "es_1m_cont_v3",
        "signal": "es_1m_cont_ratio_v3",
        "rolls": "es_1m_rolls_v3",
        "raw": "es_1m_raw",
    }

    assert main(["futures", "check", "--config", str(config)]) == 0
    text = capsys.readouterr().out
    assert canonical_futures_yaml(load_futures_config(config)) in text
    assert expected_hash in text


def test_an_unknown_config_key_is_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = _write_config(tmp_path, sizing=1)
    assert main(["futures", "check", "--config", str(config), "--json"]) == 1
    doc = json.loads(capsys.readouterr().out)
    assert doc["error"]["code"] == "configuration_error"
    assert "sizing" in doc["error"]["message"]


def test_the_schema_kind_describes_every_section(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["schema", "--kind", "futures-run"]) == 0
    schema = json.loads(capsys.readouterr().out)
    assert {
        "run",
        "root",
        "window",
        "strategy",
        "costs",
        "execution",
        "signal",
        "session",
    } <= set(schema["properties"])


# ---------------------------------------------------------------------------------------------
# the shipped example


def test_the_example_config_validates(capsys: pytest.CaptureFixture[str]) -> None:
    config = load_futures_config(EXAMPLE)
    assert config.root == "ES"
    assert config.run.family == "examples-es-sma-cross"
    assert (config.window.start, config.window.end) == (dt.date(2024, 3, 4), dt.date(2024, 3, 28))
    assert config.strategy.spec is not None  # the spec path was loaded, not kept as a path
    assert config.contracts == 1
    assert config.execution.stop_ticks == 16
    assert config.execution.target_ticks == 32
    assert config.session.flat_by_close is True

    assert main(["futures", "check", "--config", str(EXAMPLE), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["config_hash"] == futures_config_hash(config)


@pytest.mark.bench
def test_the_example_runs_on_the_real_datasets(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The real datasets of `docs/data/glbx-futures-1m.md`; skips when the store lacks them.

    Run: CRUCIBLE_DATA_STORE=D:/proyectos/crucible/data/processed uv run pytest -m bench \\
        tests/integration/test_futures_cli.py
    """
    store = Path(os.environ.get("CRUCIBLE_DATA_STORE", "data/processed"))
    missing = [name for name in DATASETS if not (store / name / "data.parquet").is_file()]
    if missing:
        pytest.skip(f"{missing} not built in {store}; see docs/data/glbx-futures-1m.md")
    artifacts = tmp_path / "artifacts"
    assert main(["futures", "run", "--config", str(EXAMPLE), "--store", str(store),
                 "--artifacts", str(artifacts), "--json"]) == 0  # fmt: skip
    doc = json.loads(capsys.readouterr().out)
    run_dir = Path(doc["run_dir"])
    assert verify_artifact(run_dir) == doc["artifact_id"]
    # one daily row per Globex trade date of the window (2024-03-04 .. 2024-03-28: no CME holiday)
    window = load_futures_config(EXAMPLE).window
    day, expected = window.start, []
    while day <= window.end:
        if day.weekday() < 5:
            expected.append(day)
        day += dt.timedelta(days=1)
    daily = pl.read_parquet(run_dir / "daily.parquet")
    assert daily["trade_date"].to_list() == expected

    metrics = json.loads((run_dir / "metrics.json").read_text(encoding="utf-8"))
    assert metrics
    assert not [name for name in metrics if "sharpe" in name]
