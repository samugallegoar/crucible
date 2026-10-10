# ADR-0043: The engine drives an ExecutionBackend; live runs use a simulated venue

- **Status**: accepted
- **Date**: 2026-09-24

## Context

Phase 7 piece 3 needs a reference live adapter behind a feature flag. The
engine built `LadderExecutionSimulator` directly, and fills were produced
synchronously inside `on_order_submitted`/`on_bar`. A venue reports fills
later, as events. The `Broker` Protocol (ADR-0040) is single-order only.

## Decision

1. **`ExecutionBackend` Protocol** (`crucible/execution/backend.py`) is exactly
   the surface the engine already called on the simulator. The engine takes
   `execution_backend_factory(ExecutionContext)`, not a ready backend, because
   a backend that must draw from the engine's `Generator` and share its
   `MarketStats` needs objects the engine creates in `__init__`.
2. **`SimulatedVenue`** keeps its own mirror `InMemoryOrderManager` and a
   private ladder simulator that shares the engine's RNG and `MarketStats`, so
   its fill *pricing* is the backtest's and parity is checkable byte for byte.
   Its order ids are the engine's (a client order id; `create` gained an
   optional `order_id`). It implements `Broker` and `Snapshottable` and never
   reads wall-clock time.
3. **`VenueExecution`** sends accepted orders to the venue and returns no
   synchronous fill. Composite orders are refused
   (`supports_composite_orders = False`, `Broker` has no bracket/OCO/OTO), as is
   Level 0 (instant fill needs the current bar).
4. **The engine books venue events** (`VenueFillEvent`, `VenueClosedEvent`)
   through the existing `_book_fill`/`_handle_closures`; the ledger stays
   derived from booked fills. A venue event for an unknown order, or one that
   arrives for an order already terminal (a fill that lost the race against a
   cancel), raises `CrucibleError` naming the order and time.
5. **Feature flag:** `ExperimentConfig.live` (default `None`);
   `LiveRuntime` refuses to construct unless `live.enabled`.

## Alternatives considered

- **A separate `LiveRuntime` loop with the broker as source of truth:**
  duplicates engine logic and breaks "the strategy cannot tell".
- **Observe-only overlay:** cannot place orders.
- **A venue that returns fills synchronously from `on_bar`:** trivially
  identical to the backtest and exercises nothing asynchronous.
- **A fully independent matching engine:** parity would only be approximate.

## Consequences

- One code path for backtest, paper and live; strategy, risk and ledger are
  untouched. Stage A of this piece changed no result and no golden hash.
- The venue is not an independent exchange: it cannot surprise the strategy.
  A real vendor adapter is a follow-up behind the same seams.
- `ExperimentConfig.live` changed every serialized config; the golden
  `config.yaml` hash and experiment id were regenerated with every simulation
  artifact verified byte-identical.
