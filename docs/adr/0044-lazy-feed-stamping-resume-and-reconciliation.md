# ADR-0044: Lazily stamping feeds, their resume, and venue reconciliation

- **Status**: accepted
- **Date**: 2026-09-24

## Context

ADR-0039 required feeds to stamp event ids and sequence numbers eagerly and
left lazy stamping unsupported until piece 3. A venue-driven feed must stamp
lazily: it cannot know fills before the strategy has placed orders. ADR-0041's
cursor resume relied on eager stamping.

## Decision

1. `DataFeed.stamping` is `"eager"` or `"lazy"`; the engine refuses a feed that
   does not declare it. `VenueDataFeed` is lazy: per bar it steps the venue,
   then yields fill events, closed-order events and the bar, stamped at pull
   time, so sequence numbers strictly increase in yield order and fills reach
   the engine before the bar's `on_market`.
2. **Lazy resume** carries state, not a count: the feed's `next_row` and its
   buffer of stamped undelivered events, the peeked head event, the last popped
   `(ts, seq, id)`, and the venue snapshot (inside the engine's `execution`
   payload). At a boundary the feed and venue are already one event ahead of the
   engine; `PeekableFeed.preload` restores the head. Eager feeds keep the
   cursor check. The payload's `feed` key records the stamping kind; a mismatch
   is refused.
3. **Reconciliation** compares the venue's stream position (fills and closures
   published) and its open orders with the checkpoint. `LiveRuntime.resume_from
   (venue_state="external")` does not restore the venue and refuses any
   difference with an itemised message; `"restore"` rebuilds the in-process
   venue. Cash and positions are not compared: the engine, not the venue,
   applies dividends and delisting liquidation.
4. The engine's setup description includes the backend's class, so a live
   checkpoint cannot resume into a backtest engine (or the reverse).

## Consequences

- Known divergences from a backtest, each pinned by a test or refused: a fill's strategy
  callback runs before that bar's `on_market` (a backtest runs it after); the
  venue processes a bar when the feed pulls it, which happens before the mark,
  so a risk FLATTEN's orders would fill one bar late and (with random latency)
  shift the shared RNG stream: the engine refuses a FLATTEN under the venue
  backend (`supports_mid_mark_orders = False`, `ConfigurationError`); ledger
  rows whose `refs` name an event id (dividends, delisting) carry a different
  id than in a backtest because event ids are numbered in yield order (amounts
  are equal; a test pins it).
- Checkpoints written before this piece cannot be resumed: the setup
  description gained `execution_backend`.
- A stateful component that does not implement `Snapshottable` is still
  silently reset on resume (ADR-0041); the resume-equivalence tests are the net.
- Real wall-clock streaming needs a blocking peek and is deferred, with a real
  vendor adapter.
