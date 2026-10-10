# ADR-0024: `examples/trend_demo` closes the null-test acceptance gap

- **Status**: accepted
- **Date**: 2026-09-18

## Context

ADR-0023 demonstrated the original requirements's PBO/DSR acceptance clauses but explicitly
deferred the other two ("null tests erase the edge," "a genuine synthetic
edge survives"), after empirical investigation found that
`examples.momentum`'s synthetic data — a *static* per-symbol drift,
fixed for the whole simulation — is invisible to all three implemented
null tests. Shuffle and synthetic-GBM both preserve each symbol's own
marginal mean exactly; sign-flip inverts it symmetrically, which a
*relative*-ranking strategy (rank symbols against each other) is
insensitive to. None of the three transforms disturb "which symbol has
been reliably better than the others the whole time," which is exactly
what a static-drift dataset provides and what momentum-style ranking
exploits.

This ADR builds the dataset ADR-0023 said was needed: one where the edge
comes from genuine *serial* dependence (autocorrelation), which shuffling
— reordering a symbol's own returns — directly destroys.

## Decision

**`examples/trend_demo/build_data.py`** generates a single symbol
(`TRENDY`) via an AR(1) return process: `r[t] = mu + phi*(r[t-1]-mu) +
eps[t]`, `eps[t] ~ N(0, sigma_eps)`, with `sigma_eps` chosen via the
standard AR(1) variance identity so the *unconditional* stdev of `r`
equals a fixed target regardless of `phi`. `phi = 0.35` (moderate, real,
non-degenerate positive serial correlation — confirmed empirically:
realized lag-1 sample autocorrelation ≈ 0.32 on the generated series).
`mu = 0.0002` (small per-bar drift) is deliberately *not* the intended
source of edge — a buy-and-hold strategy earns this same drift
regardless of shuffling (ADR-0023's own point about static effects), so
the acceptance test must show more than drift alone would explain.
Single symbol, no corporate actions/universe (both optional in
`DataConfig`, and irrelevant to what this dataset needs to demonstrate).

**`examples/trend_demo/strategy.py::TrendFollower`**: absolute
(single-symbol, not cross-sectional) trend following — go long 100% of
equity when the trailing mean return over `lookback` bars is positive,
flat otherwise. Its signal is a genuine function of *lag-1-and-beyond*
history, so shuffling (which destroys serial order while preserving each
symbol's own marginal return distribution) should directly hurt it,
unlike momentum's relative-ranking signal.

**`examples/trend_demo/strategy.py::RandomDirection`**: identical
rebalance mechanics to `TrendFollower` (same session counting,
`rebalance_every` gating, long-100%-or-flat sizing) but the long/flat
call is `rng.choice([-1, 1])`, seeded only by `params["seed"]` — zero
data dependence, exactly mirroring `overfit_demo.RandomSignal`'s design
principle applied to this single-symbol setting. Built specifically as
the **a priori, non-search-selected** test subject for the "erasure"
half of the acceptance bar — see the next point for why it must be this
and not a search winner.

**The "no genuine edge" acceptance test uses `RandomDirection` with a
single fixed seed, never a `crucible optimize` search winner.** ADR-0023
identified that testing a *search-selected* winner's own null-test
p-value conflates two different questions: whether a given, a-priori
decision rule exploits real structure (what a null test answers) versus
whether a search process finds spurious excellence even in structureless
data (what DSR/PBO answer). A search winner was chosen *because* it
looked good on the real data, so it will tend to look "significant"
against reshuffled replays of itself regardless of whether the
underlying rule has any genuine skill — this is a selection artifact,
not evidence of a real edge, and using it to test "does the null test
correctly find nothing" would have measured the wrong thing. Testing
`RandomDirection(seed=0)` — never searched over, never selected — is the
correct apples-to-apples subject: it isolates exactly one variable (data
dependence vs. RNG) against `TrendFollower`'s otherwise-identical
mechanics.

**Empirical results locked into `tests/integration
/test_phase3_acceptance.py`** (20-iteration shuffle null test, seed 0,
fully deterministic): `TrendFollower`'s real Sharpe (≈1.73) beats *every
one* of 20 shuffled replays (`p_value == 0.0`); `RandomDirection`'s real
result (≈0.73) lands squarely inside its own null distribution
(`p_value == 0.7`, comfortably within `[0.05, 0.95]`). Both results are
deterministic given the fixed config seeds and the fixed
`np.random.default_rng(0)` driving the shuffle — reproducible on every
run, not a one-off lucky draw.

**Phase 3's roadmap status flips to done.** All four clauses of the original requirements's
acceptance bar now have automated, deterministic test coverage:
PBO > 0.5 and DSR deflation (ADR-0023, `overfit_demo`/`crucible
optimize`), and null-test erasure/survival (this ADR, `trend_demo`).

## Alternatives considered

- **Retrofit `examples.momentum`'s data generator with autocorrelation**
  instead of a new example: rejected — momentum's synthetic data and
  strategy are also this project's Phase 1/2 golden-fixture subject
  (`tests/golden/fixtures/momentum_example_hashes.json`); changing its
  return-generating process would touch the golden surface for a purpose
  unrelated to Phases 1/2, and momentum's cross-sectional design isn't
  the right shape for isolating a single-symbol serial-correlation
  effect anyway. A new, purpose-built example keeps the two concerns
  (execution-realism golden fixture vs. statistical-validation
  acceptance) independently changeable.
- **Test the `overfit_demo` `RandomSignal` search-winner's null-test
  p-value as the "erasure" evidence** (avoiding a new strategy):
  rejected — this is exactly the conflation ADR-0023 flagged; the
  winner's selection bias would make the test meaningless regardless of
  the outcome.
- **Use sign-flip or synthetic-GBM instead of shuffle** for the
  acceptance test: rejected for this dataset — sign-flip only matters
  for a strategy whose direction call is *not* symmetric under a global
  sign inversion (TrendFollower's *is* asymmetric — flipping return
  signs flips which trailing-mean sign it reacts to, so sign-flip would
  also likely show an effect, but shuffle is the more direct and
  conventionally-cited test for "does this strategy need real temporal
  order," so it was chosen as the primary demonstration).

## Consequences

`examples/trend_demo/` is a new, dedicated example — not integrated into
`examples/momentum`'s or `examples/overfit_demo`'s golden/acceptance
surfaces, so it can evolve independently. Lookahead-harness coverage
added for both new strategies (`tests/lookahead/
test_poisoned_future_trend_demo.py`, AGENTS.md §7). The acceptance suite
(`tests/integration/test_phase3_acceptance.py`) now costs roughly
3 minutes total (two ~1-minute null-test runs plus the ~1-minute
`optimize` sweep) — acceptable for a one-time-per-session correctness
demonstration, not something CI needs to run on every commit if that
ever becomes a concern (not yet gated behind a marker; revisit if
suite runtime becomes a real constraint).
