"""Sensitivity sweep driving real runs (ADR-0016): every
swept point is recorded as a trial, unlike scenario fan-out."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from crucible.core.errors import ConfigurationError
from crucible.experiments.config import ExperimentConfig
from crucible.experiments.sensitivity import sweep_1d
from crucible.validation.sensitivity import SensitivitySurface1D
from examples.momentum.build_data import build_all

# Ubuntu CI only (ADR-0076): orchestration over runs covered on every OS; no OS-specific code. Runs
# everywhere locally.
pytestmark = pytest.mark.single_os


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


def test_sweep_1d_runs_every_value_and_centers_on_the_configs_own_value(
    store: Path, tmp_path_factory: pytest.TempPathFactory
) -> None:
    artifacts_root = tmp_path_factory.mktemp("artifacts")
    config = _config(store)  # lookback: 60 in examples/momentum/config.yaml
    surface, runs = sweep_1d(config, "lookback", [40, 50, 60, 70, 80], artifacts_root)
    assert isinstance(surface, SensitivitySurface1D)
    assert len(runs) == 5
    assert surface.chosen_index == 2  # index of 60 in the swept values
    assert surface.classification in {"plateau", "spike"}
    # 5 distinct configs -> 5 distinct experiment ids -> 5 artifact directories
    assert len({run.experiment_id for run in runs}) == 5


def test_every_swept_point_is_recorded_as_a_trial(
    store: Path, tmp_path_factory: pytest.TempPathFactory
) -> None:
    # ADR-0016: unlike scenario fan-out, sweeping a strategy parameter IS a
    # parameter search, so every point counts -- the family's trial count
    # after the sweep must equal the number of swept values.
    artifacts_root = tmp_path_factory.mktemp("artifacts")
    config = _config(store)
    _surface, runs = sweep_1d(config, "lookback", [40, 50, 60, 70, 80], artifacts_root)
    trial_counts = [_manifest(run.path)["trial_count"] for run in runs]
    assert trial_counts == [1, 2, 3, 4, 5]


def test_rejects_a_value_set_that_omits_the_configs_current_value(
    store: Path, tmp_path_factory: pytest.TempPathFactory
) -> None:
    artifacts_root = tmp_path_factory.mktemp("artifacts")
    config = _config(store)  # lookback: 60
    with pytest.raises(ConfigurationError, match="not among the swept values"):
        sweep_1d(config, "lookback", [40, 50, 70, 80], artifacts_root)
