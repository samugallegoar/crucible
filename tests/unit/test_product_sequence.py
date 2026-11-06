"""The one-step backtest's return-sequence risk block and its fixed table (ADR-0083)."""

from __future__ import annotations

import json

import numpy as np
import pytest

from crucible.product.sequence import (
    NOTE,
    ROW_IDS,
    build_sequence_risk,
    build_sequence_table,
)


def _returns(n: int = 300, seed: int = 1) -> np.ndarray:
    return np.random.default_rng(seed).normal(0.0004, 0.01, n)


def test_a_trades_return_on_equity_is_its_price_change_less_the_round_trip_times_its_weight() -> (
    None
):
    """Twenty identical trades: +2% price change, half the account, 1.5 bps a side. Each returns
    (0.02 - 2 * 0.00015) * 0.5 = 0.00985 on equity, so every path ends at 1.00985 ** 20."""
    block = build_sequence_risk(_returns(), [2.0] * 20, [0.5] * 20, 1.5, seed=1)
    trades = block["trades"]
    assert trades is not None
    expected = 1.00985**20
    assert trades["terminal_multiple"]["p05"] == pytest.approx(expected)
    assert trades["terminal_multiple"]["p95"] == pytest.approx(expected)
    assert trades["horizon"] == 20
    assert trades["prob_loss"] == 0.0
    assert "fan" not in trades  # a trade count is not a calendar: only the bars are fanned


def test_too_few_trades_are_reported_not_resampled_and_not_fatal() -> None:
    block = build_sequence_risk(_returns(), [1.0] * 4, [1.0] * 4, 1.5, seed=1)
    assert block["bars"] is not None
    assert block["trades"] is None
    assert "need >= 10" in block["trades_error"]
    table = build_sequence_table(block, 100_000.0)
    assert {r["id"]: r for r in table["rows"]}["prob_loss"]["trades"] == "n/a"


def test_too_few_bars_do_not_sink_the_backtest() -> None:
    block = build_sequence_risk(np.array([0.01, -0.01]), [], [], 0.0, seed=1)
    assert block["bars"] is None
    assert "bars_error" in block
    assert build_sequence_table(block, 1_000.0)["rows"][0]["bars"] == "n/a"


def test_the_block_is_tagged_json_ready_and_seeded() -> None:
    a = build_sequence_risk(_returns(), [1.0, -0.5] * 10, [1.0] * 20, 1.5, seed=7)
    b = build_sequence_risk(_returns(), [1.0, -0.5] * 10, [1.0] * 20, 1.5, seed=7)
    c = build_sequence_risk(_returns(), [1.0, -0.5] * 10, [1.0] * 20, 1.5, seed=8)
    assert a == b
    assert a != c
    assert a["kind"] == "return_sequence_risk"
    json.dumps(a, allow_nan=False)


def test_the_table_has_fixed_rows_exact_formats_and_the_note() -> None:
    summary = {
        "horizon": 500,
        "mean_block": 12.34,
        "ruin_loss": 0.5,
        "drawdown_threshold": -0.3,
        "terminal_multiple": {"p05": 0.96, "p50": 1.048, "p95": 1.21},
        "max_drawdown": {"p50": -0.061, "p05": -0.142},
        "prob_loss": 0.214,
        "prob_ruin": 0.0,
        "prob_drawdown_worse_than_threshold": 0.0123,
    }
    block = {"bars": summary, "trades": None}
    table = build_sequence_table(block, 100_000.0)
    assert [r["id"] for r in table["rows"]] == list(ROW_IDS)
    rows = {r["id"]: r for r in table["rows"]}
    assert rows["resampling"]["bars"] == "500 bars, blocks of about 12.3"
    assert rows["final_value"]["bars"] == "$96,000 / $104,800 / $121,000"
    assert rows["max_drawdown"]["bars"] == "-6.1% / -14.2%"
    assert rows["prob_loss"]["bars"] == "21.4%"
    assert rows["prob_ruin"]["bars"] == "0.0%"
    assert rows["prob_drawdown"]["bars"] == "1.2%"
    assert rows["prob_ruin"]["label"] == "Chance of ever being down 50%"
    assert rows["prob_drawdown"]["label"] == "Chance of a fall worse than 30%"
    assert all(rows[i]["trades"] == "n/a" for i in ROW_IDS)
    assert table["markdown"].endswith("*" + NOTE + "*")
    assert "not evidence of an edge" in NOTE
    lines = table["markdown"].split("\n\n")[0].splitlines()
    assert len({len(line) for line in lines}) == 1  # aligned
