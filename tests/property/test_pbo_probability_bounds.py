"""Property: PBO is always a probability in [0, 1], and the number of
combinatorial splits always matches math.comb(n_groups, n_groups // 2)
(ADR-0015)."""

from __future__ import annotations

import math

import numpy as np
from hypothesis import given
from hypothesis import strategies as st

from crucible.validation.pbo import probability_of_backtest_overfitting
from crucible.validation.splits import CombinatorialPurgedCVSplitter

_floats = st.floats(min_value=-0.1, max_value=0.1, allow_nan=False, allow_infinity=False)


@given(data=st.data())
def test_pbo_is_a_probability_with_the_expected_combination_count(data: st.DataObject) -> None:
    n_trials = data.draw(st.integers(min_value=2, max_value=5))
    n_groups = data.draw(st.sampled_from([4, 6]))
    n_periods = n_groups + data.draw(st.integers(min_value=0, max_value=20))
    rows = data.draw(
        st.lists(
            st.lists(_floats, min_size=n_periods, max_size=n_periods),
            min_size=n_trials,
            max_size=n_trials,
        )
    )
    returns = np.array(rows)
    splitter = CombinatorialPurgedCVSplitter(n_groups=n_groups, n_test_groups=n_groups // 2)

    result = probability_of_backtest_overfitting(returns, splitter)

    assert 0.0 <= result.pbo <= 1.0
    assert result.n_combinations == math.comb(n_groups, n_groups // 2)
    assert result.n_trials == n_trials
