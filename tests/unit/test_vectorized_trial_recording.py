"""A vectorized run is a trial in the shared registry (ADR-0061, ADR-0014/0015).

The registry keys trials by ``(family, experiment_id)`` and ignores a repeat, so re-running an
identical config does not change the count (the same rule as the event-driven path).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from crucible.experiments.config import ExperimentConfig
from crucible.experiments.vectorized_runner import run_vectorized_experiment
from crucible.validation.trial_registry import DuckDBTrialRegistry
from examples.trend_demo.build_data import build_all


@pytest.fixture(scope="module")
def store(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("vec_trials_store")
    build_all(root)
    return root


def _config(store: Path, *, lookback: int = 3, seed: int = 1) -> ExperimentConfig:
    raw = yaml.safe_load(
        Path("examples/trend_demo/config_vectorized.yaml").read_text(encoding="utf-8")
    )
    assert isinstance(raw, dict)
    raw["data"]["store"] = str(store)
    raw["strategy"]["params"]["lookback"] = lookback
    raw["experiment"]["seed"] = seed
    return ExperimentConfig.model_validate(raw)


def _manifest(path: Path) -> dict[str, object]:
    return json.loads((path / "manifest.json").read_text(encoding="utf-8"))  # type: ignore[no-any-return]


def test_a_vectorized_run_records_a_trial_and_fills_the_validation_fields(
    store: Path, tmp_path: Path
) -> None:
    config = _config(store)
    run = run_vectorized_experiment(config, tmp_path)
    manifest = _manifest(run.path)
    assert manifest["trial_count"] == 1
    assert manifest["trial_family"] == config.experiment.family
    # one trial cannot give a dispersion benchmark: either a number or a stated reason
    assert manifest["dsr"] is not None or isinstance(manifest["dsr_error"], str)
    assert isinstance(manifest["contamination"], bool)
    assert manifest["monte_carlo"] is None  # still not computed for the vectorized path
    registry = DuckDBTrialRegistry(tmp_path / "trial_registry.duckdb")
    assert registry.trial_count(config.experiment.family) == 1


def test_a_second_config_in_the_family_increments_the_count(store: Path, tmp_path: Path) -> None:
    run_vectorized_experiment(_config(store, lookback=3), tmp_path)
    second = run_vectorized_experiment(_config(store, lookback=5), tmp_path)
    manifest = _manifest(second.path)
    assert manifest["trial_count"] == 2
    assert manifest["dsr"] is not None  # two Sharpes give a dispersion benchmark


def test_rerunning_the_same_config_does_not_double_count(store: Path, tmp_path: Path) -> None:
    config = _config(store)
    run_vectorized_experiment(config, tmp_path)
    again = run_vectorized_experiment(config, tmp_path)
    assert _manifest(again.path)["trial_count"] == 1


def test_record_trial_false_inserts_nothing_and_reports_the_current_count(
    store: Path, tmp_path: Path
) -> None:
    config = _config(store)
    untracked = run_vectorized_experiment(config, tmp_path, record_trial=False)
    assert _manifest(untracked.path)["trial_count"] == 0
    registry = DuckDBTrialRegistry(tmp_path / "trial_registry.duckdb")
    assert registry.trial_count(config.experiment.family) == 0
    run_vectorized_experiment(_config(store, lookback=5), tmp_path)
    again = run_vectorized_experiment(config, tmp_path, record_trial=False)
    assert _manifest(again.path)["trial_count"] == 1
