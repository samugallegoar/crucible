# ADR-0039: The engine reads its market data through an injectable DataFeed and merges it with its own event queue

- **Status**: accepted
- **Date**: 2026-09-24

## Context

Phase 7 needs the same strategy to run under a paper runtime. Until now
`BacktestEngine._load_events` read every bar and corporate action from the
store and pushed them all into one `DeterministicEventQueue`; there was no
seam where a `DataFeed` could plug in. The queue is also the engine's own
scheduler: `_handle_dividend` pushes a pay-date `CorporateActionEvent` into
it mid-run (ADR-0026), so the feed cannot simply replace the queue. Event ids
and seqs come from engine counters that are also used at run time, and ids
reach the golden artifacts through ledger `refs["event_id"]`.

## Decision

1. `BacktestEngine` (and `assemble_engine`) take `feed_factory:
   Callable[[FeedContext], DataFeed] | None`. The engine calls it once per run
   with a `FeedContext` (store, datasets, window, calendar, and the engine's
   id/seq callables). Default: `ReplayDataFeed`, the old `_load_events` logic
   moved verbatim (`crucible/live/replay.py`). A factory, not an instance,
   because the counters belong to the engine.
2. `ReplayDataFeed.events()` **stamps every event when called** (stamped
   bars-then-actions, yielded in `(ts, seq)` order): bars are stamped in
   `(available_at, symbol)` order, then corporate actions, and the engine
   calls it before `strategy.on_start`, exactly where `_load_events` ran, so
   ids and seqs are byte-identical to before. After stamping, a stable sort
   by `(ts, seq)` fixes the yield order; this is exactly the old single-heap
   pop order, so a corporate action earlier than a later bar interleaves with
   the bars around it and the feed satisfies I9. Lazy stamping would
   interleave with run-time ids and change the golden hashes.
3. The engine keeps its queue for engine-scheduled events. The loop takes the
   feed's next event unless the queue's head has a strictly earlier `ts`;
   **at equal `ts` the feed goes first**. Pay-date events are created mid-run,
   after every feed event was stamped, so they always sorted last at a shared
   `ts` in the old single heap; the rule reproduces that without comparing
   `seq` across the two sources. The "mark now?" test looks at the earliest
   pending `ts` across both sources.
4. `PeekableFeed` (`crucible/live/feed.py`) gives the loop one event of
   lookahead over the feed and enforces I9 (non-decreasing `ts`, strictly
   increasing `seq` at equal `ts`) with `InvariantViolation`; it never sorts.
   The peek reads only `ts` and the peeked event is never handed to the
   strategy or the PIT accessor.
5. In this piece the feed and the PIT accessor read the same store
   (`ctx.data` is served by `StorePITAccessor`, not the feed). Only
   `ReplayDataFeed` is supported.

## Alternatives considered

- **Wrap the engine and override `_load_events` (A):** trivial, but leaves
  `Broker`/`DataFeed` decorative.
- **Extract a runtime-agnostic `EngineCore` now (B):** cleanest long-term, but
  rewrites the 1142-line engine with the golden fixtures as the only safety
  net, and freezes a guess about what a real adapter needs. This ADR is the
  first step of B done incrementally; revisit after piece 3.
- **Replace the queue with the feed:** silently drops dividend pay-date
  events (found while reviewing the spec against the code).
- **Merge by `(ts, seq)` across sources:** needs the two sources to share one
  seq space; the feed-first rule does not.

## Consequences

- Existing callers and configs are unchanged; the full existing suite and the
  golden hashes pass unmodified (this is the proof it is a pure refactor).
- I9 is now enforced twice: `DeterministicEventQueue.pop` (queue) and
  `PeekableFeed` (feed).
- The whole-stream I9 check no longer lives only in the queue. The queue now
  holds only engine-scheduled events (dividend pay dates), so a malformed pay
  date earlier than the ex-date is refused by `Clock.advance`
  (`crucible/core/clock.py`, `InvariantViolation` naming both the current and
  the requested timestamp) instead of by the queue's own I9 check.
- The `_load_events` ordering statements in ADR-0026 and ADR-0034 now refer to
  `ReplayDataFeed`; behavior is identical.
- **Known limit:** a real-time feed cannot know a timestamp is finished until
  the next event arrives, so it needs session/heartbeat events. Foreign feeds
  (own id space, restamping), a stream-backed PIT accessor, and checkpoint
  interaction are Phase 7 pieces 2 and 3.
