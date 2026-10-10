# ADR-0002: Parquet on disk + DuckDB for queries

- **Status**: accepted
- **Date**: 2026-09-16

## Context

Datasets must be columnar, local, versionable, and hashable;
the run registry needs SQL over artifacts. No external services:
results must reproduce years later on a laptop.

## Decision

Parquet files as the storage format, one directory per dataset version with a
`manifest.json` (schema version, content hash, row count, source, build
time). DuckDB as the query engine over Parquet for PIT queries, the trade
log, and the experiment registry. Polars for in-process transforms
(Arrow-native, zero-copy interop with both).

## Alternatives considered

- **SQLite**: row-oriented; poor fit for columnar scans over bar history.
- **A dataframe-only store (pickle/feather ad hoc)**: not versionable or
  hash-friendly; encourages schema drift.
- **A server database**: violates local-reproducibility.

## Consequences

Byte-identical golden outputs require deterministic Parquet writes (fixed
row order, fixed compression settings) — the Phase 1 artifact writer must pin
these and the golden test enforces them.
