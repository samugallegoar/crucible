# ADR-0081: An out-of-sample walk-forward command

Status: accepted (2026-10-25), implementation pending

## Context

The 2026-10 audit found that Crucible can *diagnose* selection overfitting (DSR, PBO) but cannot
*produce* an out-of-sample result. `crucible/validation/splits.py` implements
`WalkForwardSplitter`, `PurgedKFoldSplitter` and `CombinatorialPurgedCVSplitter` correctly — the
purge arithmetic was verified (unpurged forward labels correlate 0.85 with the next fold, purged
−0.02) — but nothing outside the tests calls the first two, and `build_splitter` has no caller at
all. `optimize_1d` picks `argmax` over trials that all ran on the same `[start, end]`, so its
winner's metrics are in-sample; `validate` is a plain run plus an optional factor regression.

The consequence is not a wrong number anywhere; it is a missing answer to "how did the rule I
chose do on data it was not chosen on?".

## Decision

Add one command, `crucible walk-forward CONFIG`, that runs a 1-D selection over time folds and
reports only out-of-fold metrics:

1. **Inputs.** The usual `ExperimentConfig`, plus `--param NAME --values a,b,c` (the same 1-D
   sweep `optimize` takes), `--train`, `--test`, `--step` intervals (`config.parse_interval`
   syntax), and `--metric` (default `sharpe`). `--holdout` optionally reserves a final tail
   window that is never used for selection and is evaluated once, after the folds.
2. **Folds.** Rolling walk-forward windows built from the run's `[start, end]`: train `[t, t+train)`,
   test `[t+train, t+train+test)`, then `t += step`. Fold arithmetic is refused — with the numbers
   in the message — when a window would be empty, when `test < 1` bar, or when no fold fits at
   all. The splitter used is `WalkForwardSplitter` through `build_splitter`, so the mechanism
   already tested is the one used in production.
3. **Selection happens on train, evaluation on test.** For each fold, every candidate value runs
   on the train window (dedicated artifacts, `mode: optimization`), the best is chosen by
   `--metric` (higher-is-better only; `volatility`/`max_drawdown` are refused rather than
   silently maximized), and **that** candidate runs on the test window with `record_trial=False`.
   The reported table is fold → chosen value, test metric, test equity, test trade count.
4. **Aggregate.** The output is the per-fold table plus the mean and standard deviation of the
   test metric across folds, the fraction of positive folds, and — when the folds are contiguous
   — the concatenated out-of-fold return series with its Sharpe and its deflated Sharpe against
   the number of folds. The aggregate is allowed to look worse than the full-sample number; it is
   the honest one.
5. **Protected final window.** With `--holdout`, the last `holdout` window is removed from the
   fold sequence, the fold winner is re-run on it once, and that result is reported separately
   and labelled as the only number in the output that has never influenced any choice.
6. **No silent trial inflation.** Every run writes its normal artifacts, and the summary is
   written to `<artifacts>/walk_forward.json` and printed. Train runs record trials (they are
   parameter evaluations); test runs do not, and the summary says so, because a fold's test
   window is a re-evaluation of an already-recorded parameter set. The selection inside a fold is
   therefore **not** deflated by DSR — the report says that too — and the DSR of the out-of-fold
   series is the number to read.

## Alternatives considered

- **Extend `optimize` with `--walk-forward`.** Rejected for now: `optimize` already owns PBO and
  the sweep panel, and adding fold management there would blur "one sweep, one panel" with
  "selection over time". A separate command can share its helpers without changing its output.
- **Evaluate a single config without selection.** Cheaper, but it answers a different question
  (stability across periods) and would be easy to misread as out-of-sample. Selection is the
  part that needs protecting.
- **Report the full-sample metrics alongside.** Rejected: the point of the command is that its
  headline is out-of-fold. The full-sample number is one `crucible run` away if wanted.
- **A `metrics` package-level API only, no CLI.** Rejected: the audit's complaint was precisely
  that the machinery was library-only and no user-facing path produced an OOS number.

## Consequences

- A new CLI command, a library entry point (`experiments/walk_forward.py`), a config-free
  argument surface, and a summary schema (`walk_forward.json`, additive).
- Runtime is `folds × (candidates + 1)` runs; the command refuses a plan above a stated cap
  rather than running for hours silently.
- Determinism: folds and candidates run sequentially in a fixed order, ids are the existing
  config/data hashes, so the summary is reproducible bar for bar.
- `docs/USAGE.md` gains a section, `docs/modules/experiments.md` and `docs/modules/validation.md`
  lose their "no OOS result exists" caveat, and ADR-0015's stale claim is corrected.
- M1 (per-bar stop pricing) and the remaining LOW items are unaffected.
