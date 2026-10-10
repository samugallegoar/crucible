# ADR-0004: All internal time is UTC int64 nanoseconds

- **Status**: accepted
- **Date**: 2026-09-16

## Context

Cross-market alignment (equities, futures, FX, crypto), DST, and half-days
make timezone-aware datetimes a recurring source of silent errors. Event
ordering must be totally deterministic.

## Decision

Internal timestamps are UTC epoch nanoseconds as `int64`
(`crucible.core.types.TimestampNs`). Timezones exist only at I/O boundaries
and inside calendar objects (`exchange_calendars`). `to_timestamp_ns` refuses
naive datetimes with a `ValueError`. Arithmetic on time is integer
arithmetic; no `datetime` objects flow through the engine.

## Alternatives considered

- **tz-aware `datetime` everywhere**: comparison/DST pitfalls; slower; not
  Arrow-native.
- **float seconds**: precision loss breaks tie-breaking determinism.
- **µs instead of ns**: ns matches Arrow/Polars `Datetime("ns")` and leaves
  headroom for Level 5 tick data.

## Consequences

Human-readable rendering happens only in reports/logs. Calendars are the one
sanctioned place where local session times are computed, then converted.
