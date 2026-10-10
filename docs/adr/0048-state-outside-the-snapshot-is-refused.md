# ADR-0048: State held outside the snapshot is refused, and other hardening

- **Status**: accepted
- **Date**: 2026-09-25

## Context

The checkpoint work (ADR-0041, ADR-0042) and the live adapter (ADR-0043,
ADR-0044) left several findings deferred in review: a strategy or risk limit
that keeps state on `self` is silently reset on resume; a failed `on_start`
left a half-started engine that a retry would rerun; two restores were not
atomic; a missing checkpoint file raised a bare `FileNotFoundError`; a `bool`
passed an int check; the engine trusted a venue's symbol, side and closed
state; the venue clock could move backwards; and two errors did not say how to
fix the problem. AGENTS.md section 1.5 says suspicious states raise.

## Decision

1. **A failed `on_start`, or a failed `resume_from` after validation, makes the
   engine unusable.** `run()`, `run_until()` and `resume_from()` then raise
   `CrucibleError` ("build a new engine"): a retry would rerun `on_start` on
   half-initialized or half-restored state.
2. **`checkpoint()` refuses state it would drop.** The engine records a
   construction-time description (`setup_fingerprint.describe`) of the strategy
   (unless it is a `StatefulStrategy`) and of every risk limit that is not
   `Snapshottable`; if any differs at `checkpoint()`, it raises
   `CheckpointError` naming the component and the changed attributes and
   saying to use `ctx.state`, `StatefulStrategy` or `Snapshottable`. The
   description sees in-place changes to `deque`, `numpy.ndarray` (by content
   hash) and `numpy.random.Generator` (by bit-generator state) as well as plain
   attributes, and the check also covers each child of a `MultiStrategy` that is
   not itself a `StatefulStrategy` (`MultiStrategy.child_strategies`).
3. **Restores are atomic** for `DeterministicEventQueue` (build locally, then
   assign) and `CompositeRiskEngine` (snapshot, restore, roll back on refusal).
4. A missing checkpoint file is a `CheckpointError`; `ckpt.expect(value, int)`
   refuses `bool`.
5. **Venue path.** The engine cross-checks a venue fill's symbol and side
   against the order and refuses a `VenueClosedEvent` with a non-terminal
   state; the simulated venue's clock never moves backwards; `summary()`'s
   `"position"` key is renamed `"emitted"` (it is an event count), so the
   checkpoint schema version is 3.
6. **Margin limits combined with `futures_specs` are refused at construction**
   (`ConfigurationError`), not at the first offending order or mark
   (ADR-0045); the runtime refusals stay as a backstop.
7. `PortfolioSnapshot.notional` names the symbol, currency, timestamp and the
   fix when an FX rate is missing.

Documented and deliberately unchanged:
- A cancel that loses the race still shows the strategy CANCELLED before the
  run aborts on the venue's buffered fill. The abort is the safe outcome; a
  "cancel pending" state would be new machinery.
- A foreign-currency order submitted before the first FX row aborts at
  submission when a risk engine is configured, earlier than its fill would
  have; the run could not have valued the position anyway.

## Alternatives considered

- **Snapshot strategy attributes automatically.** Hidden magic that would make
  `self` state silently work in checkpoints but not in the contract; the
  contract already says use `ctx.state` (ADR-0042).
- **Adopt venue events that disagree with the engine.** Silently books a
  venue's word about what the engine sent.
- **Warn instead of refuse.** Rejected by AGENTS.md section 1.5.

## Consequences

- A strategy that caches attributes during the run is refused at
  `checkpoint()`. That is intended; the message names the attribute. The
  example strategies and every existing checkpoint test pass unchanged.
  Two cases are refused by the same rule and are worth knowing: a reference
  injected after construction (the `PaperBroker` holder pattern) and a pure
  memo cache (`self._cache`, `functools.cached_property`); keep such objects
  outside the strategy's attributes or in `ctx.state`.
- Limits of the check: state nested deeper than the fingerprint's depth (6),
  a custom risk engine that is not `Snapshottable` (only limits inside a
  `CompositeRiskEngine` are checked), and stateful custom execution or slippage
  models are not detected; the resume-equivalence tests remain the real proof.
  `CompositeRiskEngine.restore` rolls back on `CheckpointError` only; a custom
  limit whose `restore` raises anything else, or whose `snapshot()` returns a
  reference to its own state, can leave a partial restore.
- Checkpoints written before schema 3 are refused on load.
- Amended by ADR-0056: the three limits above (fingerprint depth, a custom risk engine that is
  not `Snapshottable`, stateful execution models) are closed.
- Section 5-7 of `AGENTS.md` now require `Snapshottable` for stateful
  components and membership in the resume-equivalence matrix.
