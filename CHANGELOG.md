# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project follows
[Semantic Versioning](https://semver.org/); while the version is below 1.0, a minor release may
change configuration fields, artifact schemas or results (see `docs/COMPATIBILITY.md` for how each
kind of change is recorded).

## Unreleased

### Time-of-day rules (ADR-0073)
- Strategy specs gain an optional `session` block for intraday bars: `flat_by_close` (nothing held
  overnight; the position is closed on the session's next-to-last bar so the realistic re-run also
  exits before the close) and `entry_window` (open positions only on bars ending between two
  times, exchange local time). CLI `--flat-by-close`, `--entry-window HH:MM-HH:MM`; MCP
  `flat_by_close`, `entry_window`. The schedule comes from the calendar, never from later bars
  (lookahead harness extended). Specs without `session` are unchanged, ids included.

### Intraday bars in the one-step backtest (ADR-0072)
- `crucible backtest --interval` and the MCP tool's `interval`: `1d` (default) or `1h`, `30m`,
  `15m`, `5m` (yfinance). Sharpe, volatility and CAGR are annualized from the bars per session in
  the data (hourly XNYS: 7 x 252, not 252), the warm-up is checked in bars, intraday trades carry
  `entry_time`/`exit_time` and bars are stamped to the minute. Daily results are byte-identical.
- The agent guide no longer says "daily bars only"; it explains intervals, bar-counted windows and
  Yahoo's intraday history limits.

### Drawdown, dataset identity, DSR assumptions and point-in-time semantics (ADR-0071)
- **Fixed: the maximum-drawdown bootstrap dropped a first-period loss.** Resampled paths started
  at `1 + r_1` instead of 1.0 (`[-0.10, 0.10]` scored 0 %), so the interval targeted a different
  statistic than the point estimate. One definition now lives in `crucible.core.drawdown` and is
  used by the metrics and the Monte Carlo tests; invalid inputs are refused. The momentum golden's
  `metrics.json` hash moved; every simulation artifact is unchanged.
- **Fixed: one-step datasets ignored the calendar.** The calendar (canonicalised, so `nyse` and
  `XNYS` are one) is part of the dataset name, `request.json` records the effective request, and a
  stored dataset is reused only when it matches. A replaced dataset is archived under
  `<home>/archive/`. Datasets from before this change are fetched again on first use.
- **Fixed: DSR could undercount `N`.** `deflated_sharpe_ratio(..., n_trials=)` counts trials
  without a recorded Sharpe, refuses too few Sharpes to estimate the dispersion, non-finite ones
  and families that mix return frequencies (the registry now records `period_ns`, migrated in
  place). Run manifests gain `dsr_n_trials_with_sharpe` and `bars_price_basis`.
- **Fixed: `history` counted a revised observation twice.** It now returns the latest version
  available at `as_of` once per `event_time`.
- **New guard:** adjusted bars with a cash-dividend corporate-actions dataset are refused (each
  dividend would be counted twice).
- `tools/dsr_calibration.py` measures the best-of-N DSR rule: about 5 % false positives with one
  trial, 0-0.5 % with N = 10-100 (4 % for highly correlated trials), and low power (7-11 % for an
  annualized Sharpe of about 1.27 over five years). Documented as conservative, not calibrated.
- Docs separate query-time restriction, availability timestamps, version integrity (not provided)
  and price basis.

### Statistical correctness audit (ADR-0070)
- **Fixed: the null-test transforms dropped every overnight gap.** Shuffled, sign-flipped and
  synthetic bars were rebuilt with `open[k+1] = close[k]`, so the "shuffled returns" null had only
  the open-to-close drift (AAPL 2009-2025: 11.3 % a year against 26.8 % close-to-close) and any
  long-biased strategy beat it. `shuffle_bar_returns` now permutes whole bars (gap, intraday
  return, wicks, volume) and preserves every close-to-close return and the final close exactly;
  new `shuffle_intrabar_returns` and `shuffle_overnight_gaps` test the two halves separately.
- **Fixed: PBO counted ties as overfitting.** Identical or all-flat trials scored PBO = 1.0; ties
  are now resolved by expectation under random tie-breaking (identical trials score about 0.5),
  `PboResult.n_tied_splits` and the `crucible optimize --json` `pbo.n_tied_splits` key report
  them, and NaN/infinite returns, too-short partitions and constant non-zero rows are refused.
- **Fixed: Monte Carlo p-values could be 0.** `compare_to_null` returns `(k + 1) / (B + 1)` with
  `n_exceedances`, `n_valid`, `n_invalid` and a Monte Carlo standard error; NaN null values are
  excluded instead of counted as non-exceedances. The sign-flip uses the new
  `compare_to_single_null`, which has no p-value. One-step result: `validation.null_test` gains
  `exceedances`, `invalid_iterations`, `p_value_method`; `schema_version` 2.
- **Fixed: DSR printed a probability for an undefined Sharpe.** Zero-variance (and non-finite)
  return series are refused and reported as "not computable" (`dsr_error`); constancy is tested
  exactly in DSR and PBO, so a constant series no longer gets a ~1e16 Sharpe ratio.
- **Changed: the one-step default trial family is the symbol set** (`quick:<symbols>`), not
  symbols plus window, so trying another period counts as another trial. A second, home-wide DSR
  counts every one-step trial in the home (`validation.home_trial_count`, `dsr_home_wide`,
  `dsr_home_wide_error`); when it falls under 0.95 while the home has seen more trials than the
  family, the new flag `dsr_low_home_wide` blocks `some_evidence`. The result gains
  `validation.trial_family_source` and `validation.trial_count_scope`, and `provenance` gains
  `price_basis_note` and `execution_assumptions`.
- `tools/bootstrap_coverage.py` measures the empirical coverage of the Sharpe interval on
  synthetic processes; the interval is now documented as approximate, with the measured numbers
  in ADR-0070.
- Docs: README, guide, FAQ and agent guide no longer claim an interval on every number or
  point-in-time prices; yfinance is described as the core dependency it is (docstrings, error
  message, `docs/modules/data.md`, `docs/data/providers.md`).
- Golden: `sma_cross_spec_golden.json` `sha256` regenerated for the null-test, family and wording
  changes above; final equity, benchmark equity, trade count and verdict unchanged.
- **Fixed: walk-forward splits could leak forward-looking labels.** `WalkForwardSplitter` and
  `WalkForwardConfig` gain `purge` (default 0, unchanged behaviour); set it to the label horizon.
- Accounting: I2 (realized + unrealized - costs) is now property-tested over random fills,
  partial closes and reversals; its documented precision is corrected (exact up to the 28-digit
  rounding of the average cost). Unsupported corporate actions (splits and others) are pinned as
  refused.
- Determinism: resume equivalence at every boundary of a small run and eight of a randomized
  one; experiment-id sensitivity tests; a seed test that shows sub-second latency is inert on
  daily bars.
- Execution: an execution-modes table and validated-scope statement in
  `docs/modules/execution.md` (no HFT or order-book claim); mirror-case order tests; the
  slippage/spread clamp at the bar's edge is documented and pinned as a known gap.
- Acceptance scenarios indexed in `tests/README.md` §9; new edge-disappears-after-costs and
  metamorphic (scale, row-order) tests.
- CI: tests on Ubuntu, Windows and macOS; a clean-install job of the built wheel with runtime
  dependencies only. `mcp` no longer described as an optional extra.

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

### Development process and verdict guard
- **Verdict:** `some_evidence` now also requires the realism check to have run and not flagged
  `fragile_to_execution`; a result that clears every other guard without it is `not_conclusive`
  with the blocker `realism_not_checked` (ADR-0068 amendment). Existing `not_conclusive` and
  `no_edge_detected` results are unchanged.
- **Packaging:** `AGENT_GUIDE.md` at the repository root is the only copy; the wheel ships it as
  `crucible/product/AGENT_GUIDE.md`.
- **Tooling:** `python -m tools.check` runs the five gates in order and stops at the first failure;
  an opt-in fast test tier (`-m "not slow"`, `tests/slow_modules.txt`, `python -m tools.slow_report`);
  a test that every `__main__.py` guards its call. `docs/DEPENDENCIES.md` states the `yfinance` and
  `mcp` exceptions to the network-client rule.

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
