"""Look-ahead harness: a prop-firm breach never depends on a bar after it (ADR-0106, AGENTS.md §7).

The overlay is called at fixed points of a bar and never reads the next one. Poisoning every bar
after a breach with absurd prices must leave every fill and every account decision up to and
including the breach unchanged: the breach is decided from the breach bar's own marks and the
schedule, never from what came later.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from pathlib import Path

import numpy as np
import polars as pl

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

BARS = [
    (5000.00, 5000.00, 5000.00, 5000.00),
    (5000.00, 5000.25, 4990.00, 4992.00),
    (5000.00, 5001.00, 4950.00, 4960.00),  # the breach bar (breach price 4,950.25)
    (4960.00, 4970.00, 4955.00, 4965.00),
    (4965.00, 4980.00, 4960.00, 4975.00),
]
TARGETS = [1, 1, 1, 1, 1]
BREACH_BAR = 2


def _run(rows: list[tuple[float, float, float, float]]) -> tuple[pl.DataFrame, pl.DataFrame]:
    bars = pl.DataFrame(
        {
            "event_time": [_T0 + i * _MIN for i in range(len(rows))],
            "open": [r[0] for r in rows],
            "high": [r[1] for r in rows],
            "low": [r[2] for r in rows],
            "close": [r[3] for r in rows],
            "contract": ["ESH4"] * len(rows),
        }
    )
    targets = pl.DataFrame(
        {"event_time": bars["event_time"], "target": pl.Series(TARGETS, dtype=pl.Int64)}
    )
    ruleset = load_ruleset(FIXTURES / "synthetic_a_static_drawdown.yaml")
    overlay = PropAccountOverlay(
        ruleset=ruleset,
        phase=ruleset.phases[0],
        root="ES",
        tick_micro=12_500_000,
        session_close_ns=np.zeros(bars.height, dtype=np.int64),
        start_day=dt.date(2024, 1, 7),
    )
    result = simulate_futures(
        bars=bars,
        targets=targets,
        rolls=pl.DataFrame(schema=ROLL_SCHEMA),
        spec=ES,
        costs=COSTS,
        initial_capital=Decimal("50000"),
        account=overlay,
    )
    return result.fills, result.bars


def test_poisoned_bars_after_the_breach_change_nothing_up_to_and_including_it() -> None:
    """Bars after the breach are replaced by absurd prices: identical up to and including it."""
    clean_fills, clean_bars = _run(BARS)
    poisoned = BARS[: BREACH_BAR + 1] + [(1.0, 9000.0, 0.25, 1.0)] * (len(BARS) - BREACH_BAR - 1)
    dirty_fills, dirty_bars = _run(poisoned)
    limit = BREACH_BAR + 1
    assert clean_fills.equals(dirty_fills)
    assert clean_bars.head(limit).equals(dirty_bars.head(limit))
    # the breach is on the breach bar, at its own price, and the account is closed
    kinds = clean_fills["kind"].to_list()
    assert kinds == ["signal", "liquidation"]
    assert clean_fills["price"].to_list()[-1] == Decimal("4950.25")
    assert clean_bars["position"].to_list()[BREACH_BAR] == 0
