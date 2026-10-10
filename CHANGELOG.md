# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project follows
[Semantic Versioning](https://semver.org/); while the version is below 1.0, a minor release may
change configuration fields, artifact schemas or results (see `docs/COMPATIBILITY.md` for how each
kind of change is recorded).

## Unreleased

### Product layer: a no-code, one-step backtest (ADR-0067, ADR-0068, ADR-0069)
- Declarative **strategy specs** (`crucible/strategy_spec/`): moving-average crossovers, threshold
  rules on `rsi`, `roc`, `highest`/`lowest`, Bollinger bands, long-only or long/short, `all_in` or
  fixed-fraction sizing, stop-loss, take-profit and maximum holding; validated with actionable
  refusals, compiled to the vectorized signal path (and promotable). `crucible schema --kind
  strategy-spec`, `crucible spec check|templates`, `examples/sma_cross`.
- **`crucible backtest`** and the `crucible_backtest` MCP tool: fetch if missing, quality gates,
  vectorized run (one trial with DSR), buy-and-hold benchmark, seeded shuffled-returns null test,
  optional `--realism-check` (Level 2 event-driven re-run, not a trial), a deterministic
  plain-language summary and a self-contained HTML report. `crucible results`, `crucible config
  show|set-home`; results live in an absolute home folder (`CRUCIBLE_HOME`).
- **MCP server**: async tools whose cancelled or timed-out calls kill the child process
  (`CRUCIBLE_MCP_TIMEOUT`), path arguments resolved to absolute (`CRUCIBLE_WORKDIR`), the missing
  flags exposed, new product tools, the `crucible://guide` resource and the `backtest_a_strategy`
  prompt; `AGENT_GUIDE.md` for agents.
- Data: `--ohlc-repair clamp_rounding` repairs only float-rounding-sized OHLC violations (Yahoo's
  adjusted SPY was refused on a 3e-14 gap). The CLI console is UTF-8 on Windows; the MCP child no
  longer inherits `VIRTUAL_ENV`.
- `yfinance` and `mcp` are core dependencies (their extras remain as aliases).
- `examples/sma_cross` now carries the hand-written vectorized signal and `config_vectorized.yaml`
  from the SMA example branch next to the spec; both agree bar for bar on real SPY data and differ
  only on exact fast == slow ties.
- Docs: README rewritten as a product page; user pages under `docs/guide/`; a contributor hub at
  `docs/contributing/README.md`. No engine, config-hash, artifact or existing golden change.

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
