"""Built-in PortfolioConstructors against hand-computed weights (ADR-0029).

Volatility fixture trick used throughout: a 3-point series ``[x-d, x,
x+d]`` has sample stdev (ddof=1) *exactly* ``d`` -- mean = x, deviations
= (-d, 0, d), sum of squares = 2d^2, /(n-1=2) = d^2, sqrt = d. This gives
exact decimal expectations without rounding.
"""

from __future__ import annotations

from decimal import Decimal

import numpy as np
import pytest

from crucible.core.errors import ConfigurationError
from crucible.core.types import Currency, Symbol, TimestampNs
from crucible.portfolio.constructors import (
    EqualWeightConstructor,
    FixedFractionalConstructor,
    FractionalKellyConstructor,
    MeanVarianceConstructor,
    RiskParityConstructor,
    VolTargetConstructor,
)

A = Symbol("A")
B = Symbol("B")
C = Symbol("C")
D = Symbol("D")
USD = Currency("USD")


class _NoPortfolio:
    """A constructor never reads the portfolio; a stub is enough to
    satisfy the Protocol shape without a real ledger/snapshot."""

    ts = TimestampNs(0)

    def cash(self, currency: Currency) -> Decimal:
        return Decimal("0")

    def available_cash(self, currency: Currency) -> Decimal:
        return Decimal("0")

    def position(self, symbol: Symbol) -> None:
        return None

    def positions(self) -> dict[Symbol, object]:
        return {}

    def equity(self, base_currency: Currency) -> Decimal:
        return Decimal("0")

    def mark(self, symbol: Symbol) -> None:
        return None


PF = _NoPortfolio()
AS_OF = TimestampNs(0)


# ------------------------------------------------------------- EqualWeight


def test_equal_weight_splits_evenly_among_positive_signals() -> None:
    c = EqualWeightConstructor()
    weights = c.construct({A: 3.0, B: 1.0, C: -0.5, D: 2.0}, PF, AS_OF)
    assert weights == {A: pytest.approx(1 / 3), B: pytest.approx(1 / 3), D: pytest.approx(1 / 3)}


def test_equal_weight_top_k_keeps_the_highest_signals() -> None:
    c = EqualWeightConstructor(top_k=2)
    weights = c.construct({A: 3.0, B: 1.0, C: -0.5, D: 2.0}, PF, AS_OF)
    assert weights == {A: 0.5, D: 0.5}


def test_equal_weight_ties_break_by_symbol_ascending() -> None:
    c = EqualWeightConstructor(top_k=1)
    weights = c.construct({B: 1.0, A: 1.0}, PF, AS_OF)
    assert weights == {A: 1.0}


def test_equal_weight_no_candidates_is_empty() -> None:
    c = EqualWeightConstructor()
    assert c.construct({A: -1.0, B: 0.0}, PF, AS_OF) == {}


# --------------------------------------------------------- FixedFractional


def test_fixed_fractional_gives_every_candidate_the_same_fraction() -> None:
    c = FixedFractionalConstructor(fraction=0.2)
    weights = c.construct({A: 1.0, B: 2.0, C: -1.0}, PF, AS_OF)
    assert weights == {A: 0.2, B: 0.2}


def test_fixed_fractional_rejects_out_of_range_fraction() -> None:
    with pytest.raises(ConfigurationError):
        FixedFractionalConstructor(fraction=0.0)
    with pytest.raises(ConfigurationError):
        FixedFractionalConstructor(fraction=1.5)


# --------------------------------------------------------------- VolTarget


def test_vol_target_sizes_inversely_to_volatility() -> None:
    c = VolTargetConstructor(target_vol=0.02, max_weight=5.0)
    history = {A: [0.09, 0.10, 0.11], B: [0.08, 0.10, 0.12]}  # stdev 0.01, 0.02
    weights = c.construct({A: 1.0, B: 1.0}, PF, AS_OF, history=history)
    assert weights == {A: pytest.approx(2.0), B: pytest.approx(1.0)}


def test_vol_target_caps_at_max_weight() -> None:
    c = VolTargetConstructor(target_vol=0.02, max_weight=1.0)
    history = {A: [0.09, 0.10, 0.11], B: [0.08, 0.10, 0.12]}
    weights = c.construct({A: 1.0, B: 1.0}, PF, AS_OF, history=history)
    assert weights == {A: pytest.approx(1.0), B: pytest.approx(1.0)}


def test_vol_target_requires_history() -> None:
    c = VolTargetConstructor(target_vol=0.02)
    with pytest.raises(ConfigurationError, match="needs return history"):
        c.construct({A: 1.0}, PF, AS_OF, history=None)


def test_vol_target_requires_at_least_two_points() -> None:
    c = VolTargetConstructor(target_vol=0.02)
    with pytest.raises(ConfigurationError, match="need >= 2"):
        c.construct({A: 1.0}, PF, AS_OF, history={A: [0.1]})


def test_vol_target_rejects_non_positive_target() -> None:
    with pytest.raises(ConfigurationError):
        VolTargetConstructor(target_vol=0.0)


# -------------------------------------------------------------- RiskParity


def test_risk_parity_weights_are_inverse_vol_normalized() -> None:
    c = RiskParityConstructor()
    history = {A: [0.09, 0.10, 0.11], B: [0.08, 0.10, 0.12]}  # stdev 0.01, 0.02
    weights = c.construct({A: 1.0, B: 1.0}, PF, AS_OF, history=history)
    # inv_A=100, inv_B=50, total=150
    assert weights[A] == pytest.approx(100 / 150)
    assert weights[B] == pytest.approx(50 / 150)
    assert sum(weights.values()) == pytest.approx(1.0)


def test_risk_parity_caps_can_break_the_sum_to_one_property() -> None:
    c = RiskParityConstructor(max_weight=0.5)
    history = {A: [0.09, 0.10, 0.11], B: [0.08, 0.10, 0.12]}
    weights = c.construct({A: 1.0, B: 1.0}, PF, AS_OF, history=history)
    assert weights[A] == pytest.approx(0.5)  # capped down from 2/3
    assert weights[B] == pytest.approx(1 / 3)  # unaffected, already below cap
    assert sum(weights.values()) < 1.0


# ---------------------------------------------------------- FractionalKelly


def test_fractional_kelly_scales_return_by_inverse_variance() -> None:
    c = FractionalKellyConstructor(kelly_fraction=0.5)
    history = {A: [0.0, 0.10, 0.20]}  # stdev 0.10, variance 0.01
    weights = c.construct({A: 0.01}, PF, AS_OF, history=history)
    assert weights[A] == pytest.approx(0.5)  # 0.5 * 0.01 / 0.01


def test_fractional_kelly_caps_at_max_weight() -> None:
    c = FractionalKellyConstructor(kelly_fraction=0.5, max_weight=1.0)
    history = {A: [0.0, 0.10, 0.20]}
    weights = c.construct({A: 0.05}, PF, AS_OF, history=history)
    assert weights[A] == pytest.approx(1.0)  # raw 2.5, capped


def test_fractional_kelly_rejects_non_positive_fraction() -> None:
    with pytest.raises(ConfigurationError):
        FractionalKellyConstructor(kelly_fraction=0.0)


# --------------------------------------------------------- MeanVariance


def test_mean_variance_single_symbol_matches_scalar_tangency_solution() -> None:
    c = MeanVarianceConstructor(risk_aversion=1.0, ridge=0.0)
    history = {A: [0.09, 0.10, 0.11]}  # variance 0.0001
    weights = c.construct({A: 0.00005}, PF, AS_OF, history=history)
    assert weights[A] == pytest.approx(0.5)  # 0.00005 / 0.0001


def test_mean_variance_two_symbols_solves_the_covariance_system() -> None:
    # devA = [-1, 0, 1] * 0.01; devB = [1, 1, -2] * 0.01 (mean-centered,
    # both sum to 0). var(A)=0.0001, var(B)=0.0003, cov(A,B)=-0.00015
    # (hand-computed: see module docstring for the general pattern).
    history = {A: [0.09, 0.10, 0.11], B: [0.11, 0.11, 0.08]}
    mu = {A: 0.0002, B: 0.0001}
    c = MeanVarianceConstructor(risk_aversion=2.0, ridge=0.0, max_weight=10.0)
    weights = c.construct(mu, PF, AS_OF, history=history)

    # Verify the defining property directly: Sigma @ w == mu / risk_aversion.
    cov = np.cov(np.array([history[A], history[B]], dtype=float), ddof=1)
    w = np.array([weights[A], weights[B]])
    lhs = cov @ w
    rhs = np.array([mu[A], mu[B]]) / c.risk_aversion
    assert lhs == pytest.approx(rhs, abs=1e-9)


def test_mean_variance_clips_to_box_constraints() -> None:
    c = MeanVarianceConstructor(risk_aversion=1.0, ridge=0.0, max_weight=0.3)
    history = {A: [0.09, 0.10, 0.11]}  # variance 0.0001
    weights = c.construct({A: 0.00005}, PF, AS_OF, history=history)  # raw 0.5
    assert weights[A] == pytest.approx(0.3)


def test_mean_variance_rejects_misaligned_history_lengths() -> None:
    c = MeanVarianceConstructor()
    history = {A: [0.09, 0.10, 0.11], B: [0.08, 0.10, 0.12, 0.14]}
    with pytest.raises(ConfigurationError, match="equal-length"):
        c.construct({A: 0.01, B: 0.01}, PF, AS_OF, history=history)


def test_mean_variance_rejects_bad_bounds() -> None:
    with pytest.raises(ConfigurationError):
        MeanVarianceConstructor(min_weight=0.5, max_weight=0.1)
