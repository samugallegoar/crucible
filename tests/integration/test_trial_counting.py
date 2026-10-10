"""Trial registry wired into the runner (ADR-0008, ADR-0014): the manifest
and report header carry a real, persistent trial count instead of a
hardcoded 1."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from crucible.experiments.config import ExperimentConfig
from crucible.experiments.runner import run_experiment, run_with_scenarios
from examples.momentum.build_data import build_all


def _config(store: Path, **overrides: object) -> ExperimentConfig:
    raw = yaml.safe_load(Path("examples/momentum/config.yaml").read_text(encoding="utf-8"))
    assert isinstance(raw, dict)
    raw["data"]["store"] = str(store)
    for key, value in overrides.items():
        raw["experiment"][key] = value
    return ExperimentConfig.model_validate(raw)


def _manifest(path: Path) -> dict[str, object]:
    return json.loads((path / "manifest.json").read_text(encoding="utf-8"))  # type: ignore[no-any-return]


@pytest.fixture(scope="module")
def store(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("data")
    build_all(path)
    return path


def test_rerunning_the_identical_config_does_not_double_count(
    store: Path, tmp_path_factory: pytest.TempPathFactory
) -> None:
    artifacts_root = tmp_path_factory.mktemp("artifacts")
    config = _config(store)
    first = run_experiment(config, artifacts_root)
    second = run_experiment(config, artifacts_root)
    assert first.experiment_id == second.experiment_id
    assert _manifest(first.path)["trial_count"] == 1
    assert _manifest(second.path)["trial_count"] == 1


def test_a_distinct_config_in_the_same_family_increments(
    store: Path, tmp_path_factory: pytest.TempPathFactory
) -> None:
    artifacts_root = tmp_path_factory.mktemp("artifacts")
    first = run_experiment(_config(store, seed=1), artifacts_root)
    second = run_experiment(_config(store, seed=2), artifacts_root)
    assert first.experiment_id != second.experiment_id
    assert _manifest(first.path)["trial_count"] == 1
    assert _manifest(second.path)["trial_count"] == 2
    # the first run's own manifest, already on disk, is untouched by the second
    assert _manifest(first.path)["trial_count"] == 1


def test_report_header_shows_the_real_trial_count(
    store: Path, tmp_path_factory: pytest.TempPathFactory
) -> None:
    artifacts_root = tmp_path_factory.mktemp("artifacts")
    run_experiment(_config(store, seed=1), artifacts_root)
    second = run_experiment(_config(store, seed=2), artifacts_root)
    report = second.report_path.read_text(encoding="utf-8")
    assert "trial_count" in report
    assert "<td>2</td>" in report


def test_scenario_fanout_counts_only_the_base_run(
    store: Path, tmp_path_factory: pytest.TempPathFactory
) -> None:
    artifacts_root = tmp_path_factory.mktemp("artifacts")
    raw = yaml.safe_load(Path("examples/momentum/config_level4.yaml").read_text(encoding="utf-8"))
    assert isinstance(raw, dict)
    raw["data"]["store"] = str(store)
    config = ExperimentConfig.model_validate(raw)
    outcomes = run_with_scenarios(config, artifacts_root)
    assert len(outcomes) == 4  # base + optimistic/conservative/extreme
    for outcome in outcomes:
        assert _manifest(outcome.artifacts.path)["trial_count"] == 1
