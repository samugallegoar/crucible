# ADR-0046: Dividend entitlement uses the pre-ex-date position

- **Status**: accepted
- **Date**: 2026-09-25

## Context

ADR-0034 confirmed and deferred a sequencing gap. A bar and a corporate action
that share a timestamp get the bar the lower sequence number, so the bar's
fills are booked first. `_handle_dividend`'s ex-date branch then folded the
ledger after that fill, so entitlement reflected the post-trade position: a
strategy that bought on the ex-date bar received a dividend it was not
entitled to, and one that sold on it lost a dividend it was. Real ex-dividend
convention is the opposite: the holder of record is whoever held the shares
before the ex-date.

The obvious fix, enqueueing corporate actions before bars, would break
`DELISTING`, which deliberately needs the current day's mark (ADR-0010).

## Decision

The ex-date branch folds the ledger up to `event.ts - 1` ns, so fills booked at
the ex-date timestamp are excluded from entitlement. Event ordering is not
changed; the pay-date event and `DELISTING` are untouched.

Effects, with hand-computed tests: a buy that fills on the ex-date bar is not
entitled; a sell that fills on it still receives the dividend; a short covered
on it still pays.

This is the conservative choice (AGENTS.md section 10): entitlement is the
position the strategy demonstrably held before the ex-date, and never credits
shares it did not hold.

## Alternatives considered

- **Enqueue corporate actions before bars.** Breaks same-day `DELISTING`
  liquidation at the day's mark.
- **Order per action type.** More machinery in the feed for the same result.

## Consequences

- Buy-on-ex-date no longer earns a dividend; sell-on-ex-date and
  cover-on-ex-date are now correct.
- Known limit (closed by the amendment below): with intraday bars, fills from
  earlier bars on the ex-date's calendar day counted as before the ex-date.
  Daily bars were exact.

## Amendment (2026-09-25)

With a calendar the cutoff is `min(ts - 1, session_open - 1)`, where the open
comes from `session_open_at(ts)` on the calendar (the open of the session with
`open <= ts <= close`). Fills anywhere inside the ex-date's session, including
one exactly at the open, are then excluded from the holder-of-record position.
Without a calendar, or when the timestamp lies outside any session (an exchange
calendar's midnight stamp), the original `ts - 1` rule applies. Daily bars
stamped at close behave exactly as before.

Convention (found in review): the 24/7 calendar's session is the UTC day
`[D, D+1)`, so an event stamped exactly at midnight is the START of that day,
the same reading as a midnight-stamped ex-date on an exchange calendar; the
adjustment therefore only changes the cutoff for an event stamped strictly
inside a session or at a session close on an exchange calendar. Known hazard,
inherited from `session_open_by_close`: the exchange calendar is loaded with
`exchange_calendars`' default window, which is relative to today's date, so a
lookup outside that window returns `None` and falls back to `ts - 1`; a
fixed-window load is deferred.
