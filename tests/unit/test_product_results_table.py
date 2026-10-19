"""The one results table of the one-step backtest (ADR-0077): same rows and formats always."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

from crucible.product.diagnostics import alpha_beta, break_even_bps, trade_stats
from crucible.product.table import NOT_AVAILABLE, ROW_IDS, build_results_table, to_markdown, to_text


def _diagnostics() -> dict[str, Any]:
    return {
        "assumed_cost_bps_per_side": 1.5,
        "cost_drag_pct": 5.04,
        "turnover_per_year": 280.0,
        "break_even_bps_per_side": 7.14,
        "trade_net": {
            "n": 2,
            "expectancy_bps": 11.06,
            "expectancy_low_bps": -18.2,
            "expectancy_high_bps": 40.4,
            "win_rate_pct": 50.0,
            "profit_factor": 1.9,
            "payoff_ratio": 0.76,
        },
        "alpha_beta": {"n": 500, "alpha_annual_pct": 14.5, "alpha_t": 1.04, "beta": 0.15},
        "return_per_exposure_pct": 75.9,
    }


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
            "realism_check": {"sharpe": 0.37},
        },
        "trades": [{"bars_held": 4}, {"bars_held": 7}],
        "diagnostics": _diagnostics(),
    }
    doc.update(overrides)
    return doc


def _rows(doc: dict[str, Any]) -> dict[str, dict[str, str]]:
    return {r["id"]: r for r in build_results_table(doc)["rows"]}


def test_the_rows_are_always_the_same_in_the_same_order() -> None:
    table = build_results_table(_doc())
    assert [r["id"] for r in table["rows"]] == list(ROW_IDS)
    assert table["columns"] == ["Metric", "Strategy", "Buy and hold"]


def test_values_are_formatted_text_with_fixed_precision() -> None:
    by_id = _rows(_doc())
    assert by_id["final_value"]["strategy"] == "$110,250"
    assert by_id["total_return"]["strategy"] == "+10.3%"
    assert by_id["worst_fall"]["strategy"] == "-17.8%"
    assert by_id["sharpe"]["strategy"] == "0.74 (0.11 to 1.36)"
    assert by_id["avg_bars_held"]["strategy"] == "5.5"
    assert by_id["deflated_sharpe"]["strategy"] == "81%"
    assert by_id["shuffle_p_value"]["strategy"] == "0.139"
    assert by_id["cost_drag_per_year"]["strategy"] == "5.0%"
    assert by_id["turnover_per_year"]["strategy"] == "280.0x"
    assert by_id["break_even_cost"]["strategy"] == "7.1 bps (assumed 1.5)"
    assert by_id["net_expectancy"]["strategy"] == "+11.1 bps (-18.2 to +40.4)"
    assert by_id["profit_factor"]["strategy"] == "1.90"
    assert by_id["payoff_ratio"]["strategy"] == "0.76"
    assert by_id["winning_trades"]["strategy"] == "50.0%"
    assert by_id["alpha_beta"]["strategy"] == "+14.5% (t +1.0), beta 0.15"
    assert by_id["return_per_exposure"]["strategy"] == "75.9%"
    assert by_id["realism_retention"]["strategy"] == "50% (Sharpe 0.37 of 0.74)"


def test_a_missing_value_is_n_a_never_a_missing_row() -> None:
    doc = _doc(trades=[])
    doc["validation"]["null_test"] = None
    doc["validation"]["dsr"] = None
    doc["validation"]["realism_check"] = None
    del doc["diagnostics"]
    table = build_results_table(doc)
    by_id = {r["id"]: r for r in table["rows"]}
    assert [r["id"] for r in table["rows"]] == list(ROW_IDS)
    for row_id in (
        "avg_bars_held",
        "winning_trades",
        "deflated_sharpe",
        "shuffle_p_value",
        "cost_drag_per_year",
        "turnover_per_year",
        "net_expectancy",
        "profit_factor",
        "payoff_ratio",
        "alpha_beta",
        "return_per_exposure",
    ):
        assert by_id[row_id]["strategy"] == NOT_AVAILABLE, row_id
    assert by_id["break_even_cost"]["strategy"].startswith(NOT_AVAILABLE)
    assert by_id["realism_retention"]["strategy"] == "not run"
    assert by_id["sharpe"]["benchmark"] == f"0.74 (range {NOT_AVAILABLE})"


def test_a_losing_gross_strategy_reads_zero_break_even() -> None:
    doc = _doc()
    doc["diagnostics"]["break_even_bps_per_side"] = 0.0
    assert "loses money before costs" in _rows(doc)["break_even_cost"]["strategy"]


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


def test_the_agent_guide_states_the_real_row_count() -> None:
    guide = Path("AGENT_GUIDE.md").read_text(encoding="utf-8")
    assert f"same {len(ROW_IDS)} rows" in guide


# --- the diagnostics, against hand-computed values -------------------------------------------


def test_trade_stats_match_a_hand_computation() -> None:
    # wins 10 + 20 = 30, losses 5 + 10 = 15; mean 3.75; sample sd sqrt(568.75 / 3)
    stats = trade_stats([10.0, -5.0, 20.0, -10.0])
    assert stats["n"] == 4
    assert stats["expectancy_bps"] == 3.75
    assert stats["win_rate_pct"] == 50.0
    assert stats["profit_factor"] == 2.0
    assert stats["payoff_ratio"] == 2.0  # average win 15 over average loss 7.5
    half = 1.959964 * (568.75 / 3) ** 0.5 / 2
    assert abs(float(stats["expectancy_high_bps"] or 0) - (3.75 + half)) < 1e-6
    assert abs(float(stats["expectancy_low_bps"] or 0) - (3.75 - half)) < 1e-6


def test_trade_stats_degrade_to_none_not_to_a_guess() -> None:
    assert trade_stats([])["expectancy_bps"] is None
    one = trade_stats([5.0])
    assert one["expectancy_bps"] == 5.0
    assert one["expectancy_low_bps"] is None
    assert one["profit_factor"] is None  # no losing trade: not infinity
    assert trade_stats([-5.0, -1.0])["payoff_ratio"] is None  # no winning trade


def test_break_even_cost_is_where_the_mean_return_reaches_zero() -> None:
    gross = np.full(4, 0.01)
    net = gross - 0.002  # a cost of 2 bps per side took 20 bps a bar
    assert break_even_bps(gross, net, 2.0) == 10.0
    assert break_even_bps(-gross, -gross - 0.002, 2.0) == 0.0  # loses before any cost
    assert break_even_bps(gross, gross, 2.0) is None  # nothing traded
    assert break_even_bps(gross, net, 0.0) is None  # no cost assumed


def test_alpha_and_beta_recover_a_known_relationship() -> None:
    rng = np.random.default_rng(7)
    bench = rng.normal(0.0004, 0.01, 400)
    strategy = 0.5 * bench + 0.001 + rng.normal(0.0, 0.0005, 400)
    out = alpha_beta(strategy, bench, 252.0)
    assert abs(float(out["beta"] or 0) - 0.5) < 0.02
    assert abs(float(out["alpha_annual_pct"] or 0) - 25.2) < 3.0  # 0.001 a bar x 252
    assert float(out["alpha_t"] or 0) > 5.0
    assert alpha_beta(strategy[:10], bench[:10], 252.0)["beta"] is None
    assert alpha_beta(strategy, np.zeros(400), 252.0)["beta"] is None
