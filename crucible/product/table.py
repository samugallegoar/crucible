"""The one results table of the one-step backtest (ADR-0077).

Every surface that shows the headline numbers (the terminal, the HTML report, the JSON document and
so the MCP tool) takes them from :func:`build_results_table`, so the rows, their order, their labels
and their number formats are the same everywhere and from run to run. A value that does not exist
(no benchmark trades, no Sharpe interval, no null test) is the text ``n/a``/``-``, never a missing
row: a reader, human or agent, can rely on the shape.

Units: percentages are in percent, money in the account currency. Timing: the table is derived from
the finished result document, so it knows nothing the document does not.
"""

from __future__ import annotations

from typing import Any

ROW_IDS: tuple[str, ...] = (
    "final_value",
    "total_return",
    "return_per_year",
    "volatility_per_year",
    "worst_fall",
    "sharpe",
    "trades",
    "winning_trades",
    "avg_bars_held",
    "time_in_market",
    "trial_count",
    "deflated_sharpe",
    "shuffle_p_value",
    "realism_level",
)
"""The rows, in order. Adding one is additive; removing or renaming one bumps ``schema_version``."""

COLUMNS: tuple[str, str, str] = ("Metric", "Strategy", "Buy and hold")
NOT_AVAILABLE = "n/a"
NOT_APPLICABLE = "-"


def _money(value: object) -> str:
    return NOT_AVAILABLE if value is None else f"${float(str(value)):,.0f}"


def _pct(value: object, *, signed: bool = False) -> str:
    if value is None:
        return NOT_AVAILABLE
    return f"{float(str(value)):{'+' if signed else ''}.1f}%"


def _sharpe(side: dict[str, Any]) -> str:
    value = side.get("sharpe")
    if value is None:
        return NOT_AVAILABLE
    low, high = side.get("sharpe_low"), side.get("sharpe_high")
    if low is None or high is None:
        return f"{float(value):.2f} (range {NOT_AVAILABLE})"
    return f"{float(value):.2f} ({float(low):.2f} to {float(high):.2f})"


def _mean_bars_held(trades: list[dict[str, Any]]) -> str:
    if not trades:
        return NOT_AVAILABLE
    return f"{sum(float(t['bars_held']) for t in trades) / len(trades):.1f}"


def build_results_table(doc: dict[str, Any]) -> dict[str, Any]:
    """The fixed table for a result document (``results``, ``validation``, ``trades``).

    Returns ``{"columns": [...], "rows": [{"id", "label", "strategy", "benchmark"}, ...],
    "markdown": "..."}``. Every cell is already formatted text; ``markdown`` is the same table
    ready to paste, and is what an agent should show instead of composing its own.
    """
    results, validation = doc["results"], doc["validation"]
    strat, bench = results["strategy"], results["benchmark"]
    trades: list[dict[str, Any]] = doc["trades"]
    null = validation.get("null_test")
    dsr = validation.get("dsr")
    na, dash = NOT_AVAILABLE, NOT_APPLICABLE
    cells: dict[str, tuple[str, str, str]] = {
        "final_value": (
            "Final value",
            _money(strat["final_equity"]),
            _money(bench["final_equity"]),
        ),
        "total_return": (
            "Total return",
            _pct(strat["total_return_pct"], signed=True),
            _pct(bench["total_return_pct"], signed=True),
        ),
        "return_per_year": (
            "Return per year",
            _pct(strat["cagr_pct"]),
            _pct(bench["cagr_pct"]),
        ),
        "volatility_per_year": (
            "Volatility (per year)",
            _pct(strat["volatility_pct"]),
            _pct(bench["volatility_pct"]),
        ),
        "worst_fall": (
            "Worst fall from a peak",
            _pct(strat["max_drawdown_pct"]),
            _pct(bench["max_drawdown_pct"]),
        ),
        "sharpe": ("Sharpe ratio (95% range)", _sharpe(strat), _sharpe(bench)),
        "trades": ("Completed trades", str(strat.get("n_trades", na)), dash),
        "winning_trades": (
            "Winning trades (before costs)",
            _pct(strat.get("hit_rate_pct")),
            dash,
        ),
        "avg_bars_held": ("Average bars held", _mean_bars_held(trades), dash),
        "time_in_market": ("Time in the market", _pct(strat.get("time_in_market_pct")), "100.0%"),
        "trial_count": ("Variants tried (trial count)", str(validation["trial_count"]), dash),
        "deflated_sharpe": (
            "Chance the Sharpe is real (deflated)",
            na if dsr is None else f"{float(dsr) * 100:.0f}%",
            dash,
        ),
        "shuffle_p_value": (
            "Shuffled-returns p-value",
            na if null is None else f"{float(null['p_value']):.3f}",
            dash,
        ),
        "realism_level": ("Realism level", str(validation["realism_level"]), dash),
    }
    rows = [
        {
            "id": row_id,
            "label": cells[row_id][0],
            "strategy": cells[row_id][1],
            "benchmark": cells[row_id][2],
        }
        for row_id in ROW_IDS
    ]
    return {"columns": list(COLUMNS), "rows": rows, "markdown": to_markdown(rows)}


def to_markdown(rows: list[dict[str, str]]) -> str:
    """A pipe table with aligned columns; the same rows always give the same text."""
    grid = [list(COLUMNS)] + [[r["label"], r["strategy"], r["benchmark"]] for r in rows]
    widths = [max(len(line[i]) for line in grid) for i in range(3)]

    def line(cells: list[str]) -> str:
        return "| " + " | ".join(c.ljust(w) for c, w in zip(cells, widths, strict=True)) + " |"

    separator = "| " + " | ".join("-" * w for w in widths) + " |"
    return "\n".join([line(grid[0]), separator, *(line(g) for g in grid[1:])])


def to_text(rows: list[dict[str, str]]) -> str:
    """The same rows as plain aligned text, for the terminal."""
    grid = [list(COLUMNS)] + [[r["label"], r["strategy"], r["benchmark"]] for r in rows]
    widths = [max(len(line[i]) for line in grid) for i in range(2)]
    return "\n".join(
        f"  {line[0].ljust(widths[0])}  {line[1].ljust(widths[1])}  {line[2]}" for line in grid
    )
