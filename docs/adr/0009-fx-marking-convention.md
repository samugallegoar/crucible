# ADR-0009: FX — equity marked at mid; conversions transact at the adverse side

- **Status**: draft (the original requirements; conservative option chosen, applies from Phase 4)
- **Date**: 2026-09-16

## Context

Multi-currency portfolios need FX rates in two roles: (1) *marking* — 
converting position values and cash into base currency for equity/reporting;
(2) *trading* — actual currency conversions that move cash on the ledger.
Using the same convention for both either overstates costs in reporting or
understates them in trading.

## Decision

- **Marking (equity, exposures, reporting)**: mid rate `as_of` the mark time.
- **Trading (any ledger FX transaction)**: the adverse side of the quoted
  spread for the direction traded, plus configured FX costs.

Both rates come through the PIT accessor with `available_at <= as_of`.
Conservative where money actually moves (pessimism rule); standard and
comparable where it is a valuation.

## Alternatives considered

- **Mid for both**: silently optimistic on every conversion; violates the original requirements
- **Side-aware for both**: equity would jump on the marking side choice
  without any trade occurring, polluting PnL attribution with unrealized
  spread; liquidation-value reporting can be added later as a separate view.

## Consequences

FX PnL attribution must separate marking PnL from realized conversion costs.
Phase 4 accounting tests include a hand-computed multi-currency ledger
exercising both roles.
