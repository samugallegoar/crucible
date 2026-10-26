"""Shared statistical primitives on plain arrays.

Why a module: the analytics, validation and experiments layers all need *the same* Sharpe
definition, and the layering rule (``docs/ARCHITECTURE.md``, ``pyproject.toml``) makes those
layers independent siblings that must not import each other. A second estimator with slightly
different degenerate-series handling is exactly the bug this module exists to prevent: the
2026-10 audit found a constant-return strategy reporting a Sharpe of 1.7e14 because one
estimator only caught an *exact* zero standard deviation.

Nothing here touches the engine, the clock or the store: pure functions on arrays.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from numpy.typing import NDArray

DEGENERATE_TOLERANCE = 1e-12
"""Relative spread below which a return series counts as having no dispersion.

500 bars of exactly +0.1% compound to float returns whose standard deviation is ~9.4e-17
relative to a mean of 1e-3: an *exact* ``std == 0.0`` test misses it, and dividing by it
invents a Sharpe of 1.7e14. A genuinely varying series is nowhere near this ratio.
"""


def is_degenerate_returns(returns: NDArray[np.float64]) -> bool:
    """True when the series has no dispersion, so a Sharpe ratio is undefined.

    Covers three cases the caller must not score: an empty series, an all-zero series (a
    strategy that never held anything), and a constant-per-period return whose values differ
    only by float dust. Also true for a non-finite series: NaN/inf is not a return.
    """
    if returns.size == 0:
        return True
    if not np.isfinite(returns).all():
        return True
    scale = float(np.max(np.abs(returns)))
    if scale == 0.0:
        return True
    return float(np.max(returns) - np.min(returns)) <= DEGENERATE_TOLERANCE * scale


def per_period_sharpe(returns: NDArray[np.float64]) -> float:
    """``mean / std``, **per period** (never annualized), 0.0 for a degenerate series.

    Per-period on purpose: the Deflated Sharpe Ratio's derivation couples the Sharpe estimate
    to the observation count and to the higher moments, so annualizing would decouple them
    (ADR-0015). ``ddof=1`` matches ``numpy.std``'s default in the rest of the codebase.
    """
    if is_degenerate_returns(returns):
        return 0.0
    return float(returns.mean() / returns.std(ddof=1))
