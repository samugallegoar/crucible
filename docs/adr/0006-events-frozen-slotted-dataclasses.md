# ADR-0006: Events are frozen, slotted dataclasses (not msgspec)

- **Status**: draft (the original requirements; conservative option chosen, revisit when serialization throughput measurably matters)
- **Date**: 2026-09-16

## Context

Events must be immutable, cheap to create, and eventually serializable for
checkpoint/resume and the debug stepper. Candidates:
`dataclass(frozen=True, slots=True)` and `msgspec.Struct`.

## Decision

**`dataclass(frozen=True, slots=True)`**: stdlib, zero extra dependency,
first-class mypy support, hashable, and immutable by construction.
Serialization for checkpoints goes through an explicit codec at the boundary
rather than being a property of the event class.

Conservative because it adds no dependency and no bespoke serialization
semantics before correctness tests exist; msgspec can be adopted later behind
the same field layout if profiling justifies it.

## Alternatives considered

- **`msgspec.Struct`**: faster creation and built-in serialization, but adds
  a compiled dependency to the core and a second source of truth for
  validation next to Pydantic. Premature before hot paths are measured
  (ADR-0003).
- **Plain tuples/NamedTuple**: no field validation affordances; poorer
  legibility for agents.

## Consequences

Event creation is not the fastest possible. Checkpoint serialization must be
written explicitly (Phase 7), which is where its determinism gets tested.
