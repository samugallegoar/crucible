# ADR-0003: Hot paths via Numba later; no Rust/C++ in the core

- **Status**: accepted
- **Date**: 2026-09-16

## Context

Correctness before speed: no optimization before golden and
property tests exist. But the design must not paint us into a corner where
speeding up the event loop or ledger requires a rewrite.

## Decision

No JIT/no native code until Phase 2+ and only behind existing Python
interfaces, starting with Numba on measured hot loops. Rust/PyO3 remains an
optional, later port target behind the same Protocols; it is never a core
dependency (AGENTS.md §9).

## Alternatives considered

- **Numba from day one**: rejected; it constrains code style (nopython
  subset) before we know where the hot paths are, and complicates debugging.
- **Rust core now**: rejected by the original requirements; kills agent legibility and slows
  iteration on semantics, which is where the risk is.

## Consequences

Phase 1 will be slow on large universes. That is acceptable and explicitly
chosen. Benchmarks (opt-in `-m bench`) arrive after Phase 2 to find real hot
paths before anything is ported.
