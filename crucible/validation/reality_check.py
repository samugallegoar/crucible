"""Data-snooping tests for the best of several tried strategies: White's Reality Check and Hansen's
Superior Predictive Ability test (ADR-0083).

**The question.** You tried ``N`` variants and the best one looks good. If *none* of them had a
positive expected return, how often would the best of ``N`` look at least this good by luck? The
null hypothesis is "no candidate beats the benchmark" (``max_k E[d_k] <= 0``); a small p-value is
evidence that at least one candidate does, **after paying for the search**. This is evidence about
an edge, unlike ``validation.paths`` (sequence risk), and it is complementary to the others:

* the deflated Sharpe corrects for ``N`` parametrically (assuming i.i.d. normal-ish trials);
* PBO asks how often the in-sample winner ranks below the median out of sample;
* this test resamples the actual return panel, so it keeps the candidates' cross-correlation (ten
  nearly identical parameterizations are not ten independent chances) and their serial dependence.

**Method.** The stationary bootstrap (``validation.resampling``) resamples the *same time indices*
for every candidate, so cross-sectional dependence is preserved. With ``d_k`` the mean per-period
return of candidate ``k`` over the benchmark and ``T`` periods:

* White (2000), the Reality Check: ``V = max_k sqrt(T) d_k``, null distribution
  ``max_k sqrt(T) (d*_k - d_k)``.
* Hansen (2005), SPA with the consistent recentering: the studentized
  ``max(0, max_k sqrt(T) d_k / w_k)`` against a null in which candidates that are clearly poor
  (studentized mean below ``-sqrt(2 log log T)``) keep their own negative mean instead of being
  recentred to zero. Studentizing and discarding hopeless candidates make it more powerful than
  the Reality Check when many bad variants dilute the search, and never less valid.

p-values use the project's convention ``(k + 1) / (B + 1)``: never exactly 0, ties count against
the strategy.

**Limits, stated so they are not forgotten.** ``N`` is the candidates *in this panel*: variants
tried elsewhere are not counted (the same lower bound as the deflated Sharpe's trial count). The
test needs the candidates' returns over the exact same periods. Returns are used as given (no
risk-free rate is subtracted unless a ``benchmark`` is passed). With a short sample, or a few
independent heavy-tailed returns, the bootstrap p-value is only approximately calibrated.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np

from crucible.core.errors import ConfigurationError
from crucible.core.stats import is_degenerate_returns
from crucible.validation.resampling import optimal_block_length, stationary_bootstrap_indices

if TYPE_CHECKING:
    from numpy.typing import NDArray

KIND = "edge_evidence_after_search"
"""Tag on the result: evidence about an edge once the search over candidates is paid for."""

MIN_PERIODS = 30
DEFAULT_BOOTSTRAP = 1_000
_CHUNK_CELLS = 4_000_000


@dataclass(frozen=True, slots=True)
class RealityCheckResult:
    """``p_value_rc`` is White's Reality Check, ``p_value_spa`` Hansen's SPA (consistent
    recentering); both test "no candidate has a positive expected return over the benchmark".
    ``best_index`` is the candidate with the largest mean among those that vary; the means and the
    Sharpe are per period (never annualized). ``n_active`` counts the candidates with any
    variation (a candidate that never traded has none and is left out of the maximum)."""

    kind: str
    n_candidates: int
    n_active: int
    n_periods: int
    n_bootstrap: int
    mean_block: float
    best_index: int
    best_mean_per_period: float
    best_sharpe_per_period: float
    statistic_rc: float
    statistic_spa: float
    p_value_rc: float
    p_value_spa: float

    def as_dict(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "n_candidates": self.n_candidates,
            "n_active": self.n_active,
            "n_periods": self.n_periods,
            "n_bootstrap": self.n_bootstrap,
            "mean_block": self.mean_block,
            "best_index": self.best_index,
            "best_mean_per_period": self.best_mean_per_period,
            "best_sharpe_per_period": self.best_sharpe_per_period,
            "statistic_rc": self.statistic_rc,
            "statistic_spa": self.statistic_spa,
            "p_value_rc": self.p_value_rc,
            "p_value_spa": self.p_value_spa,
        }


def _panel(panel: object, benchmark: object | None) -> NDArray[np.float64]:
    x = np.asarray(panel, dtype=np.float64)
    if x.ndim == 1:
        x = x[None, :]
    if x.ndim != 2:
        msg = f"the return panel must be candidates x periods (2-D), got shape {x.shape}"
        raise ConfigurationError(msg)
    if x.shape[1] < MIN_PERIODS:
        msg = (
            f"the reality check needs >= {MIN_PERIODS} periods per candidate, got {x.shape[1]}: "
            "a bootstrap of fewer observations says nothing about the search"
        )
        raise ConfigurationError(msg)
    if not np.all(np.isfinite(x)):
        msg = "the return panel has NaN or infinite values; refusing to resample it"
        raise ConfigurationError(msg)
    if benchmark is not None:
        b = np.asarray(benchmark, dtype=np.float64)
        if b.shape != (x.shape[1],) or not np.all(np.isfinite(b)):
            msg = (
                f"the benchmark must be one finite return per period ({x.shape[1]}), got shape "
                f"{b.shape}"
            )
            raise ConfigurationError(msg)
        x = x - b[None, :]
    return x


def reality_check(
    panel: object,
    rng: np.random.Generator,
    *,
    benchmark: object | None = None,
    n_bootstrap: int = DEFAULT_BOOTSTRAP,
    mean_block: float | None = None,
) -> RealityCheckResult:
    """White's Reality Check and Hansen's SPA for the best of the candidates in ``panel``
    (candidates x periods, simple per-period returns over the same periods).

    ``benchmark`` (periods,) is subtracted from every candidate (default: zero, i.e. the
    candidates' own returns). ``mean_block`` defaults to the largest of the candidates'
    Politis-White block lengths: a longer block widens the bootstrap spread, the cautious side.
    """
    if n_bootstrap < 1:
        msg = f"n_bootstrap must be >= 1, got {n_bootstrap}"
        raise ConfigurationError(msg)
    x = _panel(panel, benchmark)
    n_cand, n_per = x.shape
    active = np.array([not is_degenerate_returns(row) for row in x])
    if not active.any():
        msg = (
            "no candidate in the panel has any variation in its returns (for example none of them "
            "ever held a position), so there is nothing to test"
        )
        raise ConfigurationError(msg)
    if mean_block is None:
        block = max(optimal_block_length(row) for row in x[active])
    else:
        block = float(mean_block)
    sqrt_t = math.sqrt(n_per)
    dbar = x.mean(axis=1)

    boot = np.empty((n_bootstrap, n_cand))
    size = max(1, _CHUNK_CELLS // (n_cand * n_per))
    for start in range(0, n_bootstrap, size):
        m = min(size, n_bootstrap - start)
        idx = stationary_bootstrap_indices(n_per, n_per, block, m, rng)
        boot[start : start + m] = x[:, idx].mean(axis=2).T

    act = np.flatnonzero(active)
    d_act, boot_act = dbar[act], boot[:, act]

    # White's Reality Check: unstudentized, every candidate recentred at its sample mean
    stat_rc = float(sqrt_t * d_act.max())
    null_rc = (sqrt_t * (boot_act - d_act[None, :])).max(axis=1)
    p_rc = (1.0 + float((null_rc >= stat_rc).sum())) / (n_bootstrap + 1.0)

    # Hansen's SPA, consistent recentering: studentize by the bootstrap sd of sqrt(T) * mean, and
    # let a hopeless candidate (studentized mean below -sqrt(2 log log T)) keep its own mean
    omega = (sqrt_t * boot_act).std(axis=0, ddof=1)
    omega = np.maximum(omega, 1e-300)
    studentized = sqrt_t * d_act / omega
    stat_spa = float(max(0.0, studentized.max()))
    threshold = math.sqrt(2.0 * math.log(math.log(max(n_per, 3))))
    centre = np.where(studentized <= -threshold, d_act, 0.0)
    null_spa = np.maximum(
        0.0,
        (sqrt_t * (boot_act - d_act[None, :] + centre[None, :]) / omega[None, :]).max(axis=1),
    )
    p_spa = (1.0 + float((null_spa >= stat_spa).sum())) / (n_bootstrap + 1.0)

    best_local = int(np.argmax(d_act))
    best_row = x[act[best_local]]
    std = float(best_row.std(ddof=1))
    return RealityCheckResult(
        kind=KIND,
        n_candidates=n_cand,
        n_active=int(active.sum()),
        n_periods=n_per,
        n_bootstrap=n_bootstrap,
        mean_block=float(block),
        best_index=int(act[best_local]),
        best_mean_per_period=float(d_act[best_local]),
        best_sharpe_per_period=float(d_act[best_local] / std) if std > 0 else 0.0,
        statistic_rc=stat_rc,
        statistic_spa=stat_spa,
        p_value_rc=p_rc,
        p_value_spa=p_spa,
    )
