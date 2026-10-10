# ADR-0049: Trade PnL split and cross-currency buying power

- **Status**: accepted
- **Date**: 2026-09-25

## Context

ADR-0034 and ADR-0047 closed the FX and futures-multiplier gaps in the risk
limits and in attribution but left two related ones. The trade log
(`analytics/trades.py`) computed `(exit - entry) * qty` in the symbol's own
currency with no futures multiplier and no FX, and a report could not tell how
much of a foreign trade's PnL came from the price and how much from the
exchange rate. `InsufficientCashLimit` compared a BUY's own-currency cost with
base-currency cash, and it rejected a futures BUY for lacking cash although no
cash is paid to open a future (ADR-0033).

## Decision

1. **The trade log values each FIFO lot with its fill's `multiplier` and
   `fx_to_base`** (the columns fill rows carry since ADR-0047). For a matched
   lot with entry price `pe` and rate `fe`, exit price `px` and rate `fx`,
   quantity `q`, multiplier `m` and direction `d` (+1 long, -1 short):
   `pnl = d*q*m*(px*fx - pe*fe)`, `pnl_price = d*q*m*(px - pe)*fe`,
   `pnl_fx = d*q*m*px*(fx - fe)`, computed in the code as `pnl - pnl_price` so
   the identity `pnl_price + pnl_fx == pnl` holds exactly in Decimal (the float
   output columns agree to float precision). `currency` and `multiplier` are new columns; entry and exit
   prices stay in the symbol's currency. Fill rows lacking `currency`,
   `multiplier` or `fx_to_base` are refused with the missing names.
2. **Buying power is the total available cash across currencies converted to
   base** (`PortfolioView.available_cash_total`), compared with the order's
   base-currency notional (`PortfolioView.notional`, ADR-0045). The engine keeps
   one balance per currency, lets a foreign balance go negative (financed,
   ADR-0032) and offers strategies no FX conversion API (ADR-0025), so a strict
   per-currency check would block every foreign purchase.
3. **A futures BUY is allowed by `InsufficientCashLimit`**: no cash changes hands
   to open a futures position; margin is the concern of the margin limits
   (ADR-0050).

## Alternatives considered

- **A strict per-currency cash check.** Blocks all foreign buys given no
  conversion API.
- **Splitting FX from price in attribution.** Needs lot matching there; the
  trade log already has it, and attribution stays as ADR-0047 defines it.

## Consequences

- `trades.parquet` gained four columns and `pnl` is now base-currency and
  multiplier-scaled; the golden `trades.parquet` hash was regenerated (only it
  moved). A base-currency equity trade has `pnl_fx == 0` and the same `pnl`.
- FX PnL is measured per lot at its entry and exit rates only; it is not a
  carry or a book-level FX exposure figure.
- Single-currency runs see numerically identical cash checks.
