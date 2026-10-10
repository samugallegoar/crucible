# Module: core

## What exists

The kernel and the run loop. Detail sections follow.

- `types.py` — `TimestampNs`, identifier NewTypes, the enums (`OrderType`, `OrderSide`,
  `TimeInForce`, `OrderState`, `RealismLevel`, `RunMode`, `TransactionType`, `CorporateActionType`,
  `MissingReason`).
- `errors.py` — `CrucibleError` and its subclasses (`docs/CONVENTIONS.md` §9).
- `events.py` / `interfaces.py` — the frozen slotted event dataclasses (`BaseEvent`, `BarEvent`,
  `CorporateActionEvent`, `OrderUpdateEvent`, `FillEvent`, `VenueFillEvent`, `VenueClosedEvent`) and
  the Protocols `Event`, `MarketEvent`, `OrderUpdateEvent`, `FillEvent`, `CorporateActionEvent`,
  `Clock`, `EventQueue`, `Snapshottable`.
- `clock.py`, `queue.py` — `SimulationClock`, `DeterministicEventQueue`.
- `invariants.py` — the `Invariant` Protocol and the registry (`register`, `all_invariants`).
- `logging.py` — `RunLogger` (simulation-time JSON lines). `instruments.py` — `FuturesSpec`.
- `checkpoint.py` — the canonical JSON codec; `setup_fingerprint.py` — `describe`,
  `changed_attributes` (the state-outside-the-snapshot check).
- `engine.py` — `BacktestEngine` (the run loop; call order in `docs/TIMING.md`) and `BacktestResult`.

## Responsibility
Value types, error hierarchy, events, clock, deterministic queue, invariant
registry, structured run log, and the backtest engine (event loop). Core's
type/error/Protocol layer depends on nothing inside `crucible`;
`core/engine.py` is the one orchestration module and imports downward into
data/orders/execution/accounting/strategy (they never import it back).

## Interfaces and implementations (`crucible/core/`)
- `types.py` / `errors.py` / `interfaces.py`: as originally defined; `Event` members
  are read-only properties so frozen dataclasses satisfy them.
- `events.py`: `BarEvent` (incl. `open_time`: true session open from the
  calendar, previous-close fallback — ADR-0012), `CorporateActionEvent`,
  `OrderUpdateEvent`, `FillEvent` — frozen slotted dataclasses (ADR-0006);
  `sequence_counter()` is the per-run monotonic seq source.
- `clock.py`: `SimulationClock` — monotonic; backward advance raises.
- `queue.py`: `DeterministicEventQueue` — `(ts, seq)` heap; pop enforces I9
  (engine-scheduled events only; market data arrives through a `DataFeed`,
  ADR-0039).
- `logging.py`: `RunLogger` — JSON lines with *simulation* time only.
- `invariants.py`: registry; accounting registers I1/I3/I4 at import.
- `engine.py`: `BacktestEngine` — see `docs/ARCHITECTURE.md` for the loop;
  timing/pessimism semantics in ADR-0010/0012. Takes an `ExecutionSetup`
  (model bundle), a calendar (for true session opens), a seeded rng, and an
  optional per-event `observer` (the debug stepper's hook), and an optional
  `feed_factory` (default `ReplayDataFeed`, ADR-0039) and an optional
  `execution_backend_factory` (ADR-0043; refuses composite orders when the
  backend is single-order only): the run loop merges
  the feed with the engine's own queue, feed first at equal `ts`; the public
  `balances()` exposes ledger-fold balances. Routes
  composite submissions (`submit_bracket`/`submit_oco`/`submit_oto`) and
  cascades closures to dormant children. Multi-currency (ADR-0025):
  optional `symbol_currency`/`fx_dataset` — refuses at construction if a
  non-base currency is named with no `fx_dataset`; `_currency_of(symbol)`
  resolves every fill/fee/delisting/dividend transaction's currency;
  `_fx_mid_rates_at` reads FX mid rates through the same `StorePITAccessor`
  as bars (`_fx_mid_for(as_of, ccy)` reads one rate; each fill row also records
  `currency`, `multiplier` and `fx_to_base`, ADR-0047; the pre-trade snapshot
  requests the order symbol's currency, ADR-0045). Dividends (ADR-0026): `_handle_dividend` — an ex-date
  `CorporateActionEvent` resolves entitlement from the position held just
  before the ex-date's session opens (`fold(up_to=min(ts - 1, session_open))`
  when the engine has a calendar, else `ts - 1`; ADR-0046) and
  pushes a second, pay-date `CorporateActionEvent` onto the engine's own
  queue (the queue is kept for exactly this, ADR-0039). This is safe:
  `DeterministicEventQueue` is a plain `(ts, seq)` heap, so a future-dated
  push mid-run needs no special handling. The pay-date event posts the
  pre-resolved amount directly, never re-resolving entitlement.
  Settlement lag (ADR-0028): `settlement_lag_days` (default 0)
  becomes `_settlement_lag_ns`; `_settled_at(ts, amount)` returns `None`
  (immediate) for a non-positive amount or zero lag, else `ts + lag` —
  applied to fill and delisting-liquidation transactions' `settled_at`.
  Dividends post with `settled_at=None` deliberately: `pay_at` already
  models the one real-world delay, so lag doesn't stack on top.
  Target resolution (ADR-0029): `resolve_target`/`resolve_targets`
  (the `TargetRouting` surface `strategy.context.EngineTargetSetter`
  forwards to) fold the ledger once, then per symbol convert a declared
  weight into a target quantity (`accounting.fx.convert_from_base_at_mid`
  for a foreign-currency symbol, `ROUND_DOWN` to an integer qty) and submit
  the delta through the same `submit_spec` path `ctx.orders.submit` uses —
  every existing pre-trade risk check and settlement-lag sizing already
  applies. `_fx_mid_rates_at` gained an `extra_currencies` parameter so a
  brand-new (not-yet-held) symbol's currency still gets a rate.
  Borrow cost / margin financing (ADR-0032): `_accrue_financing(ts)`
  runs at the top of every `_mark()` — `short_borrow_rate`/
  `margin_financing_rate` (both default `0.0`, zero behavior change)
  charge, per elapsed period since the last mark, `notional ×
  short_borrow_rate` on every short position and `|cash| ×
  margin_financing_rate` on every negative cash balance (Actual/365,
  `_YEAR_NS`), posted as `TransactionType.BORROW`/`FINANCING`. Computed
  as `notional · rate · elapsed_ns / YEAR_NS` — multiplication before
  the single final division, since `elapsed_ns/YEAR_NS` alone is a
  non-terminating decimal and would force early rounding.
  Futures (ADR-0033): `futures_specs: Mapping[Symbol,
  FuturesSpec] | None` (`core.instruments.FuturesSpec`, empty default).
  `_book_fill` branches on it — a futures fill's cash is `_futures_
  price_delta(...) × multiplier` (zero on open/increase, the realized
  gain/loss on close/reduce), never `-signed_qty × price`. New
  `_futures_price_delta` (a throwaway-clone preview of what
  `PositionState.apply` would realize — reused, never re-derived) and
  `_settle_futures_mtm` (called from `_mark()`): every held futures
  position's unrealized move since the last mark realizes to cash via a
  synthetic close-then-reopen transaction pair at the current mark, both
  replayable by `InMemoryLedger.fold`'s existing generic position-apply
  logic with no changes to `fold`/`apply` themselves. Skipped entirely
  when the realized delta is exactly zero (a lone reopen with no
  matching close would double the position). A roll needs no dedicated
  mechanism: each contract month is its own `Symbol`, so closing one and
  opening another is just two ordinary orders.

## Checkpoint/resume (E7, ADR-0041/0042)
- `checkpoint.py`: the codec (`encode`/`decode`/`canonical_json`), file
  format (`write_checkpoint`/`read_checkpoint`: canonical JSON, atomic write,
  schema version, integrity digest) and the typed accessors components use
  in `restore` (`field`, `optional_field`, `optional_number`, `field_list`,
  `field_dict`, `expect`, `as_floats`). Unsupported types, shared or cyclic
  mutable references and non-str dict keys raise `CheckpointError` naming
  the key path.
- `interfaces.py::Snapshottable`: `snapshot()` returns codec values (never
  JSON); `restore(state)` mutates in place. Implemented by the clock, event
  queue, run logger, ledger, order manager, execution simulator,
  `MarketStats`, the stateful risk limits and `CompositeRiskEngine`.
- `setup_fingerprint.py::describe`: deterministic JSON-safe description of
  configuration and run state, computed at engine construction and compared on resume and at
  `checkpoint()`. Bounded by 50,000 nodes per top-level attribute (500,000 overall) and a 40-level ceiling (cut subtrees become
  `{"cls", "truncated": True}`), a cycle guard (`"cycle": True`) and an `opaque=` option that
  names shared engine-owned types (`MarketStats`) instead of describing them (ADR-0056).
- `engine.py`: `run_until(ts)` (stop at a session boundary, without
  `on_end`; `run()` is `run_until(end)` then finish), `checkpoint(path)`
  (refuses before start, after finish, or when callbacks are pending),
  `resume_from(path)` (on a fresh engine: opens the feed, restores state,
  skips the feed through the saved cursor; never calls `on_start`).
  Sequence numbers come from an int counter, `_next_seq()`, so the counter
  is state that can be saved. Feeds declare `stamping`; the payload's `feed`
  key records it. An eager feed resumes by cursor; a lazy feed by its saved
  state, the peeked head and the venue snapshot (ADR-0044). The setup
  description includes the execution backend's class.
  `_handle_venue_event` books `VenueFillEvent`/`VenueClosedEvent` and refuses
  events for unknown or already-terminal orders, a fill whose symbol or side
  differs from the order's, and a closed event with a non-terminal state.
  Hardening (ADR-0048): a failed `on_start` leaves the engine unusable
  (`_failed`; also after a `resume_from` that fails past validation); `checkpoint()` refuses when the strategy (unless a
  `StatefulStrategy`), a non-`Snapshottable` risk limit, a non-`Snapshottable`
  custom risk engine or a non-`Snapshottable` execution model (spread, latency, slippage,
  commission, participation) changed attributes since construction (`_state_holders`,
  `setup_fingerprint.changed_attributes`; ADR-0056);
  margin limits with a futures symbol that has no margins are refused in
  `__init__` (ADR-0050); queue and
  composite-risk restores are atomic; `read_checkpoint` raises
  `CheckpointError` for a missing file; `ckpt.expect(int)` refuses `bool`;
  checkpoint schema version is 3.
- Verified on load: schema version, dataset content hashes, setup
  description, strategy `STATE_VERSION`, integrity digest, feed cursor.
  Limits: the setup description sees names and parameters, not code; the
  observer is not restored.

## Extension points
New event kinds: subclass protocol in `interfaces.py` + frozen dataclass in
`events.py` + a dispatch arm in the engine. New invariants: register +
INVARIANTS.md row + test.

## Known gaps
- The event Protocols `DataEvent`, `SignalEvent`, `OrderEvent`, `ClockEvent` and `RiskEvent` are stubs (nothing implements or emits them), and `Strategy.on_data` / `Strategy.on_session` are never dispatched (`docs/TIMING.md` §7).
No `ClockEvent`/session events yet (nothing at Level 0/1 needs them). Engine
re-folds the ledger at every mark (intentional until benchmarks, ADR-0003).
Checkpoint/resume is a library API only (see below).
The margin risk limits refuse futures symbols (ADR-0031's Reg-T short-equity
model, ADR-0045); no futures-specific margin model, commission model,
tick-size rounding, position limits, or forced-close-at-expiry (ADR-0033).
