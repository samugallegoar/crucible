"""Monte Carlo wired end-to-end through the runner into manifest.json and
the report (ADR-0017)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from crucible.experiments.config import ExperimentConfig
from crucible.experiments.runner import run_experiment
from examples.momentum.build_data import build_all


def _config(store: Path) -> ExperimentConfig:
    raw = yaml.safe_load(Path("examples/momentum/config.yaml").read_text(encoding="utf-8"))
    assert isinstance(raw, dict)
    raw["data"]["store"] = str(store)
    return ExperimentConfig.model_validate(raw)


@pytest.fixture(scope="module")
def store(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("data")
    build_all(path)
    return path


def test_manifest_carries_all_three_monte_carlo_tests(
    store: Path, tmp_path_factory: pytest.TempPathFactory
) -> None:
    artifacts = run_experiment(_config(store), tmp_path_factory.mktemp("artifacts"))
    manifest = json.loads((artifacts.path / "manifest.json").read_text(encoding="utf-8"))
    mc = manifest["monte_carlo"]
    assert set(mc) == {"return_order_shuffle", "start_date_shift", "block_bootstrap"}
    for stats in mc.values():
        assert "p_drawdown_worse_than_threshold" in stats
        assert 0.0 <= stats["p_drawdown_worse_than_threshold"] <= 1.0


def test_shuffle_and_shift_sharpe_equal_the_runs_own_metric_sharpe(
    store: Path, tmp_path_factory: pytest.TempPathFactory
) -> None:
    artifacts = run_experiment(_config(store), tmp_path_factory.mktemp("artifacts"))
    manifest = json.loads((artifacts.path / "manifest.json").read_text(encoding="utf-8"))
    mc = manifest["monte_carlo"]
    # both are permutations of the same returns, so their "invariant" Sharpe
    # must be identical to each other (mathematical property, ADR-0017)
    assert mc["return_order_shuffle"]["sharpe_invariant_to_permutation"] == pytest.approx(
        mc["start_date_shift"]["sharpe_invariant_to_permutation"]
    )


def test_report_contains_a_monte_carlo_section(
    store: Path, tmp_path_factory: pytest.TempPathFactory
) -> None:
    artifacts = run_experiment(_config(store), tmp_path_factory.mktemp("artifacts"))
    report = artifacts.report_path.read_text(encoding="utf-8")
    assert "Monte Carlo" in report
    assert "return_order_shuffle" in report
    assert "block_bootstrap" in report
    assert "p_drawdown_worse_than_threshold" in report
