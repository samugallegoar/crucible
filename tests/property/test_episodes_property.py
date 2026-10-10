"""Property: episode pnl is consistent with the equity series (ADR-0061, ADR-0062).

With one symbol, no costs and a last weight of 0, every held bar belongs to a closed episode, and
equity compounds as ``equity[t] = equity[t-1] * (1 + weight[t] * return[t])``, so the episodes'
pnl (from the per-bar pnl frame) must add up to the whole equity change.
"""

from __future__ import annotations

import polars as pl
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from crucible.analytics.trades import build_episodes

_WEIGHTS = st.sampled_from([-1.0, -0.5, 0.0, 0.5, 1.0])


@settings(max_examples=100, deadline=None)
@given(
    body=st.lists(
        st.tuples(_WEIGHTS, st.floats(min_value=-0.2, max_value=0.2)), min_size=2, max_size=30
    )
)
def test_episode_pnl_adds_up_to_the_equity_change(body: list[tuple[float, float]]) -> None:
    initial = 1000.0
    weights = [w for w, _ in body] + [0.0]  # the series ends flat: no open episode
    returns = [0.0] + [r for _, r in body]
    ts = [10 * (i + 1) for i in range(len(weights))]
    pnl_values: list[float] = []
    value = initial
    for w, r in zip(weights, returns, strict=True):
        pnl_values.append(value * w * r)
        value *= 1.0 + w * r

    out = build_episodes(
        pl.DataFrame({"ts": ts, "symbol": ["X"] * len(ts), "weight": weights}),
        pl.DataFrame({"ts": ts, "symbol": ["X"] * len(ts), "pnl": pnl_values}),
    )
    assert out["pnl"].sum() == pytest.approx(value - initial, abs=1e-6 * initial)
    for row in out.to_dicts():
        assert row["entry_ts"] <= row["exit_ts"]
        assert row["holding_ns"] == row["exit_ts"] - row["entry_ts"]
