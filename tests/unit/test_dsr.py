"""Deflated Sharpe Ratio (Bailey & López de Prado 2014; ADR-0015).

Reference values below were computed independently (not derived from this
module) with numpy + statistics.NormalDist directly against the same
formulas, then hardcoded -- see the design notes in ADR-0015."""

from __future__ import annotations

import numpy as np
import pytest

from crucible.core.errors import CrucibleError
from crucible.validation.dsr import DsrResult, _psr, deflated_sharpe_ratio

_RETURNS = np.array(
    [0.01, 0.02, -0.01, 0.015, 0.005, 0.02, -0.005, 0.01, 0.015, 0.0]
)  # sharpe=0.7745966692414834, skew=-0.4003091380494076, kurtosis=1.6173632812500007


def test_single_trial_uses_zero_benchmark_and_matches_hand_computed_dsr() -> None:
    result = deflated_sharpe_ratio(_RETURNS, trial_sharpes=[0.7745966692414834])
    assert result.n_trials == 1
    assert result.benchmark_sharpe == 0.0
    assert result.observed_sharpe == pytest.approx(0.7745966692414834)
    assert result.dsr == pytest.approx(0.9751235358326032, abs=1e-9)


def test_multiple_trials_deflate_dsr_via_cross_trial_dispersion() -> None:
    trial_sharpes = [0.7745966692414834, 0.1, -0.2, 0.05, 0.3]
    result = deflated_sharpe_ratio(_RETURNS, trial_sharpes=trial_sharpes)
    assert result.n_trials == 5
    assert result.benchmark_sharpe == pytest.approx(0.43514988947470423, abs=1e-9)
    assert result.dsr == pytest.approx(0.8050589729834455, abs=1e-9)
    # more trials searched over -> a harder bar to clear -> lower DSR
    single = deflated_sharpe_ratio(_RETURNS, trial_sharpes=[0.7745966692414834])
    assert result.dsr < single.dsr


def test_returns_type_is_the_documented_result_shape() -> None:
    result = deflated_sharpe_ratio(_RETURNS, trial_sharpes=[0.5])
    assert isinstance(result, DsrResult)


def test_rejects_too_few_return_observations() -> None:
    with pytest.raises(CrucibleError, match="need >= 3"):
        deflated_sharpe_ratio(np.array([0.01, 0.02]), trial_sharpes=[0.1])


def test_zero_std_returns_have_zero_sharpe_not_a_crash() -> None:
    flat = np.zeros(10)
    result = deflated_sharpe_ratio(flat, trial_sharpes=[0.0])
    assert result.observed_sharpe == 0.0


def test_psr_refuses_a_non_positive_denominator() -> None:
    # Contrived moments (not derivable from any real sample, by the
    # kurtosis >= skew**2 + 1 inequality) that drive the PSR denominator
    # to exactly zero: denom = 1 - skew*sharpe + (kurtosis-1)/4*sharpe**2.
    with pytest.raises(CrucibleError, match="non-positive"):
        _psr(sharpe_hat=2.0, benchmark=0.0, n=10, skew=1.0, kurtosis=1.0)
