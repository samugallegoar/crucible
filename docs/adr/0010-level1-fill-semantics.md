# ADR-0010: Level 0/1 fill semantics

- **Status**: accepted
- **Date**: 2026-09-16

## Context

The original requirements define Level 0 as "instant at reference price" and Level 1 as
"ref ± fixed bps, next bar" without pinning: which reference price, when the
fill is reported, how limits interact with the bar path, how DAY expiry works
on bars, and what happens to positions on delisting. These all affect
results, so they must be decided once, conservatively, in code.

## Decision

1. **Level 0**: instant fill at the *current bar's close* (the decision-time
   reference); zero costs. Configuring friction at Level 0 is refused.
2. **Level 1 market orders**: fill at the *next* bar of the symbol at that
   bar's **open**, adjusted adversely by `slippage_bps`, clamped into the
   bar's `[low, high]` (I5 raises if any model proposes outside).
3. **No time travel**: an order created at timestamp T never fills against a
   bar whose `available_at <= T` — that bar's open is in the order's past.
   With daily bars this forces next-session execution.
4. **Fill reporting**: the fill event carries the executing bar's
   `available_at` (its close) — the moment the fill is *knowable* — while the
   price is the intrabar execution price. The strategy cannot react intrabar.
5. **Limit orders**: fill only if price trades **through** the limit
   (strictly beyond, a touch never fills — pessimistic); at the open if the
   open is already through (price improvement is kept, it genuinely
   happened), else at the limit price.
6. **DAY expiry**: a DAY order that rests through one full bar of its symbol
   without filling expires. GTC rests until filled/cancelled/delisted.
7. **Delisting**: pending orders are cancelled; a held position is
   liquidated at the last mark (final close) as a CORPORATE_ACTION ledger
   transaction with zero commission.

## Alternatives considered

- **Fill at next close instead of next open**: adds a full extra bar of
  unmodeled delay; open is the standard next-bar convention and equally
  knowable to the simulator.
- **Touch fills for limits**: optimistic — at the touch you are last in
  queue; rejected per the original requirements pessimism (queue models arrive at Level 3).
- **Delisting at zero**: maximally pessimistic but wrong as a default for
  ordinary delistings; a configurable haircut belongs to Phase 2+ realism
  work. Revisit when delisting-reason data exists.

## Consequences

Level 1 backtests on daily bars have one-session signal-to-fill delay.
Delisting recovery assumptions are visible in the ledger as explicit
transactions. The no-time-travel rule is load-bearing for any strategy that
trades on the first bar event of a multi-symbol session.
