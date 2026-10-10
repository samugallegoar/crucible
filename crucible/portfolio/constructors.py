"""Built-in ``PortfolioConstructor``s (ADR-0029).

Selection convention shared by all six: ``signals[symbol] > 0`` marks a
long candidate (constructors are long-only). Constructors
that size by expected-return/volatility read the signal's *magnitude* as
the expected-return input; ``EqualWeightConstructor`` and
``FixedFractionalConstructor`` only use it to rank/select.

Two size-aware treatments, both documented simplifications rather than a
full covariance-aware optimizer everywhere (no scipy/cvxpy dependency,
CLAUDE.md's core-library list):
- **Diagonal** (``VolTargetConstructor``, ``RiskParityConstructor``,
  ``FractionalKellyConstructor``): each symbol's own variance only,
  correlation ignored. This is inverse-volatility risk parity, not the
  fully correlation-aware equal-risk-contribution solution.
- **Correlation-aware** (``MeanVarianceConstructor``): the full sample
  covariance matrix via ``numpy.linalg.solve`` (no QP solver, so box
  constraints are applied by clipping the unconstrained tangency
  solution, not a true active-set optimization).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np

from crucible.core.errors import ConfigurationError

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from crucible.accounting.interfaces import PortfolioView
    from crucible.core.types import Symbol, TimestampNs

_MIN_VOL = 1e-9


def _select(signals: Mapping[Symbol, float], top_k: int | None) -> list[Symbol]:
    """Long candidates (``signal > 0``), ranked by signal descending,
    ties broken by symbol for determinism; ``top_k`` truncates."""
    candidates = sorted((s for s, v in signals.items() if v > 0), key=lambda s: (-signals[s], s))
    return candidates if top_k is None else candidates[:top_k]


def _history_for(
    symbol: Symbol, history: Mapping[Symbol, Sequence[float]] | None, constructor: str
) -> Sequence[float]:
    if history is None or symbol not in history:
        msg = (
            f"{constructor} needs return history for {symbol} (ADR-0029) -- "
            "pass `history` computed via the strategy's own PIT accessor"
        )
        raise ConfigurationError(msg)
    series = history[symbol]
    if len(series) < 2:
        msg = f"{constructor}: history for {symbol} has {len(series)} points, need >= 2"
        raise ConfigurationError(msg)
    return series


def _vol(series: Sequence[float]) -> float:
    """Sample stdev (``ddof=1``), floored to avoid a zero denominator."""
    return max(float(np.std(np.asarray(series, dtype=float), ddof=1)), _MIN_VOL)


@dataclass(frozen=True, slots=True)
class EqualWeightConstructor:
    """1/N across the top ``top_k`` (or all) long candidates by signal."""

    top_k: int | None = None

    def construct(
        self,
        signals: Mapping[Symbol, float],
        portfolio: PortfolioView,
        as_of: TimestampNs,
        history: Mapping[Symbol, Sequence[float]] | None = None,
    ) -> Mapping[Symbol, float]:
        selected = _select(signals, self.top_k)
        if not selected:
            return {}
        weight = 1.0 / len(selected)
        return dict.fromkeys(selected, weight)


@dataclass(frozen=True, slots=True)
class FixedFractionalConstructor:
    """Every long candidate gets the same fixed fraction of equity,
    independent of how many are selected (classic fixed-fractional
    sizing) -- weights need not sum to 1; the remainder is unallocated
    cash."""

    fraction: float
    top_k: int | None = None

    def __post_init__(self) -> None:
        if not 0.0 < self.fraction <= 1.0:
            msg = f"fraction must be in (0, 1], got {self.fraction}"
            raise ConfigurationError(msg)

    def construct(
        self,
        signals: Mapping[Symbol, float],
        portfolio: PortfolioView,
        as_of: TimestampNs,
        history: Mapping[Symbol, Sequence[float]] | None = None,
    ) -> Mapping[Symbol, float]:
        selected = _select(signals, self.top_k)
        return dict.fromkeys(selected, self.fraction)


@dataclass(frozen=True, slots=True)
class VolTargetConstructor:
    """``weight_i = min(target_vol / vol_i, max_weight)`` -- each position
    sized to contribute the same target volatility (diagonal; ignores
    correlation)."""

    target_vol: float
    max_weight: float = 1.0

    def __post_init__(self) -> None:
        if self.target_vol <= 0:
            msg = f"target_vol must be > 0, got {self.target_vol}"
            raise ConfigurationError(msg)

    def construct(
        self,
        signals: Mapping[Symbol, float],
        portfolio: PortfolioView,
        as_of: TimestampNs,
        history: Mapping[Symbol, Sequence[float]] | None = None,
    ) -> Mapping[Symbol, float]:
        selected = _select(signals, None)
        weights: dict[Symbol, float] = {}
        for symbol in selected:
            vol = _vol(_history_for(symbol, history, "VolTargetConstructor"))
            weights[symbol] = min(self.target_vol / vol, self.max_weight)
        return weights


@dataclass(frozen=True, slots=True)
class RiskParityConstructor:
    """Inverse-volatility weighting normalized to sum to 1 across
    selected symbols (diagonal risk parity -- equal risk contribution
    only holds exactly when correlations are zero; the fully
    correlation-aware solution needs an iterative solver, out of scope,
    ADR-0029)."""

    max_weight: float = 1.0

    def construct(
        self,
        signals: Mapping[Symbol, float],
        portfolio: PortfolioView,
        as_of: TimestampNs,
        history: Mapping[Symbol, Sequence[float]] | None = None,
    ) -> Mapping[Symbol, float]:
        selected = _select(signals, None)
        if not selected:
            return {}
        inv_vol = {
            s: 1.0 / _vol(_history_for(s, history, "RiskParityConstructor")) for s in selected
        }
        total = sum(inv_vol.values())
        return {s: min(v / total, self.max_weight) for s, v in inv_vol.items()}


@dataclass(frozen=True, slots=True)
class FractionalKellyConstructor:
    """Per-asset (diagonal) fractional Kelly: ``weight_i = clip(fraction *
    mu_i / var_i, 0, max_weight)`` where ``mu_i`` is the signal (expected
    return) and ``var_i`` the symbol's own return variance -- ignores
    cross-asset covariance (the portfolio-optimal Kelly needs the full
    covariance matrix and its inverse; use ``MeanVarianceConstructor``
    for the correlation-aware treatment)."""

    kelly_fraction: float = 0.5
    max_weight: float = 1.0

    def __post_init__(self) -> None:
        if self.kelly_fraction <= 0:
            msg = f"kelly_fraction must be > 0, got {self.kelly_fraction}"
            raise ConfigurationError(msg)

    def construct(
        self,
        signals: Mapping[Symbol, float],
        portfolio: PortfolioView,
        as_of: TimestampNs,
        history: Mapping[Symbol, Sequence[float]] | None = None,
    ) -> Mapping[Symbol, float]:
        selected = _select(signals, None)
        weights: dict[Symbol, float] = {}
        for symbol in selected:
            variance = _vol(_history_for(symbol, history, "FractionalKellyConstructor")) ** 2
            raw = self.kelly_fraction * signals[symbol] / variance
            weights[symbol] = max(0.0, min(raw, self.max_weight))
        return weights


@dataclass(frozen=True, slots=True)
class MeanVarianceConstructor:
    """Correlation-aware tangency portfolio ``w = (1/risk_aversion) *
    Sigma^-1 @ mu`` (unconstrained closed form, ``numpy.linalg.solve``
    against a ridge-regularized sample covariance for numerical
    stability), then box-constrained by clipping to ``[min_weight,
    max_weight]``. Clipping is a documented approximation of "mean-
    variance with constraints": it keeps every weight legal without a
    QP solver, but the clipped weights are no longer the exact
    constrained optimum (ADR-0029)."""

    risk_aversion: float = 1.0
    min_weight: float = 0.0
    max_weight: float = 1.0
    ridge: float = 1e-6

    def __post_init__(self) -> None:
        if self.risk_aversion <= 0:
            msg = f"risk_aversion must be > 0, got {self.risk_aversion}"
            raise ConfigurationError(msg)
        if self.min_weight > self.max_weight:
            msg = f"min_weight ({self.min_weight}) > max_weight ({self.max_weight})"
            raise ConfigurationError(msg)

    def construct(
        self,
        signals: Mapping[Symbol, float],
        portfolio: PortfolioView,
        as_of: TimestampNs,
        history: Mapping[Symbol, Sequence[float]] | None = None,
    ) -> Mapping[Symbol, float]:
        selected = _select(signals, None)
        if not selected:
            return {}
        series = [_history_for(s, history, "MeanVarianceConstructor") for s in selected]
        lengths = {len(s) for s in series}
        if len(lengths) > 1:
            msg = (
                "MeanVarianceConstructor needs equal-length, aligned history series "
                f"across selected symbols; got lengths {sorted(lengths)}"
            )
            raise ConfigurationError(msg)
        mu = np.array([signals[s] for s in selected], dtype=float)
        returns = np.array(series, dtype=float)
        cov = np.atleast_2d(np.cov(returns, ddof=1))
        cov_reg = cov + self.ridge * np.eye(len(selected))
        raw = np.linalg.solve(cov_reg, mu) / self.risk_aversion
        clipped = np.clip(raw, self.min_weight, self.max_weight)
        return dict(zip(selected, (float(w) for w in clipped), strict=True))
