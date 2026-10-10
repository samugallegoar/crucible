# ADR-0064: Promotion rebalances on the last bar of a timestamp

- **Status**: accepted
- **Date**: 2026-10-07

## Context

`PromotedSignalStrategy` reruns a vectorized signal through the event-driven engine. With more than
one symbol it rebalanced on the first symbol's bar of each timestamp. The engine marks the portfolio
bar by bar, so at that moment the later symbols' marks, and therefore `portfolio.equity`, were one bar
stale, while the vectorized run sizes every weight from the equity after all of the timestamp's bars.
On a two-symbol fixture the promoted and vectorized equity differed by up to 4.7% (4.6% with FX),
recorded as a finding in ADR-0062. Promotion is how a vectorized result is checked against realistic
frictions, so a silent 4.7% disagreement in the frictionless case undermines the check.

## Decision

1. The strategy rebalances **once per timestamp, on the last of that timestamp's bars**. On the first
   bar of a timestamp it counts how many universe symbols have a bar there (a PIT read of each
   symbol's latest bar, all of which are available at that timestamp), then rebalances when it has
   seen that many.
2. A symbol with no bar at a timestamp is not waited for, so staggered calendars still rebalance
   (once per timestamp, on the last bar present).
3. Bars of symbols outside the promoted universe are ignored, and so is a bar that reaches the engine
   after a later timestamp's bar (a slower feed): the timestamp was already decided, so it never
   rebalances backwards (review finding; before the guard such a feed doubled the rebalances).
   Limit: when one symbol's bar becomes *available* later than another's at the same timestamp, only
   the bars available when the first arrives are counted, so the decision is taken with the late
   symbol's mark stale, exactly as before this change.
4. The bookkeeping lives in `ctx.state` (`seen_ts`, `seen`, `expected`, `rebalanced_ts`), so it is
   checkpointed with the rest of the strategy's state. The old `last_event_time` key is gone.

## Alternatives considered

- **Compute equity inside the strategy from PIT prices.** Avoids waiting, but would duplicate the
  engine's valuation (multi-currency cash in each currency, marks, multipliers) and could drift from
  it; rejected.
- **Keep rebalancing on the first bar and accept the gap.** Rejected: it is the conservative-looking
  choice that silently misstates the frictionless baseline.

## Consequences

- A two-symbol promoted run now agrees with the vectorized run: maximum relative equity difference
  9.9e-9 (USD only) and 7.1e-9 (one EUR symbol) over 30 bars, from 4.7% and 4.6%
  (`tests/integration/test_vectorized_fx_promotion.py`). The bound in the test is 1e-6.
- Orders are still submitted on a bar of the timestamp and fill at the next bar's open, so timing
  against the engine is unchanged for one symbol (single-symbol results are byte-identical).
- A multi-symbol promoted run's results change (they move towards the vectorized run); no golden
  fixture covers one. Cost: one extra latest-bar history read per timestamp.
- Fix found by the new resume-equivalence test: the strategy kept its settings on `self`, so the engine
  refused to checkpoint any promoted run (ADR-0048). The settings are now read from `ctx.params` on each
  call, and a two-symbol promoted run is in the resume matrix.
- Config hash, artifact schema and checkpoint schema are unchanged (strategy state keys are data).
