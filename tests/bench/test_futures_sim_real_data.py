"""Opt-in acceptance of the futures execution simulator on the real datasets (ADR-0090).

Run: uv run pytest -m bench tests/bench/test_futures_sim_real_data.py
Needs `data/processed` (or CRUCIBLE_DATA_STORE) with the `*_1m_raw`, `*_1m_cont_v2` and
`*_1m_rolls_v2` datasets of `docs/data/glbx-futures-1m.md`; skips when they are missing. Holds one
contract long from the first bar to the end, so every roll is traded. About 15-25 s and a few GB
of memory per root.
"""

from __future__ import annotations

import os
from decimal import Decimal
from pathlib import Path

import polars as pl
import pytest

from crucible.data.futures_specs import futures_spec
from crucible.execution.futures_sim import CostSchedule, simulate_futures

STORE = Path(os.environ.get("CRUCIBLE_DATA_STORE", "data/processed"))
pytestmark = pytest.mark.bench

# root: (rolls, rolls executed after the first bar of the effective session, mean |reference
# error| in USD per contract) -- the figures of ADR-0090, measured independently first
EXPECTED: dict[str, tuple[int, int, float]] = {
    "es": (66, 0, 28.79),
    "nq": (66, 1, 61.52),
    "ym": (66, 1, 51.06),
    "rty": (37, 1, 47.84),
    "nkd": (66, 35, 67.80),
}


def _need(dataset: str) -> pl.DataFrame:
    path = STORE / dataset / "data.parquet"
    if not path.exists():
        pytest.skip(f"{dataset} not built in {STORE}; see docs/data/glbx-futures-1m.md")
    return pl.read_parquet(path)


@pytest.mark.parametrize("root", sorted(EXPECTED))
def test_holding_one_contract_trades_every_roll_causally(root: str) -> None:
    bars = _need(f"{root}_1m_cont_v2")
    rolls = _need(f"{root}_1m_rolls_v2")
    raw = _need(f"{root}_1m_raw")
    spec = futures_spec(root)
    result = simulate_futures(
        bars=bars,
        targets=bars.select("event_time", target=pl.lit(1, dtype=pl.Int64)),
        rolls=rolls,
        raw=raw,
        spec=spec,
        costs=CostSchedule(commission=Decimal("2.00")),
        initial_capital=Decimal(100_000),
    )
    count, delayed, mean_error = EXPECTED[root]
    executed = result.rolls
    assert executed.height == count
    assert executed["mode"].to_list() == ["causal"] * count
    assert result.strict_execution
    assert int((executed["delay_minutes"] > 0).sum()) == delayed
    errors = executed["approximation_error_usd"].cast(pl.Float64).abs()
    assert round(float(errors.mean() or 0.0), 2) == mean_error

    fills = result.fills
    assert fills.height == 1 + 2 * count  # the entry and two legs per roll
    per_fill = Decimal("2.00") + Decimal("1.5") * spec.tick_value
    assert Decimal(result.bars["costs_usd"].sum()) == per_fill * fills.height

    # gross P&L, independently: the last close minus the entry, minus every executed roll spread
    entry = Decimal(fills["price"][0])
    spreads = sum(
        (Decimal(n) - Decimal(o))
        for o, n in zip(executed["old_price"], executed["new_price"], strict=True)
    )
    last = Decimal(str(bars["close"][-1]))
    gross = (last - entry - spreads) * spec.point_value
    final = Decimal(result.bars["equity_usd"][-1])
    assert final == Decimal(100_000) + gross - Decimal(result.bars["costs_usd"].sum())
