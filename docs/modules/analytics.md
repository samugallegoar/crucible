# Module: analytics

## What exists

Metrics with uncertainty, the trade log, plots and the report. Detail sections follow.

- `metrics.py` — `compute_metrics` and `simple_returns`. Keys of `metrics.json`: `sharpe`, `cagr`,
  `max_drawdown` (each with a block-bootstrap CI), `volatility`, `n_periods`, `n_trades`,
  `hit_rate` (only when the run had trades); units in `docs/CONVENTIONS.md` §2.
- `trades.py` — `build_trades` (FIFO round trips, base-currency PnL split into price and FX),
  `build_episodes` (closed position episodes of a vectorized run, from its pnl frame, ADR-0061/0062).
- `attribution.py` — `per_strategy_pnl_deltas`, `strategy_correlation`, `marginal_risk_contribution`.
- `plots.py` — `plot_equity_drawdown` (deterministic SVG).
- `report.py` — `render_report` (refuses without the provenance header and DSR/PBO summary).
- `interfaces.py` — `MetricValue` (a value with its CI) and the Protocols `MetricsComputer` and
  `ReportRenderer`, which are stubs: the working code is the free functions above.

## Responsibility
Metrics with uncertainty, the trade log, plots, and report rendering. The
reporting rule is structural: estimates carry bootstrap CIs; reports refuse
to render without full provenance and without a DSR/PBO validation
summary — real values or an explicit reason, never silently missing.

## Implementations
- `metrics.py`: `compute_metrics(equity, trades, rng, periods_per_year)` —
  Sharpe, CAGR, and max drawdown (R4.8) all carry circular-block-bootstrap
  percentile intervals at a nominal 95 % (block length `floor(sqrt(n))`, 1,000 resamples;
  seeded rng ⇒ deterministic). They are **approximate**: their coverage was measured only on
  synthetic processes (`tools/bootstrap_coverage.py`, ADR-0070, results in Known gaps), and
  volatility, hit rate, trade count and the one-step report's return and drawdown figures carry
  none. Maximum drawdown has one definition, `crucible.core.drawdown` (ADR-0071): the path
  starts at the initial capital (1.0 for a resample), so the point estimate and every bootstrap
  resample measure the same statistic; before ADR-0071 the resample path dropped its starting
  value and missed a first-period loss. Also volatility, hit rate,
  trade count. Refuses <3 equity points and post-ruin curves. Risk-free
  rate 0 (documented). `simple_returns
  (equity)` is the shared per-period return series both this and
  `validation.dsr` operate on (ADR-0015) — extracted so the two never
  silently drift apart.
  A series with no dispersion (a strategy that never traded, or a constant
  per-period return whose values differ only by float dust) has no Sharpe
  ratio: `sharpe` and `volatility` report `0.0`, the shared estimators live in
  `crucible/core/stats.py` with the DSR and the Monte Carlo, and the runners
  record a `NULL` trial Sharpe instead of the ~1e14 one this used to produce
  (ADR-0079).
- Two realized-PnL definitions coexist by design (2026-10 audit, M8): the **ledger**
  (`realized_pnl`) uses average cost (`PositionState.apply`), while **`trades.parquet`** uses
  FIFO lots. Buy 10 @100, buy 10 @90, sell 10 @105 gives ledger realized 100 (10 left at 95) and
  trade-log PnL 50. Both are internally consistent; they answer different questions ("what did
  the book realise on the position" vs "what did each round trip earn") and are not meant to add
  up to each other. The trade log is gross of commissions, which the ledger books separately.
- `trades.py`: `build_trades` — FIFO lot matching per symbol, longs and
  shorts, gross PnL, holding period; typed empty frame when no round trips.
  `build_episodes(weights, pnl)` (ADR-0061, ADR-0062) — closed position episodes from a
  vectorized run's lagged weights and its per-symbol gross pnl frame: a maximal same-sign run of
  the weight, entry at the close before the first held bar, exit at the close of the last held
  bar, pnl = the sum of the pnl frame over the held bars (base currency, before costs);
  open episodes are not listed. Not comparable with the lot-level `n_trades` of `build_trades`.
- `attribution.py` (ADR-0030): `per_strategy_pnl_deltas(fill_rows,
  period_ts)` — realized cash flow (fill notional minus commission),
  tagged by `strategy_id` (`strategy.multi.MultiStrategy`), bucketed onto
  the same `ts` grid as `equity_rows`; a wide frame, one float column per
  strategy plus `UNATTRIBUTED` for untagged fills (single-strategy runs,
  or an engine-generated order like a risk FLATTEN). Realized-only by
  design — an *open* shared-symbol position has no single owner to split
  unrealized PnL between (known gap, not a bug). `strategy_correlation`
  (Pearson, long format: `strategy_id`/`other_id`/`correlation`) and
  `marginal_risk_contribution` (`Cov(pnl_i, portfolio_pnl) /
  SD(portfolio_pnl)`, `portfolio_pnl` = sum of strategy columns,
  `UNATTRIBUTED` excluded) operate on raw $ PnL deltas, not normalized
  returns — correlation is scale-invariant either way, and there is no
  per-strategy capital allocation to normalize against in a shared
  portfolio. `sum_i MRC_i == SD(portfolio_pnl)` exactly (covariance
  decomposition of a sum) — this is the attribution demonstration
  exercised end-to-end in
  `tests/integration/test_multi_strategy_attribution.py`.
- `plots.py`: `plot_equity_drawdown` — deterministic SVG (fixed hashsalt,
  date stripped; ADR-0011).
- `report.py`: `render_report` — validates the 10 mandatory header fields
  plus a mandatory `validation_summary` (`dsr`, `pbo` — caller-
  formatted text, kept here as plain strings so this module doesn't import
  `validation`, which sits above it in the layered view) before
  rendering; embeds the SVG inline. Optional `monte_carlo` parameter
  (test name → named stats, also plain data) renders a report section of
  Monte Carlo distributions — optional, unlike
  `validation_summary`, so re-rendering an older manifest without it
  degrades gracefully (ADR-0017). Optional `factor_regression` parameter
  (plain dict: `alpha`/`alpha_t_stat`/`loadings`/`r_squared`/`n_obs`,
  same plain-data convention as `monte_carlo`) renders the "Factor
  regression" section — populated only by `crucible validate --factors`
  (ADR-0022); every other caller renders an explicit "not computed"
  message rather than omitting the section.

## Extension points
New metrics are pure functions added to `compute_metrics`'s dict; new checks
on the header extend `REQUIRED_HEADER_KEYS`. Regime labelers and the cost
waterfall arrive Phases 2–3.

## Known gaps
- The bootstrap intervals are approximate. Measured coverage of the nominal-95 % Sharpe interval
  (`tools/bootstrap_coverage.py`, 400 replications per cell, MC s.e. ≈ 0.011): 0.91-0.93 at
  n = 252 for every process tested (i.i.d. normal, zero alpha, Student-t 4, AR(1) 0.3, GARCH);
  0.94-0.95 at n = 1260 except Student-t 4 (0.91). The `sqrt(n)` block handles AR(1)
  autocorrelation (0.945 at n = 1260; an i.i.d. bootstrap gives 0.85). The CAGR and drawdown
  intervals have not been measured. No automatic block length, no bias-corrected (BCa) or
  studentized interval (ADR-0070).
- `MetricsComputer` and `ReportRenderer` are stub Protocols: `compute_metrics` and `render_report` are free functions with different signatures; nothing implements the Protocols.
Trade log omits delisting liquidations (ledger-only events). Its PnL is
base-currency and multiplier-scaled with a `pnl_price`/`pnl_fx` split per FIFO
lot (`pnl_fx = pnl - pnl_price` in Decimal, so the split sums to `pnl` to float
precision in the columns, ADR-0049); FX PnL is measured at
each lot's entry and exit rates only, and fill rows without `currency`/
`multiplier`/`fx_to_base` are refused. No rolling
metrics, exposures, MAE/MFE yet. Report is single-page HTML;
no interactive output. **Attribution valuation (ADR-0047):** `per_strategy_pnl_deltas` values each fill
as `(±qty * price * multiplier - commission) * fx_to_base` using the per-fill
columns the engine writes (`currency`, `multiplier`, `fx_to_base`). A futures
round trip sums to the realized PnL but its per-period timing differs from the
ledger's variation-margin bookings; FX PnL is not separated from price PnL; fill
rows from before ADR-0047 are refused. Tests: `tests/unit/test_attribution.py`, the EUR round trip in
`tests/integration/test_multi_currency_accounting.py` and the futures round
trip in `tests/integration/test_futures.py`.
