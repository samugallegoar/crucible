"""``optimize_1d`` end to end on the real momentum example (ADR-0022): assembles a real
trials x periods returns panel and
computes PBO from it -- the panel PBO needs."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from crucible.experiments.config import ExperimentConfig
from crucible.experiments.optimize import optimize_1d
from examples.momentum.build_data import build_all


def _config(store: Path) -> ExperimentConfig:
    raw = yaml.safe_load(Path("examples/momentum/config.yaml").read_text(encoding="utf-8"))
    assert isinstance(raw, dict)
    raw["data"]["store"] = str(store)
    raw["experiment"]["mode"] = "optimization"
    return ExperimentConfig.model_validate(raw)


def _manifest(path: Path) -> dict[str, object]:
    return json.loads((path / "manifest.json").read_text(encoding="utf-8"))  # type: ignore[no-any-return]


@pytest.fixture(scope="module")
def store(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("data")
    build_all(path)
    return path


def test_optimize_assembles_a_real_pbo_panel(
    store: Path, tmp_path_factory: pytest.TempPathFactory
) -> None:
    artifacts_root = tmp_path_factory.mktemp("artifacts")
    config = _config(store)
    result, runs = optimize_1d(config, "lookback", [40.0, 60.0, 80.0], artifacts_root, pbo_groups=4)
    assert len(runs) == 3
    assert len(result.experiment_ids) == 3
    assert len({run.experiment_id for run in runs}) == 3  # distinct configs
    assert 0.0 <= result.pbo.pbo <= 1.0
    assert result.pbo.n_trials == 3
    for run in runs:
        assert _manifest(run.path)["mode"] == "optimization"


def test_optimize_every_swept_point_counts_as_a_trial(
    store: Path, tmp_path_factory: pytest.TempPathFactory
) -> None:
    artifacts_root = tmp_path_factory.mktemp("artifacts")
    config = _config(store)
    _result, runs = optimize_1d(
        config, "lookback", [40.0, 60.0, 80.0], artifacts_root, pbo_groups=4
    )
    trial_counts = sorted(_manifest(run.path)["trial_count"] for run in runs)
    assert trial_counts == [1, 2, 3]


def test_optimize_with_workers_matches_sequential(
    store: Path, tmp_path_factory: pytest.TempPathFactory
) -> None:
    """ADR-0038: ``max_workers`` is purely a speed
    knob -- the PBO panel and every trial's own metrics must be identical
    to the sequential sweep."""
    config = _config(store)
    values = [40.0, 60.0, 80.0]

    sequential_result, sequential_runs = optimize_1d(
        config, "lookback", values, tmp_path_factory.mktemp("seq"), pbo_groups=4
    )
    parallel_result, parallel_runs = optimize_1d(
        config, "lookback", values, tmp_path_factory.mktemp("par"), pbo_groups=4, max_workers=2
    )

    assert parallel_result.experiment_ids == sequential_result.experiment_ids
    assert parallel_result.metric_values == sequential_result.metric_values
    assert parallel_result.pbo.pbo == sequential_result.pbo.pbo
    assert parallel_result.best_dsr.dsr == sequential_result.best_dsr.dsr
    assert [_manifest(r.path)["trial_count"] for r in parallel_runs] == [
        _manifest(r.path)["trial_count"] for r in sequential_runs
    ]
