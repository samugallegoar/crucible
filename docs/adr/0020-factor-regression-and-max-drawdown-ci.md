# ADR-0020: Factor regression scope, numerical-perfect-fit guard, and the max-drawdown bootstrap CI

- **Status**: accepted
- **Date**: 2026-09-18

## Context

The original requirements: "Factor regression: excess returns on market, size, value,
momentum, quality, low-vol (user-supplied factor files); alpha t-stat and
factor loadings in every report." R4.8: "Confidence intervals: bootstrap
(block/stationary) CIs on Sharpe, CAGR, max DD." `analytics/metrics.py`
already had block-bootstrap CIs for Sharpe and CAGR (Phase 1); max
drawdown's `MetricValue` has always carried `ci_low=ci_high=None`.

## Decision

**Factor regression is pure OLS statistics on an explicit
`factors: Mapping[str, Sequence[float]]` argument, not file ingestion.**
`crucible/validation/factor_regression.py::factor_regression(returns,
factors) -> FactorRegressionResult` (`alpha`, `alpha_t_stat`, `loadings`,
`r_squared`, `n_obs`) takes already-aligned per-period factor return
series. The original requirements' "user-supplied factor files" (market/size/value/momentum/
quality/low-vol) is a data-ingestion and config concern this ADR does not
design — same status as PBO (ADR-0015): implemented and tested, **not**
wired into every report, because no config mechanism exists yet to
associate a run with factor files. It becomes reachable at the same point
PBO does: the future `optimize`/`validate` CLI (Phase 3 priority 9), which
is where a factor-file path would naturally join `DataConfig`.

**No p-value is reported alongside `alpha_t_stat`.** A p-value needs a
t-distribution CDF; this project has no `scipy`/`statsmodels` dependency
and AGENTS.md §9 forbids adding one for a hot-path-adjacent statistics
call. The raw t-statistic is reported (the original requirements' own wording: "alpha t-stat"),
matching DSR's precedent of reporting `dsr`/`benchmark_sharpe` without a
p-value either.

**A perfect or near-perfect in-sample fit is refused via a relative
residual-variance tolerance, not an exact-zero check.** OLS via
`np.linalg.inv` leaves floating-point noise (~1e-30 scale) even for an
exactly-representable perfect fit — an exact `se_alpha == 0.0` guard is
therefore effectively unreachable, and without a guard a near-singular fit
silently produces an astronomically large but finite t-stat (observed:
~1e16) instead of refusing, violating the pessimism rule (AGENTS.md §10).
The guard instead compares `ssr <= 1e-12 * sst`: comfortably above
float64 machine epsilon (~2.2e-16), far below any non-degenerate
residual variance, and directly testable with exact-integer inputs (see
`tests/unit/test_factor_regression.py::
test_rejects_a_numerically_perfect_fit`).

**`max_drawdown` now carries a block-bootstrap CI**, closing R4.8's gap.
`analytics/metrics.py::_max_drawdown_from_returns` reconstructs an equity
curve from a *returns* array (`cumprod(1 + returns)`, starting capital
fixed at 1.0 — scale-irrelevant to drawdown) because the bootstrap
resamples returns, not equity levels; this mirrors
`validation.monte_carlo`'s identical reconstruction for the identical
reason (ADR-0017), kept as a separate small function here rather than a
cross-module import of a private helper (`monte_carlo._max_drawdown_from_returns`
is that module's own private detail, not a shared utility this ADR
promotes). Consumes the same seeded `rng` stream `compute_metrics` already
threads through — deterministic, no new generator.

**This intentionally changed `metrics.json`'s bytes and regenerated the
golden fixture** (AGENTS.md §1.6/§7: never silently). Populating
`max_drawdown`'s previously-`null` `ci_low`/`ci_high` is exactly the
change; `sharpe`/`cagr`'s CIs are unaffected (the new bootstrap call is
appended after them, so it doesn't shift their draws from the rng
stream). Regenerated via `uv run pytest tests/golden --regen-golden`;
diff is exactly one file (`metrics.json`) as expected — see this commit's
message.

## Alternatives considered

- **Auto-wire factor regression into every report with a hardcoded
  placeholder factor** (e.g., the strategy's own return series as its own
  "market factor"): rejected — meaningless regression (perfect fit,
  degenerate by the guard above) and would misrepresent what the original requirements
  means by market/size/value/etc. factors. Leaving it unwired and
  explicitly flagged is more honest than a fake wiring.
- **Report a p-value via a hand-rolled t-distribution CDF approximation**
  (e.g., a rational-function or series approximation): rejected as
  needless numerical-accuracy risk for a still-dependency-free feature
  when the raw t-stat already satisfies the original requirements' literal requirement.
- **Exact `se_alpha == 0.0` guard** (simpler code): rejected — verified
  empirically unreachable via `np.linalg.inv` for realistic (or even
  exact-integer) perfect-fit inputs; would leave the real failure mode
  (near-singular fit, huge nonsensical t-stat) unguarded.
- **Reuse `validation.monte_carlo._max_drawdown_from_returns` directly**
  instead of a second copy in `analytics/metrics.py`: rejected — it's a
  private (`_`-prefixed) helper of a different module with no declared
  contract to be shared; promoting it would mean a new public export for
  a three-line function used by exactly two call sites, doing more
  restructuring than the max-DD CI gap warrants.

## Consequences

Factor regression is not reachable from `run_experiment`/`report.html`
today — same known-gap shape as PBO, `sweep_1d`, and perturbation:
implemented, tested, waiting on priority 9's CLI to supply real inputs
(factor files, here). `metrics.json`'s golden hash changed; anyone
diffing against an older commit's fixture will see exactly the
`max_drawdown` CI fields go from `null` to real numbers. The `1e-12`
relative-tolerance threshold, like `spike_threshold`/
`N_MONTE_CARLO_ITERATIONS`, is a pragmatic default, not literature-derived
— revisit if it ever proves too strict/loose once priority 10's
acceptance examples exist to calibrate against.
