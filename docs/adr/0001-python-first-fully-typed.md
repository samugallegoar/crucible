# ADR-0001: Python ≥ 3.12, fully typed, uv-managed

- **Status**: accepted
- **Date**: 2026-09-16

## Context

The primary user is a single quant researcher; secondary users are AI coding
agents. Both need a legible, refactorable codebase over raw speed (the original requirements). Determinism and correctness are enforced by tests and types, so the type
system must actually be used.

## Decision

Python ≥ 3.12 with `mypy --strict` as a CI gate; `uv` with a committed
`uv.lock` for reproducible environments; `ruff` for lint/format. The virtual
environment pins 3.12 (`.python-version`) — the original requirements floor — for maximal
compatibility with the scientific stack.

## Alternatives considered

- **Rust/C++ core with Python bindings**: rejected as a core dependency by
  the original requirements; hot paths may later be ported behind existing Python interfaces.
- **Loose typing / gradual mypy**: rejected; the information barrier and
  Protocol-first design depend on types being load-bearing.

## Consequences

Hot loops will eventually need Numba (ADR-0003). Every public function
carries full annotations; `Any` requires a justifying comment.
