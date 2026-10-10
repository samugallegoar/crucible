"""Per-strategy PnL attribution, correlation, and marginal risk
contribution (ADR-0030).

Attribution is **realized cash flow only** (fill notional minus
commission, tagged by ``strategy_id``), never unrealized mark-to-market.
Each fill is valued at ``(±qty * price * multiplier - commission) *
fx_to_base`` (ADR-0047): converted to the run's base currency at the mid rate
of the fill's timestamp (FX PnL is not separated from price PnL) and, for a
futures fill, at its full notional times the contract multiplier, so a round
trip sums to the realized PnL ``(exit - entry) * qty * multiplier`` -- not to
the ledger's variation-margin timing, which books opening fills at zero and
settles marks without a strategy tag.

Unrealized PnL is left out because strategies share one portfolio/one
ledger, so an *open* position has no
single owner to attribute unrealized PnL to when more than one strategy
could plausibly have contributed to it. Realized cash flow has no such
ambiguity -- every fill is one order, one order belongs to at most one
strategy -- and is exact whenever a strategy trades a symbol no other
strategy touches (the common case this module is designed for). A fill
with no ``strategy_id`` (single-strategy runs, or an engine-generated
order like a risk-engine FLATTEN, ADR-0027) buckets into
``UNATTRIBUTED`` and is excluded from the strategy columns.

Correlation and marginal risk contribution operate on *raw dollar* PnL
deltas per period, not normalized returns: correlation is scale-invariant
so this makes no difference to it, and there is no natural "notional" to
divide by when strategies share one capital pool with no separate
per-strategy allocation.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
import polars as pl

from crucible.core.errors import CrucibleError

if TYPE_CHECKING:
    from collections.abc import Sequence

UNATTRIBUTED = "__unattributed__"


def per_strategy_pnl_deltas(
    fill_rows: list[dict[str, object]], period_ts: Sequence[int]
) -> pl.DataFrame:
    """Wide frame: ``ts`` (each element of ``period_ts``, ascending) plus
    one float column per ``strategy_id`` seen in ``fill_rows`` (and
    ``UNATTRIBUTED`` if any fill carries no tag) -- realized cash flow
    (``qty*price`` signed by side, minus commission) summed over fills
    whose ``ts`` falls in ``(period_ts[i-1], period_ts[i]]`` (``i=0``:
    everything at or before ``period_ts[0]``). Missing period/strategy
    combinations are ``0.0``, never null -- a strategy that didn't trade
    in a period contributed no PnL that period, which is a fact, not
    missing data."""
    periods = list(period_ts)
    if not periods:
        msg = "period_ts must be non-empty"
        raise CrucibleError(msg)
    if not fill_rows:
        return pl.DataFrame({"ts": periods})
    missing = sorted(
        {name for r in fill_rows for name in ("multiplier", "fx_to_base") if name not in r}
    )
    if missing:
        msg = (
            f"fill rows lack {missing}; attribution needs the per-fill multiplier and "
            "FX rate the engine writes since ADR-0047. Re-run the experiment (rows from "
            "an older run or checkpoint cannot be attributed)"
        )
        raise CrucibleError(msg)

    period_bounds = np.array(periods, dtype=np.int64)
    ts = np.array([int(str(r["ts"])) for r in fill_rows], dtype=np.int64)
    period_idx = np.searchsorted(period_bounds, ts, side="left")
    if (period_idx >= len(period_bounds)).any():
        msg = "a fill's ts falls after the last period_ts boundary"
        raise CrucibleError(msg)

    qty = np.array([float(str(r["qty"])) for r in fill_rows])
    price = np.array([float(str(r["price"])) for r in fill_rows])
    side = np.array([str(r["side"]) for r in fill_rows])
    commission = np.array([float(str(r["commission"])) for r in fill_rows])
    multiplier = np.array([float(str(r["multiplier"])) for r in fill_rows])
    fx_to_base = np.array([float(str(r["fx_to_base"])) for r in fill_rows])
    signed_notional = np.where(side == "sell", qty * price, -qty * price) * multiplier
    cash_flow = (signed_notional - commission) * fx_to_base
    strategy_id = [
        str(r["strategy_id"]) if r.get("strategy_id") else UNATTRIBUTED for r in fill_rows
    ]

    grouped = (
        pl.DataFrame({"period": period_idx, "strategy_id": strategy_id, "cash_flow": cash_flow})
        .group_by(["period", "strategy_id"])
        .agg(pl.col("cash_flow").sum())
    )
    wide = grouped.pivot(on="strategy_id", index="period", values="cash_flow")
    grid = pl.DataFrame(
        {"period": np.arange(len(period_bounds), dtype=np.int64), "ts": period_bounds}
    )
    result = grid.join(wide, on="period", how="left").drop("period")
    strategy_cols = sorted(c for c in result.columns if c != "ts")
    return result.select(["ts", *strategy_cols]).fill_null(0.0)


def _strategy_columns(pnl_deltas: pl.DataFrame) -> list[str]:
    return [c for c in pnl_deltas.columns if c not in ("ts", UNATTRIBUTED)]


def strategy_correlation(pnl_deltas: pl.DataFrame) -> pl.DataFrame:
    """Pearson correlation matrix across strategy columns (excludes ``ts``
    and ``UNATTRIBUTED``). Long format: ``strategy_id``, ``other_id``,
    ``correlation`` -- easier to filter/join than a wide matrix, and
    avoids relying on column-name ordering to read a cell back out."""
    cols = _strategy_columns(pnl_deltas)
    if len(cols) < 2:
        msg = f"need >= 2 strategies to compute correlation, got {len(cols)}"
        raise CrucibleError(msg)
    matrix = pnl_deltas.select(cols).to_numpy()
    if matrix.shape[0] < 2:
        msg = f"need >= 2 periods to compute correlation, got {matrix.shape[0]}"
        raise CrucibleError(msg)
    corr = np.corrcoef(matrix, rowvar=False)
    rows = [
        {"strategy_id": a, "other_id": b, "correlation": float(corr[i, j])}
        for i, a in enumerate(cols)
        for j, b in enumerate(cols)
    ]
    return pl.DataFrame(rows)


def marginal_risk_contribution(pnl_deltas: pl.DataFrame) -> dict[str, float]:
    """``MRC_i = Cov(pnl_i, portfolio_pnl) / SD(portfolio_pnl)`` where
    ``portfolio_pnl = sum of the strategy columns`` (``UNATTRIBUTED``
    excluded, see module docstring). By the covariance decomposition of a
    sum, ``sum_i MRC_i == SD(portfolio_pnl)`` exactly -- every marginal
    contribution accounts for exactly its share of total portfolio risk,
    with nothing left over. Returns ``0.0`` for every strategy if the
    portfolio series has zero variance (e.g. every period's PnL is
    identical); raises if there are fewer than 2 periods, since a sample
    standard deviation (``ddof=1``) is undefined for one point."""
    cols = _strategy_columns(pnl_deltas)
    if not cols:
        msg = "no strategy columns to compute risk contribution"
        raise CrucibleError(msg)
    matrix = pnl_deltas.select(cols).to_numpy()
    if matrix.shape[0] < 2:
        msg = f"need >= 2 periods to compute risk contribution, got {matrix.shape[0]}"
        raise CrucibleError(msg)
    portfolio = matrix.sum(axis=1)
    portfolio_sd = float(np.std(portfolio, ddof=1))
    if portfolio_sd == 0.0:
        return dict.fromkeys(cols, 0.0)
    return {
        col: float(np.cov(matrix[:, i], portfolio, ddof=1)[0, 1]) / portfolio_sd
        for i, col in enumerate(cols)
    }
