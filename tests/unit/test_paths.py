"""Return-sequence risk simulations (ADR-0083): expected values derived independently of the code
(exact binomial and dynamic-programming answers, and the project's own drawdown definition)."""

from __future__ import annotations

import json
import math

import numpy as np
import pytest

from crucible.core.drawdown import max_drawdown
from crucible.core.errors import ConfigurationError
from crucible.validation import paths
from crucible.validation.paths import (
    KIND,
    simulate_return_paths,
    simulate_trade_paths,
)

UP, DOWN = 0.05, -0.05


def _coin_flips(n: int = 40) -> np.ndarray:
    """A balanced +5% / -5% series: an i.i.d. bootstrap of it is a fair coin flipped each period."""
    return np.array([UP, DOWN] * (n // 2))


def _binomial_pmf(n: int, k: int) -> float:
    return math.comb(n, k) / 2**n


def test_a_constant_return_series_has_one_deterministic_outcome() -> None:
    summary = simulate_return_paths(
        np.full(40, 0.01), np.random.default_rng(0), n_paths=50, mean_block=3.0
    )
    assert summary.terminal_multiple["p05"] == pytest.approx(1.01**40)
    assert summary.terminal_multiple["p95"] == pytest.approx(1.01**40)
    assert summary.max_drawdown["p05"] == 0.0
    assert summary.prob_loss == 0.0
    assert summary.prob_ruin == 0.0
    assert summary.fan["p05"] == summary.fan["p95"]


def test_probability_of_loss_matches_the_exact_binomial() -> None:
    """With mean_block = 1 the bootstrap of a balanced +5%/-5% series is a fair coin per period.
    The account ends below its start when 1.05**u * 0.95**d < 1 with u + d = 40, i.e. u <= 20."""
    n = 40
    losing = [u for u in range(n + 1) if UP_LOG * u + DOWN_LOG * (n - u) < 0]
    exact = sum(_binomial_pmf(n, u) for u in losing)
    summary = simulate_return_paths(
        _coin_flips(n), np.random.default_rng(1), n_paths=40_000, mean_block=1.0
    )
    assert max(losing) == 20  # sanity of the hand derivation
    assert summary.prob_loss == pytest.approx(exact, abs=0.012)


UP_LOG = math.log(1 + UP)
DOWN_LOG = math.log(1 + DOWN)


def _exact_ruin_probability(n: int, floor: float) -> float:
    """Probability that a fair-coin +5%/-5% path ever touches ``floor`` within n steps, by dynamic
    programming over the (ups, downs) lattice: no simulation, no library code."""
    mass: dict[tuple[int, int], float] = {(0, 0): 1.0}
    ruined = 0.0
    for _ in range(n):
        nxt: dict[tuple[int, int], float] = {}
        for (u, d), p in mass.items():
            for du, dd in ((1, 0), (0, 1)):
                state = (u + du, d + dd)
                level = (1 + UP) ** state[0] * (1 + DOWN) ** state[1]
                if level <= floor + 1e-12:
                    ruined += p / 2
                else:
                    nxt[state] = nxt.get(state, 0.0) + p / 2
        mass = nxt
    return ruined


def test_probability_of_ruin_matches_an_exact_lattice_computation() -> None:
    n, ruin_loss = 40, 0.3
    exact = _exact_ruin_probability(n, 1 - ruin_loss)
    assert 0.05 < exact < 0.6  # a probability worth checking, not a degenerate 0 or 1
    summary = simulate_return_paths(
        _coin_flips(n),
        np.random.default_rng(2),
        n_paths=40_000,
        mean_block=1.0,
        ruin_loss=ruin_loss,
    )
    assert summary.prob_ruin == pytest.approx(exact, abs=0.012)


def test_ruin_is_checked_at_every_step_not_only_at_the_end() -> None:
    """One long block means each path is a rotation of -40%, +83.33%, -40%, ... Half the rotations
    open with the -40% step and touch 0.60; the others never go below the start. Every rotation
    ends at (0.6 * 1.8333) ** 10 = 1.1 ** 10 > 1, so the end alone would report no risk at all."""
    series = np.array([-0.40, 1.1 / 0.6 - 1] * 10)
    touched = simulate_return_paths(
        series, np.random.default_rng(3), n_paths=4000, mean_block=1e12, ruin_loss=0.35
    )
    assert touched.prob_ruin == pytest.approx(0.5, abs=0.03)
    assert touched.prob_loss == 0.0
    assert touched.terminal_multiple["p05"] == pytest.approx(1.1**10)
    assert touched.terminal_multiple["p95"] == pytest.approx(1.1**10)
    safe = simulate_return_paths(
        series, np.random.default_rng(3), n_paths=4000, mean_block=1e12, ruin_loss=0.45
    )
    assert safe.prob_ruin == 0.0  # the lowest the account gets is 0.60, above the 0.55 floor


def test_the_drawdown_distribution_uses_the_project_definition_path_by_path() -> None:
    returns = np.random.default_rng(4).normal(0.001, 0.02, 120)
    summary = simulate_return_paths(
        returns, np.random.default_rng(5), n_paths=300, mean_block=4.0, keep_paths=True
    )
    assert summary.paths is not None
    assert summary.paths.shape == (300, 121)
    reference = np.array([max_drawdown(row) for row in summary.paths])
    for name, pct in (("p05", 5), ("p25", 25), ("p50", 50), ("p75", 75), ("p95", 95)):
        assert summary.max_drawdown[name] == pytest.approx(float(np.percentile(reference, pct)))
    threshold = summary.drawdown_threshold
    assert summary.prob_drawdown_worse_than_threshold == pytest.approx(
        float((reference <= threshold).mean())
    )


def test_every_path_starts_at_one_and_the_terminal_column_is_the_compounded_product() -> None:
    returns = np.random.default_rng(6).normal(0.0005, 0.01, 60)
    summary = simulate_return_paths(
        returns, np.random.default_rng(7), n_paths=40, mean_block=5.0, keep_paths=True
    )
    assert summary.paths is not None
    assert np.all(summary.paths[:, 0] == 1.0)
    steps = summary.paths[:, 1:] / summary.paths[:, :-1] - 1.0
    assert set(np.round(steps.ravel(), 12)) <= set(np.round(returns, 12))  # only real returns
    assert summary.terminal_multiple["p50"] == pytest.approx(
        float(np.percentile(summary.paths[:, -1], 50))
    )


def test_the_fan_is_ordered_starts_at_one_and_ends_at_the_terminal_percentiles() -> None:
    returns = np.random.default_rng(8).normal(0.001, 0.015, 500)
    summary = simulate_return_paths(returns, np.random.default_rng(9), n_paths=400, fan_points=50)
    assert summary.fan_steps[0] == 0
    assert summary.fan_steps[-1] == 500
    assert len(summary.fan_steps) <= 50
    for name in summary.fan:
        assert summary.fan[name][0] == 1.0
    names = ["p05", "p25", "p50", "p75", "p95"]
    for i in range(len(summary.fan_steps)):
        column = [summary.fan[name][i] for name in names]
        assert column == sorted(column)
    for name in names:
        assert summary.fan[name][-1] == pytest.approx(summary.terminal_multiple[name])


def test_a_persistent_series_has_deeper_drawdowns_when_dependence_is_kept() -> None:
    """Runs of 20 gains then 20 losses: an i.i.d. draw scrambles them into a gentle walk, the
    stationary bootstrap with the data's own block length keeps the runs and their drawdowns."""
    runs = np.tile(np.r_[np.full(20, 0.01), np.full(20, -0.01)], 10)
    iid = simulate_return_paths(runs, np.random.default_rng(10), n_paths=500, mean_block=1.0)
    kept = simulate_return_paths(runs, np.random.default_rng(10), n_paths=500)
    assert kept.mean_block is not None
    assert kept.mean_block > 5.0
    assert kept.max_drawdown["p50"] < iid.max_drawdown["p50"] - 0.05  # clearly deeper


def test_the_trade_bootstrap_matches_the_exact_binomial() -> None:
    """20 trades, each +10% or -5% on equity with equal odds: the account ends below its start
    when 1.1**u * 0.95**(20-u) < 1."""
    trades = np.array([0.10, -0.05] * 10)
    n = 20
    losing = [u for u in range(n + 1) if math.log(1.1) * u + math.log(0.95) * (n - u) < 0]
    exact = sum(_binomial_pmf(n, u) for u in losing)
    summary = simulate_trade_paths(trades, np.random.default_rng(11), n_paths=40_000)
    assert summary.method == "trade_bootstrap"
    assert summary.horizon == 20
    assert summary.prob_loss == pytest.approx(exact, abs=0.012)


def test_the_trade_bootstrap_horizon_can_differ_from_the_history() -> None:
    summary = simulate_trade_paths(
        np.array([0.02, -0.01] * 10), np.random.default_rng(12), n_paths=100, n_trades=50
    )
    assert summary.horizon == 50
    assert summary.fan_steps[-1] == 50


def test_same_seed_same_summary_and_the_summary_is_json() -> None:
    returns = np.random.default_rng(13).normal(0.0004, 0.01, 200)
    a = simulate_return_paths(returns, np.random.default_rng(14), n_paths=200)
    b = simulate_return_paths(returns, np.random.default_rng(14), n_paths=200)
    assert a.as_dict() == b.as_dict()
    text = json.dumps(a.as_dict(), allow_nan=False)
    assert KIND in text
    assert a.kind == KIND == "return_sequence_risk"
    assert a.paths is None


def test_chunking_keeps_the_path_count_and_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(paths, "_CHUNK_CELLS", 500)  # forces many small chunks
    returns = np.random.default_rng(15).normal(0.0, 0.01, 100)
    summary = simulate_return_paths(
        returns, np.random.default_rng(16), n_paths=57, keep_paths=True, mean_block=3.0
    )
    assert summary.paths is not None
    assert summary.paths.shape == (57, 101)
    assert summary.n_paths == 57


def test_keeping_too_many_paths_is_refused_with_the_alternative() -> None:
    with pytest.raises(ConfigurationError, match="percentile bands"):
        simulate_return_paths(
            np.full(50, 0.001),
            np.random.default_rng(0),
            n_paths=10**6,
            horizon=10_000,
            keep_paths=True,
        )


@pytest.mark.parametrize(
    "bad",
    [
        np.zeros(5),
        np.r_[np.full(20, 0.01), np.nan],
        np.r_[np.full(20, 0.01), -1.0],
        np.zeros((4, 4)),
    ],
)
def test_series_that_cannot_support_a_distribution_are_refused(bad: np.ndarray) -> None:
    with pytest.raises(ConfigurationError):
        simulate_return_paths(bad, np.random.default_rng(0), n_paths=10)
    with pytest.raises(ConfigurationError):
        simulate_trade_paths(bad, np.random.default_rng(0), n_paths=10)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"n_paths": 0},
        {"ruin_loss": 0.0},
        {"ruin_loss": 1.0},
        {"drawdown_threshold": 0.1},
        {"drawdown_threshold": -1.0},
    ],
)
def test_invalid_levels_are_refused(kwargs: dict[str, float]) -> None:
    with pytest.raises(ConfigurationError):
        simulate_return_paths(np.full(30, 0.001), np.random.default_rng(0), **kwargs)  # type: ignore[arg-type]
