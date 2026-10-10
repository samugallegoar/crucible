# ADR-0007: Bar `available_at` = bar close + non-negative feed latency (default 0)

- **Status**: draft (the original requirements; conservative option chosen)
- **Date**: 2026-09-16

## Context

When can a strategy first see bar `t`? Candidates: at the bar's close, or at
close plus a configured feed latency. The open-of-bar question is separate:
The original requirements already forbids seeing the open of a forming bar unless explicitly
configured to trade at the open with only prior information.

## Decision

`available_at = bar_close_time + feed_latency`, where `feed_latency >= 0`
and **defaults to 0**. The parameter is validated non-negative: configuration
can only delay availability, never advance it before the close. Ingest
adapters stamp `available_at` at build time so the stored data itself carries
the truth; the accessor never recomputes it.

Conservative because the earliest possible availability is the close itself,
and the only configurable direction is later (more pessimistic).

## Alternatives considered

- **`available_at = close` fixed, latency modeled only in execution**:
  simpler, but conflates data availability with order latency; a slow vendor
  feed is a data property, not an execution property.
- **Allowing negative latency for "predictive" feeds**: absurd on its face;
  banned by validation.

## Consequences

Signal timing at Level 1 with default config: a strategy acting on bar `t`
trades no earlier than the next bar. The lookahead harness pins this.
