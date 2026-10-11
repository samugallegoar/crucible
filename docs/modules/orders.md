# Module: orders

## What exists

Order objects and their state machine. Detail sections follow.

- `interfaces.py` — `OrderSpec` and the Protocols `Order`, `OrderSubmitter`, `OrderManager`.
- `manager.py` — `ManagedOrder`, `InMemoryOrderManager` (creation-ordered, refuses overfills).
- `state.py` — the transition table and `validate_transition` (I7).
- Order types (`MARKET`, `LIMIT`, `STOP`, `STOP_LIMIT`, `TRAILING_STOP`, `BRACKET`, `OCO`, `OTO`,
  `TWAP`, `VWAP`, `PARTICIPATION`, `MARKET_ON_CLOSE`) are the `OrderType` enum in `core/types.py`;
  the simulation semantics are in `docs/modules/execution.md`. A `MARKET_ON_CLOSE` order needs
  `close_at` (a session close after its creation); no other type may set it (ADR-0074).

## Responsibility
Order objects, the state machine, and the manager that owns all transitions.

## State machine (invariant I7)
`CREATED → SUBMITTED → ACCEPTED → {PARTIALLY_FILLED → FILLED | CANCELLED |
REJECTED | EXPIRED}`, plus `SUBMITTED → CANCELLED` (cancel-before-ack),
`CREATED → CANCELLED` (dormant OTO/bracket children whose parent dies), and
`PARTIALLY_FILLED → PARTIALLY_FILLED` (successive partials). The table is
code: `orders/state.py::ALLOWED_TRANSITIONS`; every change funnels through
`validate_transition`, which raises `IllegalOrderTransition` with order id,
states, and timestamp.

## Implementations
- `manager.py`: `ManagedOrder` — validates per-type requirements at
  creation (limit price for LIMIT/STOP_LIMIT, stop for STOP/STOP_LIMIT,
  trail for TRAILING_STOP, `algo_bars`/`algo_rate` for algos); carries
  composite links (`parent_id`, `oco_with`). `InMemoryOrderManager`:
  `create`/`transition`/`apply_fill` (overfills raise)/`open_orders`/
  `link_oco`, deterministic creation order.
- `interfaces.py`: `Order`, `OrderSpec` (full order request), and
  `OrderSubmitter` — `submit` (simple), `place(spec)`, `submit_bracket`,
  `submit_oco`, `submit_oto`, `cancel`.

## Extension points
New order types: extend `OrderType`, per-type validation in `ManagedOrder`,
and an evaluation arm in `execution/ladder.py::_evaluate` (ADR-0012).

## Checkpoint/resume (E7, ADR-0041)
`InMemoryOrderManager.snapshot()` captures the id counter and every order
(spec fields including trailing/algo parameters, parent and OCO links,
`strategy_id`, state, filled quantity). `restore` rebuilds each order
through its constructor (validation still applies) and then sets its state
directly, bypassing the transition table: the single restore-only path
(documented in `restore`). Numeric
prices keep their exact type (int stays int) so a resumed run's order rows
are identical.

## Known gaps
IOC/FOK/GTD refused (need intrabar semantics). OCO sibling quantity is not
resized on a partial fill of the other leg (cancel happens on full fill
only; documented in ladder).
