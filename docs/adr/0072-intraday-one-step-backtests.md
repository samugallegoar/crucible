# ADR-0072: Intraday bars in the one-step backtest

- **Status**: accepted
- **Date**: 2026-10-11

## Context

The engine, the vectorized path, the data layer and the yfinance adapter already handle intraday
bars (5m, 15m, 30m, 1h), but the one-step backtest (`crucible backtest`, the `crucible_backtest`
MCP tool) had no interval: it always fetched `1d`, and the agent guide said "Daily bars only". The
owner wants to test intraday strategies through the same flow. Three things in that flow assumed a
day per bar:

1. **Annualization**: `periods_per_year` was 252 (365 on 24/7), so an hourly Sharpe, volatility or
   CAGR would have been annualized as if every bar were a day.
2. **The window check** compared calendar days with the rules' warm-up in bars.
3. **Wording** ("the same daily returns") and timestamps (trades and bars stamped by date only).

## Decision

- `BacktestRequest.interval` (default `1d`), `crucible backtest --interval`, and the MCP tool's
  `interval` (`1d`, `1h`, `30m`, `15m`, `5m`). The provider refuses an interval it does not offer
  (Tiingo is daily only), and the dataset identity already includes the interval (ADR-0071).
- **Bars per year from the data**: sessions per year (252 on an exchange calendar, 365 on 24/7, the
  existing convention) times the median number of bars per session, each bar assigned to the first
  session close at or after its end. Daily data gives exactly 1 x 252, so every daily result is
  byte-identical (the product golden did not move). Hourly XNYS gives 7 x 252 = 1764 (six full
  hours and the 15:30-16:00 half hour), 5-minute XNYS 78 x 252, hourly 24/7 24 x 365.
- **Window check in bars** for intraday: after the data is available, every symbol needs at least
  1.5 times the rules' warm-up in bars; daily keeps the pre-download calendar-day check.
- Intraday trades carry `entry_time`/`exit_time` and intraday bars `first_bar`/`last_bar` and chart
  points are stamped to the minute (UTC); the wording names the bar length ("1h-bar returns").
  Daily output keeps its keys and text.
- Nothing else changes: the rules count bars (`sma(20)` on hourly bars is a 20-hour average), the
  vectorized fill timing, the costs, the null test, DSR and the verdict guards apply as they are.

## Alternatives considered

- **Bars per year from the interval alone** (`6.5 h / 1 h`): wrong for a partial last bar (7 bars,
  not 6.5) and for calendars with lunch breaks or half days; counting what the data holds matches
  the returns the statistics are computed on.
- **Bars per year as rows / years spanned**: sensitive to where the window starts and ends
  (weekends, holidays), especially in a 60-day intraday window.
- **Relaxing the verdict guards for intraday** (fewer years): rejected. A two-month test is a short
  sample whatever the bar length; the guards say so.

## Consequences

- Intraday tests are short: Yahoo keeps about 60 days of 5-30 minute bars and about two years of
  hourly bars, so most intraday results are `not_conclusive` with a short-sample flag. That is the
  honest answer for so little history.
- The data-quality coverage check confirms one bar at every session close; it does not detect a
  missing bar inside a session.
- The rule language has no time-of-day conditions: "flat by the close" or "only trade the first
  hour" cannot be written; a position can be held across sessions (and takes the overnight gap).
- Verified on real data: SPY hourly bars on XNYS from Yahoo, end to end with the realism check.
  The 24/7 intraday path is covered by synthetic tests only.
