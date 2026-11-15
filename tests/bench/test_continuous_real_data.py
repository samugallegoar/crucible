"""Opt-in acceptance of the continuous futures builder on the real datasets (ADR-0086).

Run: uv run pytest -m bench tests/bench/test_continuous_real_data.py
Needs `data/processed` (or CRUCIBLE_DATA_STORE) with the datasets of `docs/data/glbx-futures-1m.md`
built by `crucible data build` and then `crucible data continuous --roots es,nq,ym,rty,nkd`. Skips
when they are missing. The numbers are those of the `v2` datasets (trade date from the Chicago wall
clock, ADR-0087); the ADR-0086 erratum records the `v1` ones, which differ in a few roll dates.
"""

from __future__ import annotations

import math
import os
from pathlib import Path

import polars as pl
import pytest

from crucible.data.continuous import trade_date_expr

STORE = Path(os.environ.get("CRUCIBLE_DATA_STORE", "data/processed"))
pytestmark = pytest.mark.bench

# root: (rolls, {reason: count}, sum of gaps in points, ratio multiplier of the oldest data)
EXPECTED: dict[str, tuple[int, dict[str, int], float, float]] = {
    "es": (66, {"volume": 66}, 670.75, 1.0405),
    "nq": (66, {"volume": 66}, 3770.25, 1.1915),
    "ym": (66, {"volume": 66}, 2750.0, 0.9687),
    "rty": (37, {"volume": 37}, 322.4, 1.1607),
    "nkd": (66, {"backstop": 62, "volume": 4}, -1020.0, 0.9667),
}


def _need(dataset: str) -> Path:
    path = STORE / dataset / "data.parquet"
    if not path.exists():
        pytest.skip(f"{dataset} not built in {STORE}; see docs/data/glbx-futures-1m.md")
    return path


@pytest.mark.parametrize("root", sorted(EXPECTED))
def test_the_rolls_reproduce_the_measured_figures(root: str) -> None:
    rolls = pl.read_parquet(_need(f"{root}_1m_rolls_v2")).sort("event_time")
    count, reasons, gap_sum, _ = EXPECTED[root]
    assert rolls.height == count
    got = {str(reason): int(n) for reason, n in rolls.group_by("reason").len().rows()}
    assert got == reasons
    assert rolls["gap_points"].sum() == pytest.approx(gap_sum, abs=0.1)
    # structure: strictly increasing effective dates, ratio = to / from, knowable at decision time
    assert rolls["effective_trade_date"].is_sorted()
    assert rolls["effective_trade_date"].n_unique() == rolls.height
    ratio = (rolls["to_price"] / rolls["from_price"]).to_list()
    assert rolls["ratio"].to_list() == pytest.approx(ratio, rel=1e-12)
    assert (rolls["available_at"] == rolls["event_time"]).all()
    # a roll is decided before the reference minute's next session opens, never after the roll
    assert (rolls["reference_time"] <= rolls["event_time"]).all()


@pytest.mark.parametrize("root", sorted(EXPECTED))
def test_the_ratio_adjustment_scales_the_oldest_data_by_the_product_of_the_ratios(
    root: str,
) -> None:
    plain = _need(f"{root}_1m_cont_v2")
    adjusted = _need(f"{root}_1m_cont_ratio_v2")
    rolls = pl.read_parquet(_need(f"{root}_1m_rolls_v2"))
    first_plain = pl.scan_parquet(plain).sort("event_time").head(1).collect()
    first_adj = pl.scan_parquet(adjusted).sort("event_time").head(1).collect()
    multiplier = first_adj["open"][0] / first_plain["open"][0]
    assert multiplier == pytest.approx(math.prod(rolls["ratio"].to_list()), rel=1e-9)
    assert multiplier == pytest.approx(EXPECTED[root][3], abs=5e-4)
    # the newest bar is untouched and no adjusted price is negative
    last_plain = pl.scan_parquet(plain).sort("event_time").tail(1).collect()
    last_adj = pl.scan_parquet(adjusted).sort("event_time").tail(1).collect()
    assert last_adj["close"][0] == last_plain["close"][0]
    assert pl.scan_parquet(adjusted).select(pl.col("low").min()).collect().item() > 0


@pytest.mark.parametrize("root", sorted(EXPECTED))
def test_both_series_have_the_same_bars_and_one_contract_per_session(root: str) -> None:
    plain = pl.scan_parquet(_need(f"{root}_1m_cont_v2"))
    adjusted = pl.scan_parquet(_need(f"{root}_1m_cont_ratio_v2"))
    keys = ["event_time", "contract", "volume"]
    assert plain.select(keys).collect().equals(adjusted.select(keys).collect())
    per_session = (
        plain.with_columns(session=trade_date_expr(60))
        .group_by("session")
        .agg(pl.col("contract").n_unique().alias("n"))
        .collect()
    )
    assert per_session["n"].max() == 1  # no session mixes two contracts
