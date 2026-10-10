"""Property: factor regression's alpha/loadings behave correctly under an
affine transform of the return series -- a textbook OLS identity, checked
here rather than assumed (ADR-0020)."""

from __future__ import annotations

import numpy as np
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from crucible.core.errors import ConfigurationError, CrucibleError
from crucible.validation.factor_regression import factor_regression

# Values quantized to multiples of 0.01: keeps every draw well-conditioned
# (no denormal-scale variance blow-up in the matrix inverse, the same
# ill-conditioning concern as test_sensitivity_scale_invariance.py's
# near-zero-denominator filter).
_returns = st.lists(
    st.integers(min_value=-50, max_value=50).map(lambda i: i / 100.0),
    min_size=6,
    max_size=6,
)
_factor = st.lists(
    st.integers(min_value=-50, max_value=50).map(lambda i: i / 100.0),
    min_size=6,
    max_size=6,
).filter(lambda xs: np.std(xs) > 0.05)


def _try(y: list[float], x: list[float]) -> object:
    try:
        return factor_regression(y, {"f": x})
    except (ConfigurationError, CrucibleError):
        return None


@settings(deadline=None)
@given(y=_returns, x=_factor, shift=st.floats(min_value=-1.0, max_value=1.0, allow_nan=False))
def test_shifting_returns_by_a_constant_shifts_only_alpha(
    y: list[float], x: list[float], shift: float
) -> None:
    base = _try(y, x)
    assume(base is not None)
    shifted = _try([v + shift for v in y], x)
    assume(shifted is not None)
    assert abs(shifted.alpha - (base.alpha + shift)) < 1e-6  # type: ignore[union-attr]
    assert abs(shifted.loadings["f"] - base.loadings["f"]) < 1e-6  # type: ignore[union-attr]
    assert abs(shifted.r_squared - base.r_squared) < 1e-6  # type: ignore[union-attr]


@settings(deadline=None)
@given(
    y=_returns,
    x=_factor,
    scale=st.floats(min_value=0.1, max_value=5.0, allow_nan=False, allow_infinity=False),
)
def test_scaling_returns_scales_alpha_and_loadings_but_not_r_squared(
    y: list[float], x: list[float], scale: float
) -> None:
    base = _try(y, x)
    assume(base is not None)
    scaled = _try([v * scale for v in y], x)
    assume(scaled is not None)
    assert abs(scaled.alpha - base.alpha * scale) < 1e-6  # type: ignore[union-attr]
    assert abs(scaled.loadings["f"] - base.loadings["f"] * scale) < 1e-6  # type: ignore[union-attr]
    assert abs(scaled.r_squared - base.r_squared) < 1e-6  # type: ignore[union-attr]
