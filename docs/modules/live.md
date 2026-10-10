# Module: live

## What exists

Live parity by interface design. Detail sections follow.

- `interfaces.py` — the Protocols `Broker`, `DataFeed`, `LazyDataFeed`.
- `replay.py` — `ReplayDataFeed`; `feed.py` — `FeedContext`, `PeekableFeed`; `rows.py` — the shared
  frame loaders.
- `paper.py` — `PaperBroker` (a facade outside the order path); `runtime.py` — `PaperRuntime`,
  `LiveRuntime` (behind `live.enabled`).
- `venue.py` — `SimulatedVenue`; `venue_feed.py` — `VenueDataFeed`; `execution.py` —
  `VenueExecution` (the venue's `ExecutionBackend`). No real vendor adapter exists.

## Responsibility
Live parity by interface design: `Broker` and `DataFeed` Protocols that the
backtest engine, the paper broker, and eventual real adapters all stand
behind. Strategies cannot tell them apart. The paper runtime
(parity, ADR-0039/0040) is the seam plus a replay-driven runtime;
checkpoint/resume is ADR-0041/0042; a reference live adapter runs on a
simulated venue (ADR-0043/0044).

## Interfaces (`crucible/live/interfaces.py`)
- `Broker.submit(spec: OrderSpec) -> OrderId` / `cancel(order_id)` /
  `order_state(order_id) -> OrderState` / `positions()` (signed non-zero
  quantities) / `cash()` (ledger fold total balance per currency, not
  settled-only). Single orders only (ADR-0040).
- `DataFeed.stamping` (`"eager"` or `"lazy"`, required: the engine refuses a
  feed without it) / `subscribe(symbols)` / `events()` — non-decreasing `ts`,
  ties by `seq`, in every environment. `LazyDataFeed` adds `snapshot()` /
  `restore()`, because a lazily stamping feed is ahead of the engine at a
  session boundary.

## Implementations
- `feed.py`: `FeedContext` (store, datasets, window, calendar, and the
  engine's id/seq callables) and `PeekableFeed` (one-event lookahead over a
  feed; enforces I9 with `InvariantViolation`, never sorts; the peek reads
  only `ts`).
- `replay.py`: `ReplayDataFeed` — the old `BacktestEngine._load_events` moved
  behind `DataFeed`. `events()` stamps every event when called (stamped
  bars-then-actions), then yields them in global `(ts, seq)` order via a
  stable sort after stamping (the old single-heap pop order, so a corporate
  action earlier than a later bar interleaves with the bars around it).
  `subscribe` narrows and validates symbols. It is the engine's default
  `feed_factory`.
- `paper.py`: `PaperBroker(engine)` — a facade over the engine, outside the
  strategy order path. `submit` goes through `engine.submit_spec` (risk
  applies); `positions`/`cash` read `BacktestEngine.balances()`.
- `runtime.py`: `PaperRuntime` — the backtest engine driven through the
  `DataFeed` seam plus a `PaperBroker`. Library API only.

## Live runtime (ADR-0043/0044)
Behind a feature flag (`ExperimentConfig.live: {enabled: true}`); library API
only. The unchanged strategy, risk engine and ledger run on the backtest
engine, but orders go to a venue and fills return as events.
- `venue.py`: `SimulatedVenue` — accepts orders under the engine's order id
  (a client order id), keeps a mirror `InMemoryOrderManager` and its own cash
  and positions, and prices fills through a private
  `LadderExecutionSimulator` that shares the engine's RNG and `MarketStats`
  (so a run can be compared byte for byte with a backtest). Implements
  `Broker` and `Snapshottable`; `summary()` (`emitted`, the count of fills and
  closures published, plus open orders) is what reconciliation compares; its
  clock never moves backwards. Refuses Level 0; single-currency;
  single orders; not an independent matching engine.
- `execution.py`: `VenueExecution` — the engine's `ExecutionBackend` for live
  runs. Returns no synchronous fill; `restore_mode` is `"restore"` (rebuild
  the in-process venue) or `"external"` (reconcile against a venue that kept
  running; any difference raises `CheckpointError` with an itemised diff).
- `venue_feed.py`: `VenueDataFeed` — lazily stamping. Per bar it steps the
  venue, then yields fill events, closed-order events and the bar, stamped at
  pull time, so fills reach the engine before that bar's `on_market`.
- `rows.py`: the polars frame loaders shared with `ReplayDataFeed`. Both feeds copy the optional
  bar quote columns (`bid_open`, `ask_open`, `bid_close`, `ask_close`) into the `BarEvent` when the
  dataset has them, so a `quoted` spread behaves the same live and in a backtest (ADR-0060).
- `runtime.py`: `LiveRuntime(config)` (`engine`, `venue`, `run()`,
  `checkpoint(path)`, `resume_from(path, venue_state="restore"|"external")`).
  Refuses: no/disabled flag, Level 0, `symbol_currency`, futures.
- Engine side: `execution_backend_factory`, `_handle_venue_event` (books
  `VenueFillEvent`/`VenueClosedEvent` through `_book_fill`/`_handle_closures`;
  refuses events for unknown or already-terminal orders).

Known divergences from a backtest (ADR-0044): a fill's strategy callback runs
before that bar's `on_market` (pinned by a test); ledger `refs` naming an event
id differ (pinned by a test); a bar is processed by the venue when the feed
pulls it, so a risk FLATTEN (an order placed during a mark) could only fill one
bar late and is refused under the venue backend (tested). Parity is proven at
Levels 1-2 (invariant I14). Also documented and unchanged (ADR-0048): a cancel
that loses the race shows the strategy CANCELLED before the run aborts on the
venue's buffered fill (the abort is the safe outcome), and a foreign-currency
order submitted before the first FX row aborts at submission when a risk
engine is configured. The engine refuses a venue fill whose symbol or side
differs from the order and a closed event with a non-terminal state.

## Checkpoint/resume
Library API on the engine (`run_until`, `checkpoint`, `resume_from`; see
`docs/modules/core.md`, ADR-0041/0042). `PaperRuntime` has no wrapper for it
yet. `PeekableFeed.peek()` lets resume compare the feed with the saved
cursor without consuming the event; for a lazily stamping feed the
checkpoint stores the feed state, the peeked head and the venue snapshot
(`PeekableFeed.preload` restores the head; ADR-0044).

## Extension points
Real broker adapters implement `Broker` behind a feature flag together with a
stream-backed `DataFeed` (pass it via `feed_factory`); they live at the I/O
boundary where timezones and wall-clock are permitted.

## Known gaps
- A real vendor adapter and wall-clock streaming (needs a blocking peek): the
  venue is simulated and reuses the backtest fill models, so it cannot
  surprise the strategy the way a real exchange would.
- Bracket/OCO/OTO on `Broker` (composite orders are refused under the venue
  backend); adopting venue state on a reconciliation mismatch; venue
  disconnect/reconnect. CLI: `crucible run <config> --runtime paper|live` (ADR-0051);
no checkpoint flags on the CLI.
- Reconciliation compares open orders and stream position, not cash or
  positions (the engine, not the venue, applies dividends and delisting).
- Stream-backed PIT accessor (the feed and the accessor read the same store).
- Strategy orders are not routed through `Broker` (they go through the
  engine's order path and the backend).
- Session/heartbeat events for real-time feeds.
