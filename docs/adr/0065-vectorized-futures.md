# ADR-0065: Futures multipliers in the vectorized engine

- **Status**: accepted
- **Date**: 2026-10-08

## Context

The vectorized runner refused `data.futures_multipliers` ("no futures MTM/multiplier handling"), the
last piece of Batch F (ADR-0061, ADR-0062). The event-driven engine prices a futures position as
`quantity * price * multiplier`, books no cash at entry and settles the price change to cash every bar
(ADR-0033). A vectorized position is not a quantity but a **fraction of equity**: the bar's pnl is
`weight * return * prior equity`.

## Decision

1. `data.futures_multipliers` is **accepted**. In a fraction-of-equity model the multiplier cancels:
   holding `w * E / (P * m)` contracts earns `w * E * (P1 / P0 - 1)` whatever `m` is. The vectorized
   equity of a futures config therefore equals that of the same config without multipliers; the
   multiplier matters only when positions are whole contracts.
2. **Promotion sizes whole contracts with the multiplier.** `promote_config` carries
   `futures_multipliers` into the promoted strategy's params (only for a futures config, so every other
   promotion keeps its params and experiment id), and `PromotedSignalStrategy` sizes
   `floor(equity * weight / (price * multiplier * fx))`. Before, a promoted futures config would have
   been sized as if the multiplier were 1.
3. **`data.futures_margins` stays refused.** The vectorized engine has no margin requirement, margin
   call or financing; running a config that declares margins would silently ignore them (the
   conservative choice is to refuse).
4. **Bars are taken as a continuous series.** Rolls between contract months, their spread and their
   cost are not modeled; a vectorized futures run assumes the data is already one continuous (rolled or
   back-adjusted) series. The event-driven engine handles explicit rolls (ADR-0033).
5. Positions are **fractional contracts**; whole-contract quantisation appears only in the promoted
   run (owner decision, 2026-10-08: multipliers on a continuous series, not whole contracts, in the
   vectorized path).

## Alternatives considered

- *Whole contracts in the vectorized path:* closer to the event engine for small accounts, but it
  changes the weight-to-return maths and is slower; deferred.
- *Keep refusing:* safe, but it closes the fast path to every futures question that does not need
  margin.

## Consequences

- A vectorized futures config runs; its equity is unchanged by the multiplier. Promoted vs vectorized
  agreement on a 1e12-cash single-symbol fixture (multiplier 10): below 1e-6
  (`tests/integration/test_vectorized_futures_promotion.py`); the first order is
  floor(1e12 * 0.5 / (97.0 * 10)) = 515,463,917 contracts, not the 5,154,639,175 a multiplier of 1 gives.
- With a small account the promoted run rounds to whole contracts and will differ from the vectorized
  run by that rounding; that gap is real, not an error.
- Config hash, artifact schema, checkpoint schema and goldens are unchanged. A futures config's
  vectorized experiment id is new (the config was refused before).
