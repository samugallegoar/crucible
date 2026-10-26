# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project follows
[Semantic Versioning](https://semver.org/); while the version is below 1.0, a minor release may
change configuration fields, artifact schemas or results (see `docs/COMPATIBILITY.md` for how each
kind of change is recorded).

## Unreleased

### Audit fixes: result integrity, execution, accounting and statistics (ADR-0079)
- **Experimental provenance no longer depends on the working directory.** `commit` and
  `env_lock_hash` were resolved relative to the process cwd, so a run from a notebook, a
  worktree or an installed wheel recorded `unknown` for both, silently. They are now resolved
  from the checkout that contains the loaded package, and every manifest also records
  `crucible_version` (additive; `schema_version` stays 1).
- **A finished run is not silently overwritten by different code.** The experiment id hashes
  the config and the data, not the code, so re-running after a code change wrote into the same
  directory. A new `code_fingerprint` (HEAD + `git status` + the working-tree diff) is recorded
  and compared; a different fingerprint raises `ExperimentError` before any file or trial is
  written, with `--overwrite` (CLI) to replace it on purpose.
- **A degenerate return series no longer invents a Sharpe of ~1e14.** A constant per-period
  return has float-dust standard deviation, which `std == 0.0` missed; the value was then
  stored in the append-only trial registry and deflated every later trial in the family. The
  Sharpe/volatility estimators share one definition (`crucible/core/stats.py`), report `0.0`
  for a series with no dispersion, and the runners record `NULL` instead of a Sharpe for it.
- **Futures delisting booked the whole notional as cash** (2 ES at 4520 credited +9040 instead
  of the price delta, leaving equity 8040 too high). The liquidation now realizes
  `price_delta * multiplier` like any futures close, with no settlement lag, and a cash
  dividend on a futures symbol is refused.
- **Annualization**: an experiment config that leaves `periods_per_year` unset now derives it
  from the bars (252 sessions x median bars per session; 365 for `24/7`) instead of assuming the
  daily 252. Intraday Sharpe/volatility/CAGR were understated by `sqrt(bars per session)`
  (hourly on XNYS: 0.81 vs 2.13 for the same series); set the field explicitly to keep the old
  value. The one-step product already derived it; now both paths share the rule in
  `crucible.data.calendars`.
- **`equity.parquet.cash` is every currency converted to the base**, as documented; it was the
  base-currency wallet only, so `cash + positions` disagreed with equity in a multi-currency
  run. `fees_paid` has the same fix (`PortfolioBalances.fees_by_currency`, converted at the mid
  instead of adding dollars to euros); a past fee is valued at the snapshot's rate. A zero balance no longer demands an FX rate, and a non-finite or non-positive mid rate
  is refused instead of silently zeroing or inverting equity.
- **Execution:** a partially filled OCO leg now cancels its sibling (the take-profit used to
  fill afterwards, taking a 100-lot pair to -110); a DAY order expires after the one full bar
  ADR-0010 specifies (it survived two); a participation cap whose ADV history is too short
  rejects the order instead of killing the run; an algo slice is no longer labelled
  "liquidity constrained"; a fill clamped into `[low, high]` now records the spread/slippage it
  dropped in the order's reason trail.
- **Vectorized engine:** a signal function that drops, duplicates or invents rows is refused
  (the lag is by row, so a sparse score frame silently re-timed every later weight and
  compressed the equity curve); a bars dataset with a duplicated `(symbol, event_time)` row is
  refused too.
- **`crucible walk-forward`** (ADR-0081): a first out-of-sample evaluation command. Each fold
  selects a 1-D parameter on its train window and reports only the following test window, with
  the per-fold table, the mean/spread across folds, the share of positive folds and an optional
  protected holdout; summary in `<artifacts>/walk_forward.json`. Test runs do not record trials,
  so the per-fold selection is not deflated (stated in the output). The concatenated
  out-of-fold series and its DSR are the next increment.
- **Invariant I2 is registered** (ADR-0080): at every mark, equity must tie out to
  `initial + realized + unrealized − fees + dividends/borrow/financing` (1e-9 relative, for the
  Decimal average-cost residue). `docs/INVARIANTS.md` called I2 "derived" while it was neither
  registered nor true once a dividend was paid; the futures-delisting defect above passed
  I1/I3/I4 and would have tripped this check. The fold gains `income_by_currency`.
- **Statistics:** `optimize` applies the same frequency-mismatch gate as the runners before
  reporting a DSR (it used to deflate across daily and hourly trials), and ranks
  `volatility`/`max_drawdown` by the smallest value rather than the largest.

### Shuffled-returns test: 1,000 shuffles by default (ADR-0078)
- `null_iterations` defaults to 1,000 (it was 100) in `crucible backtest` and the MCP tool: the
  Monte Carlo p-value's standard error drops from about 0.04 to 0.013 at p = 0.2. **Behaviour
  change:** a default run takes about 30 seconds for ten years of daily bars (it took about six
  seconds); `--null-iterations 100` restores the quick run. Default-run p-values and their
  wording change (0.228 became 0.215 on the SMA example); no seed, trial count, DSR or golden
  changed (the golden fixes `null_iterations`). A p-value below 0.001 is now shown with four
  decimals instead of `0.000`.

### One fixed results table (ADR-0077)
- `crucible backtest` (terminal, `--json`, the MCP tool and the HTML report) now takes its metric
  table from one builder: the same 23 rows, in the same order, with the same labels and number
  formats in every run, and `n/a` where a value does not exist. The JSON document gains
  `results_table` (`columns`, `rows` with stable ids, and a ready-made `markdown` text); additive,
  `schema_version` stays 2 and the product golden is unchanged. The terminal and report tables grew
  from 6-7 rows to 23. Beyond volatility, total return, bars held, time in the market and the
  validation rows, they now answer "does the edge survive?": cost drag per year, turnover, the
  break-even cost per side (from one extra frictionless run: costs are linear in turnover),
  winning trades after costs, net expectancy per trade with a 95% range, profit factor, average
  win over average loss, alpha and beta against buy-and-hold with a Newey-West t-statistic,
  return per unit of exposure, and the share of the Sharpe kept under the realism check. The
  deflated-Sharpe label no longer says "chance the Sharpe is real". The numbers are also in the
  document as `diagnostics` (additive; the golden surface is unchanged). `AGENT_GUIDE.md` and the
  `crucible_backtest` tool description tell agents to show `results_table.markdown` unchanged.

### Shorter Windows and macOS CI jobs (ADR-0076)
- A `single_os` marker labels OS-independent plumbing tests (CLI wrappers over library calls,
  the runtime flag, perturbation, sensitivity and trial-count orchestration, three MCP plumbing
  tests): CI runs them on Ubuntu only. Every OS-sensitive test and the golden, lookahead, property
  and unit tiers still run on all three OSes, and a local run still runs everything. A guard test
  fixes which modules may use the marker.

### Faster test runs (ADR-0075)
- The suite runs on worker processes (pytest-xdist, dev-only): `tools.check` on up to four,
  CI on every core of the runner; `tools.check --serial` runs one process.
- The two Phase 3 null tests moved to `tests/integration/test_phase3_null_acceptance.py` (one class
  each) and the market-on-close / `exit_at` / `time` end-to-end tests to
  `tests/integration/test_product_time_rules_e2e.py`, so the slowest pieces run side by side; the
  time-of-day backtests use two months of hourly bars instead of six. No assertion, seed or
  iteration count changed.

### Market-on-close orders, `exit_at` and `time` in conditions (ADR-0074)
- `OrderType.MARKET_ON_CLOSE` with `OrderSpec.close_at`: fills at the closing bar's close (spread
  and slippage still apply) if it reached the market ten minutes before the close (the NYSE/Nasdaq
  15:50 cutoff); later it is rejected, without a closing bar it expires. Checkpoint
  `SCHEMA_VERSION` 6.
- `session.close_with: market_on_close` lets `flat_by_close` keep the last bar: both engines exit at
  the closing price. `session.exit_at: "HH:MM"` closes positions from a clock time on. Conditions can
  read `time` (`time >= 10:30`). CLI `--market-on-close`, `--exit-at`; MCP `market_on_close`,
  `exit_at`.

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
