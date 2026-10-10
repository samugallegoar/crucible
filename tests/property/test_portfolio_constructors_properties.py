"""Properties that must hold for arbitrary signals/history (ADR-0029): every constructor's output
stays within its own declared
bounds, and never selects a non-positive-signal symbol."""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from crucible.core.types import Symbol, TimestampNs
from crucible.portfolio.constructors import (
    EqualWeightConstructor,
    FixedFractionalConstructor,
    FractionalKellyConstructor,
    MeanVarianceConstructor,
    RiskParityConstructor,
    VolTargetConstructor,
)

SYMBOLS = [Symbol(s) for s in ("AAA", "BBB", "CCC", "DDD")]
AS_OF = TimestampNs(0)


class _NoPortfolio:
    pass


PF = _NoPortfolio()

signals_st = st.dictionaries(
    st.sampled_from(SYMBOLS),
    st.floats(min_value=-5.0, max_value=5.0, allow_nan=False, allow_infinity=False),
    min_size=1,
    max_size=4,
)

# non-degenerate return series: at least 2 points, some spread, no NaN/inf
series_st = st.lists(
    st.floats(min_value=-1.0, max_value=1.0, allow_nan=False, allow_infinity=False),
    min_size=2,
    max_size=6,
).filter(lambda xs: len(set(xs)) > 1)


@given(signals_st)
def test_equal_weight_only_selects_positive_signals_and_sums_to_one(
    signals: dict[Symbol, float],
) -> None:
    weights = EqualWeightConstructor().construct(signals, PF, AS_OF)
    assert all(signals[s] > 0 for s in weights)
    if weights:
        assert abs(sum(weights.values()) - 1.0) < 1e-9


@given(signals_st, st.floats(min_value=0.01, max_value=1.0))
def test_fixed_fractional_never_exceeds_its_fraction(
    signals: dict[Symbol, float], fraction: float
) -> None:
    weights = FixedFractionalConstructor(fraction=fraction).construct(signals, PF, AS_OF)
    assert all(signals[s] > 0 for s in weights)
    assert all(w == fraction for w in weights.values())


def _history_for(signals: dict[Symbol, float], series: list[float]) -> dict[Symbol, list[float]]:
    return {s: series for s in signals if signals[s] > 0}


@settings(deadline=None)
@given(signals_st, series_st, st.floats(min_value=1.0, max_value=10.0))
def test_vol_target_never_exceeds_max_weight(
    signals: dict[Symbol, float], series: list[float], max_weight: float
) -> None:
    history = _history_for(signals, series)
    weights = VolTargetConstructor(target_vol=0.05, max_weight=max_weight).construct(
        signals, PF, AS_OF, history=history
    )
    assert all(0 < w <= max_weight + 1e-9 for w in weights.values())


@settings(deadline=None)
@given(signals_st, series_st)
def test_risk_parity_weights_are_non_negative_and_bounded_by_one(
    signals: dict[Symbol, float], series: list[float]
) -> None:
    history = _history_for(signals, series)
    weights = RiskParityConstructor().construct(signals, PF, AS_OF, history=history)
    assert all(0 < w <= 1.0 + 1e-9 for w in weights.values())
    if weights:
        assert sum(weights.values()) <= 1.0 + 1e-9


@settings(deadline=None)
@given(signals_st, series_st, st.floats(min_value=0.01, max_value=1.0))
def test_fractional_kelly_stays_within_bounds(
    signals: dict[Symbol, float], series: list[float], max_weight: float
) -> None:
    history = _history_for(signals, series)
    weights = FractionalKellyConstructor(kelly_fraction=0.5, max_weight=max_weight).construct(
        signals, PF, AS_OF, history=history
    )
    assert all(0.0 <= w <= max_weight + 1e-9 for w in weights.values())


@settings(deadline=None)
@given(signals_st, series_st)
def test_mean_variance_clips_within_box_constraints(
    signals: dict[Symbol, float], series: list[float]
) -> None:
    history = _history_for(signals, series)
    c = MeanVarianceConstructor(min_weight=0.0, max_weight=1.0)
    weights = c.construct(signals, PF, AS_OF, history=history)
    assert all(-1e-9 <= w <= 1.0 + 1e-9 for w in weights.values())
