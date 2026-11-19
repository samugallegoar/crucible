# ADR-0103: Futures statistics — daily returns on fixed capital, Sharpe, PSR, DSR with total trials, bootstrap intervals and IC

- **Status**: accepted
- **Date**: 2026-11-19

## Context

C6 is the first stage allowed to put inferential statistics on futures results: Sharpe, IC,
confidence intervals, PSR, DSR and PBO. ADR-0095, ADR-0097 and ADR-0100 to ADR-0102 kept those
results descriptive until now.

The owner approved C6 in three stages:
- C6a, statistics (this ADR);
- C6b, effective trials and PBO (ADR-0104);
- C6c, the holdout vault (ADR-0105).

The owner's binding decisions for C6a:
- returns are daily marked P&L over **fixed initial capital**;
- PSR and DSR use the per-period Sharpe;
- annualization is for presentation only;
- trials count **distinct candidates**;
- there is **no edge verdict before C7**.

## Decision

1. **Daily return.**
   - For each trade date: `daily_return_t = (closing_equity_t − closing_equity_{t−1}) /
     initial_capital`, where `closing_equity_{t−1}` is the previous trade date's closing equity and
     is `initial_capital` on the first date. Closing equity is balance plus unrealized, after every
     cost. The change therefore contains realized P&L, the change in unrealized P&L and all costs,
     exactly once.
   - A walk-forward's OOS series uses the concatenated chain of ADR-0101 over the same base
     `initial_capital`, terminal exit costs included.
   - A trade date with on-schedule bars and no position is a **zero-return observation**.
   - A trade date with no valid bars is **missing**, never zero. It is excluded, and counted as
     `missing_sessions` against the session calendar.
   - One function (`crucible.experiments.futures_stats.daily_returns`) computes the returns for
     standalone runs, batch candidates, walk-forward OOS and comparisons.
2. **Sharpe.**
   - PSR and DSR use the **per-period** Sharpe: the mean of the daily returns over their standard
     deviation, ddof=1 (`crucible.core.stats.per_period_sharpe`).
   - An annualized Sharpe (`× √252`) is reported **for presentation only**. The manifest records
     `annualization: {periods_per_year: 252, convention: "sqrt"}`.
3. **PSR and DSR.**
   - PSR is the probability that the true per-period Sharpe exceeds 0, with the skew and kurtosis
     correction (ADR-0015).
   - DSR deflates it with the expected maximum Sharpe of `total_trials` trials. The variance of
     the trial Sharpes comes from the family's distinct candidates.
   - Each candidate's Sharpe is taken from its run with the most daily observations; a tie goes to
     the earliest recorded.
   - With fewer than 2 candidate Sharpes, DSR is null with a reason. It is never computed from an
     invented variance.
4. **Trials** (registry columns are additive).
   - A **candidate id** (`CND-<16 hex>`) hashes:
     - the canonical structure id and the parameterization id (for a Python or spec strategy, its
       canonical strategy dump);
     - the datasets and root;
     - the execution and costs sections;
     - the fidelity;
     - the session and signal sections.

     It excludes the window, the warm-up, the run name and the family, so one candidate evaluated
     on several windows is one candidate.
   - The size (`contracts`) is part of the candidate. `initial_capital` and the `statistics`
     section are not: capital is the denominator of the returns, not part of the strategy.
   - The fidelity enters as its effective level, so a preset and the equivalent explicit fields
     are one candidate.
   - `candidate_id` is computed in `futures_config.py`, because it is a pure function of the
     config.
   - A futures trial's `period_ns` is now one trade date, because the recorded Sharpe is daily.
   - A walk-forward's OOS block names no single candidate. It therefore has no candidate id, and
     its IC is null with a reason.
   - Each run records its candidate id in `trials`, and each submission records it in
     `submissions`. Per family the registry reports:
     - `submission_count`, every submission event (a standalone run counts as one);
     - `unique_candidate_count`, the distinct candidate ids;
     - `total_trials`.

     `total_trials` equals `unique_candidate_count` in C6a. It is kept as its own field because
     C6b and C6c may add to it.
   - A duplicate is recorded and never counted twice.
   - Every training evaluation and fold stays in `trials` and `submissions`.
5. **Confidence intervals.**
   - A seeded circular block bootstrap gives the per-period Sharpe, the annualized Sharpe, the mean
     daily return and the mean IC a percentile interval.
   - The manifest records `bootstrap: {rng: "numpy.random.PCG64", seed, block_length_policy:
     "ceil(sqrt(n))", block_length, resamples: 1000, confidence: 0.95}`.
   - The seed is a pure function of the artifact's identity and the statistic's name
     (`int(sha256(artifact_id_basis + name)[:16], 16)`), never of a global sequence. Results are
     therefore identical whatever order or parallelism the runs execute in.
6. **Information coefficient** (single-root, time-series).
   - For each trade date, IC is the Spearman correlation between the expression score at each
     decision bar and the forward return over `h` bars (`statistics.ic_horizon_bars`, default 1).
   - The forward return is close to close on the signal series, and both bars must be in the same
     session and on the same contract. A pair that crosses a session edge or a roll is dropped,
     never filled.
   - A trade date with fewer than 10 valid pairs gives no IC.
   - The report gives mean IC with its interval, the number of IC days, and IC per calendar month.
   - IC applies only to DSL expressions; Python and spec strategies get null with a reason.
7. **Where the statistics appear.** The futures document, `batch.json` (per candidate),
   `walkforward.json` (on the OOS series only, deflated by the family's `total_trials`) and
   `cross_run.json` (per member).
   - A metric with an interval carries `assessment: "inferential"`, with its `ci_low` and `ci_high`
     filled. Purely descriptive metrics keep `assessment: "descriptive"` and null intervals.
   - In-sample training statistics stay under `in_sample_audit` and are marked so.
8. **Verdict.** `verdict_level` stays null. `verdict_reason.code` becomes `robustness_not_assessed`
   for every futures output. No document states an edge before C7.

## Alternatives considered

- **Returns on the previous day's equity.** That compounds, and it makes a run's returns depend on
  its own past P&L. The owner ruled it out.
- **Zero-filling missing sessions.** It invents observations. Rejected.
- **A global RNG, or a seed sequence shared across runs.** Results would depend on execution order.
  Rejected.
- **Counting every submission as a trial.** The owner ruled it out. Submissions are counted
  separately.
- **Cross-sectional IC.** A futures run trades one root (ADR-0099). Cross-sectional IC waits for a
  multi-root run.

## Consequences

- **Futures outputs gain inferential numbers but no verdict.** Fathom reads PSR, DSR and intervals
  while the edge decision remains with C7.
- **The candidate id is a new identity.** It joins the registry additively; existing rows have a
  null candidate id and count by experiment id as before.
- **New fields again rename futures run ids.** C6a adds a `statistics` config section, and the
  config hash dumps defaults (`docs/COMPATIBILITY.md` §2), so every futures run id changes. Results
  do not change.
