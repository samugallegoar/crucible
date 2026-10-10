# ADR-0041: Checkpoints are a canonical JSON codec over per-component snapshots

- **Status**: accepted
- **Date**: 2026-09-24

## Context

The original requirements require strategy and engine state to be serializable at any
session boundary. ADR-0006 already decided the format question in principle
("serialization for checkpoints goes through an explicit codec at the
boundary"). The engine holds lambdas and closures, mutable orders, a numpy
RNG, a heap of scheduled events, and per-component caches, and event ids reach
the golden artifacts. A resumed run must be indistinguishable from the
uninterrupted one (E1 extended across a stop/resume).

## Decision

1. **Explicit `snapshot()`/`restore(state)` per stateful component**
   (`Snapshottable`, `crucible/core/interfaces.py`): ledger, order manager,
   execution simulator, `MarketStats`, stateful risk limits (aggregated by
   `CompositeRiskEngine`), run logger, event queue, clock; the engine owns
   counters, marks, current bar, result rows, RNG and `ctx.state`.
   `snapshot()` returns codec-supported values (never JSON); `restore` is in
   place because other components hold references. Configuration is setup and
   is verified, not stored.
2. **One codec** (`crucible/core/checkpoint.py`): tagged JSON for Decimal,
   tuple, set/frozenset (sorted), non-finite floats, enums, numpy PCG64
   generators and three dataclasses. Unsupported types, shared or cyclic
   mutable references, and non-str dict keys raise `CheckpointError` naming
   the key path. Dict insertion order is state and is preserved, so the same
   state always writes identical bytes; no wall clock is written.
3. **File:** canonical JSON, atomic write, schema version, integrity digest
   over header and payload.
4. **Cursor resume** relying on ADR-0039's eager stamping: the resumed engine
   opens its replay feed with fresh counters (re-stamping exactly as the
   original run did), overwrites the counters from the checkpoint, and skips
   feed events through the saved `(ts, seq, id)` cursor, refusing if the event
   at the cursor differs.
5. **Boundary:** the point after the last event of a timestamp was fully
   handled (`run_until(ts)`); `checkpoint(path)` refuses anywhere else.
   `resume_from(path)` is an instance method on a freshly constructed engine
   (a kwargs-forwarding classmethod would need `**kwargs: Any`).
6. **Verification on load (refuse, don't warn):** schema version, data
   content hashes, a setup description (constructor arguments, execution
   models, risk limits, strategy name/params, computed at construction so it
   compares against a fresh engine's), strategy `STATE_VERSION`, digest, and
   the feed cursor.

## Alternatives considered

- **Pickle the engine:** does not pickle (closures), executes arbitrary code
  on load, breaks across code versions, contradicts ADR-0006.
- **Cursor plus replay from the start:** serializes nothing and is exact but
  saves no time, which is the point of resuming; not the original requirements' requirement.
- **`msgspec`/dataclass auto-serialization for everything:** ADR-0006 keeps
  serialization out of the event classes; per-component snapshots keep the
  determinism-relevant choices explicit and testable.

## Consequences

- Every future stateful component must implement `Snapshottable`; the
  resume-equivalence matrix (`tests/integration/
  test_checkpoint_resume_equivalence.py`) is the net that finds one that
  does not. The user is asked to add this to AGENTS.md §5/§6 and §7.
- **Limits, stated plainly:** the setup description sees names and parameters
  (including a strategy instance's attributes, so constructor arguments are
  compared), never code inside a strategy or model; a component that is
  stateful but does not implement `Snapshottable` is silently reset on resume
  (the matrix is the only net); an object nested deeper than six levels is
  described by class name only; the observer is not restored;
  `ReplayDataFeed` is the only feed whose eager stamping makes cursor resume
  work (a lazily stamping feed is unsupported until Phase 7 piece 3); a
  checkpoint is only valid against unchanged data.
- Restoring an order sets its state directly (bypassing the transition
  table); this is the single restore-only path and is documented in
  `InMemoryOrderManager.restore`.
- ADR-0006's consequence ("checkpoint serialization must be written
  explicitly (Phase 7)") is discharged by this ADR.
