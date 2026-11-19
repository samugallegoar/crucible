# ADR-0100: Futures fidelity levels (causal session-bounded resampling, cost detail) and batch evaluation

- **Status**: accepted
- **Date**: 2026-11-18

## Context

C5 (PRD §13) asks for three things: fidelity levels as configuration, batch evaluation of N
expressions per call, walk-forward, and cross-run metrics. The owner approved C5 in three stages,
each with its own ADR, PR and acceptance tests:
- C5a: fidelity and batches (this ADR);
- C5b: walk-forward;
- C5c: cross-run metrics.

The owner kept the statistical boundary of ADR-0095 and ADR-0097. The PRD's C5 list includes
Sharpe and rolling IC, and **C5 does not follow the PRD there**. C5 introduces no Sharpe, IC, PSR,
DSR, p-values, confidence intervals or statistical edge claims. C6 is the first stage allowed to
introduce any of them.

For C5a the owner required:
- 5m and 15m bars resampled causally from 1m, never across a maintenance break or a session
  boundary;
- every submitted trial preserved in the registry, even when a duplicate computation is cached or
  skipped.

## Decision

1. **Resampling** (`crucible.data.resample.resample_session_bars`).
   - **Which bars.** Each 1m bar is assigned to its CME trade-date session (ADR-0091/0092).
     Off-schedule bars are not aggregated; they are counted.
   - **Buckets.** Within a session a bucket collects the bar ends in `(k·m, (k+1)·m]` minutes, clipped
     to the session, so no bucket crosses the maintenance break or a session edge. A session edge
     that is not on an m-minute boundary gives a shorter bucket, flagged `partial`.
   - **Labels and values.** A bucket is labelled by its end, never later than the scheduled close.
     It takes the first open, the maximum high, the minimum low, the last close and the summed
     volume. An empty bucket produces no bar.
   - **Availability.** `available_at = max(label, constituents' available_at)`.
   - **Refusals.** A bucket that mixes contracts is refused.
   - **Alignment.** The execution and signal series are resampled with the same buckets.
2. **Fidelity** (`fidelity` in the futures-run config, `FIDELITY_TABLE_VERSION = "1"`).
   - `resolution` is `1m`, `5m` or `15m`.
   - `cost_detail` is `full` or `commission_only`. `commission_only` zeroes spread and slippage,
     and is recorded as an optimistic approximation.
   - The presets are:
     - `screen`: 15m and `commission_only`;
     - `standard`: 5m and `full`;
     - `full`: 1m and `full`.

     A preset that contradicts an explicit field is refused.
   - Roll legs keep the raw 1m prices. A causal roll at a coarse resolution executes at the open of
     the first simulated bar that starts at or after both the decision and the first 1m print in
     which both contracts trade, and in which both contracts have a 1m bar opening at that instant.
     Both legs are priced at those 1m opens. This is never earlier than the 1m rule (ADR-0090), and
     at 1m it is that rule exactly, so 1m results do not change. At a coarse resolution the roll can
     be delayed by up to one coarse bar, recorded as an approximation. Executing at the open of the
     bar that *contains* the first joint print was rejected: it would price the roll before both
     contracts had traded together.
     The execution policy records the grid as `roll_execution_grid_seconds` and
     `roll_execution_grid`, next to the unchanged `roll_execution` string. At 1m, if the first joint
     minute is missing from the simulated series, the roll moves to the next bar open where both
     contracts trade; strict mode no longer refuses it. This keeps the rule "never earlier, priced
     at a joint print".
   - A coarse run refuses a partial (session-clipped) bucket rather than simulate on a grid the
     session rules do not share. No such bucket occurs on the current session table: early closes
     fall on 15-minute boundaries.
   - `commission_only` refuses an explicitly non-zero `spread_ticks` or `slippage_ticks`. It never
     silently overrides a value the user wrote.
   - The fidelity is part of the config hash, and so of the run id. It is written into the manifest
     and the futures document. The hash dumps defaults (`docs/COMPATIBILITY.md` §2), so adding the
     field renames every existing futures run id, even at 1m, while the 1m results stay
     byte-identical.
   - Runs at different resolutions should use different families. Marks at 15m and at 1m are not
     comparable observations (ADR-0071), so the screen example has its own family.
3. **Batch** (`crucible futures batch`).
   - A batch file names a base futures-run config and an ordered list of candidates, each an
     expression with parameter bindings. Only the strategy and the run name change per candidate,
     so every candidate is compared under the same conditions: contracts, costs, execution,
     fidelity, session, window and family.
   - `batch_id = BAT-<16 hex>`.
   - A candidate that has the same parameterization as an earlier one, or whose sealed run already
     exists, is `cached`: computed once, never recomputed.
   - `batch.json` lists the candidates **in submission order, never sorted by a metric**. Each has
     descriptive dollar metrics with null intervals, and the batch verdict is `not_assessed`.
4. **Submissions are recorded.**
   - The trial registry gains an additive `submissions` table, keyed by (batch_id, position). Every
     submitted candidate goes into it, with its experiment id, structure id, parameterization id
     and status.
   - The `trials` table is unchanged: one row per distinct run.
   - How submissions count toward `total_trials` is decided in C6, not here.

## Alternatives considered

- **Clock-aligned buckets across the break.** A bucket that crosses 16:00–17:00 CT would merge two
  trade dates. The owner ruled it out.
- **Forward-filling empty buckets.** It would invent bars. Rejected.
- **Counting each cached duplicate as a new trial in `trials`.** That changes the trial counts that
  C6 builds on before C6 decides the rule. Rejected in favour of a separate, complete record of
  submissions.
- **Ranking candidates by net P&L in the batch output.** A ranking is a selection claim. Rejected;
  the order of submission is kept.

## Consequences

- **The research loop can screen cheaply and confirm at full fidelity.** It screens many
  expressions at 15m with commission-only costs, then confirms the survivors at 1m with full costs.
  Every screen run states its optimistic approximation.
- **C6 has a complete trial history.** The submissions table records everything that was tried, so
  C6 can count total and effective trials.
