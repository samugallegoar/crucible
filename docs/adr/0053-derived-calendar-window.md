# ADR-0053: Exchange calendars cover a window derived from the run, not from today

- **Status**: accepted
- **Date**: 2026-09-27

## Context

`exchange_calendars` builds a calendar over a default window of "today minus 20 years to
today plus one year". `get_trading_calendar(name)` used that default, so the same config and
data gave different calendars on different dates: a 2005 backtest would lose its sessions
from 2026 on, and the sessions a 2010-2026 equity run needs would start disappearing around
2030. That breaks determinism (AGENTS.md section 1, rule 3). It was recorded as a hazard in
the ADR-0046 amendment and the handoff notes; the importer already avoided it with its own range.

## Decision

1. `ExchangeCalendarAdapter(name, *, start, end)` and `get_trading_calendar(name, *, start,
   end)` take the range (UTC ns) the caller works on. There is no default: omitting it is a
   `TypeError`, so nothing can fall back to the date-dependent window.
2. The calendar is built over `[start - 366 days, end + 366 days]` (UTC dates), exposed as
   `.window`. The window depends only on the arguments. The padding covers look-back queries
   such as the previous close or session open.
3. Callers pass their own range: the runner uses `config.start_ns`/`config.end_ns` (no config
   change, so `experiment_id` and golden `config.yaml` are unchanged); `crucible data check`
   and the importer's quality check use the dataset's first and last `event_time`; the example
   data builders use their generation range.
4. A window the calendar cannot cover (unknown name, unsupported dates) is a
   `ConfigurationError` saying which calendar and dates. `end < start` is refused. `24/7`
   ignores the range.
5. Sessions outside the window do not exist for the adapter: `session_closes` is empty
   there and `next_session_close` raises `ValueError`. A run that needs sessions beyond its
   own start/end plus a year must widen its range.

## Alternatives considered

- **Explicit `calendar_start`/`calendar_end` config fields.** Another thing to configure and
  a change to the serialized config, which moves `experiment_id` and the golden `config.yaml`.
- **A fixed constant window (for example 2000-2035).** Deterministic but a time bomb, and a
  hardcoded parameter.
- **Keeping the default and refusing out-of-window dates.** Still date-dependent: the same
  run refuses in some years and not in others.

## Consequences

- The same config and data give the same calendar on any day.
- Callers of the two factories must state a range (three library call sites, two examples
  and two tests changed); external code calling them without one breaks loudly.
- The importer's `session_close` mapping (ADR-0052) keeps its own range-based calendar; it
  builds the same kind of window and is not routed through the adapter because it needs
  session labels.
- No golden change, no new invariant identity.
