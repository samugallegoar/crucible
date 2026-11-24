# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project follows
[Semantic Versioning](https://semver.org/); while the version is below 1.0, a minor release may
change configuration fields, artifact schemas or results (see `docs/COMPATIBILITY.md` for how each
kind of change is recorded).

## Unreleased

### Fathom C7b.1: participant profile, breach on fill, promotions, Topstep review decisions (ADR-0106, ADR-0107 amendments)
- **Participant profile.**
  - A run declares an immutable participant profile (dimension to value); its sha256 is in the
    manifest, the summary, every attempt row and the evaluation id.
  - Each fee row names the classification dimension it needs and is resolved against the
    profile. A missing or `unknown` dimension leaves that component a named gap; there is no
    default classification.
- **"other" fee rows.** Accepted only as a specific, named per-side charge from cmegroup.com,
  with:
  - its quote;
  - evidence that it applies;
  - a statement of why it is distinct from exchange, clearing and NFA.

  Refused: generic names, monthly or platform charges, an exchange row covering `other`, and
  duplicates.
- **Breach on fill.** An intraday loss threshold is tested after every fill and cost posting,
  flat or not, and fails at that fill. Previously a flat account below its maximum loss limit
  kept trading until its next position crossed it.
- **Blocked entries.** A blocked entry is attributed to the rule that blocked it
  (`session_entry_block`, `news_entry_block`), not to the size limit.
- **Promotions.**
  - A rule value may carry eligibility-gated promotions, applied only when the profile proves
    every requirement and the purchase date is inside the window.
  - An unknown end date never extends past the ruleset's `as_of`.
- **Assumption kinds.** Every assumption declares `section7_default`, `provisional_conservative`
  or `owner_decision`.
- **Topstep rulesets (26, all still unverified).** The owner's review decisions are applied:
  - the DLL doubled payout cap is a promotion over the standard cap;
  - XFA inactivity is a provisional conservative close on day 31;
  - Labs inactivity is sourced from the Labs page;
  - the Labs post-payout static drawdown is `not_modeled` (critical) instead of approximated by a
    trailing one;
  - the scope is TopstepX, without metals, as of 2026-11-22.
- **Ruleset lock.** A verified ruleset can never change. An unverified one may be corrected in
  place, and its owner confirmation is bound to the content hash.
- **Conditions on practical eligibility (round 2 of the Topstep review).**
  - A `compliance` rule may declare `effect: condition` with a required `condition` text: an
    obligation the simulation cannot prove, which the trader must meet.
  - Practical eligibility gains `eligible_conditional`, listing every applicable condition in
    `summary.json` and `attempts.parquet`. A mechanical pass under a condition is reported as
    `conditionally_valid_passes`, never as `practically_valid_passes`, and a
    `blocked_by_compliance` verdict still wins over a condition.
  - `practical_eligibility()` returns a `PracticalEligibility` (`status`, `conditions`, `blocker`)
    instead of a bare string.
- **What would change an unmodeled entry's materiality.** A `not_modeled` entry may declare
  `becomes_immaterial_if`: the audited fact that would let its materiality change. The declared
  materiality never changes by itself, and the condition is reported in `rule_coverage`, in
  `summary.json` (`unmodeled_rules`) and in the firm's `RESEARCH.md`.
- **Topstep rulesets (26, re-hashed in place, all still unverified).**
  - Automated trading becomes `eligible_conditional`: six `effect: condition` rules quoted from
    the TopstepX API Access article (API only in the Combine and the XFA, never a Live Funded
    Account; HFT prohibited; orders from the trader's personal device; no VPS/VPN/remote-server
    order entry; the algorithm stays subject to every rule).
  - The XFA scaling plan keeps `material`, is re-quoted to the article that makes it an XFA
    objective, names the saved ladder image and its sha256, and no longer reads as "the funded
    account has no contract limit".
  - Materialities: the 2% price-limit rule, the volatility position-limit tightening and the
    sub-minute scalping entry are material (each with the condition an audit would have to
    establish), the discretionary full-size news rule stays material, and cross-account hedging
    stays immaterial with the condition that would make it bind.
  - The payout policy's "at least $0.01 since your last Payout" gate is declared on every funded
    payout rule where it can bind; the Labs drops re-source the 90/10 split to their own page, keep
    $250 on the Daily Payout path (with $125 as the sensitivity), declare $125 on the 5 Winning
    Days path as an owner decision, and keep each variant's own maxima.
  - The Labs drops declare the page's own 90-calendar-day lifespan and 30-calendar-day inactivity
    in the evaluation phase, counting executed trades only, and no funded-phase inactivity the
    page does not publish.
- **Values printed only inside an image (ADR-0107 amendment, 2026-11-23).**
  - New evidence type `official_image_transcription`: a rule whose value is printed only in a saved
    picture carries the image's own sha256, its path under the private snapshots root, the values
    exactly as printed, and who transcribed them when. The evidence and the block must agree in both
    directions, and the block is all-or-nothing.
  - `crucible.prop.sources`: the evidence self-check as code. Every attribution's page hash must
    resolve to a saved file and its quote must appear in THAT page; an image transcription's file must
    hash to its declared sha256. `crucible prop validate <file> --snapshots-root DIR` runs it and
    refuses a mismatch (no more "the quotes verify" as a paragraph in a review). A transcription is
    never compared with page text: the numbers exist only in the picture.
  - `supporting_sources` on a rule (attributions that support its basis, timing or units without
    carrying its value) and `assumptions` (further named readings the one value depends on, each
    reported with the value).
- **`scaling_plan` balance tiers.** A step may be keyed on `min_balance_usd` (the absolute balance at
  the rule-day's close) instead of `min_profit_usd`; the first step may omit its threshold and is then
  the floor rung (so a zero or negative balance has a size); a balance ladder requires `basis:
  balance` and `evaluated: eod` and takes its rung boundary from its own `comparison` (`>=` upper
  rung, `>` lower rung). The profit form is unchanged, including its vestigial `comparison`.
- **Topstep XFA scaling-plan ladder (24 Trading Combine files, still unverified).**
  - The funded phase declares `xfa_max_contracts`, the ladder transcribed from the official image for
    its own size (50K: 2/3/5 lots; 100K: 3/4/5/10; 150K: 3/4/5/10/15), keyed on the balance, with the
    boundary in the LOWER rung, a floor tier for a zero or negative balance, and `clip` on excess.
  - The page quotes for the basis ("Your XFA starts at a $0 balance"), the timing ("Your max
    contracts do not increase mid-session"), the 10:1 mini/micro ratio and the 10-second excess
    tolerance are `supporting_sources`; three delegated decisions (boundary, negative balance, clip)
    are `assumption_kind: owner_decision` assumptions naming the delegation of 2026-11-23.
  - `xfa_scaling_plan_ladder` leaves `not_modeled` in those 24 files and stays in the 2 Labs files,
    where the article's table is not extrapolated to the Labs XFA.
  - The Trading Combine's maximum position size is never the XFA limit, and nothing in a funded
    phase changes size mid-session.

### A preliminary cross-firm cost: the versioned upper-bound cost-assumption file (ADR-0107 amendment, 2026-11-23)
- **`kind` on a cost-assumption file (REQUIRED): `point_estimate` or `upper_bound`.**
  - `point_estimate` keeps the meaning: the owner's best single figure, and an amount on a cost
    the firm already has is refused.
  - `upper_bound` states ceilings, fills only the gaps a firm's own sources leave, and skips (never
    charges, never refuses) an amount on an `included` component, one the fee dataset priced or a
    commission the firm states.
  - Existing fixtures gained `kind: point_estimate`; a file without it is refused by name.
- **`rulesets/prop/cost_assumptions/upper_bound_v1.yaml`.** The owner's explicit, unverified bound
  per root and component (ES/NQ/YM/RTY: exchange 2.00, clearing 0.50, NFA 0.02, other 0.50; NKD:
  3.00, 0.50, 0.02, 0.50; MES/MNQ/MYM/M2K: 0.60, 0.25, 0.02, 0.25 USD per contract per side), with
  the rationale per row in its evidence. Hashed like a ruleset: an INDEX.json entry of kind
  `cost_assumption` plus the run's summary, manifest and attempt rows. A change is a new file
  (`upper_bound_v2.yaml`), never an edit in place. It is not a fee table and never feeds
  `exchange_fees_v1`.
- **Labels under an upper-bound file.** `cost_bound: upper` in `summary.json` (top level and every
  scenario) and in every `attempts.parquet` row; the cash statistic is `lower_bound`
  (`cash.status`, `cash_estimate_status`); the pass probability reasons carry `costs are an upper
  bound: the probability and the net cash are pessimistic (lower bounds) under it`; every report
  carries the comparability note (`firms with fewer sourced cost components receive more of the
  bound, so cross-firm comparisons under it are pessimistic for the less documented firms`). The
  estimate stays `conditional`, never `complete`.
- **The per-firm cost-component table is unchanged:** no ruleset value, hash or verification status
  moved. `crucible prop list` keeps listing rulesets only, and the new directory is excluded from it.
- **Docs:** `docs/modules/prop.md`, `docs/USAGE.md` (how to run the analysis and read the labels),
  `docs/GLOSSARY.md` (upper-bound cost assumption), `docs/data/cme-exchange-fees.md` (the file is
  not the fee table) and `docs/SCHEMAS.md` (the new columns and keys).

### CI shape: shard the suite across runners, prove the shards add up (ADR-0109)
- **One run per change.** `on: push: branches: [main]` plus `pull_request` (a PR branch used to run
  the whole workflow twice) with `concurrency` + `cancel-in-progress`, so a superseded push stops
  instead of queueing.
- **The suite is sharded across runners, not only across cores.** `pytest-split` gives 6 shards on
  ubuntu and macOS and 8 on Windows, each on `-n auto --dist loadscope`; every shard is a runner of
  its own, so the full suite still runs on every OS for every PR.
- **`tools/check_shards.py` and the `shard-union` job prove it**: each shard uploads the JUnit report
  of what it ran, and the union of those reports must *be* the whole suite, per OS (no gap, no
  duplicate). A `-k`/`--deselect` on a shard fails the PR.
- **`.test_durations`** is committed and refreshed from ubuntu by a `workflow_dispatch` job; a stale
  file only unbalances the shards.
- **The code fingerprint is pinned once per test session** (0.143 s per backtest, ~21 s of the serial
  suite). Production behaviour is unchanged and the overwrite guard still catches an edit between two
  runs.
- Each job's `timeout-minutes` is a budget at about 2x its measured p95, not a widened limit.
- Measured on three green runs: the workflow went from 7.2 min p50 / 12.4 min p95 to
  3:52 / 4:22 / 4:53 (median 4:22). The 2-minute target is not met; ADR-0109 records why (one
  durations file for three different runners, the ~20-job concurrency ceiling, per-job fixed cost,
  and the union job's tail).
- **Amendment (ADR-0109): one durations file per OS, and a plan that fits in one wave.** The single
  ubuntu-derived file left macOS and Windows shards 1.2-1.8x over plan; there are now three
  (`.test_durations.ubuntu|macos|windows`, one `durations` matrix job each) and 6/3/6 shards, so the
  workflow runs 18 jobs at once instead of 23 and no shard waits for a slot (every ubuntu and Windows
  shard starts in 2-3 s). Measured on the final shape: 4:01, 6:53 and 12:53 of workflow wall, with
  `checks` 33-52 s, `shard-union` 24-32 s and `clean-install` 18-20 s. macOS is the tail and the
  reason the 2-minute target is still out of reach: its ~600 s suite over the 3 runners the pool
  gives is ~200 s a shard, and on 2026-11-24 a macOS job waited 604 s (or was cancelled with no
  runner) while every other shard started in 3 s.

### Fathom C7b: firm rulesets and prop evaluation over a futures run (ADR-0107)
- **201 sourced firm rulesets.**
  - Files `rulesets/prop/<firm>/` cover Topstep, Apex, MyFundedFutures, Lucid, FTMO and FundedNext.
    They include every futures product currently sold, with every size and every rule-, fee- or
    platform-changing variant.
  - All are `unverified`. Every value carries an official URL, a verbatim quote, a page snapshot
    hash and a retrieval time.
  - `RESEARCH.md` per firm holds the product matrix, conflicts, assumptions and an owner review
    checklist.
  - `rulesets/prop/INDEX.json` hash-locks every version and is append-only.
  - Verification is a sidecar bound to the content hash. Only the owner writes it, with
    `crucible prop confirm` (TTY only).
- **Ruleset schema 2.**
  - Every rule declares its metric and basis, threshold, observation frequency, reset, comparison
    and action, with no defaults.
  - Evidence types are `official_quote`, `owner_provided`, `assumption` and
    `conflict_resolution`.
  - Conflicts keep both sources and generate sensitivity scenarios.
  - Day units are explicit. `unlimited`, `unknown` and `not_modeled` are distinct, and numeric
    sentinels are refused.
  - Commissions per root are declared, and each cost component (exchange, clearing, NFA, other)
    is declared separately as `included`, `excluded` or `unknown`, with its evidence. Cost
    statistics are `complete` only when no component is unknown or unpriced.
  - An unpriced gap is priced only by an explicit cost-assumption file (unverified, hashed, per
    root and component, added to the cost). The result is then `conditional`.
  - Owner-provided CME fee files record the source URL, effective dates, root, participant type
    and the components each amount covers. Lookups are historical and per root, with no
    extrapolation across contracts.
  - Compliance rules feed practical eligibility (for example, a critical automation ban).
  - The account lifecycle is a state machine (payout cycles, post-payout effects).
- **New vocabulary.**
  - Payouts:
    - caps that are a number, `unknown` (paid as an upper bound) or `unlimited`;
    - caps by payout index, as a percentage of the balance or as a share of the withdrawable;
    - windows since the last payout;
    - cycle goals and a first-payout gate;
    - payout groups;
    - a minimum new-profit share.
  - Trailing: a separate high-water-mark basis, and multi-trigger locks.
  - Daily loss: tiered and ratcheting limits.
  - Scaling: `on_excess`.
  - Other rules:
    - daily profit cap;
    - session-relative flat, which blocks entries until the session close;
    - inactivity and activity requirements;
    - monthly and reset fees;
    - news restrictions (block or contract cap).
- **New data.**
  - `econ_events_v1` and `v2` hold FOMC statements, press conferences and minutes, CPI, PPI and
    NFP from federalreserve.gov and bls.gov.
  - An event without a stated time is a coverage gap, never a window at an invented time.
  - `exchange_fees_v1` holds the official NFA rows. CME exchange fees are taken only from
    owner-provided files.
- **Prop evaluation.** `crucible futures prop` (and `crucible_futures_prop`):
  - One causal signal, and attempts on every eligible start date.
  - Outcomes are `pass`, `fail`, `timeout`, `horizon` and `censored`.
  - `p` is computed over complete starts, with bounds for the censored starts.
  - A seeded circular block bootstrap uses blocks of at least H days.
  - `pass_probability` is reported only when nothing is unmodeled, unverified or uncosted.
    Otherwise it is `conditional_pass_probability` with `definitive: false` and the reasons.
  - Practical eligibility is reported separately.
  - The sealed artifact is `PRP-`. It is not a trial.
- **Fixes found during C7b.**
  - An EOD-evaluated pass condition is now tested only at the rule-day's last scheduled bar.
  - Days to pass are measured from the attempt's own start.
- **Scope:** no verdict (C7e). Market data stay before 2025-01-01 and the vault is closed. Current
  rules on pre-2025 data are labelled a counterfactual application.

### Fathom C7a: generic prop-firm rule engine (ADR-0106)
- **The rules run inside the simulation, bar by bar.**
  - `simulate_futures` gains an optional `account` (the `AccountOverlay` Protocol in
    `crucible/execution/interfaces.py`).
  - Without an account, the output is unchanged byte for byte, so every golden and run id is
    unchanged.
  - With an account, the per-bar order is fixed:
    1. rule-day transition and the gap-at-open test;
    2. forced flat;
    3. admission (contract limit by contract weight, scaling plan, locks);
    4. the favourable extreme, then the adverse walk, which merges lot stops and breach prices in
       path order;
    5. the close, with the EOD rules and the pass conditions.
- **Conservative OHLC semantics (`high_before_low_conservative`).**
  - An intraday high-water mark moves on the favourable extreme before the adverse extreme is
    tested.
  - Both are applied together, as a declared approximation biased against passing.
  - A breach or stop touched in a bar blocks that bar's targets.
- **Breaches liquidate at market, never at a guaranteed threshold fill.**
  - A breach fills at the first tick against the strategy, at the open when the bar gapped, or at
    the close for an EOD-evaluated breach.
  - It pays spread and slippage, plus `liquidation_extra_slippage_ticks` charged as a cost.
  - Fills stay inside the bar.
- **The new package `crucible/prop/` holds the engine.**
  - Rulesets are versioned and immutable, with a per-rule source attribution (URL, quote, snapshot
    hash, retrieval time).
  - A ruleset stays `unverified` until the owner confirms it.
  - Rule kinds: profit target, static, trailing (intraday or EOD, with lock) and daily-loss
    thresholds, each with a required `evaluated`; max contracts; scaling plan; flat-by; minimum
    trading days; consistency; time limit; fees; payouts.
  - Phases run in order, each with a fresh, flat account.
  - Rules the engine cannot express are declared `not_modeled` with a materiality.
  - `simulate_attempt` returns `pass`, `fail`, `timeout` or `censored`. The result also carries the
    breached rule, the minimum buffer, `rule_coverage`, `evaluation_status`, `material_unmodeled`
    and `counterfactual_application`.
  - It contains no firm values: a test checks that no firm name appears in `crucible/`.
- **Entry points:** `crucible prop validate`, `crucible schema --kind prop-ruleset|prop-attempt`,
  and the MCP tools `crucible_prop_validate` and `crucible_prop_schema`.
- **Scope:** synthetic rulesets only. Firm rulesets, attempt sequences and pass probability are
  C7b; no verdict before C7e.

### Fathom C6c: futures holdout vault (ADR-0105)
- **The protected period.**
  - Globex trade dates from 2025-01-01, open-ended.
  - The universe is ES, NQ, YM, RTY and NKD.
  - The scope is the family, so creating another family does not bypass it. A single-root vault
    must be declared explicitly.
  - The period was chosen after the 2026-11-19 exposure audit. It has no strategy-level exposure;
    the residual exposure (the simulator acceptance path and the integrity counts) is documented.
- **Data-layer guard** (`crucible.data.vault.VaultGuard`).
  - `ParquetDataStore.read` and `data_path` consult it on every construction path.
  - A read of a protected root whose `as_of` reaches the vault start (2024-12-31 23:00 UTC, the
    17:00 CT open of the 2025-01-01 session) raises `VaultLockedError`. So does access to a whole
    file.
  - A `metadata` access (counts, hashes and date bounds) is still allowed for the catalog.
  - Every attempt is appended to a persistent access log.
  - The declaration lives in the store root and in the Crucible home, and is enforced if either
    copy exists. It can only be widened.
- **Protocol** (`crucible vault declare|status|register|authorize|evaluate|log|set-admin`).
  - A registration (`VR-`) records the full config hash, the dataset hashes, the candidate id and
    the window.
  - Authorization needs the human admin token. It is checked against a salted scrypt hash that
    `set-admin` writes outside the repository, from interactive TTY input only. The token is never
    generated or stored in clear.
  - Each registration allows one evaluation.
    - The open counter is incremented before any data is read, so a crash still consumes the
      evaluation.
    - The config hash is re-checked.
    - The result is sealed under `VAULT/<VR->`.
    - A second evaluation is refused and logged.
  - Results stay hidden until the evaluation has run. `compare` and `trials` exclude vault
    artifacts unless asked explicitly.
  - The MCP server exposes only `status`, `register` and `log`.
- **Read horizon.** Futures runs now read up to the close of `window.end` instead of an
  open-ended `as_of`. The rows read and the results are unchanged; on real ES, `es_zscore_reversion`
  still gives 2,167 fills and a final equity of 6,526.5.
- **Tests.**
  - The test suite runs with a throwaway Crucible home (`tests/conftest.py`).
  - The real-data benches (simulator acceptance, continuous builds) now stop before 2025.
- **Consequence.** Once the vault is declared, rebuilding a continuous dataset of a protected root,
  which reads the whole raw series, is refused like any other read that reaches the vault.

### Fathom C6b: effective trials, supplementary DSR and PBO on futures candidate panels (ADR-0104)
- **Effective trials** (`crucible.validation.effective_trials`, numpy only).
  - Agglomerative clustering with average linkage on `d = sqrt((1 − ρ)/2)`, with a default
    threshold of ρ* = 0.5. Ties go to the lexicographically smallest pair.
  - Every report includes a sensitivity table for ρ* ∈ {0.3, 0.5, 0.7, 0.9}.
  - The result is labelled an estimator: threshold-dependent, and not a count of independent
    hypotheses.
  - The correlations follow the C5c rules: intersection of trade dates, equal comparison keys and a
    minimum overlap.
  - If any pair lacks a valid correlation, the estimate is `unavailable` and the reasons are listed.
    No value is substituted.
- **Supplementary DSR.**
  - `dsr_effective_trials` uses the same Sharpe and dispersion as the primary DSR, with N replaced by
    the effective count.
  - It is reported under `supplementary`. The primary `dsr` over `total_trials` is unchanged and
    remains the conservative result.
  - It never feeds a verdict, which stays `robustness_not_assessed`.
- **Entry points.** `crucible futures trials --family F`, the MCP tool `crucible_futures_trials` and
  `schema --kind futures-trials`. They write `EFT-<id>/trials.json` with the counts, the candidates,
  the pairs, the estimator and the sensitivity table.
- **PBO by CSCV.**
  - **On a batch.** The panel is the distinct candidates, and every candidate must have an
    identical set of trade dates. Otherwise PBO is `unavailable`.
  - **On a walk-forward.** It uses a separate full-window panel with one run per candidate, never
    the selected OOS path.
  - The option is `pbo: {n_groups}`, which must be even and at least 4.
  - Panel runs are recorded as trials with `mode = 'pbo_panel'`. They do not change
    `submission_count` or `total_trials`.
- **Fix: a sealed `commission_only` config now reloads.** The canonical dump no longer writes the
  unset spread and slippage ticks.
  - Before this, comparisons and the estimator marked screen-fidelity runs `unverified`.
  - The config hash and the run ids do not change; only those runs' `config.yaml` bytes do.
  - A reload failure is now reported as `config_reload_failed: <error>`.

### Fathom C6a: futures statistics (ADR-0103)
- **Inferential statistics begin; the verdict does not.**
  - Every futures output keeps `verdict_level: null`, now with
    `verdict_reason.code = "robustness_not_assessed"`. This covers the run document, `batch.json`,
    `walkforward.json` and `cross_run.json`.
  - No edge is stated before C7.
- **Daily returns on fixed capital** (`crucible.experiments.futures_stats`).
  - `(closing_equity_t − closing_equity_{t−1}) / initial_capital`, with marked P&L and all costs
    counted once.
  - A session with no position is a real zero. A missing session is excluded and counted in
    `missing_sessions`, never zero-filled.
  - One function serves standalone runs, batch candidates, walk-forward OOS and comparisons.
- **New metrics.**
  - The per-period Sharpe, which feeds PSR and DSR, and an annualized Sharpe (√252) for
    presentation only, its convention recorded in the manifest.
  - Mean daily return.
  - PSR with the skew and kurtosis correction (`validation.dsr.probabilistic_sharpe_ratio`, now
    public).
  - DSR deflated by the family's `total_trials`, null with a reason below two candidate Sharpes.
- **Seeded circular block bootstrap intervals.**
  - The manifest records the RNG (PCG64), seed, block-length policy, block length, resamples and
    confidence.
  - Each seed is derived from the artifact id and the statistic name, so results do not depend on
    execution order or parallelism.
- **Information coefficient.** The daily Spearman correlation of the expression score with the
  `h`-bar forward return on the signal series. Pairs that cross a session edge or a roll are
  dropped, and a day with fewer than 10 pairs has no IC. Mean IC comes with an interval, and IC is
  also given per month.
- **Candidate identity and trial counts.**
  - `CND-<16 hex>` covers the strategy (structure and parameterization), size, root, datasets,
    execution, costs, effective fidelity, session and signal. It excludes window, warm-up, name,
    family, capital and statistics.
  - The registry gains additive columns (`trials.candidate_id`, `trials.n_obs`, `trials.seq`,
    `submissions.candidate_id`).
  - It reports `submission_count`, `unique_candidate_count` and `total_trials`. A duplicate is
    recorded but never counted twice, and a candidate evaluated across walk-forward folds counts
    once.
- **Configuration.** `FuturesRunConfig.statistics` takes `ic_horizon_bars`, `resamples` and
  `confidence`.
- **Compatibility.** The new section renames every futures run id, because the config hash dumps
  defaults. A futures trial's period is now one trade date. Simulation results are unchanged.
- **Test fix.** `test_product_backtest.py::test_a_second_variant_is_a_second_trial` no longer
  depends on test order.

### Fathom C5c: futures cross-run metrics and descriptive daily P&L correlation (ADR-0102)
- **C5 stays descriptive.** No Sharpe, IC, PSR, DSR, p-values, confidence intervals, significance
  or ranking by a statistic is added. Every metric and correlation keeps
  `assessment: "descriptive"` with null intervals, and the verdict stays `not_assessed`. C6 is the
  first stage that may add inference.
- **Entry points:** `crucible futures compare --target ID`, the MCP tool `crucible_futures_compare`
  and `crucible schema --kind futures-compare`. The target and the pool members are sealed futures
  runs (`FUT-`) and walk-forwards (`WFA-`, whose series is the concatenated OOS).
- **Metrics per member.**
  - P&L: `marked_pnl_usd` and `realized_pnl_usd`.
  - Costs, closing drawdown and intraday drawdown.
  - Trades: position episodes, where a long-to-short flip counts as two.
  - Fills, turnover in contracts (total and per trade date), and days in market.
  - Window stability: net P&L per calendar month, with the counts of positive, negative and flat
    months, plus per-fold OOS P&L for a walk-forward.
- **Correlation.**
  - It is Pearson's correlation of the daily marked P&L over the intersection of trade dates only.
    A missing date is excluded, never treated as zero.
  - Fewer than `--min-overlap` overlapping dates (default 20, floor 10) gives
    `insufficient_overlap`. A constant series gives `constant_series`. Neither has a value.
  - Only members with an equal comparison key are correlated. The key covers the simulator
    version, fidelity, execution, session and signal input. Other pairs are `incompatible`, and
    the differing keys are listed.
  - A member whose seal fails is listed as `unverified`.
- **Output.** `cross_run.json` goes under `CMP-<16 hex>/`, outside every sealed run. The pool is
  sorted by id, never by correlation.
- **Example.** The two shipped ES examples are `incompatible`, because their bracket tick settings
  differ.

### Fathom C5b: futures walk-forward with constrained in-sample selection and concatenated OOS (ADR-0101)
- **C5 stays descriptive.** No Sharpe, IC, PSR, DSR, p-values, confidence intervals or statistical
  edge claims are added. Every metric keeps `assessment: "descriptive"` with null intervals, and
  the verdict stays `not_assessed`. C6 is the first stage that may introduce them.
- **Signal warm-up** (`window.warmup_trade_dates`, default 0).
  - The run reads the N Globex trade dates before `window.start` to compute the signal only. The
    warm-up produces no fill, mark, ledger row, position or roll.
  - A warm-up that does not cover the expression's warm-up bars is refused.
  - The manifest gains an additive `warmup` block.
  - With 0, every output is unchanged.
- **Walk-forward** (`crucible futures walkforward --config FILE`, the MCP tool
  `crucible_futures_walkforward` and `crucible schema --kind futures-walkforward`).
  - Folds are counted in trade dates, `rolling` or `anchored`. Test windows are contiguous and
    never overlap; a remainder is reported as `unused_trade_dates`.
  - Every candidate runs on the training window under the base config; only the strategy changes.
  - A candidate is eligible only if its training run meets every constraint:
    `max_intraday_drawdown_usd` (required), and optionally `min_equity_usd`, `max_fills` and
    `max_time_in_market`.
  - The selection is the largest training net P&L among the eligible candidates, with ties going
    to the earliest submission.
  - A fold with no eligible candidate is evaluated flat, with status `no_eligible_candidate`.
  - The selected candidate runs on the following test window only.
  - A position open at a test window's last bar is charged one side of the run's per-contract cost
    (`terminal_exit_cost_usd`). Every fold therefore starts and ends flat.
- **Outputs.** `walkforward.json` (`WFA-<16 hex>`, schema_version 1) and `oos_daily.parquet`.
  - The `oos` summary is computed only from the concatenated test-window series. A fold's OOS P&L
    is its marked P&L minus its terminal exit cost.
  - `window_stability` lists each fold's OOS P&L and counts folds that are positive, negative or
    flat.
  - Training results are kept under `in_sample_audit`, each marked `in_sample: true`, and never
    under `oos`.
  - Every training candidate is recorded in `submissions`, with the walk-forward id as the batch id.
- **Compatibility: every futures run id changes again.** `FuturesWindow` gained
  `warmup_trade_dates`, and the config hash dumps defaults. Results at warm-up 0 do not change.
- **Example.** `examples/futures/es_walkforward_screen.yaml` covers ES from January to June 2024 at
  15m with commission-only costs: 3 candidates, train 20 and test 10 trade dates, warm-up 5. It
  produces 10 folds, two of them with no eligible candidate. Its base sets
  `allow_unverified_sessions`, because the 2024-01-15 early close has no verified final bar.

### Fathom C5a: futures fidelity levels and batch evaluation (ADR-0100)
- **C5 stays descriptive.** No Sharpe, IC, PSR, DSR, p-values, confidence intervals or statistical
  edge claims are added. Every metric keeps `assessment: "descriptive"` with null intervals, and
  every verdict stays null with reason `not_assessed`. C6 is the first stage that may introduce
  them.
- **Causal session-bounded resampling** (`crucible.data.resample.resample_session_bars`).
  - It builds 5m and 15m bars from 1m bars. A bucket collects the bar ends in `(k·m, (k+1)·m]` and
    is clipped to its CME trade-date session, so no bar spans the maintenance break or a session
    edge.
  - Off-schedule bars are dropped and counted, and an empty bucket produces no bar.
  - `available_at` is the later of the bucket label and its constituents' `available_at`.
  - A bucket that mixes contracts is refused.
- **Fidelity in the futures run.** The new `fidelity` field takes `resolution` (`1m`, `5m` or
  `15m`), `cost_detail` (`full` or `commission_only`) and an optional `preset` (`screen`,
  `standard` or `full`). `FIDELITY_TABLE_VERSION` is "1".
  - A preset that contradicts an explicit field is refused.
  - `commission_only` refuses explicitly non-zero spread or slippage ticks, and the manifest
    records it as an optimistic approximation.
  - The manifest and the futures document gain an additive `fidelity` block. Neither
    `schema_version` changes.
  - A coarse run refuses a partial (session-clipped) bucket. None occurs on the current session
    table.
- **Causal roll on a coarse grid** (`simulate_futures`).
  - A causal roll executes at the open of the first simulated bar that is at or after its decision
    and at which both contracts have a raw 1m bar opening. Both legs are priced at those raw 1m
    opens.
  - At 1m this is the previous rule, and every 1m output is byte-identical. `SIMULATOR_VERSION`
    stays 2.
  - At 1m, a missing first joint minute in the series now moves the roll to the next bar where
    both contracts trade, where strict mode used to refuse it.
  - The policy records `roll_execution_grid_seconds` and `roll_execution_grid`.
- **Batch evaluation.**
  - Entry points: `crucible futures batch --batch FILE`, the MCP tool `crucible_futures_batch` and
    `crucible schema --kind futures-batch`.
  - Every candidate shares the base config. Only the strategy and the run name change.
  - The batch id is `BAT-<16 hex>`.
  - A canonical duplicate or an already sealed run is `cached` and never recomputed.
  - `batch.json` lists the candidates in submission order, never ranked, with descriptive dollar
    metrics.
- **Every submission is recorded.** The trial registry gains an additive `submissions` table keyed
  by (batch_id, position). The `trials` table is unchanged, and C6 decides how submissions count
  toward the trial total.
- **Compatibility: every futures run id changes.** `FuturesRunConfig` gained `fidelity`, and the
  config hash dumps defaults (`docs/COMPATIBILITY.md` §2). So every existing futures config gets a
  new `FUT-` id, even at 1m, although its marks, fills, ledger and metrics do not change. Old run
  directories stay valid as names of old runs.
- **Examples.** `examples/futures/es_zscore_screen.yaml` and `es_batch_screen.yaml` run on the real
  store: three candidates, two distinct runs and one `cached`, at 15m with the March 2024 roll
  executed causally.

### Fathom C4c: cross-sectional rank, structural similarity, incremental evaluator (ADR-0099)
- **`cs_rank` is evaluated on a panel.**
  - The universe at each `event_time` is the symbols with a row exactly at that time and a
    non-null argument, with no forward-fill.
  - Fewer than three members give null. Ties take the average rank, normalized to [0, 1].
  - `decision_at` is the latest `available_at` in the universe.
  - `cs_universe` records the members and their count per timestamp.
  - A futures run (one root) refuses an expression that uses it.
- **Structural similarity** (`crucible.dsl.similarity`).
  - The measure is Sørensen–Dice, `2·common/(nodes_a+nodes_b)`. `common` is the node count of the
    largest complete subtree shared by the two canonical ASTs.
  - Parameters are typed placeholders renumbered inside the subtree, so repeated and independent
    parameters stay distinct.
  - `pool_similarity` and `max_similarity` rank a pool.
- **Incremental evaluator** (`crucible.dsl.incremental.IncrementalEvaluator`).
  - It is `Snapshottable` and keeps per-symbol state for the same immutable `CompiledSignal`.
  - It refuses out-of-order timestamps and enforces the availability rules at every step.
  - It refuses a snapshot taken for another `compiled_id`.
- **Parity** (`crucible.dsl.parity`).
  - Nulls, booleans and decision times must match exactly. Scores must match within a relative
    1e-9, and no decision may flip sign.
  - On one real week of ES ratio-adjusted bars the two paths are bitwise equal.
- **Fix: `ts_std` on a constant window.** It now uses Welford's one-pass form, so the result is
  exactly 0 and `ts_zscore` is null. The two-pass residue had produced a huge z-score in the
  incremental path.

### Fathom C4b: DSL evaluation, the CompiledSignal, and expressions in the futures run (ADR-0098)
- **Evaluation.** `crucible.dsl.evaluate` evaluates expressions per symbol stream with fixed
  semantics:
  - windows count rows and include the current one;
  - null propagates, and every non-finite value becomes null;
  - `and`, `or` and `not` follow Kleene logic;
  - `ts_std` uses ddof = 1;
  - `ts_rank` averages ties and is normalized to [0, 1];
  - `ema` uses `adjust=False`, as in `strategy_spec`.

  `warmup_bars` gives the static warm-up. `cs_rank` is refused until C4c.
- **Versions.** Each operator now declares `min_window`. New session features `minutes_since_open`
  and `minutes_to_close` come from the CME calendar. `GRAMMAR_VERSION` and
  `OPERATOR_TABLE_VERSION` are now `"2"`, so every `structure_id` changes.
- **Availability.** `check_availability` enforces C2's `available_at`. It refuses a value before
  `event_time`, a non-monotone sequence, and a latency longer than one bar.
- **`CompiledSignal`.** `crucible.dsl.compile.compile_expression` gives an immutable, stateless,
  versioned `CompiledSignal` (`COMPILER_VERSION = "1"`).
  - Its `compiled_id` covers the input roles, not dataset hashes.
  - On ratio-adjusted input it refuses a score of non-zero price degree (ADR-0086).
- **Futures runs.** `strategy.expression` is a third strategy source. `params` bind its `$`
  parameters and `contracts` is required. The target is `sign(score) × contracts`, and a null
  score gives flat. The session policy and the empirical scale check apply.
  - The signal record carries `strategy_kind: dsl` and the three ids.
  - `futures check` prints the canonical text and the ids.
  - New example: `examples/futures/es_zscore_reversion.yaml`.

### Fathom C3c: a futures-run document Fathom can read (ADR-0097)
- **One constructor.** `crucible.experiments.futures_document.futures_document(run_dir)` builds the
  document from the sealed run directory, `schema_version` 1. Its schema is printed by
  `crucible schema --kind futures-run-document`. `futures run --json` and
  `artifact show <ART-…> --json` both use it, so the two emit the same document.
- **No verdict, and the document says why.** `verdict.verdict_level` is `null`, and
  `verdict_reason.code` is `not_assessed`: no statistical assessment happens before C6 and C7. The
  message states that this is not evidence of no edge.
- **Metrics carry an assessment status.** Every metric is
  `{value, ci_low, ci_high, assessment, unit}`. Each one is `descriptive`, with null intervals. No
  statistic is computed (the ADR-0095 restriction stands).
- **`--home`.** `futures run`, `artifact show` and `artifact verify` accept `--home`, resolved as
  `backtest` resolves it. The artifacts root, and with it the only trial registry, become
  `<home>/experiments`, and `--store` defaults to `<home>/data`. `--home` together with
  `--artifacts` is refused. Without `--home`, `futures run` now refuses a missing `--store` with a
  structured `configuration_error` (it used to be an argparse error).
- **Data catalog.** `crucible data catalog` reports `futures_run` support per root: a calendar, a
  contract spec and the four default datasets.
- **MCP.** `crucible_futures_run` and `crucible_artifact` pass `home` through.
- **Breaking:** the `futures run --json` document shape changed from the C3b-3 ad-hoc dict. Use
  `experiment_id` and `metrics`; `summary` and `manifest` are gone.

### Fathom C4a: the DSL core (ADR-0096)
- New package `crucible.dsl`, a typed causal expression language. This release covers syntax,
  types and identity only; evaluation arrives in C4b.
  - **Grammar** (`GRAMMAR_VERSION = "1"`). It refuses ambiguous text: `==`, chained comparisons,
    exponent numbers and unknown names.
  - **Types.** Every node carries price and volume exponents, so a price level compared with a
    constant is refused (ADR-0086).
  - **Operator table** (`OPERATOR_TABLE_VERSION = "1"`), with a semantic version per operator.
  - **`$` free parameters.** Repeated references share one binding. An unbounded parameter can be
    extracted and bound but is not optimizable.
  - **Bounded canonicalization.** Literal folding, the exact identities `x*1`, `x/1` and `x-0`,
    double negation, and sorting of the direct operands of `+ * min max`. `x + 0` is kept because
    it changes the sign of zero.
  - **Three ids:** `structure_id` (`DSX-`), `parameterization_id` (`DSP-`) and the `compiled_id`
    basis (`DSC-`).
  - **Structural metrics.**
- `crucible.core.canonical.canonical_json` now holds the canonical-JSON function.
  `experiments.artifact_id` re-exports it, byte-identical.
- A new import layer for `crucible.dsl` sits between `execution | portfolio` and `data`. The
  `strategy_spec` row of `docs/ARCHITECTURE.md` is corrected.

### Fathom C3b-3: the futures run (ADR-0095)
- **Config and runner.** `crucible.experiments.futures_config.FuturesRunConfig` (`kind: futures_run`)
  and `futures_run.run_futures`: a futures backtest of one root on its continuous datasets.
  - The window is in Globex trade dates.
  - The strategy is a spec or a `FuturesSignalFunction`.
  - Contracts, capital, costs, tick brackets, signal input and CME session rules are all set in the
    config.
  - A trial family is required, and every run is registered in it (mode `futures`, no Sharpe).
- **The sealed artifact** (`FUT-` run id, `ART-` artifact id) holds:
  - `marks.parquet`: per bar, the position, the balance, the close equity, and an OHLC estimate of
    the intrabar low and high equity, labelled as an approximation;
  - `daily.parquet`: per trade date, the scheduled session bounds, the opening and closing balance
    and equity, realized P&L, costs by kind, the unrealized P&L at the close, the minimum and
    maximum equity and the maximum contracts;
  - `fills.parquet`, with the position after each fill;
  - `rolls.parquet`;
  - `metrics.json`, with descriptive totals only.
- **Ledger and manifest.** The daily-ledger identities are checked before writing
  (`check_daily_ledger`). The manifest records the datasets with their hashes and adjustments, the
  signal record, the execution policy, the calendar summary, the marking policy and the
  approximations.
- **CLI and MCP.** `crucible futures run|check`, `crucible schema --kind futures-run`, and the MCP
  tools `crucible_futures_run` and `crucible_futures_check` (thin wrappers, ADR-0066).
- **Example.** `examples/futures/es_sma_cross.yaml`, with an opt-in real-data test.
- **Docs.** `tools.docgen` now documents `pl.Decimal(p, s)` columns.

### Fathom C3b-2: futures brackets per lot and the futures signal bridge (ADR-0093, ADR-0094)
- **Brackets per lot.** `simulate_futures` keeps a stop and a target in ticks per lot, measured
  from each lot's own fill:
  - an add opens a lot and a reduction closes lots FIFO;
  - a flip anchors one new lot, and a roll shifts each lot's levels by the executed spread;
  - if any lot's stop is touched in a bar, only stops fill in that bar;
  - after a partial bracket exit, `require_signal_reset` does not buy the stopped lots back.

  The simulator is now version `2`, and runs with one lot per position are unchanged.
- **Off-schedule bars.** An optional `on_schedule` column in the bars makes off-schedule bars
  ineligible for fills and bracket exits.
- **Ticks are whole.** `stop_ticks`, `target_ticks` and `target_fill_through_ticks` must be plain
  integers.
- **Futures signal bridge.** `crucible.experiments.futures_signals.futures_targets`:
  - turns a strategy spec or a Python `FuturesSignalFunction` (signed contracts) into contract
    targets;
  - signals on the ratio-adjusted series by default, with `signal_input="unadjusted"` as the
    explicit option;
  - checks that the execution and signal datasets have the right price bases, and that they are
    aligned exactly on `event_time` and `contract`;
  - enforces scale invariance: statically for specs, by declaration for functions, and
    empirically for both with prices x16 and x1/16;
  - refuses percentage stops and targets, `max_holding_bars`, explicit sizing or `stop_fill`,
    `time` conditions and the spec `session` block;
  - applies the CME session rules (`FuturesSessionPolicy`), refusing a missing final bar under
    `flat_by_close` and unverified sessions;
  - returns a provenance record with both dataset ids, hashes and price bases, and the calendar
    version.
- **New spec functions.** `crucible.strategy_spec.scale` (`scale_violations`,
  `assert_scale_invariant`) and `compile.spec_positions`.

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
