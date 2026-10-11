# ADR-0071: One drawdown definition, calendar-aware dataset identity, DSR assumptions and calibration, precise point-in-time semantics

- **Status**: accepted
- **Date**: 2026-10-11

## Context

A follow-up review raised four findings. Each was checked against the code before any change.

1. **Maximum-drawdown bootstrap (confirmed).** `analytics.metrics._max_drawdown_from_returns`
   rebuilt equity as `cumprod(1 + r)` with no starting 1.0, so a first-period loss vanished
   (`[-0.10, 0.10]` gave 0 % instead of -10 %). The point estimate runs on the equity curve, which
   does start at the initial capital, so the bootstrap interval targeted a different statistic
   than the number it was printed next to. `validation.monte_carlo` had its own copy of the same
   reconstruction with the same defect (the two layers are siblings and could not share code).
2. **Dataset identity omits the calendar (confirmed).** `product.data.dataset_name` keyed on
   provider, symbols, window, interval and basis, but `ensure_dataset` passes the calendar to the
   provider, where it decides each daily bar's `event_time` (the session close) and drops days
   that are not sessions. The same request under XNYS and 24/7 is different data, yet the second
   request reused the first's dataset; reuse trusted the name alone.
3. **DSR assumptions and calibration (partly confirmed).** The formulas match Bailey & López de
   Prado (PSR with Pearson kurtosis, the extreme-value expected maximum; ADR-0070 checked them).
   Found: `N` was `len(trial_sharpes)`, so trials recorded without a Sharpe (rows from before the
   column existed) silently dropped out of `N`, and an empty list deflated against 0; non-finite
   trial Sharpes were not checked; nothing stopped a family from pooling per-period Sharpes of
   different return frequencies (daily and weekly are not comparable); no simulation measured how
   the best-of-N DSR procedure behaves under a known null.
4. **Point-in-time semantics (partly confirmed).** The query-time barrier holds (clock guard, then
   `available_at <= as_of` inside the read itself). Found: `StorePITAccessor.history` returned a
   revised observation (same `event_time`, later `available_at`) as a second observation, so a
   moving average counted that bar twice; a provider refresh overwrote a stored dataset in place
   (old runs stay traceable through their content hash, but the previous data was gone); nothing
   refused adjusted bars combined with a cash-dividend corporate-actions dataset, which counts every
   dividend twice.

## Decision

1. **One drawdown definition** in a new pure module, `crucible.core.drawdown` (its own layer just
   above the bottom one, so `analytics` and `validation` both import it): `max_drawdown(equity)`
   on a path whose first value is the starting capital, and `max_drawdown_from_returns(returns)`
   on `[1.0, cumprod(1 + r)]`. The point estimate and every bootstrap and Monte Carlo resample
   use it. Drawdown stays in `(-1, 0]`. Non-finite values, non-positive equity and returns of
   -100 % or worse are refused (`CrucibleError`), never repaired. An empty return series is the
   path `[1.0]` (drawdown 0).
2. **Dataset identity v2.** `canonical_calendar` (data layer) gives one name per set of sessions:
   `"24/7"`, or the `exchange_calendars` code after upper-casing and alias resolution (`nyse`,
   `NYSE`, `XNAS` -> `XNYS`); unknown names are refused. The calendar joins the dataset name
   (`..._adj_xnys`, `..._adj_247`; `dataset_name` defaults to XNYS so existing calls keep
   working). `request.json` beside each product dataset records the effective request (provider,
   symbols, window, interval, price basis, canonical calendar, OHLC repair mode, identity version)
   and a stored dataset is reused only when that record matches; otherwise it is fetched again, or
   refused when offline. Datasets from before this ADR have neither the new name nor a record, so
   they are never misread: the request is fetched again. A fetch that replaces a stored dataset
   first moves it to `<home>/archive/<name>/<content hash>/`; the result reports
   `replaced_content_hash`. The provider's own data version (Yahoo re-adjusts history) is not an
   input Crucible can name; the content hash and build time are what record it.
3. **DSR inputs made explicit.** `deflated_sharpe_ratio(..., n_trials=)` takes the trial count
   separately from the recorded Sharpes: unrecorded Sharpes still count toward `N`, the dispersion
   comes from the ones that exist, and with fewer than two for `N > 1` the benchmark is unknown and
   DSR is refused. `n_trials < 1`, more Sharpes than trials and non-finite Sharpes are refused.
   Runners pass the registry's trial count; manifests gain `dsr_n_trials_with_sharpe`. The registry
   records each trial's return period (`period_ns`, the median spacing of its equity marks; old
   registries migrate in place with `ADD COLUMN IF NOT EXISTS`), and DSR is refused when the pooled
   trials' periods differ by 1.5x or more (daily on XNYS and on 24/7 both have a one-day median and
   pool; daily and weekly do not).
4. **Family membership rules** (one-step backtest; ADR-0070 set them, this ADR states them as
   rules). A *trial* is a distinct experiment id: a pure function of the config (rules, window,
   costs, capital, seed, family) and the content hashes of its data. Re-running the same config on
   the same data is the same trial and is not counted again; changing anything in the config,
   including the window or the seed, is a new trial. The *family* defaults to the symbol set
   (`quick:<symbols>`); an explicit `family` overrides it. The *home-wide* count is every distinct
   experiment in the home's registry. Both DSRs are reported and labelled; the home-wide one is a
   conservative bound over a heterogeneous pool, not a calibrated DSR of a defined search. Neither
   can see trials run outside the home (`trial_count_scope` says so).
5. **Calibration measured, not assumed.** `tools/dsr_calibration.py` simulates the researcher's
   procedure (evaluate `N` strategies, pick the best in-sample Sharpe, compute its DSR against all
   `N`) and reports how often DSR >= 0.95. Results are below. No threshold was changed.
6. **Point-in-time terms separated** (docs/modules/data.md): *query-time restriction* (the clock
   guard and the `available_at` filter, enforced in code); *availability timestamps* (what the
   dataset says, trusted as given: a provider's adjusted series is stamped with the bar's own
   close, not with when the adjusted value was computed); *version integrity* (not provided: the
   store keeps one version per dataset, plus the product's archive of replaced versions, so it
   cannot reconstruct the information set of a past date); *price basis* (declared in the manifest
   source, recorded in each run's manifest as `bars_price_basis`, `undeclared` when unknown).
   `history` now counts a revised observation once, as the latest version available at `as_of`.
   The engine refuses adjusted bars together with a corporate-actions dataset holding cash
   dividends; a dataset that does not declare its basis cannot be checked.

## DSR calibration results

`uv run python -m tools.dsr_calibration` (seed 20261011, 1,000 replications per scenario, 34.9 s):
the rate of DSR >= 0.95 for the selected best-of-N strategy, with 95 % Wilson intervals, and the
undeflated PSR against 0 of the same strategy for contrast.

| scenario | DSR >= 0.95 | naive PSR >= 0.95 | picked the edge |
|---|---|---|---|
| i.i.d. normal, N=1, T=252 | 0.053 [0.041, 0.069] | 0.053 | - |
| i.i.d. normal, N=1, T=1260 | 0.058 [0.045, 0.074] | 0.058 | - |
| i.i.d. normal, N=10, T=252 | 0.000 [0.000, 0.004] | 0.403 | - |
| i.i.d. normal, N=10, T=1260 | 0.000 [0.000, 0.004] | 0.434 | - |
| i.i.d. normal, N=100, T=252 | 0.001 [0.000, 0.006] | 0.994 | - |
| i.i.d. normal, N=100, T=1260 | 0.001 [0.000, 0.006] | 0.992 | - |
| heterogeneous windows, N=20, T in [126, 2520] | 0.001 [0.000, 0.006] | 0.471 | - |
| AR(1) phi=0.2, N=10, T=1260 | 0.004 [0.002, 0.010] | 0.614 | - |
| AR(1) phi=0.2, N=100, T=1260 | 0.005 [0.002, 0.012] | 1.000 | - |
| Student-t df=4, N=10, T=1260 | 0.002 [0.001, 0.007] | 0.400 | - |
| Student-t df=4, N=100, T=1260 | 0.000 [0.000, 0.004] | 0.992 | - |
| correlated rho=0.9, N=100, T=1260 | 0.040 [0.030, 0.054] | 0.191 | - |
| one edge (per-period SR 0.08), N=10, T=1260 | 0.108 [0.090, 0.129] | 0.916 | 0.881 |
| one edge (per-period SR 0.08), N=100, T=1260 | 0.067 [0.053, 0.084] | 1.000 | 0.605 |

Reading:

- With one trial the procedure is the PSR against zero and is close to its nominal 5 %.
- With N > 1 the DSR >= 0.95 rule was **conservative in every null tested**: 0.0-0.5 % for
  independent strategies, heterogeneous windows, AR(1) autocorrelation and fat tails, 4.0 % for
  highly correlated strategies (where the estimated dispersion shrinks with the effective N).
  Selection without deflation is badly anti-conservative (40-100 %).
- The price is **power**: a strategy with a true per-period Sharpe of 0.08 (about 1.27 annualized)
  over five years of daily data reached DSR >= 0.95 in only 10.8 % (N=10) and 6.7 % (N=100) of
  replications. The benchmark is the *expected* maximum Sharpe, and the edge strategy itself widens
  the estimated cross-trial dispersion.
- These are synthetic processes. The study does not cover regime changes, trials that share
  data in more complex ways, or searches the registry never saw.

`tests/integration/test_dsr_calibration.py` re-runs a 300-replication subset and pins that the null
rate stays within nominal plus two binomial standard deviations and that an edge is flagged more
often than the null.

## Alternatives considered

- **Patch both drawdown copies in place.** Leaves two definitions that can drift again; the shared
  module costs one layer line in `pyproject.toml`.
- **`str(calendar)` in the name.** Gives `nyse`, `NYSE` and `XNYS` three datasets for one set of
  sessions; resolution through `exchange_calendars` names the sessions, not the spelling.
- **Keep old dataset names for XNYS.** Old datasets have no record of the calendar they were built
  with, so reusing them would trust exactly what this ADR stops trusting.
- **An effective-number-of-trials estimate for correlated trials.** Not implemented: the measured
  rule is already conservative under strong correlation; an estimate would raise power but needs
  its own validation.
- **A bitemporal, versioned store.** Out of scope; the limitation is stated instead, and the
  product's archive keeps the versions it replaces.

## Consequences

- `metrics.json` `max_drawdown` intervals change for runs whose resamples start with a loss; the
  momentum golden's `metrics.json` hash moved (all five simulation artifacts are byte-identical).
- One-step datasets get new names and a `request.json`; a home's existing datasets are fetched
  again on first use (offline runs of old requests are refused with the reason).
- Trial registries gain a `period_ns` column (migrated in place); run manifests gain
  `bars_price_basis` and `dsr_n_trials_with_sharpe` (additive).
- A run that combines adjusted bars with cash dividends now fails at construction with the reason.
- DSR reports "not computable" for families that mix return frequencies or lack enough recorded
  Sharpes, instead of a number.
