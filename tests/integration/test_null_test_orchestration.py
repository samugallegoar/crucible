"""Null test orchestration (ADR-0019), exercised on the
real momentum example: re-runs against altered bar data never pollute the
real data store, never count as trials, and the comparison layer wires up
correctly around real (re-simulated) metrics."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
import yaml

from crucible.experiments.config import ExperimentConfig
from crucible.experiments.null_tests import (
    null_test_shuffle,
    null_test_sign_flip,
    null_test_synthetic_gbm,
)
from examples.momentum.build_data import build_all


def _config(store: Path) -> ExperimentConfig:
    raw = yaml.safe_load(Path("examples/momentum/config.yaml").read_text(encoding="utf-8"))
    assert isinstance(raw, dict)
    raw["data"]["store"] = str(store)
    return ExperimentConfig.model_validate(raw)


def _manifest(path: Path) -> dict[str, object]:
    return json.loads((path / "manifest.json").read_text(encoding="utf-8"))  # type: ignore[no-any-return]


@pytest.fixture(scope="module")
def store(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("data")
    build_all(path)
    return path


def test_shuffle_null_test_never_counts_null_runs_as_trials(
    store: Path, tmp_path_factory: pytest.TempPathFactory
) -> None:
    artifacts_root = tmp_path_factory.mktemp("artifacts")
    config = _config(store)
    result, real_run, null_runs = null_test_shuffle(
        config, n_iterations=2, artifacts_root=artifacts_root, rng=np.random.default_rng(7)
    )
    assert len(null_runs) == 2
    assert _manifest(real_run.path)["trial_count"] == 1
    for run in null_runs:
        assert _manifest(run.path)["trial_count"] == 1  # unchanged by null runs
    assert result.real_value == real_run.metrics["sharpe"].value
    assert result.null_values == tuple(run.metrics["sharpe"].value for run in null_runs)
    assert 0.0 <= result.p_value <= 1.0


def test_shuffle_null_test_runs_are_distinct_experiments_from_the_real_run(
    store: Path, tmp_path_factory: pytest.TempPathFactory
) -> None:
    artifacts_root = tmp_path_factory.mktemp("artifacts")
    config = _config(store)
    _result, real_run, null_runs = null_test_shuffle(
        config, n_iterations=2, artifacts_root=artifacts_root, rng=np.random.default_rng(7)
    )
    ids = {real_run.experiment_id, *(run.experiment_id for run in null_runs)}
    assert len(ids) == 3


def test_shuffle_null_test_never_writes_into_the_real_data_store(
    store: Path, tmp_path_factory: pytest.TempPathFactory
) -> None:
    artifacts_root = tmp_path_factory.mktemp("artifacts")
    config = _config(store)
    before = sorted(p.name for p in store.iterdir())
    null_test_shuffle(
        config, n_iterations=2, artifacts_root=artifacts_root, rng=np.random.default_rng(7)
    )
    after = sorted(p.name for p in store.iterdir())
    assert before == after


def test_sign_flip_null_test_is_a_single_deterministic_comparison(
    store: Path, tmp_path_factory: pytest.TempPathFactory
) -> None:
    artifacts_root = tmp_path_factory.mktemp("artifacts")
    config = _config(store)
    result, real_run, null_run = null_test_sign_flip(config, artifacts_root=artifacts_root)
    assert len(result.null_values) == 1
    assert result.null_values[0] == null_run.metrics["sharpe"].value
    assert _manifest(real_run.path)["trial_count"] == 1
    assert _manifest(null_run.path)["trial_count"] == 1


def test_sign_flip_null_test_is_reproducible(
    store: Path, tmp_path_factory: pytest.TempPathFactory
) -> None:
    artifacts_root = tmp_path_factory.mktemp("artifacts")
    config = _config(store)
    _r1, _real1, null1 = null_test_sign_flip(config, artifacts_root=artifacts_root)
    _r2, _real2, null2 = null_test_sign_flip(config, artifacts_root=artifacts_root)
    assert null1.metrics["sharpe"].value == null2.metrics["sharpe"].value


def test_synthetic_gbm_null_test_never_counts_null_runs_as_trials(
    store: Path, tmp_path_factory: pytest.TempPathFactory
) -> None:
    artifacts_root = tmp_path_factory.mktemp("artifacts")
    config = _config(store)
    result, real_run, null_runs = null_test_synthetic_gbm(
        config, n_iterations=2, artifacts_root=artifacts_root, rng=np.random.default_rng(11)
    )
    assert len(null_runs) == 2
    assert _manifest(real_run.path)["trial_count"] == 1
    for run in null_runs:
        assert _manifest(run.path)["trial_count"] == 1
    assert 0.0 <= result.p_value <= 1.0
