# ADR-0008: Trial families are explicit; DSR counts every trial in the family

- **Status**: draft (the original requirements; conservative option chosen, applies from Phase 3)
- **Date**: 2026-09-16

## Context

Deflated Sharpe needs the number of trials behind a result. When experiments
span multiple strategies, what counts as "the same search"? Under-counting
trials inflates DSR — the classic self-deception this engine exists to block.

## Decision

Every experiment config carries a mandatory `family` string (already in
`ExperimentHeader`). The trial registry counts **every parameter evaluation
recorded under that family, across strategies, seeds, and time**, and DSR/PBO
for any run in the family use that full count. Splitting a family to reset
the count requires a new family name, which is visible in the report header —
the deception at least leaves fingerprints.

Conservative because ambiguity resolves toward *more* trials and therefore a
*more* deflated Sharpe.

## Alternatives considered

- **Per-strategy automatic scoping**: undercounts when a researcher tries ten
  strategy classes on the same data — that is one search, not ten.
- **Global count over all experiments ever**: maximally pessimistic but
  punishes unrelated research lines; families keep counts meaningful while
  the header keeps them auditable.

## Consequences

Reports must show family and trial count. Registry data outlives
individual runs; deleting runs does not decrement counts.
