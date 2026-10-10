"""Equity/drawdown plot as deterministic SVG.

SVG rather than PNG so the output is byte-stable: matplotlib is pinned by
uv.lock, the hash salt is fixed, and the creation date is stripped
(ADR-0011). Wall-clock never leaks into artifacts.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import matplotlib
import numpy as np

matplotlib.use("Agg")  # never a display backend; import order matters
import matplotlib.pyplot as plt

if TYPE_CHECKING:
    from pathlib import Path

    import polars as pl


def plot_equity_drawdown(equity: pl.DataFrame, out_path: Path) -> Path:
    """Two-panel equity + drawdown figure; ``equity`` has ``ts`` and ``equity``."""
    matplotlib.rcParams["svg.hashsalt"] = "crucible"
    frame = equity.sort("ts")
    ts_days = frame.get_column("ts").to_numpy() / 86_400e9
    values = frame.get_column("equity").to_numpy()
    peaks = np.maximum.accumulate(values)
    drawdown = (values - peaks) / peaks

    fig, (ax_eq, ax_dd) = plt.subplots(2, 1, figsize=(10, 6), sharex=True, height_ratios=[3, 1])
    ax_eq.plot(ts_days, values, linewidth=1.2)
    ax_eq.set_ylabel("Equity")
    ax_eq.grid(True, alpha=0.3)
    ax_dd.fill_between(ts_days, drawdown, 0.0, alpha=0.6)
    ax_dd.set_ylabel("Drawdown")
    ax_dd.set_xlabel("Days (UTC, epoch-relative)")
    ax_dd.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(out_path, format="svg", metadata={"Date": None})
    plt.close(fig)
    return out_path
