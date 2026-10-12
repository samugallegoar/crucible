"""Perturbation Monte Carlo (ADR-0018): execution
perturbation does NOT count as trials (same reasoning as scenario
fan-out, ADR-0014); strategy-parameter perturbation DOES (same reasoning
as sensitivity sweeps, ADR-0016)."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
import yaml

from crucible.core.errors import ConfigurationError
from crucible.experiments.config import ExperimentConfig
from crucible.experiments.perturbation import perturb_execution, perturb_strategy_param
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


def test_execution_perturbation_only_the_base_run_counts_as_a_trial(
    store: Path, tmp_path_factory: pytest.TempPathFactory
) -> None:
    artifacts_root = tmp_path_factory.mktemp("artifacts")
    config = _config(store)  # slippage_bps: 5.0
    stats, runs = perturb_execution(
        config,
        "slippage_bps",
        low=1.0,
        high=10.0,
        n_iterations=4,
        artifacts_root=artifacts_root,
        rng=np.random.default_rng(3),
    )
    assert len(runs) == 5  # 1 base + 4 perturbed
    trial_counts = [_manifest(run.path)["trial_count"] for run in runs]
    assert trial_counts == [1, 1, 1, 1, 1]  # only the base incremented, once
    assert "p_drawdown_worse_than_threshold" in stats
    assert 0.0 <= stats["p_drawdown_worse_than_threshold"] <= 1.0


def test_execution_perturbation_actually_varies_slippage(
    store: Path, tmp_path_factory: pytest.TempPathFactory
) -> None:
    artifacts_root = tmp_path_factory.mktemp("artifacts")
    config = _config(store)
    _stats, runs = perturb_execution(
        config,
        "slippage_bps",
        low=1.0,
        high=10.0,
        n_iterations=4,
        artifacts_root=artifacts_root,
        rng=np.random.default_rng(3),
    )
    # 5 distinct configs (base + 4 perturbed) -> 5 distinct experiment ids
    assert len({run.experiment_id for run in runs}) == 5


def test_strategy_param_perturbation_counts_every_point_as_a_trial(
    store: Path, tmp_path_factory: pytest.TempPathFactory
) -> None:
    artifacts_root = tmp_path_factory.mktemp("artifacts")
    config = _config(store)  # lookback: 60
    stats, runs = perturb_strategy_param(
        config,
        "lookback",
        low=40,
        high=80,
        n_iterations=4,
        artifacts_root=artifacts_root,
        rng=np.random.default_rng(3),
    )
    assert len(runs) == 4  # no separate base run here -- every draw counts
    trial_counts = sorted(_manifest(run.path)["trial_count"] for run in runs)
    assert trial_counts == [1, 2, 3, 4]
    assert "p_drawdown_worse_than_threshold" in stats


def test_perturb_execution_rejects_an_unknown_field(
    store: Path, tmp_path_factory: pytest.TempPathFactory
) -> None:
    artifacts_root = tmp_path_factory.mktemp("artifacts")
    config = _config(store)
    with pytest.raises(ConfigurationError, match="execution config has no"):
        perturb_execution(
            config,
            "not_a_real_field",
            low=1.0,
            high=2.0,
            n_iterations=2,
            artifacts_root=artifacts_root,
            rng=np.random.default_rng(0),
        )


def test_perturb_strategy_param_rejects_an_unknown_field(
    store: Path, tmp_path_factory: pytest.TempPathFactory
) -> None:
    artifacts_root = tmp_path_factory.mktemp("artifacts")
    config = _config(store)
    with pytest.raises(ConfigurationError, match=r"strategy\.params has no"):
        perturb_strategy_param(
            config,
            "not_a_real_param",
            low=1.0,
            high=2.0,
            n_iterations=2,
            artifacts_root=artifacts_root,
            rng=np.random.default_rng(0),
        )
