"""Factor regression (ADR-0020).

Reference values for the single-factor case were computed independently via
the closed-form simple-regression formulas (beta = Sxy/Sxx, alpha = ybar -
beta*xbar, Var(alpha) = sigma^2 * (1/n + xbar^2/Sxx)), not by calling this
module. The two-factor case was computed independently via the general OLS
matrix formula, in a standalone script, not by calling this module."""

from __future__ import annotations

import pytest

from crucible.core.errors import ConfigurationError, CrucibleError
from crucible.validation.factor_regression import factor_regression

_Y = [0.02, -0.01, 0.03, 0.00, 0.01, -0.02]
_X = [0.01, -0.02, 0.02, 0.01, 0.00, -0.01]


def test_single_factor_matches_hand_computed_reference() -> None:
    result = factor_regression(_Y, {"market": _X})
    assert result.alpha == pytest.approx(0.0032307692307692306)
    assert result.alpha_t_stat == pytest.approx(0.6827688932004728)
    assert result.loadings == pytest.approx({"market": 1.0615384615384615})
    assert result.r_squared == pytest.approx(0.6975824175824177)
    assert result.n_obs == 6


def test_two_factor_matches_hand_computed_reference() -> None:
    y = [0.02, -0.01, 0.03, 0.00, 0.01, -0.02, 0.015, -0.008]
    x1 = [0.01, -0.02, 0.02, 0.01, 0.00, -0.01, 0.008, -0.004]
    x2 = [0.00, 0.01, -0.01, 0.02, 0.01, 0.00, -0.005, 0.003]
    result = factor_regression(y, {"market": x1, "size": x2})
    assert result.alpha == pytest.approx(0.004045991212127327)
    assert result.alpha_t_stat == pytest.approx(1.0083943069456178)
    assert result.loadings == pytest.approx(
        {"market": 1.0237708696455208, "size": -0.34645435257342494}
    )
    assert result.r_squared == pytest.approx(0.7438271336362517)
    assert result.n_obs == 8


def test_loadings_keyed_by_factor_name_regardless_of_dict_order() -> None:
    forward = factor_regression(_Y, {"market": _X})
    backward = factor_regression(_Y, dict(reversed(list({"market": _X}.items()))))
    assert forward.loadings == backward.loadings


def test_rejects_empty_factor_mapping() -> None:
    with pytest.raises(ConfigurationError, match="at least one factor"):
        factor_regression(_Y, {})


def test_rejects_a_factor_series_of_mismatched_length() -> None:
    with pytest.raises(ConfigurationError, match="expected 6"):
        factor_regression(_Y, {"market": _X[:-1]})


def test_rejects_too_few_observations_for_the_factor_count() -> None:
    with pytest.raises(ConfigurationError, match="n_obs > n_factors"):
        factor_regression([0.01, 0.02], {"a": [0.01, 0.0], "b": [0.0, 0.01]})


def test_rejects_a_singular_design_matrix() -> None:
    # two perfectly collinear factors
    x = [0.01, -0.02, 0.02, 0.01, 0.00, -0.01]
    with pytest.raises(ConfigurationError, match="singular"):
        factor_regression(_Y, {"a": x, "b": [2.0 * v for v in x]})


def test_rejects_a_numerically_perfect_fit() -> None:
    # exact-integer inputs so the fit is exact to within FP noise (~1e-30
    # scale), far below the 1e-12-relative tolerance
    x = [1.0, -2.0, 2.0, 1.0, 0.0, -1.0]
    y = [3.0 + 2.0 * v for v in x]
    with pytest.raises(CrucibleError, match="numerically zero"):
        factor_regression(y, {"market": x})
