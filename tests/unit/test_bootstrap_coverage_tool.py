"""The coverage study measures the shipped bootstrap, not a copy of it (ADR-0070)."""

from __future__ import annotations

import math

import numpy as np
import pytest

from crucible.analytics import metrics
from tools import bootstrap_coverage as study


def test_the_default_block_reproduces_the_metrics_bootstrap_exactly() -> None:
    returns = np.random.default_rng(3).normal(0.0004, 0.01, 300)

    def sharpe(r: np.ndarray) -> float:
        return metrics._sharpe(r, 252.0)

    shipped = metrics._block_bootstrap_ci(returns, sharpe, np.random.default_rng(9))
    block = study.block_lengths(300)["sqrt(n) [default]"]
    assert block == int(math.sqrt(300))
    assert study.block_bootstrap_ci(returns, sharpe, np.random.default_rng(9), block) == shipped


@pytest.mark.parametrize("process", study.PROCESSES, ids=lambda p: p.name)
def test_each_process_has_the_documented_sharpe(process: study.Process) -> None:
    # a long draw's sample Sharpe is close to the process's known annualized Sharpe
    returns = process.draw(np.random.default_rng(1), 200_000)
    assert metrics._sharpe(returns, study.PERIODS_PER_YEAR) == pytest.approx(
        process.true_sharpe, abs=0.08
    )


def test_coverage_is_deterministic_for_a_seed() -> None:
    first = study.coverage(study.PROCESSES[0], 120, 10, reps=3, seed=5)
    assert first == study.coverage(study.PROCESSES[0], 120, 10, reps=3, seed=5)
