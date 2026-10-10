# ADR-0052: Spec-driven data importers for the user's files

- **Status**: accepted
- **Date**: 2026-09-26

## Context

`crucible data build` was a stub. The project owner has historical data in CSV and Parquet
(US equities, gold and other metals, Polymarket five-minute BTC contracts). Getting them in
means deciding things the files do not say: adjusted or raw prices, timezone and bar-open
versus bar-close timestamps, what to do with rows that violate OHLC bounds, how a binary
contract's bid/ask quotes become bars, and how its outcome reaches the accounting.

## Decision

1. **A YAML import spec** (`crucible/data/importers/spec.py`, pydantic, frozen,
   unknown keys refused) declares every assumption. `price_basis` (`raw|adjusted`) has no
   default; OHLC repair is `refuse` unless the spec says `clamp`. `crucible data build
   <spec> --store S [--start --end --max-contracts --max-rows]` builds the datasets.
2. **Nothing is silent.** Every dropped or repaired row is counted by reason
   (`import_report.json` beside the dataset and the manifest `source` string, which also
   carries `price_basis`); dropped plus repaired rows above `max_dropped_fraction` refuse. A
   timestamp or number that does not parse refuses with an example; an ambiguous or
   non-existent local time (daylight saving) refuses.
3. **The quality battery runs before anything is written**; a refusal or the `--max-rows`
   guard leaves no dataset directory. Skipping a check needs a reason in the spec
   (`quality_skip` + `quality_skip_reason`); `data check --skip/--skip-reason` repeats it.
   Datasets built from calendars they do not follow (24/5 gold, prediction-market windows,
   equities that miss a session) skip only `calendar_coverage`.
4. **OHLCV timing.** `event_time` is the bar close in UTC ns: `bar_open` adds the interval
   (`1mo` rolls to the next month start), `bar_close` is used as is, `session_close` maps a
   date to that session's close on an exchange calendar (a non-session date is dropped and
   counted). `available_at = event_time + feed_latency_s`.
5. **Adjusted prices are imported, labelled.** The equities are split- and dividend-adjusted;
   the dataset says so in its manifest. This is a conscious exception to "never store
   adjusted prices as the raw source of truth" (AGENTS.md section 9): the raw files stay
   untouched, and the label prevents mistaking the data for raw prices.
6. **Polymarket contracts.** Each five-minute contract becomes `BTC5M-<start>-UP` and
   `-DOWN` symbols priced by the bid/ask mid in `bar_seconds` (default 1 s) bars closing at
   the bucket end and available then (pessimistic: never usable at the snapshot's own log
   time); a snapshot whose bucket ends at or after the window end is excluded. Quotes with
   `ask <= 0`, `bid > ask`, a negative bid or a null are dropped by reason; an empty bid side
   (`bid = 0`) is kept. Volume is 0. A spot series `BTCUSD` accompanies them.
7. **Settlement rides the existing delisting mechanism.** At the window end each symbol gets
   a flat bar at 1.0 (the recorded winner) or `settlement_floor` (default 0.001, since the
   battery needs positive prices) and a `delisting` corporate action in
   `<dataset>_actions`; the engine liquidates positions at the last mark, the settlement bar
   (bars are processed before actions at a shared timestamp). Tested end to end with a
   hand-computed cash balance. The winner comes from the data, not from BTC versus strike;
   contracts without a recorded winner are dropped and counted.
8. **Size guard.** `--max-rows` (default 5,000,000) refuses to write more bars than the
   replay feed can hold; the Parquet path reads lazily, and the importer refuses more than
   20M selected ticks in memory. A window or a contract cap is the way out.

## Alternatives considered

- **One module per source with hard-coded parsing.** No reuse; every assumption hidden in code.
- **Refusing adjusted data.** Loses the only equity source; the label gives the safety.
- **Deriving the outcome from BTC versus the strike.** The data records the winner, which is
  what settled; the arithmetic would only add a way to disagree with it.
- **Keeping bid and ask as extra columns.** Needs a quote-aware fill model; the mid is
  optimistic for a taker, which is stated in the data docs and deferred.
- **Auto-repairing OHLC bounds.** Changes prices without the owner deciding to; `clamp` is
  opt-in and counted.

## Consequences

- The user's files load with `crucible data build`; `docs/data/` documents each source
  (AGENTS.md section 14) with the real counts.
- Backtests on Polymarket data trade at the mid with no spread cost, so results are
  optimistic until a quote-aware model exists; volume-dependent fill models are meaningless
  there (volume 0).
- The equities miss sessions and are adjusted; strategies on them must tolerate a missing bar
  and must not apply dividends or splits again.
- No golden change, no new invariant identity.
- Deferred: fundamentals, news and filings (no dataset contract), quote-aware fills, Parquet
  input for the generic OHLCV importer, inferring splits and dividends from adjusted versus
  raw, incremental imports, the Interactive Brokers adapter.
