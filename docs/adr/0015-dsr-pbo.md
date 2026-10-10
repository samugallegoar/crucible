# ADR-0015: DSR/PBO formulas, per-period scale, and PBO's single-run limit

- **Status**: accepted
- **Date**: 2026-09-18

## Context

The original requirements require "Reported Sharpe is accompanied by Deflated Sharpe Ratio
and Probability of Backtest Overfitting (CSCV)," and §5 R4.3 requires "DSR
and PBO in every report." Getting from that sentence to working code needs
answers the original requirements never give: which scale (per-period or annualized) the
Bailey & López de Prado formulas operate on; where the cross-trial Sharpe
dispersion DSR's benchmark needs comes from; what happens when the
formula's own denominator can't be trusted; and — the one the original requirements'
"every report" phrasing doesn't anticipate — whether PBO can be computed
for a single `crucible run` invocation at all. Each changes what the
reported numbers mean, so AGENTS.md §10 requires resolving them here.

## Decision

### DSR is per-period, never annualized

`crucible/validation/dsr.py` computes the Probabilistic Sharpe Ratio
(Bailey & López de Prado 2012) and Deflated Sharpe Ratio (2014) entirely
on **per-period** returns, Sharpe, skewness, and kurtosis — never the
annualized Sharpe `analytics/metrics.py` reports for display. The
formula's `sqrt(n-1)` term and its skew/kurtosis correction are derived
for the per-period sample-Sharpe estimator; annualizing first would
decouple that scale from `n` (the observation count) and silently
invalidate the correction. `analytics/metrics.py::simple_returns` is now
shared by both `compute_metrics` and `dsr.py` so they operate on the
identical return series.

DSR = PSR(SR\*), where SR\* is the expected maximum Sharpe ratio a family
of N skill-less trials would produce by chance alone (extreme-value
approximation, 2014 paper eq. 10):

```
E[max_N SR] = σ_N · [(1-γ)·Φ⁻¹(1 - 1/N) + γ·Φ⁻¹(1 - 1/(N·e))]
```

`σ_N` is the cross-trial standard deviation of Sharpe estimates. `Φ`/`Φ⁻¹`
use `statistics.NormalDist` from the standard library — exact, no new
dependency.

### σ_N comes from the trial registry, not an approximation

The formula needs `σ_N` — the *actual* dispersion of Sharpe estimates
across the trials searched, not a proxy. `DuckDBTrialRegistry` (ADR-0014)
gains an optional `sharpe` column: `record_trial(family, experiment_id,
sharpe=...)` stores each distinct trial's per-period Sharpe, and
`trial_sharpes(family)` returns all of them for `σ_N = std(trial_sharpes,
ddof=1)`. This was flagged as an open question in the Phase 3 priority-2
handoff note ("may need its own storage") — extending the existing table
with a nullable column is simpler than a second, parallel one and keeps
one source of truth per trial.

**Rejected alternative**: approximate `σ_N` from the current trial's own
sampling variance (i.e. assume every trial has the same noise this one
does). This is a real technique used when trial-level data genuinely
isn't available, but we *have* the data — using a fabricated proxy when
the true empirical distribution is one column away would be strictly
worse, not more conservative.

### N ≤ 1: no deflation, not a divide-by-zero

`E[max_1 SR]` is undefined (the formula's `Φ⁻¹(1 - 1/N)` term goes to
`-∞` as `N → 1`) — it is an asymptotic approximation, not exact for small
N. With exactly one trial there is no multiple-testing bias to correct
for, so the benchmark is defined as `0.0` and DSR reduces to plain PSR
against a zero benchmark. This is the conservative reading, not a
loophole: a lone run gets *no* deflation credit, only the (already
standard) finite-sample skew/kurtosis correction.

### The PSR denominator refuses rather than produces a wrong number

`denom = 1 - γ₃·SR + (γ₄-1)/4·SR²` is, for any real finite sample, bounded
below by `(1 - γ₃·SR/2)² ≥ 0` (a consequence of the kurtosis ≥
skewness² + 1 inequality that holds for every real distribution) — so it
can only reach exactly zero at a razor's-edge boundary case, never go
negative for genuine sample moments. `dsr.py::_psr` still checks and
raises `CrucibleError` if it happens, rather than dividing by (or taking
the square root of) a non-positive number. `run_experiment` catches this
specific, narrow failure and reports `"DSR: not computable: <reason>"`
instead of crashing the whole run — the artifacts, metrics, and every
other report section are still worth having even if this one statistic
can't be trusted for this trial.

### PBO/CSCV: implemented, correct, and NOT wired into a single run's report

PBO (Bailey, Borwein, López de Prado & Zhu 2015) needs a
**trials × periods returns panel** — many trials' return series over the
*same* time periods — to ask "if I'd picked the in-sample winner, how
often would it have been an out-of-sample loser?" A single
`run_experiment` call produces exactly one trial's returns. There is no
honest way to compute PBO from that, and faking it (N=1 degenerate panel,
or reusing unrelated historical trials with different date ranges) would
produce a number that looks like PBO but answers a different, misleading
question.

`crucible/validation/pbo.py::probability_of_backtest_overfitting` is
implemented as a correct, independently-tested, standalone function over
an explicit `(n_trials, n_periods)` array — reusing
`CombinatorialPurgedCVSplitter` (priority 1) configured symmetrically
(`n_test_groups = n_groups // 2`) to generate the combinatorial CSCV
splits, since CSCV *is* CPCV's symmetric, purge=0/embargo=0 special case.
It is ready for whatever assembles a real multi-trial panel to call. That
assembly is squarely the `optimize`/`validate` CLI's job (Phase 3
priority 9) — no run-level infrastructure exists yet to collect and align
multiple trials' return series. The report's `"PBO: not computed for a
single run"` says exactly this, replacing the stale generic "(Phase 3)"
placeholder (misleading now that DSR *is* computed within this same
phase) with the actual reason.

### Terminology note: CSCV ≠ CPCV

The the original requirements use "CPCV" (Combinatorial *Purged* Cross-Validation, the
priority-1 splitter) and "CSCV" (Combinatorial *Symmetric*
Cross-Validation, PBO's specific split scheme) somewhat interchangeably
in prose, but they are different things from different papers. This ADR
and `docs/GLOSSARY.md` now distinguish them explicitly: CSCV is
implemented *using* the CPCV splitter (a symmetric configuration of it),
not as a separate splitter class.

## Alternatives considered

- **Annualized DSR** (matching the display-facing Sharpe): rejected — see
  Decision; breaks the formula's own derivation.
- **A second table for per-trial metrics** instead of extending `trials`:
  rejected — same (family, experiment_id) key as the existing table;
  keeping one row per trial avoids a join and a second source of truth.
- **Faking PBO with N=1**: rejected — see Decision; would silently violate
  R4.3's intent ("DSR and PBO in every report") by producing a number,
  just the wrong one, which is worse than an honest "not computed."

## Consequences

`manifest.json` gains `dsr`, `dsr_benchmark_sharpe`, `dsr_error`, and
`pbo` (currently always `null`) fields. The report's provenance table is
unchanged; only the free-text statistical-validity warning block's DSR/PBO
sentence is now real. Discovered while testing: at Level 1 (frictionless/
basic-friction), `experiment.seed` only feeds the metrics bootstrap CI —
there is no execution-path RNG, so two runs differing only in `seed`
produce byte-identical equity curves and therefore identical Sharpe
(`σ_N = 0` between them). This is expected, not a bug; it just means a
useful multi-trial DSR test needs a config change that actually alters
simulated behavior (a strategy parameter), not just the seed.
