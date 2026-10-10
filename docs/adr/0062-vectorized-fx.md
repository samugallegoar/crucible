# ADR-0062: FX in the vectorized engine

- **Status**: accepted
- **Date**: 2026-10-04

## Context

The vectorized runner refused `data.symbol_currency` and `data.fx_rates`, so the fast research path
was closed to every cross-currency question (silently reading a EUR price series as dollars would be
wrong, so the refusal was the safe behaviour). The event-driven engine already handles currencies
(ADR-0009, ADR-0025, ADR-0029): a foreign position is paid for from its own currency's cash (which can
go negative), equity is marked at the FX mid, and nothing is converted unless a strategy asks (it
cannot). Design note: `docs/features/vectorized-fx.md`.

## Decision

1. **The vectorized engine uses the event-driven convention** (owner choice). A foreign position is
   funded in its own currency, so an FX move changes only the accumulated pnl, never the principal.
   With `U[s]` the symbol's local pnl since inception (realised plus unrealised), equity is
   `initial - costs + sum(fx[s] * U[s])`: no per-currency cash needs tracking. At each row `U` moves by
   `q * dP`, and the quantity for the next bar is `w[t+1] * E[t] / (P[t] * fx[t])` (ADR-0029's sizing).
   Implemented in `crucible/vectorized/fx.py` (`run_fx_equity`, pure numpy).
2. **The single-currency path is untouched.** The FX loop runs only when a symbol present in the bars
   has a non-base currency; with every rate 1.0 it reduces algebraically to the existing
   `E[t-1] * (1 + sum(w * r) - turnover * rate)` (a test pins that).
3. **Costs are the existing turnover rate** taken from base cash. No FX spread: the event engine
   converts nothing, so it charges nothing (ADR-0009's adverse side applies to an explicit conversion,
   which a strategy cannot request).
4. **Point in time and refusals.** Each bar uses the rate the event engine's PIT read returns: among
   the FX rows with `available_at <= ts`, the one with the latest `event_time` (ties: the later
   `available_at`), so rows published out of order give the same rate in both engines. Refused: a missing `<CCY><BASE>` pair (a reversed pair is not inverted), no
   rate known at a bar, a non-positive or non-finite rate, `symbol_currency` naming a non-base currency
   without `fx_rates`.
5. **One aligned calendar.** Every symbol must have a bar at every timestamp of the run window; a
   staggered calendar is refused. Supporting it would need an invented rule for FX moves (and carried
   marks) between a symbol's own bars.
6. **The run starts flat at its first in-window bar**: a position held at the window start is not
   credited (the single-currency path credits it), the weight at that row is neither held nor
   traded, and the first weight actually held (at the second row) is entered from flat and charged
   the turnover cost (the pessimistic reading: an entry is never free).
7. **The engine returns a per-symbol gross pnl frame** (`VectorizedResult.pnl`, base currency, before
   costs; for a foreign symbol it includes the FX effect: `q * dP * fx[t] + U[t-1] * (fx[t] - fx[t-1])`).
   At every bar it sums to the equity change when costs are zero. `build_episodes(weights, pnl)` reads
   it instead of recomputing from bars, so episode pnl (ADR-0061) is correct for foreign symbols; this
   also removes the window-start timestamp issue deferred from the ADR-0061 review.
8. **Promotion converts a foreign symbol at the FX mid.** `PromotedSignalStrategy` sized with
   `equity * weight / price`, ignoring the symbol's currency, so a promoted FX config bought the wrong
   quantity (10,000,000 shares where 8,000,000 is right in the test fixture). It now divides the price
   by the symbol's currency-to-base mid, read through the PIT accessor (`ctx.data.get`, the engine's own
   read). The price still comes from the PIT history, so single-currency promotion, multi-symbol
   included, is byte-identical to before (an attempt to size through `ctx.targets` was dropped in
   review: the engine's marks are one bar stale for the symbols after the first at a timestamp, which
   changed multi-symbol sizing and skipped a symbol with no mark yet). `promote_config` adds the
   `symbol_currency` and `fx_rates` params only for a multi-currency config, so single-currency
   promoted experiment ids are unchanged.
9. The FX dataset enters the experiment id (`data_manifests.fx_rates`) for any vectorized config that
   sets `data.fx_rates`. Every existing config without `fx_rates` keeps its id; a config with
   `fx_rates` and no `symbol_currency` (accepted before, rate unused) gets a new id, as the
   event-driven runner's ids would. The runner also refuses a foreign `symbol_currency` entry without
   `fx_rates` even for a symbol absent from the bars, while the engine ignores such entries.

## Alternatives considered

- **Unhedged base-currency weights** (the whole position carries the FX return, adverse-spread
  conversion on turnover). Simple and textbook, but no event-driven run can reproduce it, so results
  could not be cross-checked and promotion would give different numbers. Rejected by the owner.
- **Forward-filled marks on a staggered calendar.** Needs rules for FX moves between a symbol's own
  bars and for episode pnl; deferred.
- **Charging an adverse conversion cost per trade.** The event engine converts nothing; charging one
  would make the vectorized path more pessimistic than the engine it predicts.

## Consequences

- **Measured agreement:** a promoted event-driven run of a one-foreign-symbol fixture (every open equal
  to the previous close, 1e9 of cash) matches the vectorized FX equity to 3.8e-9 relative at every one
  of 30 bars (`tests/integration/test_vectorized_fx_promotion.py`).
- **Finding, not fixed here (pre-existing):** a multi-symbol promoted run is not equivalent to the
  vectorized run, FX or not: `PromotedSignalStrategy` rebalances on the first symbol's bar at each
  timestamp, when the engine's marks, hence the equity it sizes from, are one bar stale for the later
  symbols. Two-symbol fixture, maximum relative equity gap: 4.7% USD-only (4.7% on master too) and
  4.6% with FX. The agreement test uses one symbol. A fix belongs to promotion (rebalance once all of
  a timestamp's bars are in) and is left to a later piece.
- A vectorized FX run needs a common bar calendar and starts flat; both are documented limits.
- Deferred: staggered calendars, the multi-symbol promotion equivalence, futures in the vectorized
  engine (Batch F, F4).
