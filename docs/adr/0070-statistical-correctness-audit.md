# ADR-0070: Correct the null tests, PBO ties, Monte Carlo p-values and trial families

- **Status**: accepted
- **Date**: 2026-10-10

## Context

An audit of the statistical validation layer against its own documentation and the
published methods found five defects, each of which made a result look **more** convincing
than the evidence allows, plus several claims in the user documentation that were stronger
than the code.

1. **The null-test transforms dropped every overnight gap.** `data/transforms.py` rebuilt
   shuffled, sign-flipped and synthetic bars with `open[k+1] = close[k]`. A shuffled path's
   long-run return was therefore the product of the open-to-close returns alone, not of the
   close-to-close returns the strategy was run on. On the local `equities_daily_v1` dataset,
   AAPL compounds at 26.8 % a year close-to-close but 11.3 % open-to-close (MSFT 20.2 % vs
   8.1 %), so the "shuffled returns" null had less than half the real drift. Any long-biased
   strategy beat it easily, and the one-step product's docstring claimed the opposite ("the
   long-run return and every bar's size are unchanged"). The test fixture had no gaps, so the
   defect was invisible to the tests.
2. **PBO ranked ties as worst.** `rank = 1 + sum(oos < oos[n*])` puts the in-sample winner last
   among out-of-sample ties, and `argmax` breaks in-sample ties by array position. A panel of
   identical trials, or of trials that are all flat, scored PBO = 1.0 ("always overfit").
3. **The Monte Carlo p-value could be 0.** `mean(null >= real)` reported 0.0 when no null draw
   reached the real value, as if 100 shuffles could prove the probability is zero; NaN null
   values were silently counted as non-exceedances (lowering the p-value).
4. **DSR scored an undefined Sharpe.** A zero-variance return series (a strategy that never
   held a position) got Sharpe 0 and DSR = PSR(0): a printed probability of 0.5 for a quantity
   that does not exist. A constant non-zero series is worse: its float standard deviation is
   ~1e-19, not 0, so its Sharpe came out around 1e16.
5. **The default trial family split the search by window.** The one-step backtest defaulted to
   `quick:<symbols>:<start>-<end>`, so re-running rules on another window of the same symbols
   started a new family at trial 1, and the DSR never saw the search.

Documentation overclaims: "a 95% range on every headline number" (only the Sharpe ratio has
one in the product), "prices are read point-in-time" (access is; Yahoo's adjusted prices are
re-computed after the fact), "every headline Sharpe, return and drawdown carries one" (FAQ),
and yfinance described as an optional extra while `pyproject.toml` makes it a core dependency.

## Decision

1. **Transforms carry the gap.** Each bar decomposes into `gap = open[k]/close[k-1] - 1`,
   `intrabar_return`, the two wick fractions and volume; the path is rebuilt from the real first
   open with `open[k+1] = close[k] * (1 + gap[k+1])`. Three explicitly named permutation nulls:
   `shuffle_bar_returns` permutes whole bars after the first (the multiset of close-to-close
   returns and the final close are preserved exactly; the order of daily moves is destroyed),
   `shuffle_intrabar_returns` permutes intraday shapes with gaps held on their dates, and
   `shuffle_overnight_gaps` the reverse. The sign-flip negates both components; the synthetic
   null draws i.i.d. normal close-to-close returns matched to the real mean and standard
   deviation. The module docstring tabulates what each preserves and destroys. The permutation
   nulls test exchangeability of the order; a significant result says the order mattered on
   this sample, nothing about persistence or the number of strategies tried.
2. **PBO resolves ties by expectation.** Each split contributes the probability, under uniform
   random tie-breaking among in-sample co-winners and among out-of-sample ties, that the pick
   ranks at or below the median, `2 * rank <= N + 1` (the paper's `lambda <= 0`, evaluated on
   the integer rank: no logarithm, no infinite logit). Identical trials score about 0.5, the
   probability of a random pick. `PboResult.n_tied_splits` reports how many splits depended on
   a tie. Non-finite returns, partitions shorter than two observations and constant non-zero
   rows are refused; an all-zero row scores Sharpe 0. Constancy is tested exactly
   (`all(x == x[0])`), not by `std == 0`.
3. **Monte Carlo p-values use `(k + 1) / (B + 1)`.** One-sided (higher is better), ties count as
   exceedances, NaN null values are excluded from `B` and counted (`n_invalid`), a non-finite real
   value is refused, and `n_exceedances` and `monte_carlo_se = sqrt(p (1 - p) / B)` are reported.
   The deterministic sign-flip is a separate `compare_to_single_null` with **no** p-value. The
   one-step result document's `validation.null_test` gains `exceedances`, `invalid_iterations` and
   `p_value_method`; since `p_value` changed meaning, its `schema_version` becomes 2.
4. **DSR refuses** non-finite and zero-variance returns (`CrucibleError`, recorded as
   `dsr_error` / "not computable", as other DSR refusals already were). The module docstring
   states what DSR is not: not the probability of profit, corrected only for recorded trials,
   `N` is the raw trial count, and the variance assumes i.i.d. returns.
5. **Two levels of trial counting.** A user searches along three axes: rules, windows and
   instruments. (a) The **family** defaults to the symbol set, `quick:<sorted symbols>`: every
   rule set and every window tried on the same symbols counts together, and its DSR deflates
   against trials that are genuine alternatives to each other (same instruments). (b) A
   **home-wide DSR** deflates the same returns against every one-step trial recorded in the home,
   every family (`DuckDBTrialRegistry.total_trial_count`/`all_trial_sharpes`, distinct
   experiments). Both are reported (`trial_count`, `dsr`; `home_trial_count`, `dsr_home_wide`),
   and the verdict needs **both**: when the home has seen more trials than the family and the
   home-wide DSR is under 0.95, the flag `dsr_low_home_wide` blocks `some_evidence`. Trying an
   idea on one instrument after another therefore cannot buy a stronger verdict, and an explicit
   `family` (still accepted, labelled by `trial_family_source`) groups the primary count but
   cannot lower the bar. `trial_count_scope` says the count is a lower bound: variants run outside
   this home are invisible. Re-running identical rules under a new explicit family registers a
   new experiment id (the family is part of the config), so the home-wide count can count it
   twice: an error in the conservative direction.
6. **Disclosure.** The one-step result's `provenance` gains `price_basis_note` (fills and equity
   are on a re-computed adjusted series, not historical quotes) and `execution_assumptions` (what
   the vectorized fill model does and does not model). README, the user guide, the FAQ and the
   agent guide say that only the Sharpe ratio carries an interval and that it is approximate.
7. **Measure the bootstrap instead of asserting it.** `tools/bootstrap_coverage.py` measures the
   empirical coverage of the Sharpe interval on synthetic processes with a known Sharpe ratio.
   Results are below; the interval is documented as approximate.

Pessimism: every change moves a reported result toward "less convincing" (a higher null
p-value floor, a null with the real drift, a higher trial count, fewer printed probabilities),
which is the conservative direction AGENTS.md §1.4 asks for.

## Measured coverage of the Sharpe interval

Study: `uv run python -m tools.bootstrap_coverage` (seed 20261010, 1,000 resamples, 400
replications per cell; the Monte Carlo standard error of a coverage near 0.95 is 0.011). True
annualized Sharpe 0.635 (0 for zero alpha); the default block is `floor(sqrt(n))`.

| process | n | `sqrt(n)` (default) | `n^(1/3)` | 1 (i.i.d.) |
|---|---|---|---|---|
| i.i.d. normal | 252 | 0.912 | 0.922 | 0.950 |
| i.i.d. normal | 1260 | 0.945 | 0.930 | 0.943 |
| zero alpha (i.i.d.) | 252 | 0.915 | 0.925 | 0.950 |
| zero alpha (i.i.d.) | 1260 | 0.948 | 0.930 | 0.945 |
| Student-t, 4 df | 252 | 0.920 | 0.953 | 0.950 |
| Student-t, 4 df | 1260 | 0.912 | 0.948 | 0.945 |
| AR(1), phi = 0.3 | 252 | 0.927 | 0.897 | 0.850 |
| AR(1), phi = 0.3 | 1260 | 0.945 | 0.920 | 0.853 |
| GARCH(1,1), 0.08/0.90 | 252 | 0.922 | 0.935 | 0.955 |
| GARCH(1,1), 0.08/0.90 | 1260 | 0.938 | 0.960 | 0.945 |

Reading: the default interval undercovers by about three standard errors with one year of daily
data, for every process including i.i.d. normal (percentile intervals of a ratio statistic on a
short sample), and with heavy tails even over five years. It does handle autocorrelation: the
i.i.d. bootstrap collapses to 0.85 under AR(1) while `sqrt(n)` blocks reach 0.945 at n = 1260. No
single block length wins every row, so the default is kept and the interval is documented as
approximate (nominal 95 %, measured 91-95 %). These are synthetic processes; real returns can be
worse (regime changes, jumps), and coverage says nothing about future profitability.

## Alternatives considered

- **Keep the gapless reconstruction and document it as an intraday null.** Rejected as the
  default: the product and the CLI present it as "the same returns shuffled", and the gapless
  series is not the series the strategy trades. The intraday-only question is now its own
  transform (`shuffle_intrabar_returns`) that keeps the gaps instead of deleting them.
- **PBO with mid-ranks.** Mid-ranks put a panel of identical trials exactly at the median, where
  the paper's `lambda <= 0` counts every split as overfit (PBO = 1 again); a strict `< 0` gives 0.
  Either way one boundary convention decides a degenerate case. The expectation under random
  tie-breaking agrees with the paper whenever there is no tie and gives the random-pick value
  when there is.
- **Clip `omega` away from 0 and 1.** Not needed: with `rank` in `1..N` and divisor `N + 1` the
  logit is always finite; comparing integers removes the question.
- **Keep `mean(null >= real)` and document "0 means < 1/B".** Rejected: the add-one estimator is
  the standard Monte Carlo p-value (exact level under exchangeability) and no caller needs the
  biased one.
- **Group families by symbol overlap or by strategy.** Overlap is not transitive and would make
  family membership depend on history; by strategy would let a user escape the count by changing
  one rule. The symbol set is a simple, auditable default, and `family` overrides it.
- **Symbol-set family only.** Simplest, but a user who tries the same rules on SPY, QQQ and IWM
  gets three families at trial 1 each: the instrument search is invisible.
- **One family for the whole home.** Catches every search, but makes the primary DSR benchmark
  mix the Sharpe dispersion of unrelated projects (other asset classes, other ideas). Kept as the
  second, verdict-blocking level instead of the only one.
- **Pick an automatic block length (Politis-White).** Deferred: it changes every existing
  interval; the study gives the evidence needed to decide it (see Consequences).

## Consequences

- Null-test p-values from before this ADR are not comparable with new ones; in particular old
  one-step results whose shuffled-returns p-value was small may not be small now. Old result
  documents carry `schema_version` 1.
- `crucible optimize`'s JSON `pbo` object gains `n_tied_splits`. A sweep containing a trial with
  constant non-zero returns in some partition is refused instead of scored.
- Re-running a one-step backtest gives a new experiment id (the family is part of the config) and
  joins the symbol-set family; existing `quick:<symbols>:<start>-<end>` families stay in the
  registry untouched.
- The product golden (`sma_cross_spec_golden.json`) changes its `sha256` only: final equity,
  benchmark equity, trade count and verdict are identical (see the fixtures README).
- ADR-0019 (null tests) and ADR-0015 (DSR/PBO) remain in force; this ADR amends their
  implementation details. ADR-0063's "yfinance is an optional extra" was already superseded by
  ADR-0068's dependency change; this ADR removes the remaining text that said otherwise.
- Not addressed here (open, see the module pages' Known gaps): an effective-number-of-trials
  estimate for DSR, an automatic bootstrap block length, intervals for return and drawdown in the
  one-step report, a non-adjusted executable price series for the one-step flow, and
  orchestration/CLI for the intraday-only and overnight-only nulls.

## Addendum: the remaining audit phases (same day)

Second pass over the phases the first left open. Findings and decisions:

- **Walk-forward leakage (fixed).** `WalkForwardSplitter` had no purge ("train precedes test,
  so there's no purge concept"), which is only true when every label is known at its own bar.
  It gains `purge` (default 0, so existing splits are unchanged); with an `h`-bar forward label
  it must be `h`. An adversarial test shows an unpurged 20-bar label "predicting" pure noise with
  a correlation above 0.6, and below 0.1 once purged; a property test checks the purge covers the
  label horizon for all three splitters.
- **Accounting.** I1, I3 and I4 were already enforced at every mark from a fresh ledger fold.
  New: a property test of I2 over random fills, commissions, partial closes and reversals, and a
  hand-computed long-to-short reversal ledger. Finding: I2 is not exact as documented: the
  weighted average cost is a Decimal quotient rounded at 28 significant digits, so the
  realized/unrealized split can miss by ~1e-27 (cash and equity are exact). `docs/INVARIANTS.md`
  now says so. Splits, reverse splits, stock dividends, spin-offs, mergers and symbol changes are
  refused by the engine; tests now pin that refusal. Supporting splits needs a dedicated
  position rescale (booking it as a fill would turn a reverse split into a fake realized P&L) and
  stays on the roadmap with corporate-action datasets.
- **Determinism.** Resume equivalence is now also checked at every session of the dividend run
  and at eight evenly spaced boundaries of the randomized Level 4 momentum run; the experiment id
  is tested to be stable under key order and to change with the seed, costs, capital, window and
  dataset hash. Finding: the engine's only random draw is latency, and on daily bars a sub-second
  latency never changes which bar an order reaches, so a Level 2-4 daily run does not depend on
  its seed; the seed test uses a latency of about a day, which does. Which fields are bitwise
  identical across platforms is ADR-0055's contract.
- **Execution.** `docs/modules/execution.md` gains an execution-modes table (vectorized vs Levels
  0-4: orders, timing, price source, costs, liquidity, corporate actions) and a validated-scope
  statement: bar-based only, never compared with quote or order-book data, no HFT or
  microstructure claim. New tests: sell-stop gap-down and intrabar trigger, a stop-limit that gaps
  past its limit, a touched-but-not-traded limit. Known gap pinned by a test: a spread or
  slippage that would leave the bar's range is clamped into it, erasing the cost when the open is
  the bar's extreme (slightly optimistic; changing it moves goldens and is left for its own ADR).
- **Acceptance scenarios.** `tests/README.md` §9 maps the ten scenarios of the audit brief to
  tests; new ones: an edge that disappears after costs, and metamorphic tests (vectorized returns
  invariant to price scale and to input row order).
- **CI.** The full suite now runs on Ubuntu, Windows and macOS (the golden hashes make that a
  continuous cross-platform determinism check), and a `clean-install` job installs the built
  wheel with runtime dependencies only and imports every entry point. Verified locally: the wheel
  installs and imports cleanly without dev tools; with `pyarrow` removed, the store, a vectorized
  run and the DuckDB registry still work (evidence for the open `pyarrow` decision in
  `docs/DEPENDENCIES.md`, not a removal). The `mcp` package was still described as an optional
  extra in two docstrings and an error message; corrected.
- **Refactor (declined).** `core/engine.py` (1,750 lines) was mapped: the ledger, execution
  ladder, order manager, risk engine and checkpoint codec already live in their own modules, and
  what remains is coordination that touches several of them (checkpoint payload assembly, fill
  booking, financing accrual, marking). Extracting any of it would create helpers reaching into
  the engine's private state, more code with no stronger invariant, at a risk to the
  byte-identical resume and live-parity guarantees. Not refactored; revisit when a
  responsibility gains its own invariant or a second caller.
