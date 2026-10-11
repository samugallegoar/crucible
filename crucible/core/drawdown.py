"""Maximum drawdown: one definition for the point estimate and every resample (ADR-0071).

Convention: drawdown at time ``t`` is ``equity[t] / max(equity[0..t]) - 1``; the maximum
drawdown is its minimum over the path, a number in ``(-1, 0]`` (0 for a path that never falls
below an earlier peak). The path always **includes its starting value**: an equity curve starts
at the initial capital, and a return series is turned into a path that starts at 1.0 before the
first return. An earlier reconstruction (``cumprod(1 + returns)`` with no starting 1.0) dropped
the first period's loss, so ``[-0.10, 0.10]`` scored 0 % instead of -10 %, and the bootstrap
interval targeted a different statistic than the point estimate it was printed next to.

Invalid input is refused, never repaired: a non-finite value, a non-positive equity value, or a
return of -100 % or worse (the account is ruined; drawdown past ruin is meaningless, the same
rule as ``analytics.metrics.simple_returns``).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

from crucible.core.errors import CrucibleError

if TYPE_CHECKING:
    from numpy.typing import ArrayLike


def max_drawdown(equity: ArrayLike) -> float:
    """Maximum drawdown of an equity path (its first value is the starting capital).
    Refuses an empty path, non-finite values and non-positive equity."""
    path = np.asarray(equity, dtype=np.float64)
    if path.ndim != 1 or path.size == 0:
        msg = f"max_drawdown needs a non-empty 1-D equity path, got shape {path.shape}"
        raise CrucibleError(msg)
    if not np.all(np.isfinite(path)):
        msg = "max_drawdown: the equity path has NaN or infinite values"
        raise CrucibleError(msg)
    if np.any(path <= 0.0):
        msg = (
            "max_drawdown: the equity path reaches zero or below; drawdown is meaningless past ruin"
        )
        raise CrucibleError(msg)
    peaks = np.maximum.accumulate(path)
    return float(min(0.0, float(((path - peaks) / peaks).min())))


def max_drawdown_from_returns(returns: ArrayLike) -> float:
    """Maximum drawdown of the path ``1.0, (1 + r_1), (1 + r_1)(1 + r_2), ...``: the starting
    value is part of the path, so a first-period loss counts. An empty series is the path
    ``[1.0]`` (drawdown 0). Refuses non-finite returns and returns of -100 % or worse."""
    r = np.asarray(returns, dtype=np.float64)
    if r.ndim != 1:
        msg = f"max_drawdown_from_returns needs a 1-D return series, got shape {r.shape}"
        raise CrucibleError(msg)
    if not np.all(np.isfinite(r)):
        msg = "max_drawdown_from_returns: the return series has NaN or infinite values"
        raise CrucibleError(msg)
    if np.any(r <= -1.0):
        msg = (
            "max_drawdown_from_returns: a return of -100% or worse ruins the account; drawdown "
            "is meaningless past ruin"
        )
        raise CrucibleError(msg)
    return max_drawdown(np.concatenate(([1.0], np.cumprod(1.0 + r))))
