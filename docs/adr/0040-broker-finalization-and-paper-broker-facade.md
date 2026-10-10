# ADR-0040: `Broker` finalized on `OrderSpec`; `PaperBroker` is a facade outside the order path

- **Status**: accepted
- **Date**: 2026-09-24

## Context

`Broker` was a Phase 0 sketch (`submit(Order)`, `cancel`, `positions`, `cash`)
that nothing implemented. Strategies emit `OrderSpec`, not the internal
`Order`, and a runtime needs to observe order state without reaching into
engine internals. Strategy orders currently flow `ctx.orders` ->
`EngineOrderSubmitter` -> `engine.submit_spec` -> risk -> simulator.

## Decision

- `Broker`: `submit(spec: OrderSpec) -> OrderId`, `cancel(order_id)`,
  `order_state(order_id) -> OrderState` (new), `positions()` (signed non-zero
  quantities), `cash()` (ledger fold **total** balance per currency, not
  settled-only; ADR-0028 settlement lag does not reduce it).
- `PaperBroker(engine)` is an external facade: `submit` calls
  `engine.submit_spec` (so risk applies), `order_state` reads the engine's
  order manager (re-raising its unknown-id `CrucibleError` with the simulation
  timestamp), `positions`/`cash` read the new `BacktestEngine.balances()`.
- Strategy orders do **not** pass through `Broker` in this piece. Routing
  `submit_spec` through it would touch the hottest path before a real adapter
  shows what `Broker` needs (piece 3).
- `Broker` covers single orders only; bracket/OCO/OTO have no counterpart yet.

## Alternatives considered

- **Route `submit_spec`/`cancel_order` through `Broker` now:** puts the
  Protocol on the real path, but unvalidated against any real adapter and
  risks the golden fixtures. Deferred to piece 3.
- **Return only settled cash from `cash()`:** closer to "buying power", but
  hides equity-relevant balances; `PortfolioView` already exposes available
  cash to strategies.

## Consequences

- The paper-vs-backtest parity test (`tests/integration/
  test_paper_runtime_parity.py`) is partly tautological, because both
  runtimes share one engine. It shows the feed seam changes nothing; it does
  not verify live behavior.
- Piece 3 must revisit `Broker` (composite orders, fill/ack delivery,
  reconnect semantics) and will likely supersede parts of this ADR.
