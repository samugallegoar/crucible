# ADR-0029: Portfolio constructors and target resolution (Phase 4 priority)

- **Status**: accepted
- **Date**: 2026-09-19

## Context

`crucible/portfolio/interfaces.py::PortfolioConstructor` (`construct(signals,
portfolio, as_of) -> weights`) and `TargetSetter` (`ctx.targets.set/set_all`)
have existed as Protocols since the Phase 0 scaffold with zero
implementations — `ctx.targets` unconditionally raised `ConfigurationError`
(`_TargetsNotYetAvailable`), and `docs/modules/portfolio.md` listed "no
implementations" as a known gap. The original requirements ask for six built-ins (equal
weight, fixed fractional, vol targeting, risk parity, fractional Kelly,
mean-variance with constraints) and a pluggable-optimizer interface; the original requirements say strategies emit "targets *or* orders" via `ctx.targets.set(...)`
as an alternative to `ctx.orders.submit(...)`.

`examples/momentum/strategy.py` already hand-rolls the weight→order diff
(target qty from equity×weight/price, floor, delta against current
position, submit BUY/SELL) — the reference shape this priority generalizes
into a reusable engine mechanism instead of per-strategy duplicated code.

Three design questions had no precedent: (1) how does a constructor that
needs a volatility/covariance estimate get one, given `construct`'s
existing three-argument signature carries no data access; (2) when and how
does a declared weight actually become an order; (3) how does multi-currency
sizing work when a weight is "a fraction of base-currency equity" but the
symbol trades in its own currency.

## Decision

**(1) `construct` gains an optional fourth parameter, `history:
Mapping[Symbol, Sequence[float]] | None = None`** — each candidate symbol's
recent return series, computed by the *strategy* through its own PIT
accessor (exactly like `examples/momentum/strategy.py` already does via
`ctx.data.history(...)`) and handed to the constructor. A constructor never
holds or receives a PIT accessor itself — it only transforms values the
strategy already computed under the PIT discipline, so nothing inside
`crucible/portfolio/` can leak the future on its own. `EqualWeightConstructor`
and `FixedFractionalConstructor` ignore `history` (default `None` is fine);
the four size-aware constructors raise `ConfigurationError` if a selected
symbol's history is missing or has fewer than 2 points (a sample stdev needs
at least 2 observations). This is a backward-compatible extension (optional,
defaulted) of an interface that had zero implementations before this
priority, so there is no migration cost.

**Selection convention (long-only for now, Phase 5 adds shorts): `signals[s]
> 0` marks a long candidate.** Its magnitude is the expected-return input to
size-aware constructors; `EqualWeightConstructor` only uses it to rank.
A symbol absent from `signals`, or with a non-positive value, is never
selected by any built-in constructor.

**Two documented treatments, not six independent designs** (no scipy/cvxpy
dependency — CLAUDE.md's core-library list is Polars/NumPy/DuckDB/PyArrow/
Pydantic/exchange_calendars/Numba):
- **Diagonal** (`VolTargetConstructor`, `RiskParityConstructor`,
  `FractionalKellyConstructor`): each symbol's own variance only, ignoring
  correlation. `RiskParityConstructor` is *inverse-volatility* weighting,
  the diagonal special case of risk parity — equal risk contribution holds
  exactly only when correlations are zero; the fully correlation-aware
  equal-risk-contribution solution needs an iterative solver, out of scope.
  `FractionalKellyConstructor` is per-asset Kelly (`f* = μ/σ²`, scaled by a
  fractional multiplier) — the portfolio-optimal Kelly needs the full
  covariance matrix and its inverse, which is exactly what the sixth
  constructor provides.
- **Correlation-aware** (`MeanVarianceConstructor`): the full sample
  covariance matrix via `numpy.linalg.solve` against a ridge-regularized
  matrix (`Sigma + ridge·I`, avoiding a singular-matrix crash when history
  is short or symbols move in lockstep) — the closed-form unconstrained
  tangency portfolio `w = (1/risk_aversion)·Σ⁻¹μ`. "With constraints" is
  satisfied by clipping the unconstrained solution to `[min_weight,
  max_weight]`, not a true active-set QP — this is the honest, dependency-free
  approximation: it keeps every weight legal without a solver, but a clipped
  weight is no longer the exact constrained optimum. A future session can
  swap in a real QP solver behind the same method if a dependency decision
  is made; nothing about this ADR's callers would need to change.

Both treatments are floored/regularized against divide-by-zero (`_MIN_VOL =
1e-9` on every sample stdev; `ridge` on the covariance matrix) rather than
raising on a degenerate zero-variance history — a numerical safety floor,
not a modeling choice, documented inline.

**(2) A declared weight resolves into an order synchronously, immediately,
inside the `set`/`set_all` call** — not deferred to end-of-bar or batched
across an entire session. `BacktestEngine.resolve_target`/`resolve_targets`
(the `TargetRouting` Protocol `EngineTargetSetter` forwards to, mirroring
`EngineOrderSubmitter`/`OrderRouting`) fold the ledger once, compute equity
and current positions from that single snapshot, then for every symbol in
scope: skip if there's no mark yet (log, no error — sizing a trade with no
price is impossible, not merely risky, so there's nothing safe to assume);
otherwise convert the weight into a target quantity (`floor` toward zero via
`ROUND_DOWN`, so a negative delta from a hypothetical negative weight
truncates the same way a positive one does) and submit a market order for
the delta against the current position, through the exact same `submit_spec`
pipeline `ctx.orders.submit(...)` uses — meaning every existing pre-trade
risk check (ADR-0027) and settlement-lag-aware sizing (ADR-0028, via
`InsufficientCashLimit`) already applies to a target-derived order with no
special-casing.

Deferring resolution (e.g., collecting all `set`/`set_all` calls across a
bar and resolving once after every symbol's bar event at that timestamp has
been processed) was considered and rejected: it would need new engine state
to track "pending, not-yet-resolved" targets across an unbounded number of
events, and — unlike the ex-date/pay-date split dividends needed
(ADR-0026) — there is no the original requirements requirement or accounting reason a target
needs to wait. A strategy that wants cross-sectional information from every
symbol's bar before rebalancing already gets that today by querying history
strictly before the current session (`examples/momentum/strategy.py`'s own
technique, unchanged) rather than needing today's bars to be fully in.

**`set_all` replaces the full target book: every symbol currently held but
absent from the new weights is driven to weight 0** (`TargetSetter.set_all`'s
existing contract, "symbols absent mean weight 0") — resolved by unioning
the new weights' keys with every symbol the *ledger* currently holds a
nonzero position in (no separate "previously targeted" state needs to be
tracked; the position is the record). `set` touches only the one symbol
named, leaving every other symbol's position alone.

**All symbols in one `resolve_targets` call are sized against the same
equity/position snapshot taken once at the start of that call**, even
though an earlier symbol's order in the same call could in principle fill
instantly (Level 0/frictionless) and would otherwise change equity
mid-loop. This is deliberate "simultaneous rebalance" semantics — a real
rebalance computes every leg's target trade off one NAV number taken at the
start, not a moving target that shrinks as each leg fills — not a staleness
bug.

**(3) Multi-currency sizing**: a weight is a fraction of `equity(base)`;
the target symbol may trade in its own currency (`ADR-0025`). New
`accounting/fx.py::convert_from_base_at_mid` (the mirror of the existing
`convert_at_mid`, dividing instead of multiplying since `mid_rates` is still
keyed `ccy → base`) converts the base-currency target notional into the
symbol's own currency before dividing by its own-currency mark. FX mid
rates are needed for a symbol's currency *before* any position in it
exists (sizing a brand-new position), so `_fx_mid_rates_at` gained an
`extra_currencies` parameter — its prior behavior (rates for currently-held
cash/position currencies only) is unchanged for its other two call sites
(`_current_snapshot`, `_mark`), which pass no extra currencies.

**No new restriction on negative weights (shorts).** Nothing in
`ctx.orders.submit` today prevents a raw SELL from flipping a position net
short (Phase 5 formally introduces margin/borrow modeling, but the ledger/
position math already handles a negative `qty` correctly, as ADR-0026's
short-dividend test demonstrates). `ctx.targets` behaves exactly as if the
strategy had computed the same diff itself and called `ctx.orders.submit`
— adding a target-specific restriction that raw order submission doesn't
have would be inconsistent special-casing, not a genuine safety gain.

## Alternatives considered

- **Threading a PIT accessor into `PortfolioConstructor.construct` directly**
  (so a constructor could pull its own history): rejected — the module's own
  docstring already frames constructors as receiving only PIT-safe *inputs*
  from the strategy, never the data layer itself; handing constructors a
  live accessor would blur that boundary and let a future constructor
  accidentally read data outside its declared `as_of`.
- **A single "mean-variance is the only correlation-aware built-in, the rest
  fold into it via risk_aversion→∞"**: considered to cut the built-in count,
  rejected — `RiskParityConstructor` and `FractionalKellyConstructor` have
  distinct, individually well-known formulas (inverse-vol; `μ/σ²`) that
  practitioners expect by name; collapsing them into one parameterized
  mean-variance call would obscure which formula is actually running.
- **Deferred/batched target resolution**: rejected, see Decision above.
- **Renormalizing weights after clipping** (so a capped `RiskParityConstructor`
  or `MeanVarianceConstructor` output still sums to 1): rejected — 
  renormalizing after a cap reintroduces the concentration the cap exists to
  prevent (iteratively, if applied repeatedly); real risk-limit caps are
  left unrenormalized in practice, and this is documented explicitly on
  `RiskParityConstructor` rather than silently changing weights the caller
  didn't ask for.
- **Restricting `ctx.targets` to long-only (raising on a negative weight)**:
  rejected — no restriction exists for the equivalent raw-order path, and
  Phase 5 (not this priority) is where short/margin semantics get designed
  properly; adding an inconsistent guard now would need to be un-added later.

## Consequences

New `crucible/portfolio/constructors.py` (six classes) and
`crucible/portfolio/registry.py::build_constructor` (mirrors
`execution/registry.py`/`risk/registry.py`'s stable-key-to-factory
pattern — registered for config-driven use, though the primary consumption
path is a strategy instantiating a constructor directly in its own Python
code, since the engine has no way to know what a strategy's `signals`
mean). `PortfolioConstructor.construct` gained the optional `history`
parameter (Consequences of (1) above). `accounting/fx.py` gained
`convert_from_base_at_mid`. `BacktestEngine._fx_mid_rates_at` gained an
`extra_currencies` parameter (additive, existing call sites unaffected).
`BacktestEngine` gained `resolve_target`/`resolve_targets` (the
`TargetRouting` surface) and private helpers `_resolve_target_weights`/
`_resolve_one_target`. `strategy/context.py`'s `_TargetsNotYetAvailable`
placeholder is gone; `BacktestContext.targets` now returns a real,
functioning `EngineTargetSetter` — `ctx.targets.set`/`set_all` no longer
raise. `docs/ARCHITECTURE.md`'s "Known divergences" line claiming
"strategies submit orders directly and `ctx.targets` refuses" is corrected.

Tests: `tests/unit/test_portfolio_constructors.py` (21, hand-computed —
including a 3-point-series stdev trick, `[x-d, x, x+d]`, that gives an
*exact* decimal sample stdev of `d`, avoiding irrational hand-computation),
`tests/property/test_portfolio_constructors_properties.py` (6, arbitrary signals/
history stay within each constructor's declared bounds), `tests/integration
/test_portfolio_targets.py` (3, real `BacktestEngine` runs — `set` sizes one
symbol from equity/mark; `set_all` replaces the full book and zeroes an
absent symbol; a foreign-currency symbol sizes correctly via
`convert_from_base_at_mid`, with equity conserved exactly as ADR-0025's own
multi-currency test already demonstrated).

No `ExperimentConfig` field or golden-fixture change: nothing about this
priority is applied automatically by the engine regardless of strategy code
(unlike the risk engine or settlement lag) — a constructor is a library a
strategy chooses to call, so no existing example's config or output
changes, and no golden regeneration is needed.

Known gaps carried forward: `MeanVarianceConstructor`'s constraint handling
is clip-based, not a true QP (documented above); no example strategy in
`examples/` has been migrated from its hand-rolled weight→order logic to
`ctx.targets` + a constructor yet (the momentum example's own logic still
works unchanged and isn't required to change); multi-strategy attribution
(Phase 4's next priority) will need to decide how multiple strategies'
target books compose when they share one portfolio — not addressed here,
since this priority is single-strategy only, matching every prior Phase 4
priority.
