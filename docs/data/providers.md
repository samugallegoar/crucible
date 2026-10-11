# Data providers (yfinance, Tiingo)

Source: live downloads through `crucible data fetch` (ADR-0063). Nothing here is a raw file; the fetched, normalized bars are the
dataset, and the provider's answers are cached (`data/cache/providers`, gitignored) so the same range is
not downloaded twice.

## What a fetch produces

`BAR_SCHEMA` bars (`symbol, event_time, available_at, open, high, low, close, volume`; UTC ns).
`event_time` is the bar close: the exchange-calendar session close for a daily bar (`--calendar`,
default `XNYS`), a day after the open for `24/7`, start + interval for an intraday bar.
`available_at = event_time` (no feed latency). The manifest `source` reads
`import:provider:<name>;price_basis=<basis>;rows_read=...;dropped=...;repaired=...` and
`import_report.json` records the provider, interval, symbols, range, any failed symbols and any symbol
whose first bar is more than 7 days after `--start` (`late_start:`) or whose last bar is more than 7
days before `--end` (`early_end:`, e.g. a delisting).

## Known issues

- **yfinance is unofficial.** It scrapes Yahoo Finance and can break, return gaps or throttle without
  notice. Its `Close` is already split-adjusted, so only `adjusted` is offered; ask Tiingo for `raw`.
  Intraday history is limited to about 60 days. If a ticker has less history than you asked for, the
  report lists it as `late_start:<SYMBOL>`.
- **Tiingo** free tier: 50 requests/hour, 1,000/day, 500 unique symbols/month. Daily bars only (its
  IEX intraday timestamps are undocumented, so they are not offered). A rejected key or a rate limit
  stops the fetch at once; symbols already fetched stay in the cache.
- A bar whose high/low do not bound its open/close is refused by the quality battery unless
  `--ohlc-repair clamp` (counted as `repaired`). Rows with missing prices are dropped and counted.
- The cache never expires, and an adjusted history is restated by later dividends and splits, so use `--refresh` to re-download. A range ending yesterday or later is never cached (the last session may not be published yet).
- Corporate actions are not fetched: with `adjusted` prices they are already folded into the series.

## Cleaning applied (counted in the report)

`incomplete` (a missing price), `not_a_session` (a daily bar on a day the calendar is closed),
`duplicate` (same timestamp twice, last kept), `not_closed` (a bar whose close is after the moment of the fetch: today's unfinished bar). `out_of_range` (a row outside the requested dates, judged on the exchange-local date). A missing or non-finite volume becomes 0 and is counted as repaired (`volume_zeroed`). An intraday bar's close is clipped to its session's close (Yahoo's hourly US bars start at 09:30).

## Re-run

```bash
uv sync                            # yfinance is a core dependency
uv run crucible data fetch --provider yfinance --store data/processed --dataset spy_daily \
    --symbols SPY --start 2020-01-01 --end 2024-12-31 --refresh
```

Keys: `.env` (see `.env.example`) or the environment; never pass a key on the command line.
