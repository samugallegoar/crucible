"""Return-sequence risk for the one-step backtest: a summary block and its fixed table (ADR-0083).

Resamples the finished run's own history (its per-bar returns, and its trades) and reports how much
the outcome depends on the sample: the spread of final value, of the worst drawdown, the chance of
finishing below the start and of touching a ruin level. Built on ``validation.paths``.

This is **not** evidence of an edge, and the table says so in its own text: a resampled history is
centred on the realized result, so a lucky or overfit backtest also looks safe here. The edge
evidence lives in the main table (the Sharpe range, the deflated Sharpe, the shuffled-returns
p-value, the cost and realism rows).

Failures here are recorded in the block (``error``), never raised: a supplementary distribution
must not be able to sink a backtest.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from crucible.core.errors import ConfigurationError
from crucible.product.table import NOT_AVAILABLE, to_grid_markdown
from crucible.validation import paths

SEED_KEY = 83
"""Spawn key of this module's random streams (ADR-0083): the bar and trade bootstraps are seeded
from the experiment seed and never share a stream with the null test or the reality check."""
N_PATHS = 1_000
FAN_POINTS = 60

NOTE = (
    "Sequence risk, not evidence of an edge: this resamples the one history above, so it shows "
    "how much luck is in the order and sampling of the returns, and it is centred on the result "
    "that was realized. Whether the strategy has an edge is what the Sharpe range, the deflated "
    "Sharpe, the shuffled-returns p-value and the cost rows above are for."
)

COLUMNS: tuple[str, str, str] = ("Metric", "Resampled bars", "Resampled trades")

ROW_IDS: tuple[str, ...] = (
    "resampling",
    "final_value",
    "max_drawdown",
    "prob_loss",
    "prob_ruin",
    "prob_drawdown",
)
"""The rows of the sequence table, in order (additive-only, like the main table's)."""


def build_sequence_risk(
    net_returns: np.ndarray,
    trade_changes_pct: list[float],
    trade_weights: list[float],
    per_side_bps: float,
    seed: int,
) -> dict[str, Any]:
    """The ``sequence_risk`` block of the result document.

    ``trade_changes_pct`` are each trade's signed price change in percent, ``trade_weights`` the
    average fraction of equity it held; a trade's return on equity is its price change less the
    round-trip cost, times that fraction.
    """
    block: dict[str, Any] = {"kind": paths.KIND, "note": NOTE, "bars": None, "trades": None}
    try:
        bars = paths.simulate_return_paths(
            net_returns,
            np.random.default_rng(np.random.SeedSequence([seed, SEED_KEY, 1])),
            n_paths=N_PATHS,
            fan_points=FAN_POINTS,
        )
        block["bars"] = bars.as_dict()
    except ConfigurationError as exc:
        block["bars_error"] = str(exc)
    on_equity = [
        (change / 100.0 - 2.0 * per_side_bps / 10_000.0) * weight
        for change, weight in zip(trade_changes_pct, trade_weights, strict=True)
    ]
    try:
        trades = paths.simulate_trade_paths(
            on_equity,
            np.random.default_rng(np.random.SeedSequence([seed, SEED_KEY, 2])),
            n_paths=N_PATHS,
            fan_points=2,
        )
        summary = trades.as_dict()
        summary.pop("fan")  # the fan is drawn for bars; a trade count is not a calendar
        summary.pop("fan_steps")
        block["trades"] = summary
    except ConfigurationError as exc:
        block["trades_error"] = str(exc)
    return block


def _pct(value: float) -> str:
    return f"{value * 100:.1f}%"


def _money(capital: float, multiple: float) -> str:
    return f"${capital * multiple:,.0f}"


def _column(summary: dict[str, Any] | None, capital: float, noun: str) -> dict[str, str]:
    if summary is None:
        return dict.fromkeys(ROW_IDS, NOT_AVAILABLE)
    final, drawdown = summary["terminal_multiple"], summary["max_drawdown"]
    block = summary["mean_block"]
    how = (
        f"{summary['horizon']} {noun}, blocks of about {block:.1f}"
        if block is not None
        else f"{summary['horizon']} {noun}, drawn one at a time"
    )
    return {
        "resampling": how,
        "final_value": " / ".join(_money(capital, final[k]) for k in ("p05", "p50", "p95")),
        "max_drawdown": " / ".join(_pct(drawdown[k]) for k in ("p50", "p05")),
        "prob_loss": _pct(summary["prob_loss"]),
        "prob_ruin": _pct(summary["prob_ruin"]),
        "prob_drawdown": _pct(summary["prob_drawdown_worse_than_threshold"]),
    }


def build_sequence_table(block: dict[str, Any], capital: float) -> dict[str, Any]:
    """The fixed sequence table for a ``sequence_risk`` block: the same rows and formats every
    run, ``n/a`` where a resampling could not run. ``markdown`` ends with the note that this is
    sequence risk, so pasting it keeps the distinction."""
    bars = _column(block.get("bars"), capital, "bars")
    trades = _column(block.get("trades"), capital, "trades")
    ref = block.get("bars") or block.get("trades") or {}
    ruin = float(ref.get("ruin_loss", paths.DEFAULT_RUIN_LOSS))
    threshold = float(ref.get("drawdown_threshold", paths.DEFAULT_DRAWDOWN_THRESHOLD))
    labels = {
        "resampling": "Resampled history",
        "final_value": "Final value: 5th / median / 95th percentile",
        "max_drawdown": "Worst fall: median / 5th percentile",
        "prob_loss": "Chance of finishing below the start",
        "prob_ruin": f"Chance of ever being down {ruin * 100:.0f}%",
        "prob_drawdown": f"Chance of a fall worse than {abs(threshold) * 100:.0f}%",
    }
    rows = [
        {"id": row_id, "label": labels[row_id], "bars": bars[row_id], "trades": trades[row_id]}
        for row_id in ROW_IDS
    ]
    grid = [list(COLUMNS)] + [[r["label"], r["bars"], r["trades"]] for r in rows]
    markdown = to_grid_markdown(grid) + "\n\n*" + NOTE + "*"
    return {"columns": list(COLUMNS), "rows": rows, "note": NOTE, "markdown": markdown}
