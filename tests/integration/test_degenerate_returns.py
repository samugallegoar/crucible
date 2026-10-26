"""A degenerate return series is not a trial with a Sharpe (2026-10 audit, ADR-0079).

A strategy that never trades has constant equity: every simple return is 0, or a constant
non-zero fraction whose float dust used to slip past ``std == 0.0``. The metrics layer then
reported a Sharpe of ~1e14 and the runner stored it in the append-only trial registry, where it
deflated every later trial in the family for ever. It must be stored as NULL (no Sharpe), and
the DSR must say why it cannot be computed.
"""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from crucible.experiments.config import ExperimentConfig
from crucible.experiments.vectorized_runner import run_vectorized_experiment
from crucible.validation.trial_registry import DuckDBTrialRegistry
from examples.trend_demo.build_data import build_all


def _never_trades_config(store: Path) -> ExperimentConfig:
    raw = yaml.safe_load(
        Path("examples/trend_demo/config_vectorized.yaml").read_text(encoding="utf-8")
    )
    assert isinstance(raw, dict)
    raw["data"]["store"] = str(store)
    raw["strategy"]["entrypoint"] = "crucible.strategy_spec.compile:spec_signal"
    # no entry can ever fire: prices are positive, so the position stays flat for the whole run
    raw["strategy"]["params"] = {
        "spec": {
            "spec_version": 1,
            "entry": {"long": "close < 0"},
            "exit": {"long": "close > 0"},
        }
    }
    return ExperimentConfig.model_validate(raw)


def test_a_strategy_that_never_trades_records_no_sharpe(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    build_all(data_dir)
    config = _never_trades_config(data_dir)
    artifacts_root = tmp_path / "experiments"

    run = run_vectorized_experiment(config, artifacts_root)

    manifest = json.loads((run.path / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["dsr"] is None
    assert "zero variance" in str(manifest["dsr_error"])
    # the metrics of the run itself are bounded: no invented 1e14 Sharpe
    assert abs(run.metrics["sharpe"].value) < 1e6
    assert run.metrics["volatility"].value == 0.0

    registry = DuckDBTrialRegistry(artifacts_root / "trial_registry.duckdb")
    assert registry.trial_count(config.experiment.family) == 1  # the trial is still counted
    sharpes = registry.trial_sharpes(config.experiment.family)
    assert sharpes == []  # ... but it contributes no Sharpe to the family's dispersion
