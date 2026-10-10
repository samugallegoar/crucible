# ADR-0045: Risk limits use base-currency, multiplier-scaled notional

- **Status**: accepted
- **Date**: 2026-09-25

## Context

ADR-0034 confirmed and deferred two related gaps. `MaxOrderNotionalLimit`,
`MaxGrossExposureLimit`, `MarginRequirementLimit` and `MarginCallLimit`
computed notional as `qty * portfolio.mark(symbol)`. `mark` is in the
symbol's own currency and ignores the futures contract multiplier, while the
thresholds and `equity()` are in base currency. A EUR stock was compared as if
its EUR price were USD, and a futures contract was understated by exactly its
multiplier. The fix needed `PortfolioView` to expose currency- and
instrument-aware notional, which is an interface change.

## Decision

1. `PortfolioView` gains two pure reads, implemented by `PortfolioSnapshot`
   (which already holds the FX mid rates, futures specs and currency map, and
   whose `equity()` and `realized_pnl` already convert the same way):
   - `notional(symbol, qty=None) -> Decimal | None`: base-currency notional of
     `abs(qty)` units at the last mark, `abs(qty) * mark * multiplier * fx_mid`;
     `qty=None` means the held quantity; `None` while unmarked; a missing FX
     rate raises `CrucibleError` (never assumes 1.0).
   - `is_future(symbol) -> bool`.
2. The four limits use `notional`; their private mark-based helpers are gone.
   Their decisions are numerically identical for base-currency, non-futures
   symbols.
3. The pre-trade snapshot is built with the order symbol's currency requested
   (`_current_snapshot(extra_currencies)`), because a first order in a foreign
   currency has no cash or position there yet and would otherwise have no FX
   rate.
4. `MarginRequirementLimit` and `MarginCallLimit` raise `ConfigurationError` on
   a futures symbol (an order in one, or a short position in one). They model
   Reg-T short-equity margin, which is not a futures margin model; ADR-0031 and
   ADR-0034 asked for a refusal rather than a silent miscomputation
   (AGENTS.md section 1.5).
5. `InsufficientCashLimit` is unchanged: it checks per-currency available cash
   and its own gap is documented in ADR-0028.

## Alternatives considered

- **Pass a `RiskContext` (FX rates, futures specs) to every limit.** More
  flexible, but it changes every limit signature and duplicates conversion
  logic across classes that already have a single source of truth in the
  snapshot.
- **Refuse only.** Cheap and honest, but multi-currency and futures runs could
  then not use these limits at all.

## Consequences

- Multi-currency runs now compare notional in base currency; futures notional
  includes the multiplier for `MaxOrderNotionalLimit` and `MaxGrossExposureLimit`.
- A futures run that configured the margin limits now fails with a clear
  message instead of computing a wrong number. A futures-specific margin model
  is deferred.
- A first order in a foreign currency needs an FX dataset covering that
  currency, which holding it would already require.
