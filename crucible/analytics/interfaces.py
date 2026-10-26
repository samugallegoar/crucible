"""Analytics Protocols: metrics, trade analytics, report rendering.

Reporting rule (AGENTS.md §9): no headline metric ships without CI, trial
count, DSR/PBO, and realism level in the same report. The types here make
that structural: a ``MetricValue`` carries its uncertainty or is not a
headline metric.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import polars as pl


@dataclass(frozen=True, slots=True)
class MetricValue:
    """A point estimate with its confidence interval. ``ci_low``/``ci_high``
    are None for a quantity that is an identity (e.g. total fees paid, a trade
    count) or that this build has no interval for (annualized volatility, hit
    rate): the absence is reported, never invented."""

    value: float
    ci_low: float | None
    ci_high: float | None


class MetricsComputer(Protocol):
    """Computes metrics from an equity curve and trade log."""

    def compute(
        self,
        equity: pl.DataFrame,
        trades: pl.DataFrame,
    ) -> Mapping[str, MetricValue]:
        """Equity frame: ``ts`` (UTC ns) + ``equity`` (base ccy, float).
        Returns metric name -> value with CI."""
        ...


class ReportRenderer(Protocol):
    """Renders a run report. The header block (experiment id, commit, data
     manifests, seed, realism level, mode, trial family/count, contamination
     flags) and the validation summary (``dsr``, ``pbo`` — shown explicitly
     or not at all, never omitted) are mandatory input, not optional garnish
    ."""

    def render(
        self,
        header: Mapping[str, str],
        metrics: Mapping[str, MetricValue],
        equity: pl.DataFrame,
        trades: pl.DataFrame,
        out_dir: Path,
        *,
        validation_summary: Mapping[str, str],
        monte_carlo: Mapping[str, Mapping[str, float]] | None = None,
        factor_regression: Mapping[str, object] | None = None,
    ) -> Path:
        """Writes the report and returns the path to its entry point."""
        ...
