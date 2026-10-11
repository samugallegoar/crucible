"""Deflated Sharpe Ratio (Bailey & López de Prado 2014).

Corrects the Probabilistic Sharpe Ratio for selection bias from searching
N trials: DSR = PSR(SR*), where SR* is the expected maximum Sharpe ratio a
family of N skill-less trials would produce by chance alone (an
extreme-value approximation), estimated from the family's own recorded
trial Sharpes (``TrialRegistry.trial_sharpes``, ADR-0015).

All Sharpe/skew/kurtosis figures here are per-period, never annualized --
annualizing would decouple the Sharpe estimator's scale from ``n`` (the
observation count) and the higher-moment terms, which the formula's
derivation assumes stay consistent (ADR-0015).

What it is not (ADR-0070): DSR is the probability, under the PSR's asymptotic normal
approximation, that the true per-period Sharpe exceeds the expected maximum of ``N``
skill-less trials. It is not the probability that the strategy is profitable, it corrects
only for the ``N`` trials actually recorded in the family (an unrecorded search is invisible
to it), and ``N`` is the raw count of recorded trials, not an estimate of the effective
number of independent trials (correlated variants overstate ``N``; the cross-trial Sharpe
dispersion partly compensates). The variance of the Sharpe estimator assumes i.i.d. returns;
autocorrelated returns make the reported probability too confident. A zero-variance series
has no Sharpe ratio and is refused rather than scored.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from statistics import NormalDist
from typing import TYPE_CHECKING

import numpy as np

from crucible.core.errors import CrucibleError

if TYPE_CHECKING:
    from collections.abc import Sequence

    from numpy.typing import NDArray

_NORMAL = NormalDist()
_EULER_MASCHERONI = 0.5772156649015329


@dataclass(frozen=True, slots=True)
class DsrResult:
    """``dsr`` is a probability in [0, 1]: how likely the strategy's true
    Sharpe exceeds the benchmark a family of ``n_trials`` skill-less
    strategies would produce by chance alone. Near 0: the observed edge is
    indistinguishable from search noise. Near 1: it survives the
    multiple-testing correction."""

    dsr: float
    observed_sharpe: float
    benchmark_sharpe: float
    n_trials: int


def per_period_sharpe(returns: NDArray[np.float64]) -> float:
    """The per-period (not annualized) Sharpe estimator this whole module
    operates on. Public: the runner needs it to record a trial's Sharpe
    into the registry (ADR-0015) before this trial's own DSR can be
    computed against a benchmark that includes it."""
    std = returns.std(ddof=1)
    return float(returns.mean() / std) if std else 0.0


def _skew(returns: NDArray[np.float64]) -> float:
    std = returns.std(ddof=1)
    if std == 0.0:
        return 0.0
    return float(np.mean(((returns - returns.mean()) / std) ** 3))


def _kurtosis(returns: NDArray[np.float64]) -> float:
    """Pearson kurtosis (normal distribution = 3), not excess kurtosis."""
    std = returns.std(ddof=1)
    if std == 0.0:
        return 3.0
    return float(np.mean(((returns - returns.mean()) / std) ** 4))


def _expected_max_sharpe(trial_sharpes: Sequence[float]) -> float:
    """E[max_N SR] over N skill-less trials (extreme-value approximation,
    Bailey & López de Prado 2014 eq. 10). 0.0 for N<=1: with only one
    trial there is no multiple-testing bias to deflate."""
    n = len(trial_sharpes)
    if n <= 1:
        return 0.0
    sigma_n = float(np.std(np.asarray(trial_sharpes, dtype=np.float64), ddof=1))
    term1 = (1.0 - _EULER_MASCHERONI) * _NORMAL.inv_cdf(1.0 - 1.0 / n)
    term2 = _EULER_MASCHERONI * _NORMAL.inv_cdf(1.0 - 1.0 / (n * math.e))
    return sigma_n * (term1 + term2)


def _psr(sharpe_hat: float, benchmark: float, n: int, skew: float, kurtosis: float) -> float:
    denom = 1.0 - skew * sharpe_hat + (kurtosis - 1.0) / 4.0 * sharpe_hat**2
    if denom <= 0.0:
        msg = (
            f"PSR denominator is non-positive ({denom!r}) for sharpe={sharpe_hat!r}, "
            f"skew={skew!r}, kurtosis={kurtosis!r}, n={n}; DSR cannot be computed "
            "reliably for this return distribution"
        )
        raise CrucibleError(msg)
    z = (sharpe_hat - benchmark) * math.sqrt(n - 1) / math.sqrt(denom)
    return _NORMAL.cdf(z)


def deflated_sharpe_ratio(
    returns: NDArray[np.float64], trial_sharpes: Sequence[float]
) -> DsrResult:
    """``returns``: this trial's own per-period returns (e.g. the equity
    curve's simple returns). ``trial_sharpes``: every distinct trial's
    per-period Sharpe recorded for this family, including this one
    (``TrialRegistry.trial_sharpes``) -- their cross-trial dispersion is
    what the benchmark needs (see module docstring)."""
    if len(returns) < 3:
        msg = f"cannot compute DSR from {len(returns)} return observations; need >= 3"
        raise CrucibleError(msg)
    if not np.all(np.isfinite(returns)):
        msg = "cannot compute DSR: the return series has NaN or infinite values"
        raise CrucibleError(msg)
    if np.all(returns == returns[0]):  # exact: float std of a constant series is ~1e-19
        # a flat series (a strategy that never held anything, or a constant yield) has no
        # Sharpe ratio; reporting PSR(0) here would print a confident-looking probability
        # for an undefined quantity (ADR-0070)
        msg = (
            "cannot compute DSR: the returns have zero variance (for example a strategy that "
            "never held a position), so the Sharpe ratio is undefined"
        )
        raise CrucibleError(msg)
    sharpe_hat = per_period_sharpe(returns)
    benchmark = _expected_max_sharpe(trial_sharpes)
    n = len(returns)
    dsr = _psr(sharpe_hat, benchmark, n, _skew(returns), _kurtosis(returns))
    return DsrResult(
        dsr=dsr,
        observed_sharpe=sharpe_hat,
        benchmark_sharpe=benchmark,
        n_trials=len(trial_sharpes),
    )
