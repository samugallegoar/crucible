"""Property: the prop-firm overlay never invents a trade and never fills better than its trigger.

Three properties (ADR-0106, section 3):

- a ruleset that cannot bind (a million-dollar drawdown, a thousand-contract limit, no flat-by and
  no pass condition) leaves every bar and every fill identical to ``account=None``: the overlay is
  a wrapper, not a second simulator;
- every liquidation fill is on the tick grid and inside its bar's ``[low, high]``: the breach price
  is solved and rounded against the strategy, never against it;
- a run that fails a static drawdown ends with a balance at or below its threshold
  (``starting_balance - amount``), because the liquidation pays the threshold and its costs.

Hypothesis is derandomized and keeps a small example budget, so a failure is reproducible.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from pathlib import Path

import numpy as np
import polars as pl
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from crucible.data.contracts import ROLL_SCHEMA
from crucible.data.futures_specs import futures_spec
from crucible.execution.futures_sim import CostSchedule, simulate_futures
from crucible.prop.overlay import PropAccountOverlay
from crucible.prop.ruleset import load_ruleset

ES = futures_spec("ES")
COSTS = CostSchedule(commission=Decimal("2.00"))
FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "prop"
_NS = 1_000_000_000
_MIN = 60 * _NS
_T0 = int(dt.datetime(2024, 1, 8, 15, 1, tzinfo=dt.UTC).timestamp()) * _NS
SETTINGS = settings(
    max_examples=25, derandomize=True, deadline=None, suppress_health_check=[HealthCheck.too_slow]
)


def _series(
    prices: list[tuple[int, int, int]], targets: list[int]
) -> tuple[pl.DataFrame, pl.DataFrame]:
    """Bars from ``(open, high, low)`` tick ranges on the ES grid, with their targets."""
    tick = 0.25
    bars = pl.DataFrame(
        {
            "event_time": [_T0 + i * _MIN for i in range(len(prices))],
            "open": [p[0] * tick for p in prices],
            "high": [p[1] * tick for p in prices],
            "low": [p[2] * tick for p in prices],
            "close": [p[0] * tick for p in prices],
            "contract": ["ESH4"] * len(prices),
        }
    )
    return bars, pl.DataFrame(
        {"event_time": bars["event_time"], "target": pl.Series(targets, dtype=pl.Int64)}
    )


def _overlay(name: str, n: int) -> PropAccountOverlay:
    ruleset = load_ruleset(FIXTURES / name)
    return PropAccountOverlay(
        ruleset=ruleset,
        phase=ruleset.phases[0],
        root="ES",
        tick_micro=12_500_000,
        session_close_ns=np.zeros(n, dtype=np.int64),
        start_day=dt.date(2024, 1, 7),
    )


_PRICES = st.lists(
    st.tuples(
        st.integers(min_value=19_500, max_value=20_500),
        st.integers(min_value=19_000, max_value=21_000),
        st.integers(min_value=19_000, max_value=21_000),
    ),
    min_size=1,
    max_size=8,
).map(lambda rows: [(o, max(o, h, lo), min(o, h, lo)) for o, h, lo in rows])
_TARGETS = st.integers(min_value=-2, max_value=2)


@SETTINGS
@given(prices=_PRICES, targets=st.lists(_TARGETS, min_size=1, max_size=8))
def test_a_non_binding_ruleset_matches_account_none_exactly(
    prices: list[tuple[int, int, int]], targets: list[int]
) -> None:
    n = min(len(prices), len(targets))
    bars, decided = _series(prices[:n], targets[:n])
    common = {
        "bars": bars,
        "targets": decided,
        "rolls": pl.DataFrame(schema=ROLL_SCHEMA),
        "spec": ES,
        "costs": COSTS,
        "initial_capital": Decimal("50000"),
    }
    plain = simulate_futures(**common)
    overlay = _overlay("synthetic_h_nonbinding.yaml", n)
    wrapped = simulate_futures(**common, account=overlay)
    assert wrapped.bars.equals(plain.bars)
    assert wrapped.fills.equals(plain.fills)
    assert wrapped.rolls.equals(plain.rolls)


@SETTINGS
@given(prices=_PRICES, targets=st.lists(_TARGETS, min_size=1, max_size=8))
def test_every_liquidation_fills_on_the_grid_inside_its_bar(
    prices: list[tuple[int, int, int]], targets: list[int]
) -> None:
    n = min(len(prices), len(targets))
    bars, decided = _series(prices[:n], targets[:n])
    overlay = _overlay("synthetic_a_static_drawdown.yaml", n)
    result = simulate_futures(
        bars=bars,
        targets=decided,
        rolls=pl.DataFrame(schema=ROLL_SCHEMA),
        spec=ES,
        costs=COSTS,
        initial_capital=Decimal("50000"),
        account=overlay,
    )
    lows = bars["low"].to_list()
    highs = bars["high"].to_list()
    times = bars["event_time"].to_list()
    for row in result.fills.iter_rows(named=True):
        if row["kind"] != "liquidation":
            continue
        index = times.index(row["event_time"])
        price = float(row["price"])
        assert lows[index] <= price <= highs[index], (
            f"liquidation at {price} is outside its bar's [{lows[index]}, {highs[index]}]"
        )
        assert abs(price / float(ES.tick_size) - round(price / float(ES.tick_size))) < 1e-9


@SETTINGS
@given(prices=_PRICES, targets=st.lists(_TARGETS, min_size=1, max_size=8))
def test_a_failed_static_drawdown_ends_at_or_below_its_threshold(
    prices: list[tuple[int, int, int]], targets: list[int]
) -> None:
    n = min(len(prices), len(targets))
    bars, decided = _series(prices[:n], targets[:n])
    overlay = _overlay("synthetic_a_static_drawdown.yaml", n)
    result = simulate_futures(
        bars=bars,
        targets=decided,
        rolls=pl.DataFrame(schema=ROLL_SCHEMA),
        spec=ES,
        costs=COSTS,
        initial_capital=Decimal("50000"),
        account=overlay,
    )
    if overlay.outcome != "fail":
        return
    # 50,000.00 - 2,500.00 = 47,500.00; the liquidation pays its own costs on top
    assert result.bars["balance_usd"][-1] <= Decimal("47500")
    assert overlay.breached_rule == "max_drawdown"


@SETTINGS
@given(prices=_PRICES, targets=st.lists(_TARGETS, min_size=1, max_size=8), extra=st.integers(1, 5))
def test_every_fill_of_every_kind_stays_inside_its_bar(
    prices: list[tuple[int, int, int]], targets: list[int], extra: int
) -> None:
    """I5 for the prop path: with ``liquidation_extra_slippage_ticks > 0`` the extra ticks are
    charged as money, so no fill price leaves its bar (AGENTS.md section 9).

    Checked for every fill kind: a signal or a stop fills at its own price inside the bar, a
    liquidation at its breach price or the open, and a close fill (``at_close``) exactly at the
    close. Bars whose contract did not trade carry no fills at all.
    """
    n = min(len(prices), len(targets))
    bars, decided = _series(prices[:n], targets[:n])
    overlay = _overlay("synthetic_a_static_drawdown.yaml", n)
    result = simulate_futures(
        bars=bars,
        targets=decided,
        rolls=pl.DataFrame(schema=ROLL_SCHEMA),
        spec=ES,
        costs=COSTS,
        initial_capital=Decimal("50000"),
        account=overlay,
        liquidation_extra_slippage_ticks=extra,
    )
    lows = bars["low"].to_list()
    highs = bars["high"].to_list()
    closes = bars["close"].to_list()
    times = bars["event_time"].to_list()
    for row in result.fills.iter_rows(named=True):
        index = times.index(row["event_time"])
        price = float(row["price"])
        at_close = row["fill_time"] == row["event_time"]
        if at_close:
            assert price == closes[index], (
                f"{row['kind']} at_close filled at {price}, not the close {closes[index]}"
            )
        else:
            assert lows[index] <= price <= highs[index], (
                f"{row['kind']} at {price} is outside its bar's [{lows[index]}, {highs[index]}]"
            )
