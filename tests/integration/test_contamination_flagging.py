"""Contamination flagging wired end-to-end through the runner into
manifest.json and the report header (ADR-0021)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from crucible.experiments.config import ExperimentConfig
from crucible.experiments.runner import run_experiment
from examples.momentum.build_data import build_all


def _config(store: Path, *, mode: str, start: str, end: str, seed: int = 1) -> ExperimentConfig:
    raw = yaml.safe_load(Path("examples/momentum/config.yaml").read_text(encoding="utf-8"))
    assert isinstance(raw, dict)
    raw["data"]["store"] = str(store)
    raw["experiment"]["mode"] = mode
    raw["experiment"]["seed"] = seed
    raw["start"] = start
    raw["end"] = end
    return ExperimentConfig.model_validate(raw)


def _manifest(path: Path) -> dict[str, object]:
    return json.loads((path / "manifest.json").read_text(encoding="utf-8"))  # type: ignore[no-any-return]


@pytest.fixture(scope="module")
def store(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("data")
    build_all(path)
    return path


def test_evaluation_overlapping_an_optimization_window_is_flagged(
    store: Path, tmp_path_factory: pytest.TempPathFactory
) -> None:
    artifacts_root = tmp_path_factory.mktemp("artifacts")
    run_experiment(
        _config(store, mode="optimization", start="2020-01-01", end="2020-07-01"), artifacts_root
    )
    evaluation = run_experiment(
        _config(store, mode="evaluation", start="2020-03-01", end="2020-09-01", seed=2),
        artifacts_root,
    )
    manifest = _manifest(evaluation.path)
    assert manifest["contamination"] is True
    assert manifest["contamination_overlapping_trials"]
    assert "CONTAMINATED" in evaluation.report_path.read_text(encoding="utf-8")


def test_evaluation_disjoint_from_an_optimization_window_is_not_flagged(
    store: Path, tmp_path_factory: pytest.TempPathFactory
) -> None:
    artifacts_root = tmp_path_factory.mktemp("artifacts")
    run_experiment(
        _config(store, mode="optimization", start="2020-01-01", end="2020-07-01"), artifacts_root
    )
    evaluation = run_experiment(
        _config(store, mode="evaluation", start="2021-01-01", end="2021-07-01", seed=2),
        artifacts_root,
    )
    manifest = _manifest(evaluation.path)
    assert manifest["contamination"] is False
    assert manifest["contamination_overlapping_trials"] == []


def test_an_optimization_run_is_never_flagged(
    store: Path, tmp_path_factory: pytest.TempPathFactory
) -> None:
    artifacts_root = tmp_path_factory.mktemp("artifacts")
    run_experiment(
        _config(store, mode="optimization", start="2020-01-01", end="2020-07-01"), artifacts_root
    )
    second = run_experiment(
        _config(store, mode="optimization", start="2020-01-01", end="2020-07-01", seed=2),
        artifacts_root,
    )
    manifest = _manifest(second.path)
    assert manifest["contamination"] is False


def test_an_evaluation_run_with_no_prior_trials_is_not_flagged(
    store: Path, tmp_path_factory: pytest.TempPathFactory
) -> None:
    artifacts_root = tmp_path_factory.mktemp("artifacts")
    evaluation = run_experiment(
        _config(store, mode="evaluation", start="2020-01-01", end="2020-07-01"), artifacts_root
    )
    manifest = _manifest(evaluation.path)
    assert manifest["contamination"] is False
