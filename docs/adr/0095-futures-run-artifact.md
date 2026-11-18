# ADR-0095: The futures run: its own config, a daily ledger by trade date, intraday marks, a sealed artifact

Status: accepted (2026-11-17). The owner set the requirements (milestone C3b, refinement D):
- an independent futures-run config;
- a C1 sealed artifact with every futures file in the digest and the manifest;
- a daily ledger keyed by trade date;
- timestamped equity marks and position/fill events for C7, with balance kept distinct from
  equity and OHLC marks stated as an approximation;
- mandatory trial-family registration;
- no Sharpe or edge claims;
- the CLI canonical and the MCP a thin wrapper (ADR-0066).

## Context

C3b-1 and C3b-2 built the pieces:
- the session calendar (ADR-0091) and trade dates (ADR-0092);
- per-lot brackets (ADR-0093);
- the signal bridge (ADR-0094);
- the simulator (ADR-0090).

The event-driven `ExperimentConfig` cannot describe a futures run. It has no root, no pair of
continuous datasets, no contract count, no tick brackets and no CME session policy. Its runner also
writes equity-curve metrics (Sharpe, DSR) that the owner ruled out for C3b. The prop-firm rules of
C7 need two things:
- the equity path inside each session, because trailing drawdowns are measured intraday;
- the per-trade-date balance, because daily loss limits are measured on the trade date, not the
  calendar day.

## Decision

1. **A separate config kind, `kind: futures_run`** (`crucible.experiments.futures_config`). It is
   frozen, refuses unknown keys, and its fields map one to one onto the existing dataclasses:
   - root, the four datasets (execution, signal, rolls, raw) and the window in Globex trade dates;
   - the strategy (a spec, inline or by path, or a `FuturesSignalFunction` entrypoint), the
     contract count and the capital;
   - costs (`CostSchedule`), execution (`ExecutionPolicy`), signal input (ADR-0094) and session
     (`FuturesSessionPolicy`);
   - `run.family`, which is required.

   A spec given by path is loaded, and its content (not its path) is part of the config hash.
2. **`run_futures`** reads the datasets with their manifests and selects the window by trade date
   (the same rows for the execution and the signal series). It then calls `futures_targets` and
   `simulate_futures`, builds the outputs, checks the daily ledger, registers the trial and seals.
3. **Outputs.** Every result file is in the C1 digest: `config.yaml`, `metrics.json` and Parquet.
   - **`marks.parquet`**, one row per bar:
     - the position at the close;
     - `balance_usd` (cash: capital plus realized minus costs) and `equity_usd` (balance plus
       unrealized at the close), kept as separate columns;
     - `equity_low_usd` and `equity_high_usd`, an OHLC approximation of the intrabar extremes;
     - the bar's realized and costs flows, and `on_schedule`.
   - **`daily.parquet`**, one row per trade date:
     - the scheduled session open and close, and whether the session is verified;
     - the opening and closing balance and equity;
     - realized P&L, costs by kind, and the unrealized P&L at the close;
     - the minimum and maximum equity over the marks, the maximum contracts held, and the fill
       count.
   - **`fills.parquet`**: every fill, with its trade date and the position after it. These are the
     position events.
   - **`rolls.parquet`**: every roll.
   - **`metrics.json`**: descriptive totals only. These are final balance and equity, net P&L,
     costs, counts, minimum equity and the maximum intraday drawdown on the conservative marks. It
     has no Sharpe, no return ratio and no edge statistic.
4. **Marking policy.**
   - **The close mark is exact:** it is the simulator's.
   - **The extremes are estimated.** Each bar's low and high equity are taken from its OHLC, for
     two positions:
     - the position at the close, against the close;
     - the position carried in from the previous bar, against the previous close, when the
       contract did not change.
   - **The estimate is an approximation, and stated as one.** The path inside a bar is unknown. The
     low is deeper than reality when a stop filled inside the bar, which is the conservative
     direction for a drawdown rule.
   - **Where it is recorded:** the policy text is written into the manifest and listed under
     `approximations`.
5. **The daily ledger is checked before anything is written.**
   - The identities are:
     - closing balance = opening + realized − costs;
     - closing equity = closing balance + unrealized;
     - each day opens where the previous one closed;
     - the minimum ≤ the close ≤ the maximum;
     - the last close equals the last mark;
     - the summed (realized − costs) equals the final balance minus the capital.
   - A violation raises `InvariantViolation` naming the trade date.
6. **Identity and sealing.**
   - `run_id = FUT-<16 hex>` is a hash of the config hash, the four datasets' content hashes, the
     session table's SHA-256, the spec table's SHA-256 and the simulator version.
   - The manifest records:
     - `kind`, the family, the datasets as `DatasetRef`s and the bridge's signal record;
     - the execution policy, `strict_execution` and the calendar summary;
     - the marking policy and the approximations;
     - the files, and the bar and trade-date counts.
   - `seal_artifact` (ADR-0084) gives `artifact_id`, so `crucible artifact verify` works unchanged.
7. **Trial registration is mandatory.** Every run is recorded in
   `<artifacts>/trial_registry.duckdb`:
   - under its family, with mode `futures`, its time span and no Sharpe;
   - a rerun of the same run is not counted twice.

   The count goes in the manifest's volatile `trial_count`.
8. **The CLI is canonical:** `crucible futures run --config F --store S --artifacts A`, plus
   `crucible schema --kind futures-run`. The MCP tool `crucible_futures_run` only builds that
   command line (ADR-0066).

## Alternatives considered

- **Extend `ExperimentConfig` with a futures section.** Its required fields (data universe, event
  strategy, risk engine) and its Sharpe/DSR reporting do not apply, and every existing experiment
  id would change (COMPATIBILITY §2). Rejected.
- **Compute the daily ledger by calendar day or by UTC date.** CME daily limits and settlement are
  per trade date, and a calendar day splits the evening session from its trade date. Rejected.
- **Marks only at the close.** A trailing drawdown breached inside a bar and recovered by its close
  would not be seen. The OHLC estimate is the best these bars allow, and it is labelled.
- **Write a JSON ledger.** The C1 digest covers only `config.yaml`, `metrics.json` and Parquet, so
  JSON results would not be sealed. Rejected.

## Consequences

- **C7 can read the futures path directly.** The prop-firm rules work from `marks.parquet` (the
  intraday path) and `daily.parquet` (per-trade-date limits), and know which numbers are
  approximations.
- **Futures runs join the trial counts.** Each run is counted in its family, so the multiple-testing
  statistics of C6 can include them.
- **An account that goes to zero keeps trading.** The run does not stop or flag an account whose
  equity reaches zero or below: the example `examples/futures/es_sma_cross.yaml` ends at −$9,677 on
  $50,000 after 2,726 fills, and the daily ledger and `min_equity_usd` show it. Ruin, margin and
  prop-firm stops are C7; until then a reader must check the minimum equity.
- **`crucible artifact show` does not render a futures run yet.** It expects the experiment
  document. `verify` works; a futures document builder is a follow-up.
