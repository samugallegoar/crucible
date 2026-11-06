"""Stationary bootstrap and automatic block length (ADR-0083), against known theory."""

from __future__ import annotations

import math

import numpy as np
import pytest

from crucible.core.errors import ConfigurationError
from crucible.validation.resampling import optimal_block_length, stationary_bootstrap_indices


def _ar1(phi: float, n: int, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    shocks = rng.standard_normal(n + 200)
    x = np.zeros(n + 200)
    for t in range(1, n + 200):
        x[t] = phi * x[t - 1] + shocks[t]
    return x[200:]


def test_a_huge_mean_block_is_one_consecutive_run_that_wraps() -> None:
    idx = stationary_bootstrap_indices(10, 25, 1e12, 4, np.random.default_rng(1))
    assert idx.shape == (4, 25)
    for row in idx:
        assert np.array_equal(row, (row[0] + np.arange(25)) % 10)


def test_a_mean_block_of_one_is_the_iid_bootstrap() -> None:
    idx = stationary_bootstrap_indices(1000, 2000, 1.0, 200, np.random.default_rng(2))
    continues = (idx[:, 1:] == (idx[:, :-1] + 1) % 1000).mean()
    assert continues == pytest.approx(1 / 1000, abs=5e-4)  # only chance consecutive draws
    assert idx.mean() == pytest.approx(499.5, rel=0.01)


def test_block_lengths_are_geometric_with_the_requested_mean() -> None:
    n, mean_block = 1000, 10.0
    idx = stationary_bootstrap_indices(n, 2000, mean_block, 200, np.random.default_rng(3))
    breaks = (idx[:, 1:] != (idx[:, :-1] + 1) % n).mean()
    # a restart lands on "previous + 1" by chance with probability 1 / n, hiding that break
    assert breaks == pytest.approx((1 / mean_block) * (1 - 1 / n), rel=0.03)


def test_every_observation_is_equally_likely() -> None:
    idx = stationary_bootstrap_indices(50, 500, 7.0, 400, np.random.default_rng(4))
    freq = np.bincount(idx.ravel(), minlength=50) / idx.size
    assert freq.max() - freq.min() < 0.004  # uniform is 0.02 each; sampling noise is ~0.0004


def test_resampled_autocovariance_is_the_circular_one_shrunk_by_the_block_length() -> None:
    """Politis & Romano (1994): the stationary bootstrap's lag-k autocovariance is
    ``(1 - 1/b)**k`` times the circular sample autocovariance."""
    x = _ar1(0.6, 400, 5)
    x = x - x.mean()
    n, b = x.size, 8.0
    idx = stationary_bootstrap_indices(n, 400, b, 20_000, np.random.default_rng(6))
    paths = x[idx]
    for lag in (1, 2, 3):
        circular = float(np.mean(x * np.roll(x, -lag)))
        expected = (1 - 1 / b) ** lag * circular
        observed = float(np.mean(paths[:, :-lag] * paths[:, lag:]))
        assert observed == pytest.approx(expected, rel=0.05)


def test_the_draw_is_reproducible_from_the_seed() -> None:
    a = stationary_bootstrap_indices(30, 40, 5.0, 3, np.random.default_rng(9))
    b = stationary_bootstrap_indices(30, 40, 5.0, 3, np.random.default_rng(9))
    assert np.array_equal(a, b)


@pytest.mark.parametrize(
    ("n", "length", "mean_block", "paths"),
    [(0, 5, 2.0, 2), (5, 0, 2.0, 2), (5, 5, 0.5, 2), (5, 5, float("nan"), 2), (5, 5, 2.0, 0)],
)
def test_invalid_resampling_arguments_are_refused(
    n: int, length: int, mean_block: float, paths: int
) -> None:
    with pytest.raises(ConfigurationError):
        stationary_bootstrap_indices(n, length, mean_block, paths, np.random.default_rng(0))


def test_white_noise_gets_a_short_block() -> None:
    noise = np.random.default_rng(10).standard_normal(5000)
    assert optimal_block_length(noise) < 3.0


@pytest.mark.parametrize("phi", [0.5, 0.8])
def test_an_ar1_series_gets_the_block_length_theory_gives(phi: float) -> None:
    """For AR(1) the optimal stationary-bootstrap block is
    ``(2 phi / ((1 - phi)(1 + phi))) ** (2/3) * n ** (1/3)`` (closed form of G / g)."""
    n = 20_000
    theory = (2 * phi / ((1 - phi) * (1 + phi))) ** (2 / 3) * n ** (1 / 3)
    estimates = [optimal_block_length(_ar1(phi, n, seed)) for seed in range(5)]
    assert float(np.median(estimates)) == pytest.approx(theory, rel=0.35)


def test_more_dependence_means_a_longer_block() -> None:
    lengths = [optimal_block_length(_ar1(phi, 10_000, 11)) for phi in (0.0, 0.4, 0.7, 0.9)]
    assert lengths == sorted(lengths)
    assert lengths[-1] > 3 * lengths[0]


def test_the_block_is_bounded() -> None:
    n = 300
    walk = np.cumsum(np.random.default_rng(12).standard_normal(n))  # a unit root: huge blocks
    assert optimal_block_length(walk) <= min(3 * math.sqrt(n), n / 3) + 1e-9
    assert optimal_block_length(np.random.default_rng(13).standard_normal(30)) >= 1.0


@pytest.mark.parametrize(
    "series", [[1.0] * 9, [2.0] * 50, [1.0, float("nan")] + [0.5] * 20, np.zeros((5, 5))]
)
def test_a_series_that_cannot_support_an_estimate_is_refused(series: object) -> None:
    with pytest.raises(ConfigurationError):
        optimal_block_length(series)
