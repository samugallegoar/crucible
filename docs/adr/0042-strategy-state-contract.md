# ADR-0042: Resumable strategy state lives in `ctx.state`; `StatefulStrategy` for the rest

- **Status**: accepted
- **Date**: 2026-09-24

## Context

The original requirements define `ctx.state` as "versioned, serializable strategy state for
checkpoint/resume". The engine cannot see attributes on a strategy object
(`self.x`). `MultiStrategy` builds one `BacktestContext` (each with its own
`state`) per sub-strategy inside `on_start`, which a resume must not re-run
because examples initialize their counters there.

## Decision

1. `ctx.state` may hold the codec types (None, bool, int, float, str,
   Decimal, tuple, list, dict[str, ...], set, frozenset, numpy PCG64
   Generator). Anything else makes `checkpoint()` raise `CheckpointError`
   naming the key path (`$.ctx_state.<key>`).
2. Attributes on the strategy object are not captured. The contract: a
   resumable strategy keeps all mutable state in `ctx.state`. This cannot be
   enforced generally; it is backed by the resume-equivalence matrix (every
   built-in strategy and example) and by this ADR.
3. **Resume never calls `on_start`.**
4. Optional `StatefulStrategy` Protocol (`checkpoint_state()`,
   `restore_state(ctx, state)`): the engine stores what the first returns and
   calls the second in place of `on_start`. `MultiStrategy` implements it
   (each sub-context's state plus its children's hook results; contexts are
   rebuilt by a helper shared with `on_start`).
5. A class attribute `STATE_VERSION: int` (default 1) is recorded in the
   checkpoint; a mismatch refuses the resume. This is the "versioned" in the
   the original requirements; no migration tooling.

## Alternatives considered

- **Require `get_state`/`set_state` on every strategy:** heavier for the
  common case whose state already lives in `ctx.state`.
- **Pickle the strategy object:** unsafe and unstable (ADR-0041).
- **Detect `self.x` mutation automatically:** not reliable; deferred.

## Consequences

- Sets in `ctx.state` are restored equal but with a new identity; shared
  references to one mutable object from two keys are refused.
- Strategies written before this ADR that hold state on `self` will resume
  incorrectly until migrated; the matrix catches the built-in ones.
- Schema-migration tooling and `self`-state detection are deferred.
