# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project follows
[Semantic Versioning](https://semver.org/); while the version is below 1.0, a minor release may
change configuration fields, artifact schemas or results (see `docs/COMPATIBILITY.md` for how each
kind of change is recorded).

## Unreleased

## 0.1.0 - 2026-10-09

First release.

### Engine and accounting
- Deterministic event-driven backtest engine with realism Levels 0-4: instant fills, spread,
  latency, slippage, dynamic spread, square-root impact, per-share commissions, participation caps
  and quote-aware fills (`spread: quoted`).
- Order types: market, limit, stop, stop-limit, trailing, bracket / OCO / OTO, TWAP / VWAP /
  participation; a validated order state machine.
- Ledger-derived portfolio: multi-currency with FX marking, shorts, margin and margin calls, borrow
  cost and margin financing, futures with daily mark-to-market and rolls, dividends (ex-date and
  pay-date), delistings, settlement lag; run-time invariants.
- Risk engine with pre-trade and mark-time limits; portfolio constructors; multi-strategy
  attribution.
- Checkpoint / resume (a resumed run equals the uninterrupted one), a paper runtime and a
  simulated-venue live runtime that reproduce the backtest's orders and fills.

### Data
- Point-in-time Parquet store with manifests and content hashes, `as_of` reads that filter
  `available_at <= as_of`, exchange calendars, a quality battery run before every run.
- Spec-driven importers (OHLCV CSV, Polymarket CSV / Parquet) behind `crucible data build`.
- Data providers behind one `PriceProvider` interface: yfinance (optional extra, adjusted prices,
  unofficial) and Tiingo (free key, raw and adjusted, daily), with typed errors, bounded retry, a
  raw-response cache and `crucible data fetch`. API keys come from the environment or `.env`.

### Validation and research
- Deflated Sharpe, probability of backtest overfitting (CSCV), purged K-fold / CPCV and
  walk-forward splits, Monte Carlo resampling, null tests, factor regression, sensitivity
  surfaces, contamination flagging and a trial registry.
- Vectorized engine (Levels 0-1) with FX and futures multipliers, position episodes, parallel
  trial-counted sweeps, and promotion to the event-driven engine.

### Interfaces
- `crucible` CLI: `run`, `run-vectorized`, `promote`, `optimize`, `validate`, `compare`, `report`,
  `debug`, `schema`, `data build|check|fetch|list`; `--json` on every command and
  `--override PATH=VALUE`.
- MCP server (`crucible-mcp`, optional extra `mcp`) exposing the commands as tools.

### Known limitations
See the README section "Known limitations & future improvements".
