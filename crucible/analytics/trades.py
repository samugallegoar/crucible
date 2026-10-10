"""Round-trip trade log built from fills (FIFO lot matching, per symbol).

Gross PnL per round trip in the run's base currency, scaled by the futures
multiplier; ``pnl_price`` values the price move at the entry FX rate and
``pnl_fx`` the rate move on the exit value, and they sum to ``pnl`` (ADR-0049).
Commissions are reported separately on the ledger and in the cost totals —
attribution down to the trade level is not computed.
"""

from __future__ import annotations

import itertools
from collections import deque
from decimal import Decimal

import polars as pl

from crucible.core.errors import CrucibleError

TRADE_SCHEMA: dict[str, pl.DataType] = {
    "symbol": pl.String(),  # instrument identifier
    "entry_ts": pl.Int64(),  # UTC ns; ts of the entry fill (FIFO lot)
    "exit_ts": pl.Int64(),  # UTC ns; ts of the closing fill
    "qty": pl.Float64(),  # positive; direction in `side`
    "side": pl.String(),  # long | short
    "entry_price": pl.Float64(),  # in the symbol's currency
    "exit_price": pl.Float64(),  # in the symbol's currency
    "pnl": pl.Float64(),  # base currency, gross of commissions; = pnl_price + pnl_fx
    "holding_ns": pl.Int64(),  # exit_ts - entry_ts, ns
    "currency": pl.String(),  # the symbol's currency
    "multiplier": pl.Float64(),  # futures contract multiplier, 1.0 for equities
    "pnl_price": pl.Float64(),  # base currency; price move valued at the entry FX rate
    "pnl_fx": pl.Float64(),  # base currency; FX move on the exit value (ADR-0049)
}


def build_trades(fill_rows: list[dict[str, object]]) -> pl.DataFrame:
    """FIFO round trips from engine fill rows (also consumes delisting
    liquidations when passed as fills). Input rows must be time-ordered."""
    # signed qty, price, ts, multiplier, fx_to_base
    lots: dict[str, deque[tuple[Decimal, Decimal, int, Decimal, Decimal]]] = {}
    trades: list[dict[str, object]] = []
    missing = sorted(
        {
            name
            for row in fill_rows
            for name in ("currency", "multiplier", "fx_to_base")
            if name not in row
        }
    )
    if missing:
        msg = (
            f"fill rows lack {missing}; the trade log needs the per-fill currency, "
            "multiplier and FX rate the engine writes since ADR-0047. Re-run the experiment "
            "(rows from an older run or checkpoint cannot be turned into trades)"
        )
        raise CrucibleError(msg)

    for row in fill_rows:
        symbol = str(row["symbol"])
        qty = Decimal(str(row["qty"]))
        signed = qty if row["side"] == "buy" else -qty
        price = Decimal(repr(float(str(row["price"]))))
        ts = int(str(row["ts"]))
        multiplier = Decimal(str(row["multiplier"]))
        fx = Decimal(str(row["fx_to_base"]))
        currency = str(row["currency"])
        queue = lots.setdefault(symbol, deque())

        while signed != 0:
            if not queue or (queue[0][0] > 0) == (signed > 0):
                queue.append((signed, price, ts, multiplier, fx))
                break
            lot_qty, lot_price, lot_ts, lot_mult, lot_fx = queue.popleft()
            matched = min(abs(signed), abs(lot_qty))
            direction = Decimal(1) if lot_qty > 0 else Decimal(-1)
            scale = matched * lot_mult * direction
            pnl = scale * (price * fx - lot_price * lot_fx)
            pnl_price = scale * (price - lot_price) * lot_fx
            pnl_fx = pnl - pnl_price  # so the Decimal identity is exact by construction
            trades.append(
                {
                    "symbol": symbol,
                    "entry_ts": lot_ts,
                    "exit_ts": ts,
                    "qty": float(matched),
                    "side": "long" if lot_qty > 0 else "short",
                    "entry_price": float(lot_price),
                    "exit_price": float(price),
                    "pnl": float(pnl),
                    "holding_ns": ts - lot_ts,
                    "currency": currency,
                    "multiplier": float(lot_mult),
                    "pnl_price": float(pnl_price),
                    "pnl_fx": float(pnl_fx),
                }
            )
            remainder_lot = lot_qty + matched * -direction
            if remainder_lot != 0:
                queue.appendleft((remainder_lot, lot_price, lot_ts, lot_mult, lot_fx))
            signed += matched * direction

    frame = (
        pl.from_dicts(trades, schema=TRADE_SCHEMA) if trades else pl.DataFrame(schema=TRADE_SCHEMA)
    )
    return frame.sort(["exit_ts", "symbol", "entry_ts"])


EPISODE_SCHEMA: dict[str, pl.DataType] = {
    "symbol": pl.String(),  # instrument identifier
    "side": pl.String(),  # long | short (sign of the weight)
    "entry_ts": pl.Int64(),  # UTC ns; close of the bar before the first held bar (own ts if none)
    "exit_ts": pl.Int64(),  # UTC ns; close of the last held bar
    "holding_ns": pl.Int64(),  # exit_ts - entry_ts, ns
    "avg_abs_weight": pl.Float64(),  # mean absolute weight over the held bars (fraction of equity)
    "pnl": pl.Float64(),  # run currency, gross of costs: sum of prior equity * weight * return
}


EPISODE_LABEL = "position episodes, gross of costs"
"""How a vectorized run's trade count is worded in reports: episodes, not fill-level round trips,
and their pnl and hit rate are before the turnover cost model (ADR-0061)."""

_FLAT_EPSILON = 1e-12
"""A weight smaller than this in absolute value is flat: float dust (1e-17 from a rounded sizing
step) must not open a position episode."""


def sign_of(weight: float) -> int:
    return (weight > _FLAT_EPSILON) - (weight < -_FLAT_EPSILON)


def build_episodes(weights: pl.DataFrame, pnl: pl.DataFrame) -> pl.DataFrame:
    """Closed position episodes of a vectorized run (ADR-0061, ADR-0062).

    ``weights`` (``ts``, ``symbol``, ``weight``) is the lagged weight in force over each bar's
    return, so an episode never starts before the information behind it was knowable. ``pnl``
    (``ts``, ``symbol``, ``pnl``) is the engine's gross per-symbol per-bar pnl in the run's
    currency (before costs; for a foreign symbol it includes the FX effect) and only holds the bars
    of the run window. An episode is a maximal run of bars with the same nonzero sign; a flip
    closes one and opens the next. Only closed episodes are returned (a run still held at the last
    bar has no exit), as the event-driven trade log only counts closed round trips. An episode's
    ``pnl`` is the sum of the frame over its held bars, **before costs**: the cost model is a
    per-bar turnover rate, so costs cannot be attributed to an episode without inventing a rule;
    the equity curve is net. Units: ``pnl`` in the run's currency, ``holding_ns`` in nanoseconds;
    a weight within 1e-12 of 0 is flat. An episode already open at the first row of the window is
    clipped to it (its entry is that row's own timestamp); the earlier part is outside the run.
    """
    rows = (
        weights.select("ts", "symbol", "weight")
        .join(pnl.select("ts", "symbol", "pnl"), on=["symbol", "ts"], how="inner")
        .sort(["symbol", "ts"])
        .iter_rows(named=True)
    )
    episodes: list[dict[str, object]] = []
    for symbol, group in itertools.groupby(rows, key=lambda row: str(row["symbol"])):
        series = [(int(row["ts"]), float(row["weight"]), float(row["pnl"])) for row in group]
        index = 0
        while index < len(series):
            weight = series[index][1]
            sign = sign_of(weight)
            if sign == 0:
                index += 1
                continue
            end = index
            episode_pnl = 0.0
            weight_sum = 0.0
            while end < len(series) and sign_of(series[end][1]) == sign:
                _, w_end, pnl_end = series[end]
                episode_pnl += pnl_end
                weight_sum += abs(w_end)
                end += 1
            if end < len(series):  # a later bar has a different sign: the episode is closed
                entry_ts = series[index - 1][0] if index > 0 else series[index][0]
                exit_ts = series[end - 1][0]
                episodes.append(
                    {
                        "symbol": symbol,
                        "side": "long" if sign > 0 else "short",
                        "entry_ts": entry_ts,
                        "exit_ts": exit_ts,
                        "holding_ns": exit_ts - entry_ts,
                        "avg_abs_weight": weight_sum / (end - index),
                        "pnl": episode_pnl,
                    }
                )
            index = end
    frame = (
        pl.from_dicts(episodes, schema=EPISODE_SCHEMA)
        if episodes
        else pl.DataFrame(schema=EPISODE_SCHEMA)
    )
    return frame.sort(["exit_ts", "symbol", "entry_ts"])
