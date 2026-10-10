"""Property: the FX loop never invents money (ADR-0062).

With zero costs, at every bar the per-symbol gross pnl (base currency) sums to the change in equity,
for any weights, prices and positive rates, across several currencies.
"""

from __future__ import annotations

import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from crucible.vectorized.fx import run_fx_equity

_WEIGHTS = st.sampled_from([-1.0, -0.5, 0.0, 0.5, 1.0])


@settings(max_examples=100, deadline=None)
@given(
    data=st.data(),
    n_symbols=st.integers(min_value=1, max_value=3),
    n_bars=st.integers(min_value=2, max_value=25),
)
def test_pnl_sums_to_the_equity_change(data: st.DataObject, n_symbols: int, n_bars: int) -> None:
    close = np.empty((n_bars, n_symbols))
    fx = np.empty((n_bars, n_symbols))
    weight = np.empty((n_bars, n_symbols))
    for s in range(n_symbols):
        price, rate = 100.0, 1.0
        for t in range(n_bars):
            price *= 1.0 + data.draw(st.floats(min_value=-0.2, max_value=0.2))
            rate *= 1.0 + data.draw(st.floats(min_value=-0.1, max_value=0.1))
            close[t, s], fx[t, s], weight[t, s] = price, rate, data.draw(_WEIGHTS)
    equity, pnl = run_fx_equity(
        close=close, weight=weight, fx=fx, initial_cash=1000.0, cost_rate=0.0
    )
    assert np.isfinite(equity).all()
    previous = 1000.0
    for t in range(n_bars):
        assert pnl[t].sum() == pytest.approx(equity[t] - previous, abs=1e-9, rel=1e-9)
        previous = equity[t]
