"""A vectorized run that cannot be honored is refused before it leaves anything behind (ADR-0061).

The trial registry is shared with event-driven runs, so one bad vectorized run must neither record
a poisoned trial nor leave an artifact directory.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from crucible.core.errors import ConfigurationError, CrucibleError
from crucible.experiments.config import ExperimentConfig
from crucible.experiments.optimize import optimize_1d
from crucible.experiments.vectorized_runner import (
    run_vectorized_experiment,
    run_vectorized_experiment_parallel,
)
from crucible.validation.trial_registry import DuckDBTrialRegistry
from examples.trend_demo.build_data import build_all


@pytest.fixture(scope="module")
def store(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("vec_refusal_store")
    build_all(root)
    return root


def _raw(store: Path, name: str = "config_vectorized.yaml") -> dict:  # type: ignore[type-arg]
    raw = yaml.safe_load(Path(f"examples/trend_demo/{name}").read_text(encoding="utf-8"))
    assert isinstance(raw, dict)
    raw["data"]["store"] = str(store)
    return raw


def _nothing_left(root: Path) -> bool:
    return not root.exists() or not any(root.iterdir())


def test_a_nan_signal_is_refused_and_never_reaches_the_registry(
    store: Path, tmp_path: Path
) -> None:
    good = ExperimentConfig.model_validate(_raw(store))
    run_vectorized_experiment(good, tmp_path)  # a healthy trial first
    registry = DuckDBTrialRegistry(tmp_path / "trial_registry.duckdb")
    before = registry.trial_sharpes(good.experiment.family)

    raw = _raw(store)
    raw["strategy"]["entrypoint"] = "vectorized_test_signals:nan_signal"
    raw["strategy"]["params"]["lookback"] = 5
    with pytest.raises(CrucibleError, match="non-finite"):
        run_vectorized_experiment(ExperimentConfig.model_validate(raw), tmp_path)

    assert registry.trial_sharpes(good.experiment.family) == before  # nothing recorded
    # the family still gives a finite DSR to the next good run
    again = _raw(store)
    again["strategy"]["params"]["lookback"] = 4
    run = run_vectorized_experiment(ExperimentConfig.model_validate(again), tmp_path)
    manifest = (run.path / "manifest.json").read_text(encoding="utf-8")
    assert "NaN" not in manifest


def test_an_event_driven_config_under_the_vectorized_engine_is_refused_cleanly(
    store: Path, tmp_path: Path
) -> None:
    raw = _raw(store, "config.yaml")  # TrendFollower is a strategy class, not a signal function
    raw["experiment"]["mode"] = "optimization"
    config = ExperimentConfig.model_validate(raw)
    with pytest.raises(ConfigurationError, match="signal function"):
        optimize_1d(
            config, "lookback", [3.0, 5.0], tmp_path / "root", engine="vectorized", max_workers=2
        )
    assert _nothing_left(tmp_path / "root")
    with pytest.raises(ConfigurationError, match="signal function"):
        run_vectorized_experiment(config, tmp_path / "single")
    assert _nothing_left(tmp_path / "single")
    with pytest.raises(ConfigurationError, match="signal function"):
        run_vectorized_experiment_parallel([config], tmp_path / "batch", max_workers=2)
    assert _nothing_left(tmp_path / "batch")


def test_a_signal_without_a_score_column_leaves_no_directory(store: Path, tmp_path: Path) -> None:
    raw = _raw(store)
    raw["strategy"]["entrypoint"] = "vectorized_test_signals:missing_score_signal"
    with pytest.raises(ConfigurationError, match="score"):
        run_vectorized_experiment(ExperimentConfig.model_validate(raw), tmp_path / "root")
    assert _nothing_left(tmp_path / "root")
