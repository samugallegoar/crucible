# ADR-0050: Futures margin model

- **Status**: accepted
- **Date**: 2026-09-25

## Context

`MarginRequirementLimit` and `MarginCallLimit` implement a Reg-T short-equity
model (ADR-0031), which is the wrong model for futures; ADR-0045 made them
refuse futures symbols. Futures margin is quoted by exchanges as a fixed
amount per contract (initial and maintenance), and equity already includes
futures mark-to-market (ADR-0033).

## Decision

1. `FuturesSpec` gains optional per-contract `initial_margin` and
   `maintenance_margin` in the contract's currency: both or neither, and
   `initial >= maintenance > 0` (`ConfigurationError` otherwise). Config:
   `data.futures_margins: {SYMBOL: {initial, maintenance}}`; each symbol must
   also appear in `futures_multipliers`.
2. `PortfolioView.margin_required(symbol, qty=None, kind)` returns the
   base-currency margin for `abs(qty)` contracts (default: the held quantity),
   FX-converted; `None` for a non-future or a spec without margins; a missing FX
   rate raises.
3. The two margin limits gain a futures leg added to the Reg-T short-equity
   leg and compared with equity. `MarginRequirementLimit` rejects an order that
   raises the sum of initial margins (over all held futures with the order
   applied) plus `initial_margin_rate` times short-equity notional above equity;
   a futures order that reduces `|position|` is always allowed (risk may leave
   freely, the pessimism rule); equality `equity == required` is allowed.
   `MarginCallLimit` uses maintenance margins and FLATTENs the whole book
   (ADR-0031's simplification stays).
4. A futures symbol without margins under a margin limit is refused: at engine
   construction (`ConfigurationError` naming the symbols) and, as a backstop,
   at check time.
5. Margin is a requirement, not a ledger transfer: no cash moves.

## Alternatives considered

- **Percent of notional.** Simpler to configure across price moves, but not how
  exchanges quote margin.
- **Portfolio (SPAN-style) margining.** Out of scope: needs risk arrays and
  offsets between contracts.
- **Partial (targeted) liquidation on a margin call.** A harder optimisation
  than the whole-book FLATTEN that ADR-0027 and ADR-0031 already test.

## Consequences

- Futures runs can now use the margin limits. The golden `config.yaml` hash and
  `experiment_id` changed because `DataConfig` gained a serialized field; every
  simulation artifact was byte-identical (README records it).
- The comparison mixes mark-to-market equity with a fixed requirement: a
  strategy near the limit sees rejections a broker's intraday margin would also
  give. The vectorized engine and the live runtime still refuse futures.
- Deferred: percent or SPAN margin, partial liquidation, futures commission and
  tick-size modelling.
