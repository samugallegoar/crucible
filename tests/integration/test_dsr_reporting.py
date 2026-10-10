"""DSR wired end-to-end through the runner into manifest.json and the
report (ADR-0015). PBO stays honestly "not computed" for
a single run -- see ADR-0015 for why."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from crucible.experiments.config import ExperimentConfig
from crucible.experiments.runner import run_experiment
from examples.momentum.build_data import build_all


def _config(store: Path, *, seed: int, lookback: int = 60) -> ExperimentConfig:
    raw = yaml.safe_load(Path("examples/momentum/config.yaml").read_text(encoding="utf-8"))
    assert isinstance(raw, dict)
    raw["data"]["store"] = str(store)
    raw["experiment"]["seed"] = seed
    raw["strategy"]["params"]["lookback"] = lookback
    return ExperimentConfig.model_validate(raw)


def _manifest(path: Path) -> dict[str, object]:
    return json.loads((path / "manifest.json").read_text(encoding="utf-8"))  # type: ignore[no-any-return]


@pytest.fixture(scope="module")
def store(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("data")
    build_all(path)
    return path


def test_manifest_carries_a_real_dsr_value(
    store: Path, tmp_path_factory: pytest.TempPathFactory
) -> None:
    artifacts_root = tmp_path_factory.mktemp("artifacts")
    artifacts = run_experiment(_config(store, seed=1), artifacts_root)
    manifest = _manifest(artifacts.path)
    assert manifest["dsr"] is not None
    dsr = manifest["dsr"]
    assert isinstance(dsr, float)
    assert 0.0 <= dsr <= 1.0
    assert manifest["dsr_error"] is None
    assert manifest["pbo"] is None  # honestly not computable for a single run


def test_a_second_trial_in_the_family_changes_the_benchmark(
    store: Path, tmp_path_factory: pytest.TempPathFactory
) -> None:
    artifacts_root = tmp_path_factory.mktemp("artifacts")
    # A different lookback genuinely changes the strategy's trades/equity
    # curve (unlike varying only `seed`, which at Level 1 -- no execution
    # RNG -- doesn't change the simulated trajectory at all, only the
    # bootstrap CI draws).
    first = run_experiment(_config(store, seed=1, lookback=60), artifacts_root)
    second = run_experiment(_config(store, seed=1, lookback=40), artifacts_root)
    first_manifest = _manifest(first.path)
    second_manifest = _manifest(second.path)
    assert first_manifest["dsr_benchmark_sharpe"] == 0.0  # n_trials=1, no deflation yet
    assert second_manifest["trial_count"] == 2
    # with >= 2 trials of genuinely different Sharpe, the benchmark is the
    # extreme-value E[max_N] estimate, not the single-trial zero
    assert second_manifest["dsr_benchmark_sharpe"] != 0.0


def test_report_shows_a_real_dsr_and_an_honest_pbo_note(
    store: Path, tmp_path_factory: pytest.TempPathFactory
) -> None:
    artifacts_root = tmp_path_factory.mktemp("artifacts")
    artifacts = run_experiment(_config(store, seed=1), artifacts_root)
    report = artifacts.report_path.read_text(encoding="utf-8")
    assert "DSR: not computed" not in report
    assert "PBO: not computed for a single run" in report
    assert "benchmark_sharpe=" in report
