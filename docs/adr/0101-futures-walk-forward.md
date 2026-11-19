# ADR-0101: Futures walk-forward with constrained in-sample selection and concatenated out-of-sample evaluation

- **Status**: accepted
- **Date**: 2026-11-18

## Context

C5b is the second of the three C5 stages (ADR-0100). The owner's requirements:

- The selection objective is net P&L, and it is used only inside each training window.
- Risk constraints are explicit, so that a candidate cannot win by taking excessive exposure.
- Sizing, costs, fidelity and execution conditions are identical across candidates.
- The selected candidate is evaluated only on the test window that follows its training window, and
  the out-of-sample (OOS) results are concatenated.
- The training results are kept for audit and are never presented as OOS.

The statistical boundary of ADR-0095, ADR-0097 and ADR-0100 is unchanged. C5b reports no Sharpe,
IC, PSR, DSR, p-values, confidence intervals or statistical edge claims, and its verdict is
`not_assessed`. C6 is the first stage that may introduce them.

Two properties of the futures run (ADR-0095) matter here:

- **The signal is computed from the window's bars only.** A test window would therefore begin with
  the expression's warm-up, flat. A long window parameter loses days of every fold.
- **An open position at a run's last bar is marked to that bar's close with no exit cost.** Chaining
  folds that each start flat would therefore close every fold-end position for free, which is
  optimistic.

## Decision

1. **Signal warm-up** (`window.warmup_trade_dates`, integer, default 0).
   - The futures run may read the given number of Globex trade dates *before* `window.start`, and
     uses them only to compute the signal. Those bars produce no fill, no mark and no ledger row,
     and they hold no position.
   - The target on the first window bar is computed from data up to and including that bar, as
     always. Warm-up is past data, so it introduces no lookahead.
   - A run whose warm-up does not cover the expression's `min_window` on the first window bar is
     refused.
   - The sufficiency check applies only when N > 0. Python and spec strategies, which declare no
     warm-up in bars, use the explicit N unchecked.
   - The manifest records the warm-up in its own `warmup` block; `window` keeps only `start` and
     `end`.
   - With 0 the run is exactly the current one, so results do not change. The field joins the
     config hash, and so the run id (`docs/COMPATIBILITY.md` §2).
2. **Folds over trade dates.**
   - The walk-forward config gives a base futures-run config, a candidate list (the batch format of
     ADR-0100), `train_trade_dates` (N), `test_trade_dates` (M), `scheme` (`rolling` or
     `anchored`) and `warmup_trade_dates`.
   - The trade dates are the base window's Globex trade dates that have on-schedule bars in the
     execution dataset.
   - Fold k tests on trade dates `[N + k·M, N + (k+1)·M)`. Its training window is the N dates
     before that (`rolling`), or every date from the first one (`anchored`).
   - The test windows are contiguous and never overlap. A trailing remainder shorter than M is not
     evaluated, and is reported as `unused_trade_dates`.
   - Fewer than one complete fold is refused.
3. **Selection, inside the training window only.**
   - Every candidate runs on the fold's training window under the base config. Only the strategy
     and the run name change (the batch rule of ADR-0100).
   - A candidate is **eligible** only if its training run satisfies every risk constraint:
     - `max_intraday_drawdown_usd` (required);
     - `min_equity_usd` (optional floor on the lowest intraday equity);
     - `max_fills` (optional cap on fills in the training window);
     - `max_time_in_market` (optional cap on the fraction of window bars holding a position).
   - The selected candidate is the eligible one with the largest training net P&L. A tie goes to
     the earliest submission position.
   - When no candidate is eligible, the fold has no selection. It is evaluated flat: zero P&L and
     zero costs, with status `no_eligible_candidate`. Being flat is a decision, not a missing
     observation.
4. **Out-of-sample evaluation.**
   - The selected candidate runs on the fold's test window only, with the same warm-up rule.
   - **Terminal exit at the end of each test window.** If a position is open at the test window's
     last bar, the fold is charged an exit: the open contracts times one side of the full cost
     (commission, fees, spread and slippage ticks), as `terminal_exit_cost_usd`. Each fold
     therefore starts and ends flat at a known cost.
   - The exit cost follows the simulator's own formula: the fees per side, plus half the spread,
     plus the slippage, in ticks, times the tick value. It uses the run's effective costs, so a
     `commission_only` run pays fees only.
   - A fold's OOS P&L is the test run's *marked* P&L (final equity minus capital) minus the
     terminal exit cost. Realized P&L alone would leave the open mark outside the equity chain.
   - The OOS series concatenates the test windows' daily ledgers in date order. Fold k's equity
     starts at the base `initial_capital` plus the net P&L of folds 0 to k−1, after their terminal
     exit costs.
5. **Outputs** (`WFA-<16 hex>`, a hash of the walk-forward config and the base config).
   - **`walkforward.json`** (`schema_version` 1). It has:
     - `folds`, giving each fold's dates, selection, `selection_reason` and OOS run;
     - `oos`, the summary computed from the OOS series only: net P&L, costs, fills, maximum
       drawdown on the concatenated daily closing equity, trade dates and folds with a selection;
     - `window_stability`, each fold's OOS net P&L, listed;
     - `in_sample_audit`, every training run's metrics, constraint checks and violations, keyed
       separately and each marked `in_sample: true`;
     - `verdict`, which is `not_assessed`.
   - **`oos_daily.parquet`**, the concatenated OOS series.
   - Every metric keeps `assessment: "descriptive"` and null intervals.
   - The training metrics never appear under `oos`.
6. **Trials.** Every training and OOS run is a sealed futures run registered with `record_trial`. Each
   fold's training candidates are recorded in `submissions`, with the walk-forward id as the batch
   id and position `fold·K + candidate`. How those count toward `total_trials` is decided in C6.

## Alternatives considered

- **Warm-up inside the test window (no `warmup_trade_dates`).** This is causal, but it systematically
  drops the start of every fold, and the loss grows with the window parameter. Rejected.
- **Carrying the position across folds.** The next fold's candidate can differ, so a carried position
  would belong to neither. Rejected in favour of a costed exit at each fold end.
- **Selecting on a statistic (Sharpe, t-stat).** The owner ruled it out before C6.
- **Picking the best training P&L with no constraints.** The owner ruled it out: a candidate could
  win by taking excessive exposure.
- **Ranking the candidates in the output.** Only the selection is reported, with its reason. The
  candidates stay in submission order (ADR-0100).

## Consequences

- **The concatenated OOS P&L is the only walk-forward result presented as performance.** Training
  numbers are kept, but only as audit.
- **The fold-end exit cost is pessimistic.** A strategy that would have held through the boundary
  pays one extra side per fold.
- **Adding `warmup_trade_dates` renames every futures run id again.** Results with warm-up 0 are
  unchanged.
