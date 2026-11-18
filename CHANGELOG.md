# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project follows
[Semantic Versioning](https://semver.org/); while the version is below 1.0, a minor release may
change configuration fields, artifact schemas or results (see `docs/COMPATIBILITY.md` for how each
kind of change is recorded).

## Unreleased

### Fathom C3b-1b: Globex trade dates from the session calendar; continuous datasets v3 (ADR-0092)
- **Behaviour change (data).**
  - The continuous builder and the integrity report's `cme` rule now date bars by the CME session
    calendar (ADR-0091) instead of the 17:00 wall-clock rule of ADR-0087, which was wrong in
    three cases:
    - before trade date 2012-11-19, when the session opened at 15:30;
    - on holiday Mondays and Thanksgiving, which it made into 87 false short sessions;
    - on the Fridays booked to a Monday trade date.
  - `calendars.cme_trade_date_expr` is removed. `continuous.DATASET_VERSION` is `v3`, and the
    `*_v2` datasets are reported as superseded.
  - On the real store, ES re-dates 123,953 of 5,745,346 bars and has 4,146 sessions instead of
    4,233. No roll of ES, NQ, YM or RTY moves.
- **Out-of-coverage bars are refused.**
  - Raw bars outside the calendar's coverage are refused.
  - `crucible data continuous --trim-to-calendar` (or `build_continuous_datasets(trim_to_calendar=True)`)
    drops and counts them. The manifests record `trimmed_rows` and the calendar version and hash.
  - `nkd_*_v3` starts at NKD's coverage (contract NKDZ2012, 314,040 raw bars trimmed). It has 56
    rolls; the futures-simulator acceptance figures for NKD become 56 rolls, 31 delayed and a
    mean reference error of $77.23.
- **Integrity report.**
  - Under `cme`, the root is read from the symbols.
  - A root without a calendar is refused, with a hint to use `--session utc`.
  - Bars outside the calendar are counted per symbol in `outside_calendar_bars` and are not dated.
- **New functions.**
  - `cme_sessions.session_trade_dates`: an off-schedule print takes the last session that opened
    before it, and is flagged.
  - `cme_sessions.coverage_span`.
  - `continuous.trade_dates`, `continuous.calendar_for` and `continuous.outside_calendar`.
- **Fix in `cme_sessions.assign_bars`.** It now loads a week of sessions on both sides of the bars.
  Before, a lone bar in a session that opened four days before its trade date (Monday's on the
  Thursday of a Friday holiday) was left off schedule.

### Fathom C3b-1: CME Globex session calendar (ADR-0091)
- **`crucible.data.cme_session_table`**: a versioned table (`cme-equity-sessions-1`, hashed) of the
  Globex sessions of ES, NQ, YM, RTY and NKD from 2010-06 to 2027-12, transcribed from CME
  documents with their URLs and SHA-256s: four regimes (15:30 open and 16:30 maintenance before
  2012-11-19; 16:15 close and the 15:15-15:30 halt to 2015-09-18; 16:00 close; halt removed from
  2021-06-28; NKD's own changes), every holiday and early close, and the special closures (Hurricane
  Sandy 2012, the 2018 and 2025 national days of mourning, U.S. roots only).
- **`crucible.data.cme_sessions`**: `SessionCalendar` (scheduled segments per trade date; refuses
  overlaps, a session after a closed weekday without an explicit open, dates outside coverage),
  `assign_bars` / `trade_date_of`, `session_rule_masks` (`flat_by_close` decided on the penultimate
  scheduled bar and filled at the final bar's open; `exit_at` and entry windows on the trade-date
  clock; missing final bars reported, not replaced; off-schedule bars not tradable) and
  `schedule_report` (observed bars vs the schedule; never changes it).
- Unsourced: most 2023 holidays, MLK 2024 and NKD on the 2023-2025 ES-only dates; those sessions
  are flagged unverified. Findings: the table agrees with every raw bar except prints in the minute
  after a close; the 2012-11..2014-02 holiday morning segments are missing from the Databento
  batch; the ADR-0087 17:00 trade-date rule is wrong before 2012-11-19 (fix pending).
- `calendars.chicago_wall_to_utc_ns` / `utc_ns_to_chicago_wall`: the wall-clock boundary converters.

### Fathom C3a: futures execution simulator in contracts and dollars (ADR-0090)
- **`crucible.execution.futures_sim.simulate_futures`**: signed whole-contract targets decided at
  each bar's close, filled at the next eligible bar's open by default (`signal_bar_close` is the
  declared, optimistic alternative); costs per contract per side (`commission` required, exchange,
  clearing and regulatory fees, `spread_ticks / 2 + slippage_ticks` times the tick value, flagged
  uncalibrated, with Chicago-time session overrides); stop/target brackets in ticks from the fill
  price, stop first when a bar touches both, a target only on a trade through and at its limit;
  re-entry `require_signal_reset` by default. Per bar: realized and unrealized P&L, costs by kind,
  balance and equity in USD as exact `Decimal(38, 6)` (integer ticks and micro-dollars inside).
- **Rolls are two causal trades**: both legs at the raw opens of the first minute at or after the
  roll decision in which both contracts traded; strict mode refuses a roll it cannot execute so;
  `reference_approximation` is labelled and makes `strict_execution` False. Each roll reports its
  approximation error in ticks and USD per contract (real data: mean $28.79 ES to $67.80 NKD).
- **`crucible.data.futures_specs`**: the versioned contract specification table for ES, NQ, YM,
  RTY, NKD (tick size, point value, tick value, source, effective dates, version and SHA-256);
  execution prices off the tick grid are refused.
- `execution_policy()` records every execution assumption. The prop-firm rule engine stays a
  separate component (milestone C7); the wiring to the strategy spec, CLI and run manifest is next.

### Fathom C2e: dataset registry derived from manifests (ADR-0089)
- **`crucible data catalog --store S`** (and the MCP tool `crucible_data_catalog`): per dataset the
  identity (schema version, content hash, rows, build time), origin and root origin (the provider,
  reached through the `from=<dataset>@<hash>` lineage), price basis, data contract and range (first
  and last `event_time`, symbols). Derived at query time, never stored. A manifest that disagrees
  with its data file (row count, name, missing file; SHA-256 with `--verify`) sets `ok: false` and
  exit code 1; a rebuilt or missing parent and a superseded continuous builder are findings.
- `ParquetDataStore.data_path(dataset)`: the data file's path, for hashing and metadata.

### Fathom C2d: minute-level integrity report (ADR-0088)
- **`crucible data integrity --store S --dataset D`** (and the MCP tool `crucible_data_integrity`):
  per symbol and per session (Globex trade date, or the UTC day) it reports the bars, the minutes
  absent inside the session's own span, the largest hole, sessions under half the median bars,
  weekend-dated sessions and zero-volume bars, plus an optional comparison of session dates with an
  `exchange_calendars` calendar (`--calendar CMES`). Rows that break the data contract (duplicates,
  nulls, non-positive prices, OHLC outside its bounds, `available_at < event_time`, negative volume)
  set `ok: false` and exit code 1; gaps are findings and never fail it. Read-only: nothing is
  repaired, filled or dropped.
- `ExchangeCalendarAdapter.session_dates(start, end)` lists session labels. Real-data results for the
  five continuous datasets: `docs/data/glbx-futures-1m.md`.

### Fathom C2c: CME trade date from the Chicago wall clock (ADR-0087)
- **Corrects ADR-0086's trade-date rule.** `date(open + 2h UTC)` sent the last 13-15 minutes of every
  Friday of 2012-12..2015-03 (the session then closed at 16:15 CT) to a Saturday: 49 stub "sessions",
  and a one-hour error in winter generally. The trade date is now the Chicago date of the open's wall
  clock + 7 h (`crucible.data.calendars.cme_trade_date_expr`, hand-computed cases across both DST
  transitions in `tests/unit/test_cme_trade_date.py`).
- **The continuous datasets are `v2`** (`{root}_1m_cont_v2`, `_cont_ratio_v2`, `_rolls_v2`;
  `continuous.DATASET_VERSION`, manifest `source` tag `continuous:v2`). The roll sequence of ES, NQ, YM
  and RTY is unchanged; a few effective roll dates move (ES 5, NQ 4, YM 4, NKD 4) and NKD's reasons go
  from 58 backstop + 8 volume to 62 + 4. `v1` is superseded; no golden fixture changed.

### Fathom C2b: continuous futures series (ADR-0086)
- **`crucible data continuous`** builds, per root, `{root}_1m_cont_v1` (the held contract's own
  bars, `price_basis=raw`), `{root}_1m_cont_ratio_v1` (ratio back-adjusted, `price_basis=adjusted`)
  and `{root}_1m_rolls_v1`, from the raw per-contract datasets. The roll is causal: previous-session
  volume of the successor vs the held contract (`--threshold`, default 1.0), plus a backstop that
  keeps the series out of a contract's final session (`--backstop-sessions`, default 1); one-way.
  New schemas `CONTINUOUS_BAR_SCHEMA` and `ROLL_SCHEMA`; `contract`-tagged bars.
- **ADR-0086** records the decision and an erratum: the evidence it was written from had the sign
  of the adjustment reversed (a difference adjustment adds the gaps; it does not give NQ negative
  prices) and the expiry proxy invented a roll on contracts still trading at the end of the data.
  The decision stands on the corrected evidence (the difference adjustment rescales early-year
  percent returns, the ratio one does not).

### Fathom C2a: Databento futures ingestion (ADR-0085)
- **`kind: databento_dbn`** for `crucible data build`: reads `ohlcv-1s|1m|1h` DBN files into one raw
  dataset per root (`{root}_1m_raw`), one symbol per individual contract with its expiry year
  (`ESH2024`). `event_time` is the bar close (Databento stamps the open); calendar spreads and
  other products are dropped and counted; `instrument_id` is resolved by date (the provider reuses
  ids); `expected_sha256` verifies the provider's checksum. Example spec
  `examples/imports/glbx_futures_1m.yaml`.
- **`databento` is an optional extra** (`uv sync --extra databento`), imported only by the importer
  (its decoder is Rust; AGENTS.md §9 keeps that out of the core).

### Fathom C1: the artifact contract (ADR-0084)
- **`artifact_id`** (`ART-<16 hex>`) beside `experiment_id` (unchanged): SHA-256 over the canonical
  manifest and a digest of `config.yaml`, `metrics.json` and every `*.parquet`. Both runners seal the
  manifest after the last result file; `RunArtifacts.artifact_id`. The identity excludes `created_at`,
  `factor_regression` and the trial-registry statistics (`trial_count`, `dsr*`, `contamination*`), so
  a run keeps its id when the family grows. `created_at` is kept by an idempotent re-run.
- **The manifest says what was run**: new keys `datasets`, `window`, `execution`, `expression`,
  `results_digest`, `artifact_id`, `created_at`. Additive: run-artifact `schema_version` stays 1.
- **`crucible artifact show|verify`** and `crucible_artifact` (MCP): a run by artifact id, compact by
  default, `--detail` for the full manifest and file inventory; `verify` recomputes the id from the
  files and refuses an edited artifact. `run` and `run-vectorized` take `--detail`.
- **Versioned documents and schemas**: the run document gains `schema_version`, `kind`, `artifact_id`;
  `crucible schema --kind run|verification|error|manifest` (generated from the models and
  `MANIFEST_FIELDS`); `crucible_schema(kind)`.
- **Structured errors**: `CrucibleError.code` (snake_case class name) and `.at(**location)`; the
  `--json` envelope is `{"error": {schema_version, code, type, message, location}}`. MCP tool errors
  for a `CrucibleError` are now that JSON document (was `Type: message`). Renaming an error class now
  changes its `code`.

### Return-sequence risk, a reality check and cost stress (ADR-0083)
- **Two kinds of statement, kept apart.** *Return-sequence risk* resamples the one history a
  backtest produced: how much the final value, the worst drawdown, the chance of finishing below
  the start or of touching a ruin level depend on the sample and its order. It is centred on the
  realized result, so a lucky or overfit run also looks safe; it is **not** evidence of an edge.
  *Edge evidence* is the nulls and the corrections for the search.
- `validation/resampling.py`: the stationary bootstrap and an automatic block length (Politis-White).
  `validation/paths.py`: bootstrap equity paths of per-bar returns or of per-trade returns, with
  terminal-value, max-drawdown, probability-of-loss, ruin and drawdown-threshold distributions and a
  P5/P25/P50/P75/P95 fan; paths are kept only on request.
- **The one-step backtest** gains `sequence_risk` and a fixed `sequence_table` (with the note that
  it is not evidence of an edge) in its document, and a fan chart in the report (additive; golden
  unchanged; one more row, `cost_stress`, in the results table, now 24 rows).
- **`crucible simulate-paths RUN`** resamples any finished run (folder or experiment id) and, with
  `--export-paths FILE`, writes every simulated path to Parquet (path, step, multiple).
- **`validation/reality_check.py` and `crucible optimize`**: White's Reality Check and Hansen's SPA
  over the sweep's return panel, printed and emitted (`reality_check`) beside PBO and the deflated
  Sharpe: does the best swept value beat zero once the search is paid for? Calibrated by simulation
  (with 20 zero-edge candidates the naive best-candidate test rejects 65% of the time, White 4.8%,
  Hansen 5.8% at a nominal 5%).
- **Cost stress**: `diagnostics.cost_stress` re-prices the run at 1x, 2x, 3x and 5x its costs (the
  engine's costs are linear in turnover, so no re-run), verified against a real re-run at doubled
  costs; the table shows the Sharpe at 2x / 3x / 5x.
- Evaluated and not built (reasons in the ADR): a default store of every path, a regime-conditioned
  bootstrap, a bootstrap test of the mean, a random-entry null, an event-driven stress grid.

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
  `crucible.data.calendars`. Bars are counted by distinct time, not by row: with several symbols
  the rule counted every symbol's row, so two symbols on daily bars were annualized with 504
  instead of 252 (Sharpe and volatility too large by sqrt(2)), in the one-step product too.
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
- **Strategy-spec stops now fill inside the bar** (ADR-0082). `risk.stop_fill: level` (the new
  default) triggers on the bar's high/low instead of only its close, fills at the stop/take level
  (or at the open when the bar gapped through it), and lets the stop win when one bar touches
  both; the vectorized engine values that bar at the fill, not at its close. **Behaviour change**
  for any spec with `stop_loss_pct`/`take_profit_pct`: exits that used to wait for a closing
  breach now happen where the market went. `stop_fill: close` reproduces the old model. The
  product golden's numbers are unchanged (its spec has no stops); its artifact hash moved because
  the canonical spec now records `stop_fill`, so spec-run experiment ids change (documented in
  `docs/COMPATIBILITY.md`). The promoted run still exits at the next open (it cannot fill inside a
  bar), and the vectorized multi-currency path refuses `stop_fill: level`.
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
