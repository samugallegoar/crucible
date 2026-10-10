"""``optimize_1d`` guard clauses (ADR-0022). The
real panel-assembly + PBO path is exercised end-to-end against the
momentum example in ``tests/integration/test_optimize.py``."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from crucible.core.errors import ConfigurationError
from crucible.experiments.config import ExperimentConfig
from crucible.experiments.optimize import optimize_1d


def _config(*, mode: str) -> ExperimentConfig:
    raw = yaml.safe_load(Path("examples/momentum/config.yaml").read_text(encoding="utf-8"))
    assert isinstance(raw, dict)
    raw["data"]["store"] = "examples/momentum/data"
    raw["experiment"]["mode"] = mode
    return ExperimentConfig.model_validate(raw)


def test_refuses_a_config_not_already_tagged_optimization(tmp_path: Path) -> None:
    config = _config(mode="evaluation")
    with pytest.raises(ConfigurationError, match=r"experiment\.mode: optimization"):
        optimize_1d(config, "lookback", [40.0, 60.0], tmp_path)


def test_refuses_fewer_than_two_values(tmp_path: Path) -> None:
    config = _config(mode="optimization")
    with pytest.raises(ConfigurationError, match=">= 2 values"):
        optimize_1d(config, "lookback", [40.0], tmp_path)


def test_refuses_an_engine_it_does_not_know(tmp_path: Path) -> None:
    config = _config(mode="optimization")
    with pytest.raises(ConfigurationError, match=r"engine.*'vectorised'.*event.*vectorized"):
        optimize_1d(
            config,
            "lookback",
            [40.0, 60.0],
            tmp_path,
            engine="vectorised",  # type: ignore[arg-type]
        )
