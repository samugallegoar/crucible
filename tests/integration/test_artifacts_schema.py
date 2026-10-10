"""The run artifacts match the schemas that docs/SCHEMAS.md is generated from, and
``load_experiment`` / ``compare_metrics`` read a finished run back (docs/USAGE.md,
docs/COMPATIBILITY.md §3)."""

from __future__ import annotations

import json
from pathlib import Path

import polars as pl
import pytest
import yaml

from crucible.analytics.trades import TRADE_SCHEMA
from crucible.core.errors import ExperimentError
from crucible.experiments.artifacts import (
    EQUITY_SCHEMA,
    FILL_SCHEMA,
    LEDGER_SCHEMA,
    MANIFEST_FIELDS,
    ORDER_SCHEMA,
    SCHEMA_VERSION,
    compare_metrics,
    load_experiment,
    manifest_keys,
)
from crucible.experiments.config import ExperimentConfig
from crucible.experiments.runner import RunArtifacts, run_experiment
from crucible.experiments.vectorized_runner import run_vectorized_experiment
from examples.momentum.build_data import build_all
from examples.trend_demo.build_data import build_all as build_trend_data


def _config(store: Path, *, lookback: int = 60) -> ExperimentConfig:
    raw = yaml.safe_load(Path("examples/momentum/config.yaml").read_text(encoding="utf-8"))
    assert isinstance(raw, dict)
    raw["data"]["store"] = str(store)
    raw["strategy"]["params"]["lookback"] = lookback
    return ExperimentConfig.model_validate(raw)


@pytest.fixture(scope="module")
def artifacts_root(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return tmp_path_factory.mktemp("artifacts")


@pytest.fixture(scope="module")
def run(tmp_path_factory: pytest.TempPathFactory, artifacts_root: Path) -> RunArtifacts:
    store = tmp_path_factory.mktemp("data")
    build_all(store)
    return run_experiment(_config(store), artifacts_root)


def test_parquet_artifacts_match_the_declared_schemas(run: RunArtifacts) -> None:
    expected = {
        "ledger.parquet": LEDGER_SCHEMA,
        "orders.parquet": ORDER_SCHEMA,
        "fills.parquet": FILL_SCHEMA,
        "equity.parquet": EQUITY_SCHEMA,
        "trades.parquet": TRADE_SCHEMA,
    }
    for name, schema in expected.items():
        frame = pl.read_parquet(run.path / name)
        assert frame.height > 0, f"{name} is empty; the example should trade"
        assert dict(frame.schema) == schema, name


def test_manifest_keys_match_the_declared_fields(run: RunArtifacts) -> None:
    manifest = json.loads((run.path / "manifest.json").read_text(encoding="utf-8"))
    assert set(manifest) == manifest_keys("event-driven")
    assert manifest["schema_version"] == SCHEMA_VERSION


def test_vectorized_manifest_keys_match_the_declared_fields(tmp_path: Path) -> None:
    store = tmp_path / "data"
    build_trend_data(store)
    raw = yaml.safe_load(
        Path("examples/trend_demo/config_vectorized.yaml").read_text(encoding="utf-8")
    )
    raw["data"]["store"] = str(store)
    result = run_vectorized_experiment(ExperimentConfig.model_validate(raw), tmp_path / "out")
    manifest = json.loads((result.path / "manifest.json").read_text(encoding="utf-8"))
    assert set(manifest) == manifest_keys("vectorized")


def test_every_manifest_field_states_its_type_and_paths() -> None:
    for key, spec in MANIFEST_FIELDS.items():
        assert spec.type, key
        assert spec.description, key


def test_load_experiment_reads_back_what_the_run_wrote(
    run: RunArtifacts, artifacts_root: Path
) -> None:
    loaded = load_experiment(artifacts_root, str(run.experiment_id))
    assert loaded.experiment_id == run.experiment_id
    assert loaded.manifest["experiment_id"] == str(run.experiment_id)
    assert set(loaded.metrics) == set(run.metrics)
    assert loaded.metrics["sharpe"] == run.metrics["sharpe"]
    assert loaded.config.experiment.name
    assert dict(loaded.equity.schema) == EQUITY_SCHEMA
    assert loaded.orders.height > 0
    assert loaded.fills.height > 0


def test_load_experiment_refuses_a_missing_run(tmp_path: Path) -> None:
    with pytest.raises(ExperimentError, match="no run 'EXP-nope'"):
        load_experiment(tmp_path, "EXP-nope")


def test_load_experiment_refuses_a_newer_schema_version(
    run: RunArtifacts, artifacts_root: Path, tmp_path: Path
) -> None:
    copy = tmp_path / "copy"
    copy.mkdir()
    target = copy / str(run.experiment_id)
    target.mkdir()
    for file in run.path.iterdir():
        if file.is_file():
            (target / file.name).write_bytes(file.read_bytes())
    manifest = json.loads((target / "manifest.json").read_text(encoding="utf-8"))
    manifest["schema_version"] = SCHEMA_VERSION + 1
    (target / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ExperimentError, match="schema_version"):
        load_experiment(copy, str(run.experiment_id))


def test_a_manifest_without_schema_version_is_read_as_version_zero(
    run: RunArtifacts, tmp_path: Path
) -> None:
    copy = tmp_path / "old"
    target = copy / str(run.experiment_id)
    target.mkdir(parents=True)
    for file in run.path.iterdir():
        if file.is_file():
            (target / file.name).write_bytes(file.read_bytes())
    manifest = json.loads((target / "manifest.json").read_text(encoding="utf-8"))
    del manifest["schema_version"]
    (target / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    assert load_experiment(copy, str(run.experiment_id)).experiment_id == run.experiment_id


def test_compare_metrics_always_carries_the_provenance_columns(
    tmp_path_factory: pytest.TempPathFactory, artifacts_root: Path, run: RunArtifacts
) -> None:
    store = tmp_path_factory.mktemp("data2")
    build_all(store)
    other = run_experiment(_config(store, lookback=40), artifacts_root)
    runs = [
        load_experiment(artifacts_root, str(run.experiment_id)),
        load_experiment(artifacts_root, str(other.experiment_id)),
    ]
    table = compare_metrics(runs, ["sharpe", "max_drawdown"])
    assert table.height == 2
    for column in (
        "experiment_id",
        "realism_level",
        "mode",
        "trial_family",
        "trial_count",
        "dsr",
        "sharpe",
        "sharpe_ci_low",
        "sharpe_ci_high",
        "max_drawdown_ci_low",
    ):
        assert column in table.columns, column
    assert set(table["experiment_id"]) == {str(run.experiment_id), str(other.experiment_id)}
    with pytest.raises(ExperimentError, match="unknown metric"):
        compare_metrics(runs, ["not_a_metric"])
