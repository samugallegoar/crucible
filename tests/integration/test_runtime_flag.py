"""run_experiment's runtime flag (batch 3, ADR-0051)."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
import yaml

from crucible.core.errors import ConfigurationError
from crucible.experiments.config import ExperimentConfig
from crucible.experiments.runner import run_experiment
from crucible.validation.trial_registry import DuckDBTrialRegistry
from examples.trend_demo.build_data import build_all

# Ubuntu CI only (ADR-0076): config-flag plumbing; live parity (I14) is test_live_parity on every
# OS. Runs everywhere locally.
pytestmark = pytest.mark.single_os


@pytest.fixture(scope="module")
def store(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("runtime_store")
    build_all(root)
    return root


def _config(store: Path, *, live: bool = False) -> ExperimentConfig:
    raw = yaml.safe_load(Path("examples/trend_demo/config.yaml").read_text(encoding="utf-8"))
    raw["data"]["store"] = str(store)
    if live:
        raw["live"] = {"enabled": True}
    return ExperimentConfig.model_validate(raw)


def _manifest(path: Path) -> dict[str, object]:
    manifest = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
    assert isinstance(manifest, dict)
    return manifest


def test_a_paper_run_matches_the_backtest_artifacts(store: Path, tmp_path: Path) -> None:
    backtest = run_experiment(_config(store), tmp_path / "a")
    paper = run_experiment(_config(store), tmp_path / "b", runtime="paper")
    for name in ("equity.parquet", "fills.parquet", "ledger.parquet", "orders.parquet"):
        assert (backtest.path / name).read_bytes() == (paper.path / name).read_bytes(), name
    assert _manifest(backtest.path)["runtime"] == "backtest"
    assert _manifest(paper.path)["runtime"] == "paper"


def test_a_paper_run_is_not_a_new_trial(store: Path, tmp_path: Path) -> None:
    config = _config(store)
    run_experiment(config, tmp_path, runtime="paper")
    registry = DuckDBTrialRegistry(tmp_path / "trial_registry.duckdb")
    assert registry.trial_count(config.experiment.family) == 0
    run_experiment(config, tmp_path)
    assert registry.trial_count(config.experiment.family) == 1


def test_a_live_run_matches_the_backtest_and_is_labelled(store: Path, tmp_path: Path) -> None:
    backtest = run_experiment(_config(store), tmp_path / "a")
    live = run_experiment(_config(store, live=True), tmp_path / "b", runtime="live")
    for name in ("equity.parquet", "fills.parquet"):
        assert (live.path / name).read_bytes() == (backtest.path / name).read_bytes(), name
    assert _manifest(live.path)["runtime"] == "live"
    assert live.experiment_id != backtest.experiment_id  # `live` is part of the config hash


@pytest.mark.parametrize(
    ("live_flag", "runtime", "message"),
    [
        (False, "live", "live: {enabled: true}"),
        (True, "backtest", "--runtime live"),
        (True, "paper", "--runtime live"),
    ],
)
def test_the_runtime_and_the_live_flag_must_agree(
    store: Path, tmp_path: Path, live_flag: bool, runtime: str, message: str
) -> None:
    with pytest.raises(ConfigurationError, match=re.escape(message)):
        run_experiment(_config(store, live=live_flag), tmp_path, runtime=runtime)  # type: ignore[arg-type]
    assert not list(tmp_path.iterdir()), "a refused run must not write artifacts"


def test_a_refused_live_runtime_leaves_no_artifacts(store: Path, tmp_path: Path) -> None:
    """LiveRuntime refuses Level 0 in its constructor; the refusal must happen before any
    artifact directory is created (ADR-0051)."""
    raw = yaml.safe_load(Path("examples/trend_demo/config.yaml").read_text(encoding="utf-8"))
    raw["data"]["store"] = str(store)
    raw["experiment"]["realism_level"] = 0
    raw["live"] = {"enabled": True}
    config = ExperimentConfig.model_validate(raw)
    with pytest.raises(ConfigurationError, match="realism level"):
        run_experiment(config, tmp_path, runtime="live")
    assert not list(tmp_path.iterdir())


def test_the_report_states_the_runtime(store: Path, tmp_path: Path) -> None:
    paper = run_experiment(_config(store), tmp_path, runtime="paper")
    report = paper.report_path.read_text(encoding="utf-8")
    assert "runtime" in report
    assert "paper" in report
