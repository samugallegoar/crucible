"""Null-hypothesis comparison (ADR-0019, ADR-0070)."""

from __future__ import annotations

import math

import numpy as np
import pytest

from crucible.core.errors import ConfigurationError
from crucible.validation.null_tests import compare_to_null, compare_to_single_null


def test_p_value_is_the_monte_carlo_add_one_estimate() -> None:
    result = compare_to_null(real_value=1.0, null_values=[0.5, 1.0, 1.5, 2.0])
    assert result.n_exceedances == 3  # 1.0 (a tie counts against the strategy), 1.5, 2.0
    assert result.n_valid == 4
    assert result.p_value == pytest.approx((3 + 1) / (4 + 1))


def test_zero_exceedances_is_bounded_by_one_over_b_plus_one_not_zero() -> None:
    # regression: mean(null >= real) reported exactly 0, as if the true p-value were zero
    result = compare_to_null(real_value=5.0, null_values=[0.1, 0.2, 0.3])
    assert result.n_exceedances == 0
    assert result.p_value == pytest.approx(1 / 4)


def test_p_value_one_when_every_null_value_at_least_matches_real() -> None:
    result = compare_to_null(real_value=-1.0, null_values=[0.0, 0.5, 1.0])
    assert result.p_value == 1.0
    assert result.monte_carlo_se == 0.0


def test_constant_null_statistic_tied_with_real_counts_every_draw() -> None:
    result = compare_to_null(real_value=0.3, null_values=[0.3] * 9)
    assert result.n_exceedances == 9
    assert result.p_value == 1.0


def test_nan_null_values_are_excluded_and_reported() -> None:
    result = compare_to_null(real_value=1.0, null_values=[0.5, float("nan"), 2.0, float("nan")])
    assert (result.n_valid, result.n_invalid, result.n_exceedances) == (2, 2, 1)
    assert result.p_value == pytest.approx(2 / 3)
    assert len(result.null_values) == 4  # every value as produced is kept


def test_infinite_null_value_is_a_valid_exceedance() -> None:
    result = compare_to_null(real_value=1.0, null_values=[float("inf"), 0.0])
    assert (result.n_valid, result.n_exceedances) == (2, 1)


def test_monte_carlo_standard_error() -> None:
    result = compare_to_null(real_value=1.0, null_values=[0.0] * 98 + [2.0] * 1)
    p = 2 / 100
    assert result.p_value == pytest.approx(p)
    assert result.monte_carlo_se == pytest.approx(math.sqrt(p * (1 - p) / 99))


def test_result_carries_real_value_and_null_values_through() -> None:
    result = compare_to_null(real_value=0.7, null_values=[0.1, 0.2])
    assert result.real_value == 0.7
    assert result.null_values == (0.1, 0.2)
    assert result.method == "monte_carlo"


def test_rejects_an_empty_null_distribution() -> None:
    with pytest.raises(ConfigurationError, match="at least one"):
        compare_to_null(real_value=1.0, null_values=[])


def test_rejects_all_invalid_null_values() -> None:
    with pytest.raises(ConfigurationError, match="NaN"):
        compare_to_null(real_value=1.0, null_values=[float("nan")] * 3)


@pytest.mark.parametrize("real", [float("nan"), float("inf"), float("-inf")])
def test_rejects_a_non_finite_real_value(real: float) -> None:
    with pytest.raises(ConfigurationError, match="finite"):
        compare_to_null(real_value=real, null_values=[0.1, 0.2])


def test_single_comparison_has_no_p_value() -> None:
    # one deterministic transform (the sign-flip) is not a distribution
    beaten = compare_to_single_null(real_value=1.0, null_value=2.0)
    assert beaten.p_value is None
    assert beaten.method == "single_comparison"
    assert beaten.null_matched_or_beat_real
    winning = compare_to_single_null(real_value=1.0, null_value=0.5)
    assert winning.p_value is None
    assert not winning.null_matched_or_beat_real


def test_p_value_is_calibrated_under_the_null() -> None:
    # when the real value is exchangeable with the null draws, P(p <= alpha) <= alpha exactly
    # for alpha a multiple of 1/(B+1); 4000 replications, B = 19, alpha = 0.05 (= 1/20)
    rng = np.random.default_rng(20261010)
    b, reps = 19, 4000
    rejections = 0
    for _ in range(reps):
        draws = rng.standard_normal(b + 1)
        result = compare_to_null(real_value=float(draws[0]), null_values=draws[1:].tolist())
        assert result.p_value is not None
        rejections += int(result.p_value <= 0.05)
    rate = rejections / reps
    # exact level is 0.05; binomial sd at 4000 reps is ~0.0034, so 4 sd either side
    assert abs(rate - 0.05) < 0.014
