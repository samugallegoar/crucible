# ADR-0074: Market-on-close orders, `exit_at` and `time` in conditions

- **Status**: accepted
- **Date**: 2026-10-11

## Context

ADR-0073 added `flat_by_close` and an entry window, with three gaps: `flat_by_close` gave up the
session's last bar because the event-driven engine had no way to trade at the closing price, a
position could not be closed at a chosen clock time ("exit at 12:00"), and conditions could not
mention the time of day ("RSI below 30 after 10:30").

## Decision

1. **`OrderType.MARKET_ON_CLOSE`** with `OrderSpec.close_at` (a session close, UTC ns). It fills on
   the bar that ends at `close_at`, at that bar's close adjusted adversely like any aggressive fill
   and clamped into the bar (I5), so spread and slippage still apply. It must reach the market by
   `close_at - MOC_CUTOFF_NS`, ten minutes before the close (NYSE and Nasdaq stop accepting
   market-on-close orders at 15:50 ET); later it is **rejected**, and if no bar ends at `close_at`
   (a halt, missing data) it **expires**. Level 0 refuses it like every non-market type. The order
   carries `close_at` through checkpoints (`checkpoint.SCHEMA_VERSION` 6) and both creation paths
   (engine and simulated venue), so live parity holds.
2. **`session.close_with: market_on_close`** (with `flat_by_close`; the default stays
   `next_to_last_bar`, which needs no auction). The headline engine decides flat on the session's
   last bar, so it exits at the closing price; the spec signal adds a `close_at` column on the last
   bar ending by the cutoff (15:30 on hourly US bars, 15:50 on 5-minute bars) while a position is
   held, and the promotion path answers it with a market-on-close order for the target position.
   Both engines exit at the same close. No entry after the cutoff (the event-driven run could no
   longer take it out at the auction). Refused on 24/7 calendars (no closing auction). If the
   order is rejected, the next bar's flat decision trades at the next open: the honest worse case.
3. **`session.exit_at: "HH:MM"`**: positions are closed on the first bar ending at or after that
   exchange time and nothing opens again until the session ends. The headline exits at that bar's
   close, the event-driven run at the next bar's open, the same moment. On hourly US bars that end
   at :30, `exit_at: "12:00"` exits at 12:30: the first bar that ends after noon.
4. **`time` in conditions**: `time` is when the deciding bar ends, in minutes after local midnight,
   exchange time; it compares with a clock literal (`time >= 10:30`, `time < 15:00`) using `>`,
   `>=`, `<`, `<=` only; crossings, and clock literals against prices, are refused. Any spec that
   reads `time` needs `params["session"]` (the one-step backtest passes it) and intraday bars.
5. All three read the schedule (calendar, declared interval), never later bars; the lookahead
   harness covers a market-on-close spec, an `exit_at` spec and a spec with `time` conditions.

## Alternatives considered

- **Market-on-close fills when the order arrives before the closing bar opens.** Rejected while
  testing: a decision at 15:30 on hourly bars arrives a little after 15:30 with any latency, so
  every order would miss; the exchanges' real rule is a 15:50 cutoff, which is what is modelled.
- **A configurable cutoff.** An execution-config field would change every config hash
  (COMPATIBILITY §2); the cutoff is an exchange rule, recorded once (`MOC_CUTOFF_NS`) with its
  source, applied to every exchange calendar.
- **`time` as a number (`time >= 630`).** Unreadable and error-prone; clock literals are refused
  anywhere except against `time`.

## Consequences

- Checkpoints written before this change are refused (`SCHEMA_VERSION` 5 -> 6), as for every
  snapshot change.
- Verified on real hourly SPY data (Aug-Oct 2026): with `close_with: market_on_close` every headline
  exit was at the 16:00 close, and the event-driven re-run filled all 13 market-on-close orders at
  16:00 (none rejected).
- The ten-minute cutoff is the US rule; other exchanges' closing auctions have their own, not
  modelled (the same ten minutes are applied).
- Not addressed: market-on-open orders, a cutoff per exchange, day-of-week conditions.
