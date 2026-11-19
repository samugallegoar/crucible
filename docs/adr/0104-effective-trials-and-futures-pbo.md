# ADR-0104: Effective trials by correlation clustering, supplementary DSR, and PBO on valid futures candidate panels

- **Status**: accepted
- **Date**: 2026-11-19

## Context

C6a (ADR-0103) deflates every futures Sharpe by the family's `total_trials`, its count of distinct
candidates. Correlated candidates overstate the number of independent trials: two variants that
differ only in a window length are not two independent hypotheses.

C6b adds an estimate of the effective number of trials and the probability of backtest overfitting
(PBO, by CSCV, ADR-0015/0070) for futures candidate sets. The owner required:

- **DSR(total_trials) stays the primary, conservative result.**
- **DSR(effective_trials) is supplementary, never a replacement.**
- **The effective count is a threshold-dependent estimator.** It is not an exact number of
  independent hypotheses. Its method, threshold and overlap requirements must be recorded, with a
  threshold sensitivity.
- **Insufficient overlap means the estimate is unavailable.** A value is never invented.
- **PBO needs a valid, comparable candidate-return panel.** It is never computed from one selected
  walk-forward OOS path.

## Decision

1. **Series.**
   - Each candidate of a family is represented by its daily returns (ADR-0103 decision 1), from its
     representative run: the run with the most daily observations, a tie going to the earliest
     recorded, as in `candidate_sharpes`.
   - A candidate whose representative artifact is missing or fails verification makes the estimate
     `unavailable`. The reason names the candidate.
2. **Pairwise correlation** follows the rules of ADR-0102:
   - only on the intersection of trade dates, with nothing filled;
   - only between members with equal comparison keys;
   - with at least `min_overlap_trade_dates` dates (default 20, never below 10);
   - not for a constant series.

   **If any pair lacks a valid correlation, the effective count is `unavailable`.** The report
   lists the pairs and their statuses. A missing correlation is never replaced by 0 or 1.
3. **Estimator** (`crucible.validation.effective_trials`, implemented from its formula; scipy stays
   forbidden, `docs/DEPENDENCIES.md`).
   - The distance is `d = sqrt((1 − ρ)/2)`.
   - Clustering is agglomerative with **average linkage**. At each step it merges the pair of
     clusters with the smallest mean inter-cluster distance. A tie goes to the lexicographically
     smallest pair of sorted member ids, so the result is deterministic.
   - It stops when the smallest distance exceeds the threshold. `effective_trials` is then the
     number of clusters.
   - The default threshold is `ρ* = 0.5`, so candidates whose average correlation is at least 0.5
     merge.
   - The report always includes a **sensitivity table** for ρ* ∈ {0.3, 0.5, 0.7, 0.9}, giving the
     cluster count and the cluster membership at each threshold.
   - The report records the method, linkage, distance formula, threshold, minimum overlap and
     comparison-key rule, and the candidate ids.
   - It is labelled an estimate: `assessment: "estimator"`, with the note "threshold-dependent; not
     a count of independent hypotheses".
   - `1 ≤ effective_trials ≤ total_trials` always.
4. **Supplementary DSR.**
   - `dsr_effective_trials` uses the same per-period Sharpe and the same variance of the candidate
     Sharpes as the primary DSR. Only N is replaced by `effective_trials`.
   - It appears next to the primary `dsr`, which is unchanged, under a `supplementary` key. It
     records its threshold, and it is null with the estimator's reason when the estimate is
     unavailable.
   - It never feeds a verdict, which stays `robustness_not_assessed` until C7.
5. **Where it appears.**
   - `crucible futures trials --family F [--threshold ρ] [--min-overlap N]` (with the MCP tool
     `crucible_futures_trials` and `schema --kind futures-trials`) writes `trials.json` under
     `artifacts_root/EFT-<16 hex>/`. It holds the counts (`submission_count`,
     `unique_candidate_count`, `total_trials`), the estimator, the sensitivity table and each
     candidate's Sharpe. The id hashes the family's sorted candidate ids, their representative run
     ids and the options.
   - The futures run document, `batch.json` and `walkforward.json` (OOS) carry
     `dsr_effective_trials` as the supplementary estimate, computed when they are written from the
     family's candidates at that moment. The candidate set used is recorded.
6. **PBO on a valid panel** (`probability_of_backtest_overfitting`, CSCV).
   - **Batch.** The panel is the candidates' daily returns on the batch window. Every distinct
     computed candidate shares the base config, so the dates should match.
     - The panel requires an **identical set of trade dates** across candidates. Otherwise the
       batch is not a valid panel and PBO is `unavailable`, with the differing dates. Nothing is
       filled.
     - Cached duplicates enter once.
     - `pbo.n_groups` (an even number, default 8) sets the CSCV groups. Fewer than 2 candidates, or
       fewer than `n_groups` observations, makes PBO `unavailable`.
   - **Walk-forward.** PBO is computed on a **separate full-window panel**: each distinct candidate
     runs once on the walk-forward's base window, with the same base config and warm-up. These runs
     are recorded as trials of the same candidates, so `total_trials` does not grow. They are
     reported under `in_sample_audit.pbo_panel`, marked `in_sample: true`.
     - **The selected OOS path is never a PBO input.**
     - The panel follows the same identical-dates rule.
   - **A panel run is a trial, not a submission.** It is recorded in `trials` with
     `mode = 'pbo_panel'`.
     - It evaluates a candidate the family already holds, submitted by no one and selected by no
       fold. `submission_count` therefore leaves it out, and `unique_candidate_count` and
       `total_trials` do not change.
     - It stays fully auditable.
     - The contamination check reads only `mode = 'optimization'`, so the new mode does not
       affect it.
   - `n_groups` must be even and at least 4: the CSCV splitter needs at least 3 groups, with
     `n_test_groups = n_groups / 2`.
   - In `batch.json`, the supplementary DSR sits beside each candidate's primary `dsr`. The `pbo`
     block appears only when it is requested.
   - The output records `{value, n_groups, n_combinations, n_candidates, n_observations,
     assessment: "inferential", method: "CSCV", tie_rule}` and a reason whenever PBO is null.

7. **A sealed `commission_only` config now reloads.** This fixes a C5a bug that C6b exposed.
   - `canonical_futures_yaml` dumped the unset `costs.spread_ticks` and `costs.slippage_ticks`, so
     reloading a sealed screen-fidelity `config.yaml` refused its own file. Every such run then
     showed as `unverified` in comparisons and in the estimator.
   - The dump now omits those fields when they are unset under `commission_only`.
   - The validator is unchanged: an explicit non-zero tick is still refused.
   - The config hash and the run ids do not change, because they are computed from the model.
   - A sealed config that fails to reload is reported as `config_reload_failed: <error>`, never as
     a bare `unverified`.

## Alternatives considered

- **Treating a pair with insufficient overlap as uncorrelated** (ρ = 0, adding clusters). It is
  conservative for DSR, but it invents a value. The owner ruled it out.
- **Effective trials from the eigenvalues of the correlation matrix.** These need a complete matrix
  (the same rule applies), and they give a non-integer N whose threshold choice is less transparent.
  Deferred; average linkage with a sensitivity table was chosen.
- **PBO on the walk-forward's training runs.** Their windows differ across folds, so they do not form
  a panel. Rejected.
- **Replacing DSR with DSR(effective_trials).** The owner ruled it out.

## Consequences

- **The DSR now comes in two readings.** The conservative, primary reading uses all distinct
  candidates. The supplementary one shows how much the deflation depends on the candidates'
  correlation, and that dependence is visible in the threshold sensitivity table.
- **The full-window PBO panel costs one extra run per candidate.** That cost buys a valid panel.
