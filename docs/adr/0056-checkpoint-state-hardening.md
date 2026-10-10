# ADR-0056: Checkpoint state hardening

- **Status**: accepted
- **Date**: 2026-09-30

## Context

ADR-0048 made `checkpoint()` refuse state it would silently drop, and listed three limits it did
not cover: state nested deeper than the setup fingerprint's depth, a custom risk engine that is
not `Snapshottable`, and stateful custom execution or slippage models. Tracing them to code
showed exactly where each hid:

- `setup_fingerprint.describe()` cut everything below six levels to a bare class name, which
  reads as "unchanged" whatever happened underneath.
- `_state_holders()` reached risk state only through `pre_trade_limits`/`mark_limits`, so a
  hand-written `RiskEngine` with neither attribute was never described.
- `LadderExecutionSimulator.snapshot()` saved only resting orders and the why-not-filled trail;
  the five pluggable models (spread, latency, slippage, commission, participation) were assumed
  pure, never described for drift and never persisted, even if a model implemented
  `Snapshottable`.

## Decision

1. **`describe()` is bounded by budget, not by a shallow wall.** At most 50,000 container or
   object nodes **per top-level attribute** (each direct child of the described object has its
   own count), 500,000 overall, and 40 levels (a recursion-safety ceiling, not the everyday
   limiter). What is cut becomes `{"cls": name, "truncated": True}`, visibly different from a
   bare class name. An object already on the recursion path becomes
   `{"cls": name, "cycle": True}` (required once the ceiling rises: an unguarded cycle would
   expand to it). A keyword `opaque` names instances of given types without recursing, for shared
   engine-owned state that is snapshotted elsewhere. Two properties came out of the independent
   review of this batch and are load-bearing: the budget is per attribute (a first version used
   one global count, so a 4,000-instrument read-only list starved every later attribute and a
   mutating counter read as unchanged, a regression against ADR-0048), and set items are described
   with independent budgets (a shared budget truncated different items depending on hash order, so
   the description stored in the checkpoint header differed between processes). Dates, times,
   `bytes`/`bytearray`, `Fraction`, `complex` and numpy scalars are described by value (they used
   to read as a bare class name, hiding changes).
2. **A custom `RiskEngine` that is not `Snapshottable` is described and checked whole**
   (`risk_engine <Class>`), in addition to the per-limit check that still covers
   `CompositeRiskEngine`'s own non-`Snapshottable` limits.
3. **Execution models get the same contract risk limits have.** A `Snapshottable` model is saved
   by `LadderExecutionSimulator.snapshot()` under `models` and restored in place, all-or-nothing:
   a different model set is refused, state for a stateless model is refused, and any exception
   while restoring a model rolls every model back (from a deep-copied backup, so an aliased
   `snapshot()` cannot defeat it) before re-raising; resting orders and the why-not-filled trail
   are parsed first and assigned last, so they are untouched by a refusal. A model that is not `Snapshottable` is described at construction and
   refused at `checkpoint()` if it changed (`execution.<slot> <Class>`). `SCHEMA_VERSION` is 4.
4. **`MarketStats` is opaque** when models are described. `SqrtImpact` and `LinearImpact` hold a
   reference to the shared statistics object, which changes every bar and is snapshotted by the
   engine; describing it would have refused every Level 3+ run. Found while planning, proved by
   the existing Level 4 resume test.
5. The simulated venue wraps its own ladder built from the same models, so live checkpoints gain
   the `models` entry without venue code changes.

## Alternatives considered

- **A content hash at the truncation boundary.** `repr()` of a plain object is identity-based, so
  a hash would claim to watch a subtree it does not; the explicit marker is honest.
- **A generic snapshot for any `ExecutionBackend`.** A backend supplied through
  `execution_backend_factory` owns its own state and its own `snapshot()`/`restore()`.
- **Detection only for models.** It would leave models the one stateful category with no way to
  be legitimately resumable.

## Consequences

- A stateful custom risk engine or execution model is refused at `checkpoint()`, by name, unless
  it implements `Snapshottable`, in which case the ladder (and the simulated venue, which wraps
  one) persists it. Built-in models are stateless and behave exactly as before; all 288
  combinations of built-in spread, latency, slippage, commission and participation checkpoint
  and resume cleanly at Level 4; no golden and no result changed.
- A custom backend from `execution_backend_factory` owns the persistence of any model it uses:
  the engine still checks the models as configured but cannot know whether that backend saves a
  `Snapshottable` model's state.
- Checkpoints written under schema 3 are refused on load with the existing message.
- Residual limits: a single attribute with more than 50,000 container or object nodes has its
  tail unchecked (its truncation marker still shows the boundary); a `snapshot()` that returns a
  reference to live state can still alias outside the ladder's own rollback (ADR-0048); the
  resume-equivalence tests remain the real proof.
