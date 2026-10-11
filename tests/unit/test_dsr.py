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


@pytest.mark.parametrize("value", [0.0, 0.001])
def test_zero_variance_returns_are_undefined_not_a_probability(value: float) -> None:
    # regression: a flat series scored Sharpe 0 and DSR = PSR(0) = 0.5 with one trial, a
    # confident-looking probability for a strategy whose Sharpe ratio does not exist (ADR-0070)
    with pytest.raises(CrucibleError, match="zero variance"):
        deflated_sharpe_ratio(np.full(10, value), trial_sharpes=[0.0])


def test_rejects_non_finite_returns() -> None:
    with pytest.raises(CrucibleError, match="NaN or infinite"):
        deflated_sharpe_ratio(np.array([0.01, np.nan, 0.02, 0.0]), trial_sharpes=[0.1])


def test_dsr_rises_with_sample_length_for_the_same_sharpe() -> None:
    # same per-period moments, four times the observations: more evidence, higher PSR/DSR
    short = deflated_sharpe_ratio(_RETURNS, trial_sharpes=[0.2, 0.0, -0.1])
    long = deflated_sharpe_ratio(np.tile(_RETURNS, 4), trial_sharpes=[0.2, 0.0, -0.1])
    assert long.dsr > short.dsr


def test_more_dispersed_trials_raise_the_benchmark() -> None:
    narrow = deflated_sharpe_ratio(_RETURNS, trial_sharpes=[0.1, 0.11, 0.12, 0.13])
    wide = deflated_sharpe_ratio(_RETURNS, trial_sharpes=[-0.5, 0.0, 0.5, 1.0])
    assert wide.benchmark_sharpe > narrow.benchmark_sharpe
    assert wide.dsr < narrow.dsr


def test_psr_refuses_a_non_positive_denominator() -> None:
    # Contrived moments (not derivable from any real sample, by the
    # kurtosis >= skew**2 + 1 inequality) that drive the PSR denominator
    # to exactly zero: denom = 1 - skew*sharpe + (kurtosis-1)/4*sharpe**2.
    with pytest.raises(CrucibleError, match="non-positive"):
        _psr(sharpe_hat=2.0, benchmark=0.0, n=10, skew=1.0, kurtosis=1.0)


# --- ADR-0071: trial count, missing metadata and independent references -------------------


def test_one_trial_is_not_deflated_and_more_trials_are() -> None:
    one = deflated_sharpe_ratio(_RETURNS, trial_sharpes=[0.2])
    many = deflated_sharpe_ratio(_RETURNS, trial_sharpes=[0.2, -0.1, 0.05, 0.3, 0.0])
    assert one.benchmark_sharpe == 0.0
    assert many.benchmark_sharpe > 0.0
    assert many.dsr < one.dsr


def test_more_trials_with_the_same_dispersion_lower_the_dsr() -> None:
    # observed Sharpe and the dispersion estimate held fixed; only N grows
    sharpes = [0.2, -0.1, 0.05, 0.3]
    values = [
        deflated_sharpe_ratio(_RETURNS, trial_sharpes=sharpes, n_trials=n).dsr
        for n in (4, 10, 100, 1000)
    ]
    assert values == sorted(values, reverse=True)
    assert len(set(values)) == 4


def test_trials_without_a_recorded_sharpe_still_count() -> None:
    # 2 Sharpes recorded, 10 trials searched: N = 10, not 2 (missing metadata is not "no trial")
    partial = deflated_sharpe_ratio(_RETURNS, trial_sharpes=[0.2, -0.1], n_trials=10)
    assert partial.n_trials == 10
    assert partial.n_trials_with_sharpe == 2
    undercounted = deflated_sharpe_ratio(_RETURNS, trial_sharpes=[0.2, -0.1])
    assert partial.benchmark_sharpe > undercounted.benchmark_sharpe


def test_too_few_recorded_sharpes_to_estimate_the_dispersion_is_refused() -> None:
    with pytest.raises(CrucibleError, match="only 1 has a recorded Sharpe"):
        deflated_sharpe_ratio(_RETURNS, trial_sharpes=[0.2], n_trials=5)


@pytest.mark.parametrize(
    ("sharpes", "n_trials", "match"),
    [
        ([0.1, 0.2], 1, "must cover every Sharpe"),
        ([], 0, "over 0 trials"),
        ([0.1, float("nan")], None, "NaN or infinite"),
    ],
)
def test_invalid_trial_configurations_are_refused(
    sharpes: list[float], n_trials: int | None, match: str
) -> None:
    with pytest.raises(CrucibleError, match=match):
        deflated_sharpe_ratio(_RETURNS, trial_sharpes=sharpes, n_trials=n_trials)


def test_identical_trials_carry_no_dispersion_so_no_deflation() -> None:
    # documented behaviour, not a dependence model: N copies of one strategy have zero
    # cross-trial dispersion, so the benchmark is 0 whatever N is
    copies = deflated_sharpe_ratio(_RETURNS, trial_sharpes=[0.3] * 50)
    assert copies.benchmark_sharpe == pytest.approx(0.0, abs=1e-12)  # float noise only


def test_dsr_is_invariant_to_the_scale_of_the_returns() -> None:
    sharpes = [0.2, -0.1, 0.05]
    base = deflated_sharpe_ratio(_RETURNS, trial_sharpes=sharpes)
    scaled = deflated_sharpe_ratio(_RETURNS * 7.0, trial_sharpes=sharpes)
    assert scaled.dsr == pytest.approx(base.dsr)


@pytest.mark.parametrize("n", [10, 100, 1000])
def test_the_benchmark_matches_a_monte_carlo_expected_maximum(n: int) -> None:
    # independent of the extreme-value formula: simulate max of n normal Sharpes with known sd
    from crucible.validation.dsr import _expected_max_sharpe

    sigma = 0.05
    rng = np.random.default_rng(11)
    simulated = float(np.mean(rng.normal(0.0, sigma, size=(20_000, n)).max(axis=1)))
    # feed the formula a dispersion of exactly sigma
    sharpes = [-sigma, sigma]  # sample sd = sigma * sqrt(2)
    analytic = _expected_max_sharpe(sharpes, n) / np.sqrt(2.0)
    assert analytic == pytest.approx(simulated, rel=0.05)


def test_psr_against_zero_is_calibrated_under_the_null_for_iid_normal_returns() -> None:
    # independent of the PSR formula: one skill-less strategy, iid normal returns, T = 252;
    # P(PSR >= 0.95) should be about 0.05. 4000 replications, binomial sd ~ 0.0034.
    rng = np.random.default_rng(12)
    hits = 0
    reps = 4000
    for _ in range(reps):
        r = rng.normal(0.0, 0.01, 252)
        hits += int(deflated_sharpe_ratio(r, trial_sharpes=[0.0]).dsr >= 0.95)
    assert abs(hits / reps - 0.05) < 0.015
