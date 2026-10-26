"""Headline metrics with uncertainty (AGENTS.md §9).

Estimates (Sharpe, CAGR, max drawdown) carry circular-block-bootstrap
confidence intervals; identities (fees, trade counts) carry none. The
bootstrap takes an explicit seeded ``numpy.random.Generator`` — metric CIs
are part of the deterministic output.

Conventions: risk-free rate is 0 (documented); annualization uses the caller's ``periods_per_year``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
import polars as pl

from crucible.analytics.interfaces import MetricValue
from crucible.core.drawdown import max_drawdown, max_drawdown_from_returns
from crucible.core.errors import CrucibleError
from crucible.core.stats import is_degenerate_returns

if TYPE_CHECKING:
    from collections.abc import Callable

    from numpy.typing import NDArray

N_BOOTSTRAP = 1_000
CI_LEVEL = 0.95


def _sharpe(returns: NDArray[np.float64], periods_per_year: float) -> float:
    if is_degenerate_returns(returns):
        return 0.0
    return float(returns.mean() / returns.std(ddof=1) * np.sqrt(periods_per_year))


def _cagr(returns: NDArray[np.float64], periods_per_year: float) -> float:
    growth = float(np.prod(1.0 + returns))
    if growth <= 0.0:
        return -1.0
    years = len(returns) / periods_per_year
    return float(growth ** (1.0 / years) - 1.0) if years > 0 else 0.0


def _volatility(returns: NDArray[np.float64], periods_per_year: float) -> float:
    """Annualized standard deviation; 0.0 for a degenerate series (no dispersion to report)."""
    if is_degenerate_returns(returns):
        return 0.0
    return float(returns.std(ddof=1) * np.sqrt(periods_per_year))


def _block_bootstrap_ci(
    returns: NDArray[np.float64],
    stat: Callable[[NDArray[np.float64]], float],
    rng: np.random.Generator,
) -> tuple[float, float]:
    """Circular block bootstrap; block length ~ sqrt(n)."""
    n = len(returns)
    block = max(1, int(np.sqrt(n)))
    n_blocks = -(-n // block)
    samples = np.empty(N_BOOTSTRAP)
    for i in range(N_BOOTSTRAP):
        starts = rng.integers(0, n, size=n_blocks)
        idx = (starts[:, None] + np.arange(block)[None, :]).ravel()[:n] % n
        samples[i] = stat(returns[idx])
    alpha = (1.0 - CI_LEVEL) / 2.0
    return (
        float(np.quantile(samples, alpha)),
        float(np.quantile(samples, 1.0 - alpha)),
    )


def simple_returns(equity: pl.DataFrame) -> NDArray[np.float64]:
    """Equity frame: ``ts`` (int ns) + ``equity`` (base-ccy float), one row
    per mark. Shared by :func:`compute_metrics` and DSR (``validation.dsr``,
    ADR-0015) so both operate on the identical per-period return series."""
    if equity.height < 3:
        msg = f"cannot compute returns from {equity.height} equity points; need >= 3"
        raise CrucibleError(msg)
    values = equity.sort("ts").get_column("equity").to_numpy()
    if np.any(values <= 0):
        msg = "equity curve crosses zero or negative; metrics are meaningless past ruin"
        raise CrucibleError(msg)
    returns: NDArray[np.float64] = values[1:] / values[:-1] - 1.0
    return returns


def compute_metrics(
    equity: pl.DataFrame,
    trades: pl.DataFrame,
    *,
    rng: np.random.Generator,
    periods_per_year: float,
) -> dict[str, MetricValue]:
    """``trades`` from :mod:`crucible.analytics.trades`."""
    returns = simple_returns(equity)
    values = equity.sort("ts").get_column("equity").to_numpy()

    sharpe_ci = _block_bootstrap_ci(returns, lambda r: _sharpe(r, periods_per_year), rng)
    cagr_ci = _block_bootstrap_ci(returns, lambda r: _cagr(r, periods_per_year), rng)
    # the point estimate and every bootstrap resample use the same definition: a path that
    # starts at the initial capital (1.0 for a resample), ADR-0071
    max_dd_ci = _block_bootstrap_ci(returns, max_drawdown_from_returns, rng)

    out: dict[str, MetricValue] = {
        "sharpe": MetricValue(_sharpe(returns, periods_per_year), *sharpe_ci),
        "cagr": MetricValue(_cagr(returns, periods_per_year), *cagr_ci),
        "volatility": MetricValue(
            _volatility(returns, periods_per_year),
            None,
            None,
        ),
        "max_drawdown": MetricValue(max_drawdown(values), *max_dd_ci),
        "n_periods": MetricValue(float(len(returns)), None, None),
    }
    if trades.height:
        pnl = trades.get_column("pnl").to_numpy()
        out["n_trades"] = MetricValue(float(trades.height), None, None)
        out["hit_rate"] = MetricValue(float((pnl > 0).mean()), None, None)
    else:
        out["n_trades"] = MetricValue(0.0, None, None)
    return out
