"""Calibration of the best-of-N DSR procedure on synthetic processes (ADR-0071).

Runs ``tools.dsr_calibration`` at 300 replications per scenario (seeded, so deterministic) and
pins what the full study measured: under every tested null the rate of DSR >= 0.95 stays at or
under the nominal 5 % (Wilson upper bound), and a strategy with a true edge is flagged more often
than a null one. It does NOT claim DSR is calibrated in general: the full study shows it is very
conservative for N > 1, with low power."""

from __future__ import annotations

import math

import pytest

from tools import dsr_calibration as study

REPS = 300
SCENARIOS = {s.name: s for s in study.scenarios()}


def _rate(name: str, seed: int) -> tuple[float, float]:
    res = study.run(SCENARIOS[name], REPS, seed)
    valid = res.reps - res.invalid
    _, high = study.wilson(res.strong_dsr, valid)
    return res.strong_dsr / valid, high


@pytest.mark.parametrize(
    "name",
    [
        "iid normal, N=1, T=252",
        "iid normal, N=10, T=1260",
        "iid normal, N=100, T=252",
        "heterogeneous windows, N=20, T in [126, 2520]",
        "AR(1) phi=0.2, N=10, T=1260",
        "Student-t df=4, N=10, T=1260",
        "correlated rho=0.9, N=100, T=1260",
    ],
)
def test_the_null_false_positive_rate_does_not_exceed_nominal(name: str) -> None:
    rate, _high = _rate(name, seed=7)
    # 300 replications: a binomial sd of ~0.0126 at p = 0.05; allow two of them
    assert rate <= 0.05 + 2 * 0.0126


def test_a_single_trial_is_close_to_nominal() -> None:
    # with N = 1 the DSR is the PSR against 0, which is calibrated under iid normal returns
    rate, high = _rate("iid normal, N=1, T=1260", seed=8)
    assert high >= 0.05 >= rate - 0.04


def test_a_true_edge_is_flagged_more_often_than_the_null() -> None:
    edge, _ = _rate("one edge SR=0.08/period, N=10, T=1260", seed=9)
    null, _ = _rate("iid normal, N=10, T=1260", seed=9)
    assert edge > null


def test_wilson_interval() -> None:
    low, high = study.wilson(5, 100)
    assert low < 0.05 < high
    assert all(math.isnan(v) for v in study.wilson(0, 0))  # no data, no interval
