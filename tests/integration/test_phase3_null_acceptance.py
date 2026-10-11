"""Overfit-detection acceptance, clauses 3-4 (see ``test_phase3_acceptance.py`` for the whole bar
and ADR-0023/0024 for why a purpose-built autocorrelated dataset is needed).

3. A genuine synthetic edge (``examples.trend_demo.strategy.TrendFollower``, exploiting real AR(1)
   serial autocorrelation) survives a return-order-shuffle null test: its real Sharpe beats every
   shuffled replay.
4. A strategy with no genuine edge on the *same* data (``RandomDirection``) is correctly *not*
   flagged as significant by the same null test.

Each clause is its own class so that a parallel run (``pytest -n``, ``--dist loadscope``) can
put the two ~30-second null tests on different workers (ADR-0075). Nothing in them changed when
they moved here from ``test_phase3_acceptance.py``.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import yaml

from crucible.experiments.config import ExperimentConfig
from crucible.experiments.null_tests import null_test_shuffle
from examples.trend_demo.build_data import build_all as build_trend_data

_NULL_ITERATIONS = 20


def _trend_config(store: Path) -> ExperimentConfig:
    raw = yaml.safe_load(Path("examples/trend_demo/config.yaml").read_text(encoding="utf-8"))
    assert isinstance(raw, dict)
    raw["data"]["store"] = str(store)
    return ExperimentConfig.model_validate(raw)


def _random_direction_config(store: Path) -> ExperimentConfig:
    raw = yaml.safe_load(Path("examples/trend_demo/config_random.yaml").read_text(encoding="utf-8"))
    assert isinstance(raw, dict)
    raw["data"]["store"] = str(store)
    return ExperimentConfig.model_validate(raw)


@pytest.fixture(scope="module")
def trend_store(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("trend_data")
    build_trend_data(path)
    return path


class TestGenuineEdge:
    def test_genuine_autocorrelation_edge_survives_a_shuffle_null_test(
        self, trend_store: Path, tmp_path_factory: pytest.TempPathFactory
    ) -> None:
        """TrendFollower's signal is the trailing mean return's sign -- a
        real dependency on the AR(1) data's lag-1 structure. Shuffling
        destroys that structure while preserving the symbol's overall mean
        and variance, so if the edge is genuine, the real (unshuffled) run
        should beat every shuffled replay."""
        artifacts_root = tmp_path_factory.mktemp("artifacts")
        config = _trend_config(trend_store)
        result, real_run, null_runs = null_test_shuffle(
            config,
            n_iterations=_NULL_ITERATIONS,
            artifacts_root=artifacts_root,
            rng=np.random.default_rng(0),
        )
        assert len(null_runs) == _NULL_ITERATIONS
        assert real_run.metrics["sharpe"].value > 1.0
        assert result.n_exceedances == 0  # beats every one of the shuffled replays
        # ...which a Monte Carlo test reports as its floor 1/(B+1), never 0 (ADR-0070)
        assert result.p_value == pytest.approx(1 / (_NULL_ITERATIONS + 1))


class TestNoEdge:
    def test_a_priori_no_edge_strategy_is_not_flagged_by_the_same_null_test(
        self, trend_store: Path, tmp_path_factory: pytest.TempPathFactory
    ) -> None:
        """RandomDirection has the exact same rebalance mechanics as
        TrendFollower on the exact same data, but its long/flat call is
        `rng.choice`, never the data. A null test correctly finds nothing
        unusual about it: its real result should land comfortably inside the
        shuffled distribution, not in either tail."""
        artifacts_root = tmp_path_factory.mktemp("artifacts")
        config = _random_direction_config(trend_store)
        result, _real_run, null_runs = null_test_shuffle(
            config,
            n_iterations=_NULL_ITERATIONS,
            artifacts_root=artifacts_root,
            rng=np.random.default_rng(0),
        )
        assert len(null_runs) == _NULL_ITERATIONS
        assert 0.05 <= result.p_value <= 0.95  # unremarkable -- correctly not "significant"
