"""The one results table of the one-step backtest (ADR-0077): same rows and formats always."""

from __future__ import annotations

from typing import Any

from crucible.product.table import NOT_AVAILABLE, ROW_IDS, build_results_table, to_markdown, to_text


def _doc(**overrides: Any) -> dict[str, Any]:
    side = {
        "final_equity": 110_250.4,
        "total_return_pct": 10.2504,
        "cagr_pct": 4.9,
        "volatility_pct": 12.34,
        "max_drawdown_pct": -17.84,
        "sharpe": 0.74,
        "sharpe_low": 0.11,
        "sharpe_high": 1.36,
    }
    doc: dict[str, Any] = {
        "results": {
            "strategy": {**side, "n_trades": 2, "hit_rate_pct": 50.0, "time_in_market_pct": 41.0},
            "benchmark": {**side, "final_equity": 120_000.0, "sharpe_low": None},
        },
        "validation": {
            "trial_count": 3,
            "dsr": 0.8135,
            "realism_level": "BASIC_FRICTION",
            "null_test": {"p_value": 0.1386},
        },
        "trades": [{"bars_held": 4}, {"bars_held": 7}],
    }
    doc.update(overrides)
    return doc


def test_the_rows_are_always_the_same_in_the_same_order() -> None:
    table = build_results_table(_doc())
    assert [r["id"] for r in table["rows"]] == list(ROW_IDS)
    assert table["columns"] == ["Metric", "Strategy", "Buy and hold"]


def test_values_are_formatted_text_with_fixed_precision() -> None:
    by_id = {r["id"]: r for r in build_results_table(_doc())["rows"]}
    assert by_id["final_value"]["strategy"] == "$110,250"
    assert by_id["total_return"]["strategy"] == "+10.3%"
    assert by_id["worst_fall"]["strategy"] == "-17.8%"
    assert by_id["sharpe"]["strategy"] == "0.74 (0.11 to 1.36)"
    assert by_id["avg_bars_held"]["strategy"] == "5.5"
    assert by_id["deflated_sharpe"]["strategy"] == "81%"
    assert by_id["shuffle_p_value"]["strategy"] == "0.139"


def test_a_missing_value_is_n_a_never_a_missing_row() -> None:
    doc = _doc(trades=[])
    doc["validation"]["null_test"] = None
    doc["validation"]["dsr"] = None
    doc["results"]["strategy"]["hit_rate_pct"] = None
    table = build_results_table(doc)
    by_id = {r["id"]: r for r in table["rows"]}
    assert [r["id"] for r in table["rows"]] == list(ROW_IDS)
    for row_id in ("avg_bars_held", "winning_trades", "deflated_sharpe", "shuffle_p_value"):
        assert by_id[row_id]["strategy"] == NOT_AVAILABLE
    assert by_id["sharpe"]["benchmark"] == f"0.74 (range {NOT_AVAILABLE})"


def test_markdown_and_text_carry_every_row_and_are_deterministic() -> None:
    table = build_results_table(_doc())
    assert table["markdown"] == build_results_table(_doc())["markdown"]
    assert table["markdown"] == to_markdown(table["rows"])
    lines = table["markdown"].splitlines()
    assert len(lines) == len(ROW_IDS) + 2
    assert len({len(line) for line in lines}) == 1  # aligned
    for row in table["rows"]:
        assert row["label"] in table["markdown"]
        assert row["label"] in to_text(table["rows"])
