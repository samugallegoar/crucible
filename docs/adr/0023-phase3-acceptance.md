# ADR-0023: Phase 3 acceptance scope, RandomSignal design, and a null-test limitation

- **Status**: accepted
- **Date**: 2026-09-18

## Context

The original requirements's Phase 3 acceptance bar is a conjunction: "a known-overfit
strategy (optimized on noise) shows PBO > 0.5 and DSR ≈ 0; null tests
erase the edge; a genuine synthetic edge survives." Every statistical
primitive this bar needs (DSR, PBO, null tests, `optimize`) was already
implemented and tested earlier this session (priorities 1-9). This ADR
covers what it took to actually *demonstrate* the bar against a real
strategy, and records a real limitation discovered in the process.

## Decision

**`examples/overfit_demo/strategy.py::RandomSignal`** is the known-overfit
vehicle: a long-only, equal-weight, periodic-rebalance strategy whose
*symbol selection* is `rng.choice`, seeded only by `params["seed"]` —
zero relationship to price data by construction. Mechanically it mirrors
`examples.momentum.strategy.Momentum` (session counting,
`rebalance_every` gating, equal-weight sizing) so the only difference
between "genuine strategy" and "known-overfit strategy" in this
codebase's example set is the selection rule itself, not unrelated
plumbing. The rng is seeded once in `on_start` from `params["seed"]`
(CLAUDE.md's explicit-rng rule — never global RNG).

**Acceptance test** (`tests/integration/test_phase3_acceptance.py`):
sweeps `seed` over 40 values via `crucible.experiments.optimize
.optimize_1d` (`pbo_groups=8`) against `examples/overfit_demo/config.yaml`
(reuses `examples/momentum`'s synthetic bars — no new dataset needed) and
asserts, deterministically (every seed and config value is a fixed
integer, so the whole test is reproducible byte-for-byte across runs):
- `pbo.pbo > 0.5` — the in-sample winner ranks at/below the OOS median
  more often than chance across CSCV's combinatorial splits.
- the winning trial's raw Sharpe is `> 0.9` (it does look good in
  isolation — the overfitting is real, not a strawman) while its
  properly-deflated DSR is `< 0.5` (dramatically lower than an
  undeflated read of that Sharpe would suggest).

**Bug found and fixed while building this: `optimize_1d`'s reported DSR
was wrong.** Before this ADR, `OptimizeResult` only returned each trial's
own `RunArtifacts`, whose `manifest.json["dsr"]` was computed *at that
trial's own recording time* — i.e., trial 7 of a 40-trial sweep only sees
the first 7 trials' Sharpe dispersion, not the full 40, because
`run_experiment` computes DSR against the trial registry's contents *as
of that run*, and trials are recorded sequentially as the sweep proceeds.
Reading the winning trial's own manifest.json therefore under-deflates
it whenever the winner isn't the *last* trial run. Fixed by adding
`best_dsr`/`best_experiment_id` to `OptimizeResult`: after all trials are
recorded, `optimize_1d` re-reads the trial registry's *complete*
`trial_sharpes(family)` and recomputes `deflated_sharpe_ratio` for the
best-performing trial's own return series against that full history.
This is the DSR a real practitioner should read off an `optimize` run —
each trial's own `manifest.json["dsr"]` remains correct *for what it
is* (the deflation known at that point in the search) but is not the
right number to report as "the search's final verdict on its winner."

**Methodological finding, not fixed (a real limitation, documented
rather than hidden): none of the three implemented null tests
(shuffle/sign-flip/synthetic-GBM) can distinguish a *static
cross-sectional drift* edge from noise.** All three either preserve each
symbol's own marginal mean exactly (shuffle keeps the same per-symbol
return multiset in a new order; synthetic-GBM redraws from a normal
matched to that symbol's own empirical mean/stdev) or invert it
symmetrically (sign-flip) in a way a *relative*-ranking strategy is
insensitive to (ranking by "highest recent return" under a uniform sign
flip just relabels which absolute direction wins, not whether a
consistently-highest-drift symbol keeps winning). `examples/momentum`'s
synthetic data (`build_data.py`: "heterogeneous drift" — a *fixed*
per-symbol drift parameter for the whole simulation) is exactly this
kind of edge. Empirically, across multiple configurations tried during
this session's investigation, momentum's own null-test p-values did not
reliably show erasure, and testing a `crucible optimize` search-winner's
null-test p-value conflates *two different questions*: whether a single,
a-priori-chosen decision rule exploits real structure (what a null test
answers) versus whether a search process finds spurious excellence even
in structureless data (what DSR/PBO answer, and what this ADR's
acceptance test uses). A genuinely autocorrelation-based synthetic edge
(returns causally dependent on their own recent history, not merely a
fixed per-symbol mean) would be shuffle-erasable and momentum-style
static drift is not — building that dataset is out of scope for this
session (see Consequences).

**Scope**: this ADR's acceptance test demonstrates the original requirements's PBO/DSR
clauses only. The "null tests erase the edge" and "a genuine synthetic
edge survives" clauses are **not** demonstrated by an automated test —
recorded as a known gap, not silently skipped.

## Alternatives considered

- **Force a null-test-based demonstration using `examples.momentum` as
  the "genuine edge" and the RandomSignal search-winner as the
  "erased edge"**: rejected after empirical investigation (see Decision)
  — the results were inconsistent and, once understood, revealed the
  comparison itself was measuring the wrong thing for both strategies.
  Shipping a flaky or misleading acceptance test would violate CLAUDE.md
  §1's correctness-over-speed and refuse-don't-warn directives more than
  shipping a partial, honestly-scoped one.
- **Tune `examples.momentum`'s parameters further to find a config whose
  edge does look shuffle-erasable**: rejected — even after finding a
  parameterization with a clearly positive raw Sharpe (`lookback=60,
  top_k=4, rebalance_every=20`, Sharpe ≈0.95), it failed the sign-flip
  null test as thoroughly as any random search would, for the structural
  reason above; further tuning would only be curve-fitting the
  *demonstration* itself, which is precisely the kind of thing this
  phase's tooling exists to catch.
- **Build a new autocorrelation-based synthetic dataset and strategy
  pair now**: deferred, not rejected — real, additional scope (a new
  data generator, a new strategy, its own acceptance test) that the
  session's already-large scope didn't have room for; flagged as the
  concrete next step for whoever picks up the null-test half of R4.6's
  acceptance bar.

## Consequences

Phase 3's roadmap status remains **in progress**, not **done** — the original requirements's
bar is a four-part conjunction and only two parts (PBO, DSR) have test
coverage. the roadmap records exactly which two, and what remains.
`optimize_1d`'s `best_dsr` fix changes `OptimizeResult`'s shape (two new
fields) — no other caller existed yet (this session built both), so no
migration was needed. The null-test limitation applies to any future
example whose "edge" is a static per-symbol factor exposure rather than
genuine serial dependence — worth remembering before reaching for
shuffle/sign-flip/GBM null tests to validate that kind of strategy.
