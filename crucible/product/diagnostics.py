"""Evidence diagnostics behind the results table (ADR-0077): what survives costs, per trade, and
against simply holding the benchmark.

Everything here is a pure function of arrays the one-step backtest already has. Units: basis points
(bps) of traded notional for costs and per-trade returns, percent for annual returns. Timing: the
inputs are the finished run's returns, so nothing here is knowable before the run ends.

Pessimism: costs are the run's own assumption, a trade's net return subtracts a full round trip
(entry and exit), and a confidence range that cannot be computed is ``None``, not a guess.
"""

from __future__ import annotations

import math

import numpy as np

_Z95 = 1.959964
MIN_ALPHA_BARS = 30
"""Fewer bars than this and a regression's t-statistic is not worth reporting."""


def annual_return_pct(final: float, capital: float, years: float) -> float:
    """Compound annual growth, in percent, from the start and end of an equity curve."""
    if years <= 0 or capital <= 0 or final <= 0:
        return -100.0 if final <= 0 else 0.0
    growth: float = (final / capital) ** (1.0 / years)
    return (growth - 1.0) * 100.0


def break_even_bps(
    gross_returns: np.ndarray, net_returns: np.ndarray, assumed_bps_per_side: float
) -> float | None:
    """The cost per side, in bps, at which the mean per-bar return reaches zero.

    The engine charges ``turnover x (slippage + commission)`` each bar, so the net return is
    linear in the cost rate: ``mean(net) = mean(gross) - rate x mean(turnover)``. Returns ``None``
    when no cost was assumed or nothing was traded (the rate cannot be scaled), ``0.0`` when the
    rules lose money before any cost.
    """
    if assumed_bps_per_side <= 0 or gross_returns.size == 0:
        return None
    mean_gross = float(np.mean(gross_returns))
    mean_cost = float(np.mean(gross_returns - net_returns))
    if mean_cost <= 0:
        return None
    if mean_gross <= 0:
        return 0.0
    return assumed_bps_per_side * mean_gross / mean_cost


STRESS_MULTIPLIERS: tuple[float, ...] = (1.0, 2.0, 3.0, 5.0)
"""Cost multiples of the grid: the assumed cost, then 2x, 3x and 5x of it."""


def cost_stress(
    gross_returns: np.ndarray,
    net_returns: np.ndarray,
    capital: float,
    years: float,
    periods_per_year: float,
    multipliers: tuple[float, ...] = STRESS_MULTIPLIERS,
) -> list[dict[str, float | None]]:
    """The run re-priced at several multiples of its own costs, without re-running it.

    The engine charges ``turnover x (slippage + commission)`` each bar, so the net return of a
    bar at ``k`` times the costs is exactly ``gross - k * (gross - net)``; compounding that gives
    the final equity and annual return, and the annualized Sharpe uses the same formula as the
    headline metrics. Returns one row per multiplier with ``sharpe``, ``cagr_pct`` and
    ``final_equity`` (``None`` for a row that would lose everything). It is a *linear* stress: it
    scales the assumed cost per unit traded, so it does not model costs that rise with size or in
    a fast market, and it holds the trades fixed.
    """
    cost = gross_returns - net_returns
    rows: list[dict[str, float | None]] = []
    for k in multipliers:
        stressed = gross_returns - k * cost
        if stressed.size == 0 or np.any(stressed <= -1.0):
            rows.append({"multiplier": k, "sharpe": None, "cagr_pct": None, "final_equity": None})
            continue
        final = float(capital * np.prod(1.0 + stressed))
        degenerate = stressed.size < 2 or float(np.std(stressed, ddof=1)) == 0.0
        sharpe = (
            0.0
            if degenerate
            else float(stressed.mean() / stressed.std(ddof=1) * math.sqrt(periods_per_year))
        )
        rows.append(
            {
                "multiplier": k,
                "sharpe": sharpe,
                "cagr_pct": annual_return_pct(final, capital, years),
                "final_equity": final,
            }
        )
    return rows


def turnover_per_year(abs_weight_changes: float, years: float) -> float | None:
    """Traded notional per year as a multiple of capital (absolute weight changes / years)."""
    return None if years <= 0 else abs_weight_changes / years


def trade_stats(net_bps: list[float]) -> dict[str, float | int | None]:
    """Per-trade statistics from each trade's net return on deployed notional, in bps.

    ``expectancy`` is the mean with a normal 95% range (trades treated as independent, which is
    generous for overlapping positions); ``profit_factor`` is gross wins over gross losses and
    ``payoff_ratio`` the average win over the average loss, both ``None`` when one side is empty.
    """
    n = len(net_bps)
    out: dict[str, float | int | None] = {
        "n": n,
        "expectancy_bps": None,
        "expectancy_low_bps": None,
        "expectancy_high_bps": None,
        "win_rate_pct": None,
        "profit_factor": None,
        "payoff_ratio": None,
    }
    if n == 0:
        return out
    values = np.asarray(net_bps, dtype=float)
    wins, losses = values[values > 0], values[values < 0]
    out["expectancy_bps"] = float(values.mean())
    out["win_rate_pct"] = 100.0 * float(wins.size) / n
    if n >= 2:
        half = _Z95 * float(values.std(ddof=1)) / math.sqrt(n)
        out["expectancy_low_bps"] = float(values.mean()) - half
        out["expectancy_high_bps"] = float(values.mean()) + half
    if losses.size:
        out["profit_factor"] = float(wins.sum() / -losses.sum())
        if wins.size:
            out["payoff_ratio"] = float(wins.mean() / -losses.mean())
    return out


def alpha_beta(
    strategy: np.ndarray, benchmark: np.ndarray, periods_per_year: float
) -> dict[str, float | int | None]:
    """OLS of the strategy's per-bar returns on the benchmark's: beta, annual alpha, its t-stat.

    The t-statistic uses Newey-West (Bartlett) standard errors, because bar returns of a position
    strategy are autocorrelated. ``alpha_annual_pct`` is the arithmetic per-bar alpha times the
    bars per year. All ``None`` when there are too few bars or the benchmark never moves.
    """
    n = int(strategy.size)
    empty: dict[str, float | int | None] = {
        "n": n,
        "alpha_annual_pct": None,
        "alpha_t": None,
        "beta": None,
    }
    if n < MIN_ALPHA_BARS or n != benchmark.size or float(np.var(benchmark)) <= 0:
        return empty
    x = np.column_stack([np.ones(n), benchmark])
    coef, *_ = np.linalg.lstsq(x, strategy, rcond=None)
    resid = strategy - x @ coef
    lags = math.floor(4.0 * (n / 100.0) ** (2.0 / 9.0))
    xe = x * resid[:, None]
    meat = xe.T @ xe
    for lag in range(1, lags + 1):
        weight = 1.0 - lag / (lags + 1.0)
        gamma = xe[lag:].T @ xe[:-lag]
        meat += weight * (gamma + gamma.T)
    bread = np.linalg.inv(x.T @ x)
    cov = bread @ meat @ bread
    se_alpha = math.sqrt(max(float(cov[0, 0]), 0.0))
    alpha_bar = float(coef[0])
    return {
        "n": n,
        "alpha_annual_pct": alpha_bar * periods_per_year * 100.0,
        "alpha_t": None if se_alpha == 0 else alpha_bar / se_alpha,
        "beta": float(coef[1]),
    }
