# Module: experiments

## What exists

Reproducibility: configs, the runner, artifacts and the research orchestrators. Detail sections follow.

- `futures_config.py` + `futures_run.py` + `futures_artifacts.py` — the futures run (ADR-0095).
  - **`FuturesRunConfig`** (`kind: futures_run`, `load_futures_config`, `futures_config_hash`): root,
    the four datasets, a trade-date window, the strategy (exactly one of a spec, a
    `FuturesSignalFunction` entrypoint or a DSL `strategy.expression`), contracts, capital, costs,
    execution, signal input and session policy, with `run.family` required. An expression is
    compiled at load (`FuturesStrategyConfig.compiled_signal(signal_input)`), so a type, window,
    parameter or scale error surfaces at `futures check`, which also prints the canonical text and
    the three ids; its `params` bind the `$` parameters and `contracts` sizes the side.
  - **`fidelity`** (C5a, ADR-0100; `FuturesFidelityConfig`): `resolution` (`1m` default, `5m`,
    `15m`), `cost_detail` (`full` default, `commission_only`) and the optional `preset`
    (`screen` = 15m + commission_only, `standard` = 5m + full, `full` = 1m + full;
    `FIDELITY_PRESETS`, `FIDELITY_TABLE_VERSION = "1"`). A preset that contradicts an explicit
    field is refused, and so is an explicitly non-zero `costs.spread_ticks`/`slippage_ticks` under
    `commission_only` (the run would silently drop it). `resolution` decides the bar length
    everywhere downstream (session masks, availability check, the simulator, the marks, the
    registry's `period_ns`); `cost_detail: commission_only` zeroes the tick costs and adds the
    approximation "costs reduced to commission and fees (fidelity screen): optimistic".
  - **`run_futures`** selects the window by trade date, resamples BOTH series when the resolution
    is not `1m` (`_resampled` -> `crucible.data.resample.resample_session_bars`, same buckets for
    execution and signal, so the bridge's alignment check holds), and calls `futures_targets` and
    `simulate_futures`. It builds the marks, the daily ledger, the fills, the rolls and the
    descriptive `metrics.json` (no Sharpe), and checks the ledger identities
    (`check_daily_ledger`). It then registers the trial (mandatory) and seals the run
    (`FUT-` run id, `ART-` artifact id). `futures_run_id(config, store_root=)` gives the id a
    config WOULD get without simulating (the batch uses it to reuse a sealed run).
  - **signal warm-up** (C5b, ADR-0101; `window.warmup_trade_dates`, integer, default 0): the run
    reads the N Globex trade dates WITH ON-SCHEDULE BARS immediately before `window.start` and
    computes targets (`futures_targets`: session masks, availability check, DSL evaluation) on the
    extended series, then DROPS the warm-up rows before the simulator (`_prepare` -> `_subset`). No
    fill, mark, ledger row, position or roll can come from the warm-up, and the rolls stay filtered
    by the window; resampling applies to the extended series with the same buckets. A request the
    dataset cannot honour (fewer prior trade dates than N) is refused (`DataQualityError`), and so
    is a warm-up that does not cover an expression's own requirement
    (`CompiledSignal.warmup_bars + 1` bars up to and including the first window bar,
    `ConfigurationError`); a spec or a `FuturesSignalFunction` declares no warm-up, so for them only
    the explicit N applies and no bar count is checked. The check applies to a run that ASKED for a
    warm-up (`N > 0`): with `0` the expression's first bars are decided flat for lack of history,
    which is the ADR-0095 behaviour a refusal would silently change. The field joins the config
    hash, so it
    renames every futures run id; with `0` the extended and window series are the same frame, so the
    run is exactly the ADR-0095 one. The manifest records it in its `warmup` block:
    `{trade_dates, first_trade_date, last_trade_date, bars, signal_bars_required}`.
  - **`canonical_futures_yaml(config)`** is the sealed `config.yaml`, and it RELOADS: for a
    `fidelity.cost_detail: commission_only` run it omits a `costs.spread_ticks`/
    `costs.slippage_ticks` the caller did not set, because writing the defaults explicitly is
    exactly what the validator refuses (the run would silently ignore them) and every reader
    of a finished run parses the file back (a comparison member's key, the effective-trials
    report). The config hash and the run id hash the MODEL, so they are untouched; only the
    bytes of a `commission_only` run's file change (`docs/COMPATIBILITY.md` §3).
  - **Interfaces:** `crucible futures run|check|batch|walkforward|compare|trials` and MCP
    `crucible_futures_run|check|batch|walkforward|compare|trials`.
    The schemas are in `docs/SCHEMAS.md`, and the marking policy is in the manifest.
- `futures_stats.py` — the futures statistics (C6a, ADR-0103): the ONE returns function and the
  inferential report every futures path (standalone, batch, walk-forward, comparison) reads.
  - **`daily_returns(daily, *, initial_capital, calendar, window) -> ReturnsSeries`**: the daily
    marked P&L over the FIXED initial capital, `(closing_equity_t - closing_equity_{t-1}) /
    initial_capital` (previous trade date's closing equity, capital on the first one). The
    differences are exact `Decimal`; only the division is float64. A trade date with on-schedule
    bars and no position (`max_contracts == 0`) is a real zero-return observation; a trade date of
    the session calendar with no row is `missing_sessions` — excluded and counted, NEVER zero-filled.
    `daily_returns_from_oos(oos_daily, ...)` is the same function over a walk-forward's
    `closing_equity_usd` chain (terminal exits included); the chain has no position column, so a
    day on which no candidate was selected (a flat fold) is its zero-position day.
  - **`futures_statistics(returns, *, owner_id, total_trials, trial_sharpes, config, ic=None)`**
    -> `{"metrics": ..., "block": ...}`: per-period Sharpe (`core.stats.per_period_sharpe`), the
    annualized Sharpe (`x sqrt(252)`, PRESENTATION only), the mean daily return, PSR against a
    benchmark of 0 (`validation.dsr.probabilistic_sharpe_ratio`, skew/kurtosis corrected) and DSR
    (`deflated_sharpe_ratio`, deflated by `total_trials` over the family's distinct candidate
    Sharpes). PSR/DSR carry no interval (closed-form probabilities) and say how they were made;
    the Sharpe, the annualized Sharpe, the mean return and the mean IC carry a percentile interval.
    A statistic that cannot be computed is `null` WITH a reason: fewer than 3 observations, a
    series with no dispersion, or fewer than 2 candidate Sharpes (DSR is never computed from an
    invented variance).
  - **`bootstrap_seed(owner_id, statistic_name)`** = `int(sha256(f"{owner}:{name}")
    .hexdigest()[:16], 16)`: each statistic's interval is a seeded CIRCULAR block bootstrap
    (`block_length = ceil(sqrt(n))`, `numpy.random.PCG64`, `resamples` and `confidence` from the
    config). The seed is a pure function of the artifact's id and the statistic's name, so the
    numbers do not depend on the order or the parallelism the artifacts were computed in (a test
    proves it with a thread pool).
  - **`information_coefficient(outputs, signal_bars, *, horizon_bars, calendar, bar_seconds)`**:
    the time-series IC — per trade date, Spearman (average ties) between the expression's score at
    each decision bar and the close-to-close return over `horizon_bars` bars of the SIGNAL series.
    A pair crossing a session edge or a contract change is dropped, never filled; a trade date with
    fewer than `MIN_IC_PAIRS` (10) valid pairs gives no IC. Returns the mean, the per-date values,
    `by_month` and the pair count, or a null with a reason. Only a DSL expression has one: a spec or
    a Python `FuturesSignalFunction` decides a position, not a score, and records null with a reason.
  - **`StatisticsConfig`** = `FuturesRunConfig.statistics` (`ic_horizon_bars` default 1, `>= 1`;
    `resamples` default 1000, `>= 200`; `confidence` default 0.95, `0.5..0.999`, all
    `extra="forbid"`). It joins the config hash, so adding the section renamed every futures run
    id (results unchanged, `docs/COMPATIBILITY.md` §3).
- `futures_trials.py` — effective trials, the supplementary DSR and PBO panels (C6b, ADR-0104).
  - **`futures_effective_trials(family, *, artifacts_root, rho_threshold=0.5,
    min_overlap_trade_dates=20, owner=None) -> FuturesTrialsReport`**: the family's effective number
    of trials. Each distinct candidate is represented by its representative run
    (`DuckDBTrialRegistry.candidate_trials`: most `n_obs`, tie to the earliest `seq`) and its daily
    series; every pair is correlated with the C5c rules (`futures_compare.daily_correlation`, and
    `comparison_key`/`key_diff` — an inner join on trade dates, nothing filled, at least
    `min_overlap_trade_dates` shared dates, never below `MIN_OVERLAP_FLOOR` = 10, never for a
    constant series). The correlation runs on daily P&L and Pearson of the daily returns equals
    Pearson of the daily P&L (a return is `P&L / initial_capital` and a family shares one capital),
    so the C5c series is reused rather than re-derived. `owner` is the run being written at that
    moment: it has no seal yet, so it hands its in-memory series and its config-derived comparison
    key (`futures_compare.config_comparison_key`) in instead. ONE pair without a valid correlation
    makes the estimate `unavailable` with the reasons (a missing or unverified artifact, a
    non-futures run id, too little overlap, incompatible keys, a constant series) — never 0, never
    1. Label: `assessment: "estimator"`, note "threshold-dependent; not a count of independent
    hypotheses", plus the method (linkage, distance, threshold rule, tie rule, overlap and key
    rules) and the candidate ids.
  - **`run_futures_trials(family, ...)`** writes `<artifacts>/EFT-<16 hex>/trials.json` (sorted
    keys, `schema_version` 1, `kind: futures_trials`): the family's counts, each candidate (id,
    representative `run_id`, `n_obs`, `sharpe_per_period`), every pair with its status, overlap and
    `rho`, the `estimator` block, the `sensitivity` table and the null verdict. The id hashes the
    family, the sorted (candidate id, run id) pairs and the options, so another threshold is another
    report. `futures_trials_json_schema()` is the output kind `futures-trials`.
  - **`supplementary_dsr(returns, *, report)` / `supplementary_block(...)`**: the
    `dsr_effective_trials` entry that sits under a `supplementary` key beside the PRIMARY `dsr`,
    which is unchanged: `deflated_sharpe_ratio_over_effective_trials` on the same series with the
    same candidate-Sharpe dispersion and `N` = the effective count. Null with a reason when the
    estimate is unavailable, when the family has fewer than 2 candidate Sharpes or when the series
    cannot be scored; it records the threshold, the effective count and the candidate ids, carries
    no interval, and feeds no verdict. It is written by `run_futures` (into the manifest's
    `statistics.supplementary` and `metrics.json`), by `run_futures_batch` (per candidate, computed
    at the batch's write time) and by `run_futures_walkforward` (into `oos.statistics.supplementary`,
    computed on the OOS chain).
  - **`pbo_on_panel(panel, *, n_groups=8) -> PboOutcome`**: the probability of backtest overfitting
    of a candidate panel, through `probability_of_backtest_overfitting` with
    `CombinatorialPurgedCVSplitter(n_groups, n_test_groups=n_groups // 2, embargo=0)`. The panel must
    hold at least two DISTINCT candidates over an IDENTICAL set of trade dates; unequal dates,
    fewer than two candidates or fewer observations than groups make it unavailable with the reason
    (and the dates that differ), never a number. `n_groups` must be even and at least 4.
    A walk-forward's panel runs are `run_futures(..., mode=PBO_PANEL_MODE)`
    (`"pbo_panel"`, `crucible.validation.trial_registry`): they stay auditable in `trials` and
    move no count at all — `submission_count`, `unique_candidate_count` and `total_trials` are
    exactly what the same walk-forward reports without the option — because nothing submitted
    or selected them.
- `futures_document.py` — the futures-run document (ADR-0097): `futures_document(run_dir)` builds
  one versioned document (`FUTURES_DOCUMENT_SCHEMA_VERSION`) from the sealed run directory alone
  (manifest + metrics, after `verify_artifact`), so `futures run --json`, `futures run`'s human
  output, `artifact show` and the MCP tools all emit the same document. It carries the identity,
  the window, the datasets, the approximations, a **null verdict with a reason**
  (`VERDICT_REASON_CODES`, today only `robustness_not_assessed`, plus the `backtest`
  `VERDICT_VOCABULARY`), and
  every metric as `{value, ci_low, ci_high, assessment, unit}` where `assessment` is a closed set
  (`METRIC_ASSESSMENTS`: `descriptive`, `inferential`, `statistical`) — a descriptive metric must
  have null intervals and an inferential one may carry them, and an inferential metric with a null
  value must state a `reason` — plus (C6a) a `statistics` block: the returns convention, the
  annualization, the bootstrap recipe (rng, seed, block policy and length, resamples, confidence),
  the family's `trials` counts, the `candidate_id`, `missing_sessions`, `zero_position_days` and
  the IC record (`horizon_bars`, `days`, `pairs`, `by_month`, `reason`). A manifest written before
  C6a has no block and the document reports `statistics: null`. It refuses (a) a directory that is
  not a futures run, (b) one whose seal does not verify, (c) a descriptive metric that claims an
  interval, (d) a metric with half an interval and (e) a null inferential metric with no reason.
  Its JSON Schema is the output kind `futures-run-document`; `verdict_document` and `metric_document` hold the invariants.
  Since C5a (ADR-0100) the document also carries `fidelity` `{resolution, cost_detail, preset,
  table_version, resampled, dropped_off_schedule, partial_buckets}`; adding the key is additive, so
  `FUTURES_DOCUMENT_SCHEMA_VERSION` stays 1, and a manifest written before C5a (no `fidelity` key)
  reads as `1m` + `full` (`DEFAULT_FIDELITY`).
- `futures_batch.py` — batch evaluation of N DSL expressions on ONE base config (C5a, ADR-0100):
  `load_futures_batch(path)` (`FuturesBatchFile` = the file's contract and its JSON Schema,
  `futures_batch_json_schema`), `batch_id(base, candidates)` (`BAT-` + the hash of the base config
  and the ORDERED candidates), `candidate_config(base, candidate)` (only `strategy` and `run.name`
  change; the dump is `exclude_unset` so a base default is not turned into an explicit setting) and
  `run_futures_batch(batch, *, store_root, artifacts_root, overwrite=False)` -> `BatchResult`
  (`batch_dir`, `batch_id`, `document`). A candidate is a `BatchCandidate` (`position`, `name`,
  `expression`, `params`, and nothing else: any other key is refused). Deduplication is by
  `crucible.dsl.identity.parameterization_id` after canonicalization and binding: a repeat computes
  ONE run, and the later candidates are `cached` with the first one's run and artifact ids; a run
  directory that already exists and verifies is `cached` too.
  The output is `<artifacts>/<BAT-ID>/batch.json` (`schema_version` 1): the batch identity, the
  family, the base config hash, the `fidelity` block, one row per candidate in SUBMISSION order
  (never sorted by a metric) with its status and the five descriptive metrics
  (`CANDIDATE_METRICS`: `net_pnl_usd`, `total_costs_usd`, `fills`, `max_intraday_drawdown_usd`,
  `min_equity_usd`, each `{value, ci_low: null, ci_high: null, assessment: "descriptive", unit}`),
  `submitted`, `distinct_runs`, the family's `trials` counts and the null verdict
  (`robustness_not_assessed`). Since C6a each candidate row also carries its `candidate_id` and a
  `statistics` block copied from its run's sealed `metrics.json` (a `cached` candidate reports the
  numbers of the run it reuses), so the batch document ranks nothing but states every candidate's
  Sharpe, PSR, DSR and IC with their intervals and reasons. Every submitted candidate is recorded
  in the registry's `submissions` table (with its `candidate_id`), and each computed run registers
  its trial as any futures run does.
  The keys of `batch.json` are in `docs/SCHEMAS.md`; the CLI and MCP surfaces are
  `crucible futures batch` and `crucible_futures_batch`.
- `futures_walkforward.py` — walk-forward evaluation of N DSL expressions on ONE base config (C5b,
  ADR-0101): `load_futures_walkforward(path)` (`FuturesWalkForwardFile` = the file's contract and
  its JSON Schema, `futures_walkforward_json_schema`, `crucible schema --kind
  futures-walkforward`), `walkforward_id(base, file)` (`WFA-` + the hash of the file, base path
  excluded, and the base config), `walkforward_trade_dates(config, store_root=)` (the base window's
  Globex trade dates with on-schedule bars), `walkforward_folds(trade_dates, *, train_trade_dates,
  test_trade_dates, scheme)` -> `(folds, unused_trade_dates)` and
  `run_futures_walkforward(walkforward, *, store_root, artifacts_root, overwrite=False)` ->
  `WalkForwardResult` (`walkforward_dir`, `wf_id`, `document`).
  - **Folds** (decision 2): fold k tests on trade dates `[N + k*M, N + (k+1)*M)` and trains on the N
    before it (`rolling`) or on every date from the first one (`anchored`); test windows are
    contiguous and never overlap, a trailing remainder shorter than M is reported as
    `unused_trade_dates`, and fewer than one complete fold is refused.
  - **Per fold**: every candidate runs on the training window with the base config, changing only
    `strategy`, `run.name` (`<base>/wf/<fold>/train/<name>`) and the window plus its warm-up; a
    candidate is eligible when its training run satisfies every constraint (required
    `max_intraday_drawdown_usd`, optional `min_equity_usd`, `max_fills`, `max_time_in_market`), each
    check recorded as `{constraint, limit, value, ok}`; the selected candidate is the eligible one
    with the largest training `net_pnl_usd`, a tie going to the earliest submission position; with
    no eligible candidate the fold is FLAT (`status: no_eligible_candidate`, zero P&L and costs, no
    run). The selected candidate then runs on the test window (`<base>/wf/<fold>/test/<name>`).
  - **Terminal exit** (decision 4, `terminal_exit_cost`): the contracts open at the test window's
    last bar times ONE side of the full per-contract cost from the run's effective
    `CostSchedule` (fees + half the spread + slippage ticks x tick value; a `commission_only` run
    charges the fees only), in exact micro-dollars, so every fold starts and ends flat at a known,
    pessimistic price.
  - **`oos_daily.parquet`** is the CONCATENATED chain: each fold's `closing_equity_usd` is its run's
    own daily equity shifted to `base capital + previous folds' net P&L`, the terminal exit is
    booked as a cost on the fold's last trade date, and a flat fold has one zero row per test trade
    date. `walkforward.json` (`schema_version` 1) carries the folds, the `oos` summary computed from
    that frame alone (net, costs, fills, trade dates, max drawdown on the chain, folds with a
    selection), `window_stability` (each fold's OOS net P&L plus counts of positive/negative/flat
    folds), `in_sample_audit` (every training run, marked `in_sample: true`) and the null verdict.
  - **Trials**: every training and test run is a sealed futures run that registers its trial, and
    each fold's candidates are `submissions` with `batch_id = wf_id` and position
    `fold * K + candidate`, so re-running is idempotent (every run `cached`, no duplicate
    submission). Each submission and each trial row carries the candidate's `CND-` id, so a
    candidate trained in several folds counts ONCE while every fold's row stays (ADR-0103).
  - **Statistics (C6a, ADR-0103)**: `oos.statistics` is the C6a report computed on the
    CONCATENATED OOS chain alone (`daily_returns_from_oos`, `owner_id = wf_id`) and deflated by the
    FAMILY's `total_trials`; its IC is null with a reason (a concatenation of folds has no single
    signal to rank). Each training run's own statistics are repeated under `in_sample_audit` with
    `in_sample: true`, and the document's `trials` block carries the family's counts. The verdict
    stays null with `robustness_not_assessed`: robustness is C7.
  - **Interfaces:** `crucible futures walkforward` and MCP `crucible_futures_walkforward`; the keys
    and columns are in `docs/SCHEMAS.md`.
- `futures_compare.py` — cross-run metrics and a DESCRIPTIVE daily P&L correlation against
  the artifact pool (C5c, ADR-0102). It reads sealed artifacts and never simulates, so it
  cannot change a result; the only file it writes is `<artifacts>/<CMP-ID>/cross_run.json`,
  outside every sealed run directory.
  - **`load_member(artifacts_root, member_id)` -> `Member`** reads a `FUT-` run (daily P&L =
    `closing_equity_usd - opening_equity_usd` per trade date from `daily.parquet`, plus its
    marks for the episodes, the turnover, the days in market and the conservative intraday
    drawdown, and its fills) or a `WFA-` walk-forward (`oos_daily.parquet`'s `net_pnl_usd` per
    trade date, its per-fold OOS net P&L, and its test runs' marks and fills for the
    aggregates: a flat fold contributes nothing). Every seal involved is verified first; a
    member that does not verify comes back with status `unverified` and the reason in its
    `detail` — listed, never skipped, never read as if it were sound.
  - **`comparison_key(member)`** (decision 4) is the simulator version, `fidelity`
    (`resolution`, `cost_detail`, `table_version`; a pre-C5a manifest reads `1m`/`full`/`"1"`),
    the execution section (fill, roll execution, strictness, the bracket policy and
    `reentry`), the session section (flatten rules, entry window, unverified-session policy)
    and the signal input. Root, contracts, cost amounts, strategy, window, family and capital
    are NOT in it. It is read from the run's sealed `config.yaml` and `manifest.json`; a
    walk-forward's key is its BASE config's key, taken from a fold's own run (a fold changes
    only the strategy, the name and the window) plus the `fidelity` block `walkforward.json`
    records. `key_diff(a, b)` lists the differing dotted paths (`fidelity.resolution`,
    `execution.brackets.stop_ticks`, ...).
  - **`member_metrics(member)`** (decision 3) reports, from exact `Decimal` money rounded only
    when it is reported, in the
    `{value, ci_low: null, ci_high: null, assessment: "descriptive", unit}` shape:
    `marked_pnl_usd` (the sum of the daily MARKED P&L, so an open position's mark is included:
    final closing equity minus capital), `realized_pnl_usd` (the run's OWN `metrics.json`
    `net_pnl_usd`, final BALANCE minus capital; null for a walk-forward, which has no balance of
    its own), `total_costs_usd`, `max_drawdown_usd` (peak-to-trough on the daily CLOSING equity,
    the opening equity as the first peak), `max_intraday_drawdown_usd` (the OHLC rule of
    `build_metrics`; for a walk-forward the worst of its test runs), `trades`, `fills`,
    `turnover_contracts`, `trade_dates`, `days_in_market`. The marked total is deliberately NOT
    called `net_pnl_usd`: that key already means the realized number in a run's own
    `metrics.json`, and a document never repurposes a key (`docs/COMPATIBILITY.md` §3).
    **Trades** are position episodes: a
    maximal run of bars with the same non-zero SIGN, a still-open episode counting, and a
    long-to-short flip counting as one episode ending plus one starting. **Turnover** is the
    sum of `|Δposition|` in contracts, in total and per trade date (the run starting flat); a
    roll keeps the net position, so it adds none. **`days_in_market`** counts the trade dates
    with a non-zero position on at least one bar. `window_stability(member)` gives each
    calendar month's net P&L (by trade date) and the counts of positive/negative/flat months,
    and a walk-forward's `fold_oos_net_pnl_usd` — counts and lists, never a dispersion
    statistic. Every value there is MARKED (final equity minus capital over the period), nested
    under its own keys, so nothing reads as the run's realized `net_pnl_usd`.
  - **`daily_correlation(a, b, *, min_overlap)`** -> `CorrelationResult(status, value,
    overlap_trade_dates, first, last)` is Pearson's coefficient over the INNER JOIN of the two
    series' trade dates: nothing is filled, so a date missing from either side is excluded
    and never treated as a zero P&L. Fewer than `min_overlap` overlapping dates is
    `insufficient_overlap` with no value; a series constant over the overlap is
    `constant_series` with no value; otherwise `ok` with the value, computed in float64 from
    the exact Decimals and clamped to [-1, 1] only for rounding (an out-of-range value raises
    `InvariantViolation` instead of being clamped).
  - **`compare_futures(target_id, *, artifacts_root, min_overlap_trade_dates=20)`** ->
    `CompareResult(compare_dir, cmp_id, document)` builds the pool (every `FUT-`/`WFA-`
    directory except the target, minus a walk-forward target's own training and test runs
    read from `walkforward.json`), gives each pair a status (`ok`, `incompatible` with its
    `differing_keys`, `insufficient_overlap`, `constant_series`, `unverified`) and writes
    `cross_run.json` (`COMPARE_SCHEMA_VERSION` 1, sorted keys): the target with its metrics,
    its window stability and its comparison key, the `options`, the pool SORTED BY ID with
    each member's status, differing keys, overlap, correlation and metrics, a `summary`
    (members, `by_status`, the largest absolute correlation with its member id) and the null
    verdict (`robustness_not_assessed`). `cmp_id` is `CMP-` + the hash of the target, the sorted
    VERIFIED pool ids and the overlap option, so a corrupted member does not change it and a
    re-run is byte-identical. `min_overlap_trade_dates` below 10 is refused
    (`ConfigurationError`, `MIN_OVERLAP_FLOOR`), and so is an unverified target. Listing the
    artifacts root counts only `FUT-`/`WFA-` directories as members, so a `BAT-` or `CMP-`
    document is never mistaken for a run.
  - **Statistics (C6a, ADR-0103)**: `member_metrics` also repeats each member's OWN recorded
    statistics — `sharpe_per_period`, `sharpe_annualized`, `psr`, `dsr` — read from its
    `metrics.json` (or a walk-forward's `oos.statistics`), never recomputed: a comparison reads
    artifacts. A member written before C6a reports them as nulls with a reason. The correlation
    itself stays descriptive with null intervals, and the verdict is `robustness_not_assessed`
    (C5c added inference to nothing, and C7 owns the verdict).
  - **Interfaces:** `crucible futures compare` and MCP `crucible_futures_compare`;
    `crucible schema --kind futures-compare` prints `cross_run.json`'s JSON Schema; the keys
    are in `docs/SCHEMAS.md`.
- `futures_prop.py` — the **prop evaluation** (C7b, ADR-0107 sections 4-6 and 10-12):
  `run_prop_evaluation(config, *, ruleset_path, horizon_trading_days, execution_mode, ...)` ->
  `PropEvaluationResult(evaluation_dir, evaluation_id, artifact_id, summary)`. It prepares the run
  ONCE (`import_prepared_run`, so the signal is the run's own causal one and no second pipeline
  exists), starts an attempt on every Globex trade date of the window with an on-schedule bar,
  converts H trading days into a calendar-day window per start with the CME session calendar,
  refuses an H shorter than any phase's own limit (a `time_limit` rule included, a calendar-day
  limit converted per start), and runs `crucible.prop.attempt.simulate_attempt` for every
  (scenario, start) with the rule's news events and its coverage, the `ComponentFeeSource` the
  commission's excluded components need, the run's `participant_profile` and the
  `cost_assumption` FILE. It then classifies every attempt
  (`classify_attempt`: `pass | fail | timeout | horizon | censored`, evaluation phases only) and
  writes the statistics (section "Prop evaluation" below), the labels and the sealed artifact
  `PRP-<16 hex>/` (`attempts.parquet`, `summary.json`, `ruleset.yaml`, `manifest.json`).
  `PROP_ATTEMPTS_SCHEMA` is the attempt frame's contract, `prop_evaluation_json_schema()` is
  `summary.json`'s JSON Schema and `attempts_frame`/`covered_intervals`/`evaluation_basis` are the
  pieces a test hand-checks. Nothing here records a trial.
- `futures_signals.py` — the futures signal bridge (ADR-0094, ADR-0098): `futures_targets` turns a
  `StrategySpec`, a `FuturesSignalFunction` or a compiled DSL `CompiledSignal` into the targets and
  the `on_schedule` column of `execution.futures_sim.simulate_futures`. Signal on the
  ratio-adjusted series by default (`signal_input`), fills on the unadjusted one. It enforces:
  - the price basis of both `DatasetRef`s and exact row alignment (`event_time`, `contract`);
  - scale invariance on ratio-adjusted input: statically for a spec, by typing for an expression
    (a score must have price degree 0) and by declaration (`scale_invariant`) for a function;
    empirically for all three, with prices x16 and x1/16 (an expression records
    `strategy_kind: dsl`, its `describe()` document and `scale_invariance.static: typed`);
  - refusal of the spec's percentage stops, `max_holding_bars`, explicit sizing, `time` and
    `session`;
  - CME session rules (`FuturesSessionPolicy`): a missing final bar and unverified sessions are
    refused.

  It returns a provenance record. The run that uses it is C3b-3.
- `config.py` — the frozen pydantic `ExperimentConfig` tree, `load_config`, `config_hash`,
  `canonical_yaml` (fields in `docs/SCHEMAS.md`).
- `runner.py` — `run_experiment`, `run_experiment_parallel`, `run_with_scenarios`, `rebuild_report`,
  `assemble_engine`, `experiment_id`, `RunArtifacts`.
- `artifacts.py` — the artifact schemas (`LEDGER_SCHEMA`, `ORDER_SCHEMA`, `FILL_SCHEMA`,
  `EQUITY_SCHEMA`), `MANIFEST_FIELDS`, `SCHEMA_VERSION`, and the reader `load_experiment` /
  `compare_metrics` (`docs/USAGE.md`).
- `artifact_id.py` — the artifact identity (ADR-0084): `canonical_json`, `manifest_basis`,
  `results_digest`, `compute_artifact_id`, `seal_artifact`, `verify_artifact`, `find_artifact`,
  `read_seal`, `write_manifest`. The digest covers `config.yaml`, `metrics.json`, `summary.json`
  and `ruleset.yaml` plus every `*.parquet`, so a prop evaluation's JSON/YAML results are sealed
  like a run's (only an artifact that writes one of those names is affected); `provenance.py` — the manifest blocks that say what was run
  (`datasets_block`, `window_block`, `execution_block`, `expression_block`); `contracts.py` — the
  versioned output documents and their JSON Schemas (`run_document`, `RunDocument`,
  `VerificationDocument`, `ErrorDocument`, `manifest_json_schema`, `OUTPUT_SCHEMA_VERSION`).
- `vectorized_runner.py` — `run_vectorized_experiment`, `run_vectorized_experiment_parallel`; `promotion.py` — `promote_config`,
  `PromotedSignalStrategy`.
- `optimize.py` (`optimize_1d`), `sensitivity.py` (`sweep_1d`), `perturbation.py`
  (`perturb_execution`, `perturb_strategy_param`), `null_tests.py` (`null_test_shuffle`,
  `null_test_sign_flip`, `null_test_synthetic_gbm`), `validate.py` (`validate_run`,
  `load_factors_csv`).
- `interfaces.py` — the Protocols `ArtifactStore` and `RunRegistry`, both stubs (see Known gaps).

## Responsibility
Reproducibility: frozen hashed configs, the runner, the filesystem artifact
store. An experiment = config hash + code commit (+ dirty) + data manifest
hashes + seed + env lock hash + realism level + trial family. Identical
inputs ⇒ identical experiment id ⇒ byte-identical artifacts (golden-tested).

**Artifact identity (ADR-0084).** The experiment id names the directory and covers config + data.
`artifact_id` (`ART-<16 hex>`) covers the manifest and the result files: SHA-256 over the canonical
manifest (minus `artifact_id`, `created_at`, `factor_regression` and the trial-registry statistics
`trial_count`, `dsr*`, `contamination*`) and a digest of `config.yaml`, `metrics.json` and every
`*.parquet`. Both runners seal the manifest after the last result file is written; `created_at` is
outside the hash and a re-run that reproduces the id keeps it. `verify_artifact` recomputes the id
from the files and refuses an edited artifact; `find_artifact(root, id)` returns the directory.
The manifest also records `datasets`, `window`, `execution` and `expression` (what was run); the
dataset range and provider registry, the fill-policy name and the DSL expression kind come with
milestones C2-C4.

## Implementations
- `config.py`: frozen Pydantic tree (`ExperimentConfig` = experiment header
  + data + strategy + execution + cash/window), all `extra="forbid"`;
  `load_config` (YAML), `config_hash` (canonical JSON SHA-256),
  `canonical_yaml` (deterministic artifact rendering). Dates are ISO
  strings; datetimes must carry a timezone. `DataConfig.futures_margins`
  (per-symbol `initial`/`maintenance` futures margin; each symbol needs a
  `futures_multipliers` entry; wired into `FuturesSpec`, ADR-0050).
  `DataConfig.symbol_currency`
  (per-symbol trading currency; unlisted symbols default to
  `base_currency`) and `fx_rates` (FX rate dataset id),
  ADR-0025 — both wired through `assemble_engine` into
  `BacktestEngine`'s `symbol_currency`/`fx_dataset`, and `fx_rates`'
  manifest hash joins `corporate_actions`/`universe` in `data_hashes`.
- `runner.py` checkpointing (ADR-0058): `checkpoint_experiment(config, path, *, stop_at,
  runtime, resume_from)` runs to the session boundary at or before `stop_at`, writes the
  checkpoint and returns `CheckpointWritten(path, boundary_ts)` (no experiment directory, report
  or trial); `run_experiment(..., resume_from=, checkpoint_path=, checkpoint_every_ns=)` resumes
  a saved run through the normal pipeline and/or atomically rewrites a checkpoint every interval
  of simulated time (`start + k * interval`, at most `MAX_CHECKPOINTS`); both share
  `_prepare_run` (quality gate, engine build, resume), which creates no directory, so any
  refusal leaves nothing behind. `config.parse_interval("4h")` parses the cadence.
- `runner.py`: `run_experiment(..., runtime="backtest"|"paper"|"live")` (ADR-0051):
  `_check_runtime` refuses a runtime that disagrees with `live.enabled`, `_build_engine`
  builds the engine for the runtime, paper/live never record a trial, and
  `manifest.json` gains `runtime`. Quality gate (refuses; skips need a
  logged reason recorded in the manifest) → engine → trades/metrics →
  artifacts: `config.yaml, manifest.json, ledger/orders/fills/trades/equity
  .parquet, metrics.json, equity.svg, report.html, logs/run.jsonl`.
  `experiment_id` = `EXP-` + hash of (config hash, data hashes).
- `walk_forward.py` (ADR-0081): `walk_forward(config, artifacts_root, *, param_name, values,
  train, test, step, metric, holdout, max_runs)` builds rolling folds with
  `validation.splits.WalkForwardSplitter` semantics (`fold_windows` is the pure, tested
  arithmetic), selects each fold's value on train with the ordinary `run_experiment`, evaluates
  it on test with `record_trial=False`, and writes `<artifacts>/walk_forward.json`. First
  increment: no concatenated out-of-fold series/DSR yet, and the per-fold selection is not
  deflated (both stated in the summary).
- `runner.py` annualization (2026-10 audit, M5): when the config leaves `periods_per_year`
  unset (`model_fields_set`), `_prepare_run` derives it from the bars' spacing and the
  calendar -- 252 sessions a year times the median bars per session, 365 for `24/7`
  (`crucible.data.calendars.periods_per_year_for`, the same rule the one-step product uses).
  An explicit value always wins. Before this, an intraday config that left the daily default
  annualized per-bar Sharpe by `1/sqrt(bars per session)` too little (hourly on XNYS: 0.81
  instead of 2.13 for the same series); the derivation costs one `event_time` column scan and
  only runs when the field is untouched. The vectorized runner applies the same rule.
- `runner.py` result identity (ADR-0079): the manifest records
  `crucible_version`, `commit`, `dirty` and `code_fingerprint` (HEAD +
  `git status` + the working-tree diff), all resolved from the checkout that
  contains the loaded package rather than the process cwd (a run from another
  directory used to record `commit="unknown"`). Before the trial registry and
  before any file, `_refuse_overwrite` compares the existing manifest's code
  identity with the current run's: the same fingerprint is an idempotent
  re-run, a different one raises `ExperimentError` unless `overwrite=True`
  (`crucible run --overwrite`), so a run of different code cannot silently
  replace the earlier numbers.
  Git commit/dirty captured via subprocess (unknown ⇒ treated dirty);
  env hash = SHA-256 of `uv.lock`. `trial_count` in the manifest/report
  header comes from `validation.trial_registry.DuckDBTrialRegistry`
  (`<artifacts_root>/trial_registry.duckdb`, ADR-0008/ADR-0014) — recorded
  once per distinct `experiment_id` per family, keyword-only
  `record_trial=False` reports without incrementing. `dsr`/
  `dsr_benchmark_sharpe`/`dsr_error` in the manifest and the report's
  statistical-validity block come from `validation.dsr.deflated_sharpe_ratio`
  (ADR-0015); `pbo` is always `null` — a single run has no multi-trial
  panel to compute it from. `monte_carlo` in the manifest/report comes
  from three `validation.monte_carlo.ResamplingTest`s
  (`N_MONTE_CARLO_ITERATIONS = 1,000` each), run on the same seeded `rng`
  `compute_metrics` already advanced (ADR-0017). `contamination`/
  `contamination_reason`/`contamination_overlapping_trials` in the
  manifest and the report header's `contamination_flags` cell come from
  `validation.contamination.check_contamination` (ADR-0021) — the trial
  registry call above also now passes `mode`/`start_ns`/`end_ns` so this
  check has what it needs. Also:
  `build_execution_setup` (config → models via the level-gated registry,
  one shared `MarketStats`), `assemble_engine` (shared by run and debug so
  replay = original run; optional `feed_factory` and
  `execution_backend_factory`), `ExperimentConfig.live`
  (`LiveConfig`: `enabled`, `venue: simulated`; default `None`, off; ADR-0043), and `run_with_scenarios` (R3.10: base + each
  scenario as separate experiments, only the base counted as a trial;
  `scenario_decay.json`/`.html` written into the base run's artifacts).
- `sensitivity.py`: `sweep_1d(config, param_name, values, artifacts_root)`
  — runs `run_experiment` once per swept value (every point recorded as a
  trial, per ADR-0016 — unlike scenario fan-out), reads a metric from
  each, and hands the series to `validation.sensitivity` for the
  plateau/spike diagnostic. Also exposes `_cast_like`/`_derived_param_config`,
  shared with `perturbation.py`.
- `perturbation.py`: `perturb_execution(config, field_name, low, high,
  n_iterations, ...)` and `perturb_strategy_param(...)` — Monte Carlo by
  re-simulation rather than resampling
  (`validation.monte_carlo`, ADR-0017). `perturb_execution` runs the base
  config once (counted as the one real trial) then perturbs a scalar
  execution field (`slippage_bps`-style only — model-slot fields are a
  known gap) without counting the perturbed runs as trials, mirroring
  scenario fan-out (ADR-0014). `perturb_strategy_param` counts every
  perturbed draw as a trial, mirroring sensitivity sweeps (ADR-0016). Both
  decisions contrasted and justified in ADR-0018.
- `null_tests.py`: `null_test_shuffle`/`null_test_sign_flip`/
  `null_test_synthetic_gbm(config, ...)` — the null tests.
  Reads the real bars via `ParquetDataStore`, transforms them with
  `data.transforms.{shuffle_bar_returns,sign_flip_returns,
  synthetic_gbm_like}`, writes each transformed variant into its own fresh
  temp store under `<artifacts_root>/_null_test_stores/<variant_id>`
  (`_run_on_transformed_bars`, copying the real corporate-actions/universe
  datasets across unchanged so the derived config is self-contained), and
  re-runs `run_experiment` with `record_trial=False` against it — the real
  `config.data.store` is only ever read, never written. None of the null
  runs count as trials (they never touch real market data, so they aren't
  a parameter evaluation in ADR-0008's sense); the one real run is subject
  to ordinary trial counting. Shuffle/GBM run `n_iterations` times with an
  explicit `rng` and compare a distribution; sign-flip is deterministic
  and runs exactly once. All three return
  `(validation.null_tests.NullTestResult, real_run, null_run(s))`. Design
  rationale (decompose/reconstruct bar transform, temp-store isolation,
  trial-counting, deferred time-shift scope) pinned in ADR-0019.
- `optimize.py`: `optimize_1d(config, param_name, values, artifacts_root,
  ...) -> (OptimizeResult, list[RunArtifacts])` — the `crucible optimize`
  CLI's library function (ADR-0022). Runs one trial
  per swept value (every point counted, ADR-0016), refuses unless
  `config.experiment.mode` is already `optimization`, then reads each
  trial's own returns back from its `equity.parquet` and assembles the
  trials × periods panel `validation.pbo.probability_of_backtest_overfitting`
  needs. `DEFAULT_PBO_GROUPS = 6` (untuned default). The same panel feeds
  `validation.reality_check.reality_check` (ADR-0083): `OptimizeResult.reality_check` /
  `reality_check_error`, seeded from the experiment seed.
  `OptimizeResult.best_dsr`/`best_experiment_id`: the winning trial's
  Deflated Sharpe, recomputed against the *full completed sweep's* trial
  history — each trial's own `manifest.json["dsr"]` only reflects the
  trial count as of *its own* recording time mid-sweep, which
  under-deflates a winner that wasn't the last trial run (bug found and
  fixed while building the overfit-detection acceptance test, ADR-0023).
- `validate.py`: `validate_run(config, artifacts_root, *, factors=None) ->
  ValidateResult` — the `crucible validate` CLI's library function. A
  plain `run_experiment` call when `factors` is omitted; when given
  (`load_factors_csv`: one column per factor, row-aligned to the run's own
  returns, no date column), regresses the run's returns on them
  (`validation.factor_regression`) and merges the result into the run's
  manifest/report via `runner.rebuild_report`.
- `runner.py::rebuild_report(out_dir, *, factor_regression=None)` —
  re-renders `report.html` from a finished run's on-disk artifacts,
  optionally merging a factor regression into `manifest.json` first.
  Shared by the `crucible report` CLI command and `validate_run` (a
  refactor out of `_cmd_report`'s former inline body once `validate_run`
  became its second caller, ADR-0022).
- `interfaces.py`: `ArtifactStore`/`RunRegistry` Protocols.
- `runner.py` (ADR-0038): `run_experiment` is now a
  two-line wrapper over `_run_experiment_compute` (quality gate, engine,
  metrics, Monte Carlo — touches only the read-only data store and this
  run's own artifact directory) then `_finalize_experiment` (trial
  registry, DSR, contamination, artifact writing — the only part that
  touches `trial_registry.duckdb`). `run_experiment_parallel(configs,
  artifacts_root, *, max_workers=None) -> list[RunArtifacts]` runs the
  first phase across a `ProcessPoolExecutor` (`pool.map`, which preserves
  `configs` order regardless of completion order) and finalizes serially,
  in the parent, in that same order — reproducing sequential
  `run_experiment` calls byte-for-byte (E1). This split exists *because*
  DuckDB allows only one process to hold `trial_registry.duckdb` at a
  time (fails fast otherwise) and, separately, because even a
  lock-protected concurrent registry write would make each trial's
  provisional DSR depend on wall-clock scheduling instead of `configs`
  order — both verified/derived in ADR-0038, not assumed.
- `optimize.py::optimize_1d` gained `max_workers: int | None = None` —
  routes through `run_experiment_parallel` when set (default: sequential,
  unchanged). `crucible optimize --workers N` on the CLI.
- `crucible compare FAMILY` (`crucible/cli/main.py`):
  lists every trial recorded for a family via
  `validation.trial_registry.DuckDBTrialRegistry.all_trials`, sorted by
  per-period Sharpe descending, with each trial's DSR read back from its
  own `manifest.json` when still on disk (`dsr=unknown` otherwise — a
  missing sibling artifact for an old trial is expected, not exceptional).

## Holdout vault protocol (C6c, ADR-0105)

`vault.py` is the protocol around the data-layer lock (`crucible.data.vault`): registration, the
human authorization and the one evaluation per registration.

- `VaultRegistry(store_root, home, artifacts_root)` (`registry_for`) and its database
  `<home>/vault.duckdb`: `registrations`, `counter`, `access_log`. Append-only: the code has no
  UPDATE and no DELETE apart from the two status transitions (`pending` -> `authorized` ->
  `evaluated`) and the counter increment. `<store>/vault.json` mirrors `{opens, last_log_hash}`, and
  `verify()` refuses a database that is missing, behind that state, or whose log does not contain the
  row the mirror names.
- `register(config_path)` — records `VR-<16 hex>` with the COMPLETE config hash
  (`futures_config_hash`), the datasets' content hashes, the `CND-` candidate id, the window (which
  must lie INSIDE the vault), the requester and the config path. It reads manifests only: no
  protected row. Registering the same config and window twice is refused (one registration).
- `authorize(vr_id)` — a HUMAN step. The admin token comes from an interactive TTY prompt or
  `CRUCIBLE_VAULT_TOKEN`, is verified with `hmac.compare_digest` against the salted `scrypt` hash in
  `<home>/vault_admin` (written by `set_admin`, TTY only, 0600 where supported), and is never
  generated, printed, logged or stored in clear. `hash_token`/`write_admin_secret` are the
  primitives (`write_admin_secret` exists so a test can plant a throwaway token in a throwaway
  home). A wrong token and a non-interactive call without the variable are refused and logged.
- `evaluate(vr_id)` — recomputes the config hash and every dataset hash (a config or dataset that
  changed after registration is refused and logged), increments the persistent counter BEFORE any
  read (a crash consumes the evaluation), opens the `VaultSession`, runs `run_futures` into
  `<artifacts_root>/VAULT/<VR-...>/`, seals it, and moves the status to `evaluated`. The trial is
  recorded in the FAMILY's registry (`run_futures(registry_root=<artifacts_root>)`), so the C6a
  deflation uses the family's `total_trials` while the artifact stays outside every pool. A second
  evaluation is refused and logged.
- `status()` / `access_log(limit)` — ids, the open counter, statuses and attempts. No metric:
  results stay hidden until the evaluation has run.
- `vault_declaration_json_schema` / `vault_registration_json_schema` — the two `crucible schema
  --kind` documents.
- `futures_compare.compare_futures(..., include_vault=...)` and
  `futures_trials.run_futures_trials(..., include_vault=...)` add the vault members
  (`experiments.artifacts.vault_member_dirs`) to their pool only when asked; the family's counts
  include the evaluation either way.

## Prop evaluation (C7b, ADR-0107)

`run_prop_evaluation` answers one question about an existing candidate: *if this strategy traded
this futures run under one firm's ruleset, how often would an attempt starting on trade date `d`
pass, and how little would that number know?* The strategy signal is causal and independent of the
account, so it is prepared once (`import_prepared_run`, ADR-0095) and every attempt replays a slice
of the same bars, targets, rolls and raw per-contract bars.

- **Start dates.** Every Globex trade date of the run's window with at least one on-schedule bar.
  An attempt begins at the open of its trade date; a date the series reaches only off schedule has
  no open and cannot start one.
- **The horizon.** `horizon_trading_days` (H) is the analyst's horizon, in TRADING days, and it is
  required. It becomes a calendar-day window per start with the CME session calendar
  (`_nth_trade_date`), so the same H covers more calendar days around a holiday. It is refused when
  it is shorter than any phase's own limit — `Phase.max_trading_days`, `Phase.max_calendar_days` or
  a `time_limit` rule's — because a firm limit that could never fire inside H would make the
  horizon a lie. Each phase's calendar-day limit is converted per start.
- **Outcome classes.** `pass` (every EVALUATION phase passed; the funded phase's own outcome is
  descriptive), `fail` (a hard breach in an evaluation phase), `timeout` (the firm's own limit),
  `horizon` (H reached unresolved) and `censored` (the data ended before `d + H` and before
  resolution). `horizon` and `censored` are separate classes and neither is a failure or a pass.
  A `time_limit` can resolve an attempt whose H trade dates do not fit in the data: such a start is
  `timeout` and still INCOMPLETE, because completeness is about H, not about resolution.
- **Complete starts and the bounds.** A complete start is `d + H <= last trade date`. `p = passes /
  complete`, `p_low = passes / all starts` (censored as failures), `p_high = (passes + censored) /
  all starts` (censored as passes) and `effective_independent_attempts = n / H`.
- **The interval.** A seeded circular block bootstrap over the complete starts in date order
  (`futures_stats.circular_block_bootstrap`, ADR-0103) with block length `max(H, ceil(sqrt(n)))`
  (`prop_block_length`), seed `bootstrap_seed(evaluation_id, statistic)`, resamples and confidence
  from the run's `statistics` section, and a percentile interval for `p` and for the mean net cash
  per attempt. With `n < 2 * block` the interval is `unavailable` with its reason and no number is
  invented; with no complete start the mean cash is null rather than a number beside an
  `unavailable` status.
- **The cash statistic.** The mean net cash per attempt (trader payouts minus the attempt's fees)
  follows the attempts' `cash_estimate_status`: `exact`, `conditional` (a named cost assumption),
  `upper_bound` (a payout cap the sources do not state) or `unavailable` (an unknown cost), and its
  reasons are listed. Commissions are charged INSIDE the simulated account; the attempt fee columns
  carry the ruleset's own evaluation/activation/monthly/reset fees.
- **Labels, never a verdict.** The number is `pass_probability` only when nothing qualifies it
  (`definitive: true`); otherwise `conditional_pass_probability` with `definitive: false` and every
  reason: unmodeled material or critical rules, an unverified ruleset, a cost assumption, an unknown
  cost, a news-calendar coverage gap, an unsourced session-calendar window, the counterfactual
  application of a current ruleset to pre-2025 data, and a compliance blocker.
  `practical_eligibility` is judged for the `execution_mode`: under `blocked_by_compliance`,
  `mechanically_passes` is reported and `practically_valid_passes` is 0 with the reason.
- **Scenarios.** `scenarios="primary"` evaluates the selected ruleset only; `"all"` adds one full
  sensitivity scenario per conflict alternative (`crucible.prop.scenarios`), each a row per start
  and a scenario summary labelled `alternative_sensitivity` beside the primary's
  `official_primary`.
- **The artifact.** `<artifacts>/PRP-<16 hex>/`: `attempts.parquet` (one row per scenario and start,
  `PROP_ATTEMPTS_SCHEMA`), `summary.json` (`PropEvaluationSummary`, the statistics, the bootstrap
  record and the coverage), `ruleset.yaml` (the exact bytes read) and `manifest.json` with the run
  id basis, the candidate id (ADR-0103), the ruleset id/version/sha256/verification status, H, the
  execution mode, the payout policy, the cost assumption, the participant profile and its
  canonical SHA-256, the promotions applied and NOT applied (each `promotion <id> not applied:
  <reason>`), and every dataset hash. `PRP-` is a pure
  function of the inputs (`evaluation_basis`, `evaluation_id_of`), so the same inputs reproduce the
  same directory and the same bytes; the seal (`seal_artifact`) covers the three result files.
  A prop evaluation is NOT a submission: it records no trial and changes neither
  `submission_count` nor `total_trials` (ADR-0107 section 6).

## Extension points
New config sections join `ExperimentConfig` as (discriminated-union) fields
in their phase; hash coverage extends automatically because the hash is over
the whole model.

## Known gaps
- The futures path (ADR-0095, ADR-0100, ADR-0101, ADR-0102, ADR-0103). C5a (fidelity and
  batches), C5b (walk-forward), C5c (cross-run metrics) and C6a (statistics) are done;
  what remains:
  - **The prop evaluation reports, it does not judge.** It resamples the COMPLETE starts only, so
    a window much shorter than H reports wide bounds and an `unavailable` interval instead of a
    narrower one; the funded phase is descriptive (survival, breaches, payouts, fees) and carries no
    probability; the analyst's H is the only horizon the sequence knows, and a firm's own time limit
    shorter than H ends attempts as `timeout`. There is no verdict and no threshold anywhere (C7e),
    and a ruleset stays `unverified` until the owner confirms it, which the summary labels.
  - **Statistics without a verdict.** C6a reports the per-period and annualized Sharpe, the mean
    daily return, PSR, DSR, bootstrap intervals and (for a DSL expression) the IC, and C6b adds the
    SUPPLEMENTARY effective-trials deflation and PBO on a valid panel, but no ROBUSTNESS
    assessment: `verdict_level` is null everywhere with `robustness_not_assessed` (C7). There is no
    holdout vault yet (C6c), and `dsr_effective_trials` is a second reading of the same evidence,
    never a replacement for the primary deflation by `total_trials`.
  - **The effective count and PBO are estimates with stated limits.** The effective count is
    threshold-dependent and needs a complete correlation matrix (one bad pair makes it unavailable);
    PBO needs a comparable panel, so the batch reports it only when the batch file asks for it and a
    walk-forward only by running each distinct candidate once more on the base window (an in-sample
    panel). Neither is a probability that the strategy is profitable.
  - The IC is time series only (one root, ADR-0099): no cross-sectional IC, no rolling window and
    no IC for a spec or Python strategy (null with a reason).
  - The intervals are percentile block-bootstrap intervals over the daily series, not a
    studentized or stationary-bootstrap variant, and the DSR's cross-trial dispersion is the
    sample variance of the family's candidate Sharpes (no shrinkage).
  - The comparison key is deliberately conservative: two runs that differ only in the
    bracket policy or the fill timing are `incompatible` and get no correlation (ADR-0102),
    and loosening it is a later decision. There is no override and no way to compare a member
    with a hand-made series.
  - The correlation is Pearson over the overlap only: no lag, no rolling window, no
    partial or factor-adjusted version.
  - It does not stop or flag an account whose equity falls to zero or below. It keeps trading;
    `min_equity_usd` and the daily ledger show it. Ruin and prop-firm rules are C7.
  - `FuturesSignalFunction` is a stub Protocol: no implementation ships in the package (the tests
    hold fixtures; a spec goes through `spec_positions`).
- `artifact_id` is verified, not enforced: nothing stops a process with disk access from editing an
  artifact and re-sealing it (ADR-0084). Runs written before it have no id (`verify` says so).
- `ArtifactStore` and `RunRegistry` are stub Protocols: `run_experiment` writes the layout itself and `crucible compare` reads the trial registry directly.
- Adding any config field renames every experiment id (the hash covers defaults); see `docs/COMPATIBILITY.md` §2 for the open decision.
Checkpoint/resume (E7) is library API only (`BacktestEngine.run_until`/`checkpoint`/`resume_from`); no runner integration, auto-checkpointing or CLI. `report.html`/`equity.svg` sit
outside the golden byte surface (ADR-0011). `null_tests.py`'s
per-iteration temp stores under `_null_test_stores/` aren't cleaned up
automatically. The vectorized path has a parallel runner and trial recording
(`run_vectorized_experiment_parallel`, ADR-0061); `crucible optimize --vectorized` drives it.
