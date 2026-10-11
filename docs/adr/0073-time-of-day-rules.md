# ADR-0073: Time-of-day rules in the strategy spec

- **Status**: accepted
- **Date**: 2026-10-11

## Context

ADR-0072 opened the one-step backtest to intraday bars but left the spec without any notion of
time: "flat by the close" or "only enter in the first hour", the most common intraday rules, could
not be written, so every position could be carried overnight. Two constraints shape how they can be
added:

1. **The two engines trade a decision at different moments.** The headline vectorized engine takes
   the position decided on bar `t` at bar `t`'s close; the event-driven realism re-run (the
   promotion path) trades it at the next bar. A flat decision made on a session's last bar is
   flat at the close on the headline, but on the re-run it only executes at the next session's
   open, carrying exactly the overnight gap the rule is meant to avoid.
2. **No lookahead.** Knowing that a bar is a session's last, or next-to-last, must not come from
   the next bar's timestamp (a halt or a missing bar would leak); it must come from the schedule.

## Decision

An optional `session` block in the spec (spec_version stays 1; absent, every existing spec, its
canonical form and its experiment id are unchanged):

- `flat_by_close: true` - the position is closed by the decision of the session's
  **next-to-last** bar, and no entry is taken on the last two bars. The headline then exits at the
  next-to-last bar's close and the event-driven re-run at the last bar's open: both are flat
  across the close, and the two engines agree about it. It counts as a way out for an entry that
  has no exit rule.
- `entry_window: {start: "HH:MM", end: "HH:MM"}` - new positions (and flips) only on bars that
  **end** in the window, inclusive, in the exchange's local time (UTC on 24/7). Exits are never
  restricted.
- The schedule comes from the calendar: a bar is its session's last when it ends at the session
  close, and its next-to-last when one more bar of the declared interval would reach the close.
  The signal therefore needs `params["session"] = {"calendar", "interval"}`; the one-step backtest
  passes it only for specs that use `session`, so other specs keep their params and ids.
  `ExchangeCalendarAdapter.timezone` / `AlwaysOpenCalendar.timezone` give the local clock.
- Refused: `session` on daily bars (every bar is a whole session), an empty `session`, a time
  that is not `HH:MM`, a window that ends before it starts.
- CLI `--flat-by-close`, `--entry-window HH:MM-HH:MM`; MCP `flat_by_close`, `entry_window`.

## Alternatives considered

- **Flat on the session's last bar.** Better for the headline (it keeps the last bar's return) but
  the re-run cannot exit at the close without a market-on-close order type, so the realism check
  would hold the overnight gap and the two engines would disagree. Adding market-on-close orders
  to the event-driven engine is the way to lift this (see Consequences).
- **Mark the last bar by "the next bar is another session".** Reads the next bar's timestamp, a
  lookahead the prefix test would expose when a session ends early or a bar is missing.
- **Bar length estimated from the data.** The promotion path evaluates a growing window; an
  estimate from two bars across a weekend would differ from the full-history one.

## Consequences

- `flat_by_close` gives up the last bar's return (the last half hour on US hourly bars, five
  minutes on 5-minute bars): documented in the spec guide.
- Lookahead harness: three session specs on hourly XNYS bars pass the poisoned-future and the
  prefix tests. Integration tests check that no headline trade spans a close and that the
  event-driven re-run's fills leave the position at zero at every session close. On real hourly
  SPY data (Yahoo, Aug-Oct 2026) a flat-by-close spec with a 10:30-14:30 window made 13 trades, none
  overnight, every entry inside the window, every forced exit on the 15:30 bar.
- The buy-and-hold benchmark stays buy-and-hold (it holds overnight).
- Not addressed: market-on-close orders, time-based exits other than the close (`exit at 12:00`),
  conditions on the time of day inside `entry`/`exit` expressions, sessions that span local
  midnight on exchange calendars.
- Supersedes ADR-0072's "the rule language has no time-of-day conditions".
