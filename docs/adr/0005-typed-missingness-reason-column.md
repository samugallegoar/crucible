# ADR-0005: Typed missingness via nullable value + reason enum column

- **Status**: draft (the original requirements; conservative option chosen, revisit before Phase 1 data layer freezes)
- **Date**: 2026-09-16

## Context

The original requirements require missingness to be typed: `NaN` (measured but empty) vs
`unavailable` (not yet published) vs `delisted` vs `market_closed` vs
`no_liquidity`. Two candidate encodings: (a) sentinel values inside the data
column, (b) nullable value column plus an explicit companion reason column.

## Decision

**Nullable value column + companion `missing_reason` enum column**
(`crucible.core.types.MissingReason`, stored as Arrow dictionary/categorical).
A null value with a null reason is a data-quality error: if a value is
missing, the dataset must say why, or the quality engine refuses the run.

This is the conservative option: no magic values that arithmetic can silently
consume, and an unexplained missing value is a refusal, not a guess.

## Alternatives considered

- **Sentinel scheme (e.g. NaN vs ±inf vs magic constants)**: compact but
  arithmetic-hazardous; a sentinel that survives a computation produces
  silently wrong numbers — the exact failure mode this engine exists to
  prevent.
- **Struct column (value, reason)**: semantically clean but awkward across
  Polars/DuckDB operations and joins today.

## Consequences

Datasets grow one categorical column per value column that can be missing
(cheap under dictionary encoding). Accessors must propagate the reason
column; the vectorized path masks on it explicitly.
