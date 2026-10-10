"""Factor regression (ADR-0020): OLS of a strategy's
per-period returns on a set of already-aligned factor return series,
reporting alpha (the intercept -- return unexplained by the factors), its
t-statistic, and each factor's loading (beta).

Pure statistics: takes an explicit ``factors`` mapping of per-period factor
returns, already aligned to ``returns``. A "user-supplied factor files" setup
(market/size/value/momentum/quality/low-vol) is a data-ingestion concern
this module doesn't implement -- factor files are supplied on the command
line (`crucible validate --factors`, ADR-0022).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np

from crucible.core.errors import ConfigurationError, CrucibleError

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence


@dataclass(frozen=True, slots=True)
class FactorRegressionResult:
    """``alpha``/``loadings`` are per-period (never annualized, matching
    DSR's convention -- ADR-0015). ``alpha_t_stat`` tests whether alpha is
    distinguishable from zero given this sample; no p-value is reported
    (would need a t-distribution CDF, not available without a new
    dependency -- AGENTS.md §9)."""

    alpha: float
    alpha_t_stat: float
    loadings: dict[str, float]
    r_squared: float
    n_obs: int


def factor_regression(
    returns: Sequence[float], factors: Mapping[str, Sequence[float]]
) -> FactorRegressionResult:
    if len(factors) == 0:
        msg = "factor_regression needs at least one factor return series"
        raise ConfigurationError(msg)
    y = np.asarray(returns, dtype=np.float64)
    n = len(y)
    names = sorted(factors)  # deterministic column order, independent of dict insertion order
    columns = [np.asarray(factors[name], dtype=np.float64) for name in names]
    for name, col in zip(names, columns, strict=True):
        if len(col) != n:
            msg = (
                f"factor {name!r} has {len(col)} observations, expected {n} "
                "(same length as returns)"
            )
            raise ConfigurationError(msg)

    k = 1 + len(names)  # intercept + factors
    if n <= k:
        msg = (
            f"factor_regression needs n_obs > n_factors + 1 (intercept); "
            f"got n_obs={n}, n_factors={len(names)}"
        )
        raise ConfigurationError(msg)

    design = np.column_stack([np.ones(n), *columns])
    try:
        xtx_inv = np.linalg.inv(design.T @ design)
    except np.linalg.LinAlgError as exc:
        msg = (
            "factor design matrix is singular -- factors are perfectly "
            "collinear, or there are too few observations relative to "
            "the number of factors"
        )
        raise ConfigurationError(msg) from exc

    beta = xtx_inv @ design.T @ y
    residuals = y - design @ beta
    ssr = float(residuals @ residuals)
    sst = float(((y - y.mean()) ** 2).sum())
    # Exact zero residual variance is essentially unreachable in float64
    # (matrix inversion leaves ~1e-30-scale noise even for an exact fit),
    # so a relative tolerance -- comfortably above machine epsilon, far
    # below any non-degenerate residual variance -- catches the case an
    # exact-equality check would silently miss, leaving a nonsense
    # astronomically large t-stat instead of refusing (pessimism rule,
    # AGENTS.md §10).
    if sst == 0.0 or ssr <= 1e-12 * sst:
        msg = (
            "residual variance is numerically zero relative to the data "
            "(a perfect or degenerate in-sample fit); alpha's t-statistic "
            "is not meaningful"
        )
        raise CrucibleError(msg)

    dof = n - k
    sigma2 = ssr / dof
    se_alpha = float(np.sqrt(xtx_inv[0, 0] * sigma2))
    alpha = float(beta[0])
    r_squared = 1.0 - ssr / sst
    return FactorRegressionResult(
        alpha=alpha,
        alpha_t_stat=alpha / se_alpha,
        loadings=dict(zip(names, (float(b) for b in beta[1:]), strict=True)),
        r_squared=r_squared,
        n_obs=n,
    )
