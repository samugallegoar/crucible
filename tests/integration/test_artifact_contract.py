"""The artifact contract on real runs (ADR-0084): identity, determinism, immutability, lookup."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

import polars as pl
import pytest
import yaml

from crucible.core.errors import ExperimentError
from crucible.experiments import artifact_id as artifact_id_module
from crucible.experiments.artifact_id import (
    ARTIFACT_PREFIX,
    find_artifact,
    verify_artifact,
    write_manifest,
)
from crucible.experiments.config import ExperimentConfig
from crucible.experiments.runner import rebuild_report, run_experiment
from crucible.experiments.vectorized_runner import run_vectorized_experiment
from examples.momentum.build_data import build_all
from examples.trend_demo.build_data import build_all as build_trend_data

if TYPE_CHECKING:
    from crucible.experiments.runner import RunArtifacts

_VOLATILE = {"created_at"}


def _momentum(store: Path, *, lookback: int = 60) -> ExperimentConfig:
    raw = yaml.safe_load(Path("examples/momentum/config.yaml").read_text(encoding="utf-8"))
    raw["data"]["store"] = str(store)
    raw["strategy"]["params"]["lookback"] = lookback
    return ExperimentConfig.model_validate(raw)


def _vectorized(store: Path) -> ExperimentConfig:
    raw = yaml.safe_load(
        Path("examples/trend_demo/config_vectorized.yaml").read_text(encoding="utf-8")
    )
    raw["data"]["store"] = str(store)
    return ExperimentConfig.model_validate(raw)


def _manifest(run: RunArtifacts) -> dict[str, object]:
    loaded: dict[str, object] = json.loads((run.path / "manifest.json").read_text(encoding="utf-8"))
    return loaded


@pytest.fixture(scope="module")
def momentum_store(tmp_path_factory: pytest.TempPathFactory) -> Path:
    store = tmp_path_factory.mktemp("momentum_data")
    build_all(store)
    return store


@pytest.fixture(scope="module")
def trend_store(tmp_path_factory: pytest.TempPathFactory) -> Path:
    store = tmp_path_factory.mktemp("trend_data")
    build_trend_data(store)
    return store


# ------------------------------------------------------------------ determinism


def test_the_same_event_driven_run_gives_the_same_artifact(
    momentum_store: Path, tmp_path: Path
) -> None:
    first = run_experiment(_momentum(momentum_store), tmp_path / "a")
    second = run_experiment(_momentum(momentum_store), tmp_path / "b")
    assert first.artifact_id.startswith(ARTIFACT_PREFIX)
    assert first.artifact_id == second.artifact_id
    one, two = _manifest(first), _manifest(second)
    assert {k: v for k, v in one.items() if k not in _VOLATILE} == {
        k: v for k, v in two.items() if k not in _VOLATILE
    }
    for name in ("metrics.json", "equity.parquet", "fills.parquet", "ledger.parquet"):
        assert (first.path / name).read_bytes() == (second.path / name).read_bytes(), name


def test_the_same_vectorized_run_gives_the_same_artifact(trend_store: Path, tmp_path: Path) -> None:
    first = run_vectorized_experiment(_vectorized(trend_store), tmp_path / "a")
    second = run_vectorized_experiment(_vectorized(trend_store), tmp_path / "b")
    assert first.artifact_id == second.artifact_id
    assert _manifest(first)["results_digest"] == _manifest(second)["results_digest"]


def test_a_different_parameter_gives_a_different_artifact(
    momentum_store: Path, tmp_path: Path
) -> None:
    a = run_experiment(_momentum(momentum_store, lookback=60), tmp_path)
    b = run_experiment(_momentum(momentum_store, lookback=40), tmp_path)
    assert a.artifact_id != b.artifact_id


def test_the_identity_does_not_depend_on_the_other_trials_of_the_family(
    momentum_store: Path, tmp_path: Path
) -> None:
    """DSR and trial_count move when the family grows; the artifact id must not."""
    alone = run_experiment(_momentum(momentum_store), tmp_path / "alone")
    crowded_root = tmp_path / "crowded"
    run_experiment(_momentum(momentum_store, lookback=30), crowded_root)
    run_experiment(_momentum(momentum_store, lookback=45), crowded_root)
    crowded = run_experiment(_momentum(momentum_store), crowded_root)
    assert _manifest(crowded)["trial_count"] != _manifest(alone)["trial_count"]
    assert crowded.artifact_id == alone.artifact_id


# ---------------------------------------------------- the manifest says what was run


def test_the_manifest_records_datasets_window_execution_and_expression(
    momentum_store: Path, tmp_path: Path
) -> None:
    run = run_experiment(_momentum(momentum_store), tmp_path)
    manifest = _manifest(run)
    datasets = manifest["datasets"]
    assert isinstance(datasets, dict)
    bars = datasets["bars"]
    assert bars["content_hash"] == manifest["data_manifests"]["bars"]  # type: ignore[index]
    assert set(bars) == {"dataset", "source", "schema_version", "content_hash", "row_count"}
    window = manifest["window"]
    assert isinstance(window, dict)
    assert window["start_ns"] < window["end_ns"]
    execution = manifest["execution"]
    assert isinstance(execution, dict)
    assert execution["engine"] == "event_driven"
    assert execution["realism_level"] == "BASIC_FRICTION"
    expression = manifest["expression"]
    assert isinstance(expression, dict)
    assert expression["kind"] == "entrypoint"
    assert "examples.momentum.strategy:Momentum" in str(expression["canonical"])
    assert len(str(expression["hash"])) == 64


def test_a_vectorized_manifest_records_the_signal_lag(trend_store: Path, tmp_path: Path) -> None:
    run = run_vectorized_experiment(_vectorized(trend_store), tmp_path)
    execution = _manifest(run)["execution"]
    assert isinstance(execution, dict)
    assert execution["engine"] == "vectorized"
    assert execution["lag_bars"] == 1


# ------------------------------------------------- immutability, verification, lookup


def test_a_rerun_of_the_same_artifact_keeps_its_first_seal_time(
    momentum_store: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(artifact_id_module, "_now_utc", lambda: "2026-01-01T00:00:00Z")
    first = run_experiment(_momentum(momentum_store), tmp_path)
    assert _manifest(first)["created_at"] == "2026-01-01T00:00:00Z"
    monkeypatch.setattr(artifact_id_module, "_now_utc", lambda: "2030-06-06T06:06:06Z")
    again = run_experiment(_momentum(momentum_store), tmp_path)
    assert again.artifact_id == first.artifact_id
    assert _manifest(again)["created_at"] == "2026-01-01T00:00:00Z"


def test_verify_accepts_a_sealed_artifact(momentum_store: Path, tmp_path: Path) -> None:
    run = run_experiment(_momentum(momentum_store), tmp_path)
    assert verify_artifact(run.path) == run.artifact_id


def test_verify_refuses_an_edited_result_file(momentum_store: Path, tmp_path: Path) -> None:
    run = run_experiment(_momentum(momentum_store), tmp_path)
    metrics = run.path / "metrics.json"
    metrics.write_text(metrics.read_text(encoding="utf-8") + " ", encoding="utf-8")
    with pytest.raises(ExperimentError, match="does not match its artifact_id") as info:
        verify_artifact(run.path)
    assert info.value.location is not None
    assert info.value.location["artifact_id"] == run.artifact_id


def test_verify_refuses_an_edited_parquet(momentum_store: Path, tmp_path: Path) -> None:
    run = run_experiment(_momentum(momentum_store), tmp_path)
    equity = pl.read_parquet(run.path / "equity.parquet")
    equity.with_columns(pl.col("equity") + 1.0).write_parquet(run.path / "equity.parquet")
    with pytest.raises(ExperimentError, match="does not match"):
        verify_artifact(run.path)


def test_a_factor_regression_merged_after_the_run_does_not_break_the_seal(
    momentum_store: Path, tmp_path: Path
) -> None:
    """`crucible validate --factors` merges into the manifest after sealing (ADR-0022): the
    regression is recorded, but it is outside the identity, so the artifact still verifies."""
    regression = {
        "alpha": 0.1,
        "alpha_t_stat": 2.0,
        "r_squared": 0.5,
        "n_obs": 100,
        "loadings": {"MKT": 1.0},
    }
    run = run_experiment(_momentum(momentum_store), tmp_path)
    rebuild_report(run.path, factor_regression=regression)
    assert _manifest(run)["factor_regression"] == regression
    assert verify_artifact(run.path) == run.artifact_id


def test_verify_refuses_an_edited_manifest(momentum_store: Path, tmp_path: Path) -> None:
    run = run_experiment(_momentum(momentum_store), tmp_path)
    manifest = _manifest(run)
    manifest["seed"] = 12345
    write_manifest(run.path, manifest)
    with pytest.raises(ExperimentError, match="does not match"):
        verify_artifact(run.path)


def test_verify_says_when_a_run_predates_the_contract(momentum_store: Path, tmp_path: Path) -> None:
    run = run_experiment(_momentum(momentum_store), tmp_path)
    manifest = _manifest(run)
    for key in ("artifact_id", "created_at", "results_digest"):
        del manifest[key]
    write_manifest(run.path, manifest)
    with pytest.raises(ExperimentError, match="no artifact_id"):
        verify_artifact(run.path)


def test_an_artifact_is_found_by_its_id(momentum_store: Path, tmp_path: Path) -> None:
    a = run_experiment(_momentum(momentum_store, lookback=60), tmp_path)
    b = run_experiment(_momentum(momentum_store, lookback=40), tmp_path)
    assert find_artifact(tmp_path, a.artifact_id) == a.path
    assert find_artifact(tmp_path, b.artifact_id) == b.path
    assert find_artifact(tmp_path, str(a.experiment_id)) == a.path


def test_a_missing_artifact_is_refused_with_where_and_what(tmp_path: Path) -> None:
    with pytest.raises(ExperimentError, match="no artifact 'ART-nope'") as info:
        find_artifact(tmp_path, "ART-nope")
    assert info.value.location == {"root": str(tmp_path), "artifact_id": "ART-nope"}
