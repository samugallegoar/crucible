"""Multi-currency equity for the vectorized engine (ADR-0062).

The convention is the event-driven engine's (ADR-0009, ADR-0025): a foreign-currency position is
funded in its own currency, so an FX move changes only the accumulated pnl, never the principal, and
equity is marked at the mid. With ``U[s]`` the symbol's local pnl since inception (realised plus
unrealised, in its own currency), equity is ``initial - costs + sum(fx[s] * U[s])``: no per-currency
cash needs tracking. Pure and deterministic; touches no store.
"""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray


def run_fx_equity(
    *,
    close: NDArray[np.float64],
    weight: NDArray[np.float64],
    fx: NDArray[np.float64],
    initial_cash: float,
    cost_rate: float,
) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    """``close`` (T x S, local currency), ``weight`` (T x S, the lagged weight in force over the
    bar ending at row t), ``fx`` (T x S, each symbol's currency-to-base mid at row t; 1.0 for a
    base-currency symbol). All three share one aligned timestamp grid with no gaps. Returns the
    equity ``(T,)`` after costs and the gross per-symbol per-bar pnl ``(T, S)`` in base currency.

    At row t: ``U`` moves by ``q * dP`` (the quantity ``q`` was set at row t-1), the turnover cost
    ``cost_rate * sum(|w[t] - w[t-1]|) * E[t-1]`` is taken from base cash (the single-currency
    engine's model, ADR-0035), equity is marked, and the quantity for the next bar is set to
    ``w[t+1] * E[t] / (P[t] * fx[t])`` (ADR-0029's sizing). The run starts flat at its first row:
    the weight at row 0 is not held (no pnl) and not traded (no cost), and the first weight actually
    held, at row 1, is entered from flat and charged as such (the pessimistic reading).
    """
    rows, symbols = close.shape
    equity = np.empty(rows, dtype=np.float64)
    pnl = np.zeros((rows, symbols), dtype=np.float64)
    quantity = np.zeros(symbols, dtype=np.float64)
    local_pnl = np.zeros(symbols, dtype=np.float64)
    cumulative_cost = 0.0
    previous_equity = initial_cash
    previous_weight = np.zeros(symbols, dtype=np.float64)  # the run starts flat
    for t in range(rows):
        if t > 0:
            move = quantity * (close[t] - close[t - 1])
            pnl[t] = move * fx[t] + local_pnl * (fx[t] - fx[t - 1])
            local_pnl = local_pnl + move
            turnover = float(np.abs(weight[t] - previous_weight).sum())
            cumulative_cost += cost_rate * turnover * previous_equity
        equity[t] = initial_cash - cumulative_cost + float((fx[t] * local_pnl).sum())
        if t + 1 < rows:
            quantity = weight[t + 1] * equity[t] / (close[t] * fx[t])
        if t > 0:  # the row-0 weight is never held, so the next transition is measured from flat
            previous_weight = weight[t]
        previous_equity = float(equity[t])
    return equity, pnl
