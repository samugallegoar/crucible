# ADR-0061: Vectorized position episodes and trial-counted parallel sweeps

- **Status**: accepted
- **Date**: 2026-10-04

## Context

Two things about the vectorized path misled or blocked a researcher. A vectorized run passed an
empty trade log to `compute_metrics`, so every run reported `n_trades = 0` with no `hit_rate`, which
reads as "never traded". And a vectorized run recorded no trial and no DSR (`trial_count` and `dsr`
were `null`), while the engine exists to make parameter sweeps cheap: a 500-config sweep would
report its best Sharpe with no deflation, against AGENTS.md section 9. There was also no parallel
runner for it, and `crucible optimize` only drove the event-driven engine. Design note:
`docs/features/vectorized-episodes-and-sweeps.md`.

## Decision

1. **Position episodes.** `analytics.trades.build_episodes` derives the vectorized run's "trades"
   from its lagged weights: per symbol, a maximal run of bars with the same nonzero sign; a flip
   closes one episode and opens the next at the same bar; changes of size inside a run do not split
   it. `entry_ts` is the close of the bar before the first held bar (its own ts if there is none),
   `exit_ts` the close of the last held bar. Only **closed** episodes are listed (an episode still
   held at the last bar has no exit, as the event-driven log only counts closed round trips).
   `pnl` is the sum over the held bars of the prior equity times weight times return, **before
   costs**. The log is `trades.parquet` (`EPISODE_SCHEMA`, `docs/SCHEMAS.md` section 2.5a), and
   `n_trades` and `hit_rate` count episodes.
2. **Vectorized runs are trials.** `run_vectorized_experiment` records the run in the shared
   registry (`<artifacts_root>/trial_registry.duckdb`) under `experiment.family`, with the same
   rules as `_finalize_experiment` (the trial's own per-period Sharpe is recorded before the family's
   Sharpes are read; a repeat of the same config is ignored by the registry; `record_trial=False`
   reports the current count), and fills `trial_count`, `dsr` or `dsr_error`, and the contamination
   fields. `pbo` and `monte_carlo` stay null for a single vectorized run.
3. **Parallel runner.** `run_vectorized_experiment_parallel` follows ADR-0038: every config is
   checked first (a refusal leaves no artifact and no trial), the simulations run in a spawn pool,
   and trials are recorded and artifacts written serially in the parent in `configs` order, so the
   output equals a sequential loop byte for byte.
4. **`optimize --vectorized`.** `optimize_1d(..., engine="vectorized")` and the CLI flag run every
   point on the vectorized engine; PBO and the best point's DSR are computed from the runs'
   `equity.parquet` and the shared registry as for the event-driven sweep. The engine choice is a
   call argument, not a config field, so config hashes do not change.
5. **A promoted strategy is counted twice, and that is a known over-count.** Promoting a vectorized
   config to the event-driven engine (ADR-0037) keeps its `experiment.family`, and the promoted run
   already recorded a trial through `run_experiment` before this ADR. With this ADR the vectorized
   run is recorded too, so one idea evaluated at two realism levels is two trials. ADR-0014's
   reasoning points the other way (it does not count a re-run of the same parameter evaluation, nor
   scenario fan-out under other execution assumptions), so this is not justified by it: it is a
   consequence of two runs having different experiment ids. It over-counts, which only deflates DSR
   more, never less. Exempting promoted runs (`record_trial=False`) would change promotion and is
   left to the owner (an open question in the project notes).

## Alternatives considered

- **Attributing turnover costs to episodes.** The cost model is a per-bar turnover rate, not per
  fill; attributing it to an episode would invent a rule. Episode pnl is gross and the equity curve
  stays net.
- **Leaving vectorized runs unrecorded.** Cheap, but lets a large sweep report an undeflated Sharpe.
- **An `engine:` config field.** Would change every config hash (`docs/COMPATIBILITY.md` section 2).
- **Matching the event-driven lot-level `n_trades`.** Not possible without simulating fills and lots;
  see the finding below.

## Consequences

- **`n_trades` is not comparable across the two engines.** The event-driven trade log is FIFO per
  lot, and a strategy that scales in closes one position as several lot round trips: TrendFollower
  resizes to 100% of equity at every rebalance, so the trend demo has 307 fills and 257 lot round
  trips for 50 positions. The comparable quantity is the flat-to-flat position: on the trend demo the
  vectorized run has 50 episodes, the event-driven fills have 50 positions, and both hit rates are
  0.5 (`tests/integration/test_vectorized_episodes_agreement.py` derives the event-driven positions
  from `fills.parquet`, independently of `build_episodes`). The design note had expected the two
  `n_trades` to be equal; that was wrong and is corrected here.
- Re-running an old vectorized config now records a trial in its family, so the DSR of other runs in
  that family is computed against a larger set; a promoted strategy is counted at both realism levels
  (decision 5).
- A vectorized run whose equity is not finite (a NaN score, for example) is refused before anything is
  written or recorded, and nothing is created for a run that is refused: the output directory is
  created when the artifacts are written, not before the engine runs. The vectorized engine itself
  still accepts NaN scores silently (it was not changed); the runner refuses the result.
- The vectorized manifest keeps the same keys (no `schema_version` bump) but their values are filled;
  `trades.parquet` exists for a vectorized run.
- Deferred: FX and futures in the vectorized engine (Batch F, F3 and F4), Monte Carlo and a PBO for a
  single run, an episode-level cost attribution.
