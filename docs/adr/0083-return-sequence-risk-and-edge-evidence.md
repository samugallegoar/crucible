# ADR-0083: Return-sequence risk, edge evidence after the search, and cost stress

- **Status**: accepted
- **Date**: 2026-11-05

## Context

A request to review Crucible's Monte Carlo, equity-path and edge-validation capabilities and to
add what is worth adding. What existed:

- `validation/monte_carlo.py`: a return-order shuffle, a circular start shift and a fixed-length
  circular block bootstrap (block ~ sqrt(n)), reporting only summary numbers (ADR-0017). Shuffle and
  shift permute the same returns, so terminal equity and Sharpe cannot vary; only the drawdown does.
- Re-simulation null tests (shuffled bars, sign flip, synthetic GBM; ADR-0019), the one-step
  product's shuffled-returns p-value (ADR-0068/0070/0078), perturbation Monte Carlo of an execution
  scalar or a strategy parameter through the event-driven engine (ADR-0018; library only), the
  deflated Sharpe (ADR-0015), PBO on `optimize`'s panel, a factor regression.
- Not there: simulated equity paths, a terminal-equity distribution, probability of loss, risk of
  ruin, fan percentiles, a stationary bootstrap or any automatic block length, a trade-level
  resampling, a test of the best of several tried strategies that resamples their returns, and a
  deterministic cost stress.

The two kinds of question these tools answer were also easy to confuse. A resampled history is
built from the realized returns, so it is centred on the realized result: its "probability of
loss" is low for any lucky or overfit backtest. That is **return-sequence risk** (how much of the
outcome is the sample and its order). Whether a strategy has a genuine edge is a different
question, answered by a null hypothesis that the strategy's value is zero, or by a correction for
the search that produced it. This ADR keeps them apart in the code, the output and the docs.

## Decision

**Evaluated and implemented**

1. `validation/resampling.py`: the stationary bootstrap (Politis & Romano 1994) and an automatic
   mean block length (Politis & White 2004 with the Patton, Politis & White 2009 correction),
   bounded to `[1, min(3 sqrt(n), n / 3)]`. One definition of the block rule for everything that
   resamples a return series. The fixed circular `BlockBootstrapTest` is left as it is (its manifest
   numbers and the artifacts built on them stay reproducible).
2. `validation/paths.py` (**return-sequence risk**): equity paths from the stationary bootstrap of
   per-period returns (`simulate_return_paths`) or an i.i.d. bootstrap of per-trade returns on equity
   (`simulate_trade_paths`), summarized as terminal-equity percentiles, max-drawdown percentiles, the
   probability of finishing below the start, of touching a ruin level (checked at every step) and of a
   drawdown beyond a threshold, and a percentile fan (P5, P25, P50, P75, P95). Every summary carries
   `kind = "return_sequence_risk"`. Paths are generated and summarized in chunks; individual paths
   are returned only on request (`keep_paths`), refused above a cell budget.
3. `validation/reality_check.py` (**edge evidence after the search**): White's Reality Check and
   Hansen's SPA (consistent recentering) for the best of the candidates of a return panel, driven by
   the stationary bootstrap over shared time indices so the candidates' cross-correlation is kept.
   `kind = "edge_evidence_after_search"`. Wired into `crucible optimize` (its panel already exists)
   next to PBO and the deflated Sharpe.
4. The one-step product: a `sequence_risk` block and a fixed `sequence_table` (with the note that it
   is not evidence of an edge), a fan chart in the HTML report, and `crucible simulate-paths RUN`
   for any finished run, which writes every simulated path to Parquet only with `--export-paths`.
5. `diagnostics.cost_stress` and a table row: the run re-priced at 1x/2x/3x/5x its costs without
   re-running it (the engine's net return is `gross - turnover x rate`, so it is linear in the
   multiple); verified against a real re-run at doubled costs.

**Evaluated and deliberately excluded**

- **Storing every path by default.** 1,000 paths of ten years of daily bars is ~22 MB per run and
  adds no information beyond the percentile bands and the distributions; paths are recomputable
  from the seed. Export exists on demand (`--export-paths`).
- **Regime-conditioned bootstrap.** Regime labels have to be estimated, and estimated on the full
  sample they use the future; each regime has fewer observations, so the resampled distribution is
  noisier and the choice of regime model becomes a degree of freedom that can be tuned until the
  paths look good. It changes the question rather than sharpening it. Not implemented; if a regime
  view is wanted, run the one-step backtest per period or per volatility bucket and compare.
- **A bootstrap test of "mean return = 0".** The existing block-bootstrap Sharpe interval already
  is that test; a second copy would be a duplicate metric.
- **A random-entry ("monkey") null.** Same question as the shuffled-returns test (does the order
  of returns matter to these rules?), with more free parameters; the existing test stays the null.
- **An event-driven spread/slippage stress grid.** One event-driven run costs ~30 s, and the
  random perturbation of ADR-0018 already exists for it; the linear stress above covers the
  vectorized headline for free. A non-linear stress (costs rising with size or in fast markets) is
  a model of the market, not a re-pricing, and is left to the realism check and perturbation.
- **Hidden-Markov or other regime null tests, and the time-shifted-signal null**: need machinery
  (signal delay, a regime model) that this work does not justify.

## Alternatives considered

- **Extend `BlockBootstrapTest` and the `ResamplingTest` Protocol.** Rejected: the Protocol returns
  a flat dict of floats and takes only returns; paths, bands and trade-level resampling do not fit
  it, and changing the manifest's `monte_carlo` block would move reproducible artifacts.
- **Mean block length from the data for every method, replacing `sqrt(n)`.** Done for the new code
  only, for the same reason.
- **A parametric reality check (a t-test with a Bonferroni or Sidak correction).** Rejected: it
  treats the candidates as independent, which neighbouring parameter values are not, and ignores
  serial dependence.

## Consequences

- **How to read the two kinds of output.** `return_sequence_risk` tells you how fragile the
  *realized* result is to the sample: wide bands, a deep 5th-percentile drawdown or a high chance of
  finishing below the start say the history was lucky *or* short. A narrow, comfortable fan does
  **not** say there is an edge. `edge_evidence_after_search` and the existing nulls (shuffled
  returns, the Sharpe range, the deflated Sharpe, PBO) are the evidence. The sequence table and the
  agent guide say this in words.
- **Statistical limits, stated.** The bootstrap keeps short-range dependence (block structure) but
  not long memory or regime shifts; a bar bootstrap's effective sample is the number of blocks, a
  trade bootstrap's is the number of trades and assumes constant sizing and independence, and sees
  closed-trade drawdowns only. The reality check's `N` is the candidates in the panel, not every
  variant ever tried (the same lower bound as the deflated Sharpe), and a p-value from a short
  or heavy-tailed sample is approximate. The cost stress is linear and holds the trades fixed.
- **Calibration.** Under a true null with 20 zero-edge candidates the naive best-candidate t-test
  rejects at 5% about 65% of the time (theory: 64%), White's test 4.8% and Hansen's SPA 5.8%; with
  one modest edge among 60 poor candidates SPA has 69% power against White's 24%
  (`tests/unit/test_reality_check.py`). The stationary bootstrap reproduces the Politis-Romano
  autocovariance identity, and the block length matches the closed form for AR(1)
  (`tests/unit/test_resampling.py`). Path probabilities match exact binomial and lattice
  computations (`tests/unit/test_paths.py`).
- Cost (measured): the 1,000 paths of a one-step run take 0.12 s for ten years of daily bars and
  0.84 s for 20,000 intraday bars; the cost stress is free; the reality check adds O(B x N x T) to
  `optimize` (seconds for a handful of values).
- Additive: no artifact schema changed, no existing metric or manifest key moved, and the product
  golden's surface is untouched.
- Not done: reality check over a multi-parameter or multi-strategy sweep (only the 1-D `optimize`
  panel feeds it), an MCP tool for `simulate-paths` (agents get the block from `crucible_backtest`),
  and an effective-number-of-trials estimate for the deflated Sharpe.
