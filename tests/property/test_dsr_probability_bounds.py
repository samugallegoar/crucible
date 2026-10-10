"""Property: DSR is always a probability in [0, 1] for any valid input
(it's a normal CDF output by construction) -- ADR-0015."""

from __future__ import annotations

import numpy as np
from hypothesis import given
from hypothesis import strategies as st

from crucible.core.errors import CrucibleError
from crucible.validation.dsr import deflated_sharpe_ratio

_floats = st.floats(min_value=-1.0, max_value=1.0, allow_nan=False, allow_infinity=False, width=32)


@given(
    returns=st.lists(_floats, min_size=3, max_size=50),
    trial_sharpes=st.lists(_floats, min_size=1, max_size=20),
)
def test_dsr_is_always_a_probability(returns: list[float], trial_sharpes: list[float]) -> None:
    try:
        result = deflated_sharpe_ratio(np.array(returns), trial_sharpes)
    except CrucibleError:
        return  # a legitimate refusal (e.g. degenerate PSR denominator)
    assert 0.0 <= result.dsr <= 1.0
    assert result.n_trials == len(trial_sharpes)
