"""The one results table of the one-step backtest (ADR-0077).

Every surface that shows the headline numbers (the terminal, the HTML report, the JSON document and
so the MCP tool) takes them from :func:`build_results_table`, so the rows, their order, their labels
and their number formats are the same everywhere and from run to run. A value that does not exist
(no benchmark trades, no Sharpe interval, no null test) is the text ``n/a``/``-``, never a missing
row: a reader, human or agent, can rely on the shape.

The rows come in three kinds: the outcome (what the account did), the evidence (what survives
costs, per trade, and against holding the benchmark) and the validation (how much searching went
into the result and how it holds up against luck). Units: percentages are in percent, money in the
account currency, costs and per-trade returns in basis points. Timing: the table is derived from
the finished result document, so it knows nothing the document does not.
"""

from __future__ import annotations

from typing import Any

ROW_IDS: tuple[str, ...] = (
    "final_value",
    "total_return",
    "return_per_year",
    "cost_drag_per_year",
    "turnover_per_year",
    "break_even_cost",
    "volatility_per_year",
    "worst_fall",
    "sharpe",
    "alpha_beta",
    "return_per_exposure",
    "trades",
    "winning_trades",
    "net_expectancy",
    "profit_factor",
    "payoff_ratio",
    "avg_bars_held",
    "time_in_market",
    "trial_count",
    "deflated_sharpe",
    "shuffle_p_value",
    "realism_retention",
    "realism_level",
)
"""The rows, in order. Adding one is additive; removing or renaming one bumps ``schema_version``."""

COLUMNS: tuple[str, str, str] = ("Metric", "Strategy", "Buy and hold")
NOT_AVAILABLE = "n/a"
NOT_APPLICABLE = "-"


def _num(value: object, fmt: str, suffix: str = "") -> str:
    return NOT_AVAILABLE if value is None else f"{float(str(value)):{fmt}}{suffix}"


def _money(value: object) -> str:
    return NOT_AVAILABLE if value is None else f"${float(str(value)):,.0f}"


def _pct(value: object, *, signed: bool = False) -> str:
    return _num(value, "+.1f" if signed else ".1f", "%")


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


def _break_even(diag: dict[str, Any]) -> str:
    assumed = diag.get("assumed_cost_bps_per_side")
    if assumed is None or float(assumed) <= 0:
        return f"{NOT_AVAILABLE} (no costs assumed)"
    value = diag.get("break_even_bps_per_side")
    if value is None:
        return f"{NOT_AVAILABLE} (assumed {float(assumed):.1f} bps)"
    if float(value) <= 0:
        return f"0.0 bps (loses money before costs; assumed {float(assumed):.1f})"
    return f"{float(value):.1f} bps (assumed {float(assumed):.1f})"


def _expectancy(trade: dict[str, Any]) -> str:
    mean = trade.get("expectancy_bps")
    if mean is None:
        return NOT_AVAILABLE
    low, high = trade.get("expectancy_low_bps"), trade.get("expectancy_high_bps")
    if low is None or high is None:
        return f"{float(mean):+.1f} bps (range {NOT_AVAILABLE})"
    return f"{float(mean):+.1f} bps ({float(low):+.1f} to {float(high):+.1f})"


def _alpha_beta(ab: dict[str, Any]) -> str:
    alpha = ab.get("alpha_annual_pct")
    if alpha is None:
        return NOT_AVAILABLE
    t = ab.get("alpha_t")
    t_text = NOT_AVAILABLE if t is None else f"{float(t):+.1f}"
    return f"{float(alpha):+.1f}% (t {t_text}), beta {float(ab['beta']):.2f}"


def _realism_retention(validation: dict[str, Any], strat: dict[str, Any]) -> str:
    check = validation.get("realism_check")
    if check is None:
        return "not run"
    base, tested = float(strat["sharpe"]), float(check["sharpe"])
    if base <= 0:
        return f"{NOT_AVAILABLE} (Sharpe {tested:.2f} vs {base:.2f}; no positive Sharpe to keep)"
    return f"{tested / base * 100:.0f}% (Sharpe {tested:.2f} of {base:.2f})"


def build_results_table(doc: dict[str, Any]) -> dict[str, Any]:
    """The fixed table for a result document (``results``, ``validation``, ``trades``, and the
    ``diagnostics`` block when present).

    Returns ``{"columns": [...], "rows": [{"id", "label", "strategy", "benchmark"}, ...],
    "markdown": "..."}``. Every cell is already formatted text; ``markdown`` is the same table
    ready to paste, and is what an agent should show instead of composing its own.
    """
    results, validation = doc["results"], doc["validation"]
    strat, bench = results["strategy"], results["benchmark"]
    trades: list[dict[str, Any]] = doc["trades"]
    diag: dict[str, Any] = doc.get("diagnostics") or {}
    trade_net: dict[str, Any] = diag.get("trade_net") or {}
    null = validation.get("null_test")
    dsr = validation.get("dsr")
    na, dash = NOT_AVAILABLE, NOT_APPLICABLE
    profit_factor, payoff = trade_net.get("profit_factor"), trade_net.get("payoff_ratio")
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
            "Return per year (after costs)",
            _pct(strat["cagr_pct"]),
            _pct(bench["cagr_pct"]),
        ),
        "cost_drag_per_year": ("Cost drag per year", _pct(diag.get("cost_drag_pct")), dash),
        "turnover_per_year": (
            "Turnover per year (x capital)",
            _num(diag.get("turnover_per_year"), ".1f", "x"),
            dash,
        ),
        "break_even_cost": ("Break-even cost per side", _break_even(diag), dash),
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
        "alpha_beta": (
            "Alpha per year vs buy and hold",
            _alpha_beta(diag.get("alpha_beta") or {}),
            dash,
        ),
        "return_per_exposure": (
            "Return per year per unit of exposure",
            _pct(diag.get("return_per_exposure_pct")),
            _pct(bench["cagr_pct"]),
        ),
        "trades": ("Completed trades", str(strat.get("n_trades", na)), dash),
        "winning_trades": (
            "Winning trades (after costs)",
            _pct(trade_net.get("win_rate_pct")),
            dash,
        ),
        "net_expectancy": ("Net expectancy per trade", _expectancy(trade_net), dash),
        "profit_factor": (
            "Profit factor (net)",
            na if profit_factor is None else f"{float(profit_factor):.2f}",
            dash,
        ),
        "payoff_ratio": (
            "Average win / average loss (net)",
            na if payoff is None else f"{float(payoff):.2f}",
            dash,
        ),
        "avg_bars_held": ("Average bars held", _mean_bars_held(trades), dash),
        "time_in_market": ("Time in the market", _pct(strat.get("time_in_market_pct")), "100.0%"),
        "trial_count": ("Variants tried (trial count)", str(validation["trial_count"]), dash),
        "deflated_sharpe": (
            "Deflated Sharpe (chance it beats luck)",
            na if dsr is None else f"{float(dsr) * 100:.0f}%",
            dash,
        ),
        "shuffle_p_value": (
            "Shuffled-returns p-value",
            na if null is None else f"{float(null['p_value']):.3f}",
            dash,
        ),
        "realism_retention": (
            "Sharpe kept under realistic fills",
            _realism_retention(validation, strat),
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
