"""Property: drop_ratio is scale-invariant (it's a relative measure), and a
perfectly flat surface always reads as a plateau with drop_ratio == 0
(ADR-0016)."""

from __future__ import annotations

from hypothesis import given
from hypothesis import strategies as st

from crucible.validation.sensitivity import sensitivity_surface_1d

_nonzero = st.floats(
    min_value=0.01, max_value=100.0, allow_nan=False, allow_infinity=False
) | st.floats(min_value=-100.0, max_value=-0.01, allow_nan=False, allow_infinity=False)


@given(
    metric_values=st.lists(
        st.floats(min_value=-10.0, max_value=10.0, allow_nan=False, allow_infinity=False),
        min_size=5,
        max_size=5,
        # Excludes the chosen point (index 2): a near-zero denominator
        # amplifies float error regardless of the ratio formula's
        # correctness -- this is ill-conditioning, not a logic bug.
    ).filter(lambda vs: abs(vs[2]) > 0.1),
    scale=st.floats(min_value=0.01, max_value=100.0, allow_nan=False, allow_infinity=False),
)
def test_drop_ratio_is_invariant_to_positive_scaling(
    metric_values: list[float], scale: float
) -> None:
    param_values = [0, 10, 20, 30, 40]
    baseline = sensitivity_surface_1d(param_values, metric_values, chosen_index=2)
    scaled_metrics = [v * scale for v in metric_values]
    scaled = sensitivity_surface_1d(param_values, scaled_metrics, chosen_index=2)
    assert abs(scaled.drop_ratio - baseline.drop_ratio) < 1e-9


@given(value=_nonzero)
def test_a_perfectly_flat_surface_is_always_a_plateau(value: float) -> None:
    result = sensitivity_surface_1d([0, 10, 20], [value, value, value], chosen_index=1)
    assert result.drop_ratio == 0.0
    assert result.classification == "plateau"
