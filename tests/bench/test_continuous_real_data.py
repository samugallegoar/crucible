"""Opt-in acceptance of the continuous futures builder on the real datasets (ADR-0086).

Run: uv run pytest -m bench tests/bench/test_continuous_real_data.py
Needs `data/processed` (or CRUCIBLE_DATA_STORE) with the datasets of `docs/data/glbx-futures-1m.md`
built by `crucible data build` and then `crucible data continuous --roots es,nq,ym,rty,nkd
--trim-to-calendar`. Skips when they are missing. The numbers are those of the `v3` datasets (trade
date from the CME session calendar, ADR-0092): the four U.S. roots roll on the same dates as `v2`;
NKD starts at its calendar coverage (2012-11-19), so it has ten fewer rolls. The ADR-0086 erratum
records the `v1` figures.
"""

from __future__ import annotations

import os
from pathlib import Path

import polars as pl
import pytest

from crucible.data.continuous import calendar_for, trade_dates

STORE = Path(os.environ.get("CRUCIBLE_DATA_STORE", "data/processed"))
pytestmark = pytest.mark.bench

VAULT_START_NS = 1_735_686_000_000_000_000
"""2024-12-31T23:00:00Z: the open of the first protected Globex trade date (ADR-0105). The bench
reads the span BEFORE it and nothing at or after it: the protected period is not research data."""

# root: (rolls before the vault, {reason: count}, sum of gaps in points, the oldest data's ratio
# multiplier). The counts and gap sums were re-measured over the pre-vault span when the holdout
# vault was introduced (ADR-0105: this bench now stops before it; the full-span figures -- 66 rolls
# for the four U.S. roots, 37 for RTY, 56 for NKD -- are part of the documented exposure). The
# multiplier is unchanged by the narrowing: it scales the OLDEST bar, and it is the product of every
# roll's ratio including the protected ones (ADR-0105, "ratio-adjusted series" residual risk).
EXPECTED: dict[str, tuple[int, dict[str, int], float, float]] = {
    "es": (59, {"volume": 59}, 267.5, 1.0405),
    "nq": (59, {"volume": 59}, 2035.75, 1.1915),
    "ym": (59, {"volume": 59}, 289.0, 0.9687),
    "rty": (30, {"volume": 30}, 192.0, 1.1607),
    "nkd": (49, {"backstop": 46, "volume": 3}, -1170.0, 0.9712),
}


def _need(dataset: str) -> Path:
    path = STORE / dataset / "data.parquet"
    if not path.exists():
        pytest.skip(f"{dataset} not built in {STORE}; see docs/data/glbx-futures-1m.md")
    return path


def _pre_vault(dataset: str) -> pl.LazyFrame:
    """The dataset lazily, filtered to the span before the holdout vault (ADR-0105)."""
    return pl.scan_parquet(_need(dataset)).filter(pl.col("event_time") < VAULT_START_NS)


@pytest.mark.parametrize("root", sorted(EXPECTED))
def test_the_rolls_reproduce_the_measured_figures(root: str) -> None:
    rolls = _pre_vault(f"{root}_1m_rolls_v3").sort("event_time").collect()
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
def test_the_ratio_adjustment_is_one_constant_per_contract_segment(root: str) -> None:
    """Backward ratio adjustment is ONE multiplier per contract segment, and a jump happens exactly
    at a roll, its size being that roll's ratio.

    The absolute level of each segment also contains the ratios of the rolls INSIDE the vault, so
    the product is not recomputed here (ADR-0105 lists it as a residual: the constant carries no
    usable information because a signal must be scale invariant, ADR-0094). What is checked is the
    structure -- constant within a segment, jumps at the rolls -- plus the oldest bar's multiplier,
    which the narrowing does not change.
    """
    plain = _pre_vault(f"{root}_1m_cont_v3").select("event_time", "contract", "low")
    adjusted = _pre_vault(f"{root}_1m_cont_ratio_v3").select(
        "event_time", pl.col("low").alias("low_adj")
    )
    joined = plain.join(adjusted, on="event_time", how="inner")
    ratios = joined.with_columns(ratio=pl.col("low_adj") / pl.col("low"))
    segments = (
        ratios.group_by("contract")
        .agg(
            pl.col("ratio").min().alias("lowest"),
            pl.col("ratio").max().alias("highest"),
            pl.col("event_time").min().alias("first"),
            pl.len().alias("rows"),
        )
        .sort("first")
        .collect()
    )
    # one constant per contract segment (not a per-bar re-scaling)
    spread = (segments["highest"] - segments["lowest"]).abs().max()
    assert spread is not None
    assert spread < 1e-9 * float(segments["highest"].max() or 1.0)
    # the oldest bar keeps the multiplier ADR-0086 measured for it
    assert float(segments["lowest"][0] or 0.0) == pytest.approx(EXPECTED[root][3], abs=5e-4)
    # and each jump to the next contract is that roll's ratio
    rolls = _pre_vault(f"{root}_1m_rolls_v3").sort("event_time").collect()
    by_segment = {
        str(contract): float(lowest)
        for contract, lowest in zip(segments["contract"], segments["lowest"], strict=True)
    }
    checked = 0
    for row in rolls.iter_rows(named=True):
        older = by_segment.get(str(row["from_contract"]))
        newer = by_segment.get(str(row["to_contract"]))
        if older is None or newer is None:
            continue
        assert older / newer == pytest.approx(float(row["ratio"]), rel=1e-6)
        checked += 1
    assert checked >= 1, "the pre-vault span has no roll between two visible segments"
    # no adjusted price went negative
    assert _pre_vault(f"{root}_1m_cont_ratio_v3").select(pl.col("low").min()).collect().item() > 0


@pytest.mark.parametrize("root", sorted(EXPECTED))
def test_both_series_have_the_same_bars_and_one_contract_per_session(root: str) -> None:
    plain = _pre_vault(f"{root}_1m_cont_v3")
    adjusted = _pre_vault(f"{root}_1m_cont_ratio_v3")
    keys = ["event_time", "contract", "volume"]
    assert plain.select(keys).collect().equals(adjusted.select(keys).collect())
    frame = plain.select("event_time", "contract").collect()
    per_session = (
        frame.with_columns(session=trade_dates(frame["event_time"], calendar_for(root), 60))
        .group_by("session")
        .agg(pl.col("contract").n_unique().alias("n"))
    )
    assert per_session["n"].max() == 1  # no session mixes two contracts
