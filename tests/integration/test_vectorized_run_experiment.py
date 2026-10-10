"""Integration test for the config-driven vectorized run:
``crucible run-vectorized examples/trend_demo/config_vectorized.yaml``, at library level."""

from __future__ import annotations

import json
from pathlib import Path

import polars as pl
import pytest
import yaml

from crucible.analytics.trades import EPISODE_SCHEMA
from crucible.core.errors import ConfigurationError
from crucible.experiments.config import ExperimentConfig
from crucible.experiments.vectorized_runner import run_vectorized_experiment
from examples.trend_demo.build_data import build_all


def _config(store_path: Path) -> ExperimentConfig:
    raw = yaml.safe_load(
        Path("examples/trend_demo/config_vectorized.yaml").read_text(encoding="utf-8")
    )
    assert isinstance(raw, dict)
    raw["data"]["store"] = str(store_path)
    return ExperimentConfig.model_validate(raw)


def test_run_vectorized_experiment_writes_a_complete_artifact_set(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    build_all(data_dir)
    config = _config(data_dir)
    artifacts_root = tmp_path / "experiments"

    result = run_vectorized_experiment(config, artifacts_root)

    for name in (
        "config.yaml",
        "manifest.json",
        "equity.parquet",
        "weights.parquet",
        "scores.parquet",
        "trades.parquet",
        "metrics.json",
        "equity.svg",
        "report.html",
    ):
        assert (result.path / name).is_file(), f"missing artifact {name}"

    manifest = json.loads((result.path / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["experiment_id"] == str(result.experiment_id)
    assert manifest["vectorized"] is True
    assert manifest["trial_count"] == 1  # a vectorized run is a trial (ADR-0061)
    assert manifest["trial_family"] == config.experiment.family

    equity = pl.read_parquet(result.path / "equity.parquet")
    assert equity.columns == ["ts", "equity"]
    assert equity.height > 0
    assert "sharpe" in result.metrics
    assert pl.read_parquet(result.path / "trades.parquet").schema == pl.Schema(EPISODE_SCHEMA)

    # deterministic: rerunning with the same config reaches the same id
    # and byte-identical equity (E1)
    again = run_vectorized_experiment(config, artifacts_root)
    assert again.experiment_id == result.experiment_id
    assert pl.read_parquet(again.path / "equity.parquet").equals(equity)


def test_run_vectorized_experiment_refuses_an_out_of_scope_config(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    build_all(data_dir)
    config = _config(data_dir).model_copy(update={"settlement_lag_days": 1})
    with pytest.raises(ConfigurationError, match="settlement"):
        run_vectorized_experiment(config, tmp_path / "experiments")


def test_rebuilding_a_vectorized_report_keeps_the_episode_wording(tmp_path: Path) -> None:
    from crucible.experiments.runner import rebuild_report

    data_dir = tmp_path / "data"
    build_all(data_dir)
    result = run_vectorized_experiment(_config(data_dir), tmp_path / "experiments")
    rebuilt = rebuild_report(result.path).read_text(encoding="utf-8")
    assert "position episodes" in rebuilt
    assert "round trips" not in rebuilt
    assert "gross of costs" in rebuilt
