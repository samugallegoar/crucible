# Module: portfolio

## What exists

Signals to target weights. Detail sections follow.

- `constructors.py` — `EqualWeightConstructor`, `FixedFractionalConstructor`, `VolTargetConstructor`,
  `RiskParityConstructor`, `FractionalKellyConstructor`, `MeanVarianceConstructor`.
- `registry.py` — `build_constructor` (keys in `docs/INVENTORY.md`).
- `interfaces.py` — the Protocols `PortfolioConstructor` and `TargetSetter` (`ctx.targets`).

## Responsibility
Turning signals into target positions — separate from alpha (strategy) and
from execution. Constraints and optimizers plug in here.

## Interfaces (`crucible/portfolio/interfaces.py`)
- `TargetSetter.set/set_all` — the strategy-facing declarative target API;
  weights are fractions of equity. Implemented by `strategy.context.
  EngineTargetSetter` (ADR-0029) — no longer a placeholder.
- `PortfolioConstructor.construct(signals, portfolio, as_of, history=None)`
  — target weights using only information available at `as_of`.
  `signals[symbol] > 0` marks a long candidate (constructors are long-only);
  `history` is each candidate's recent return series, computed by the
  *strategy* through its own PIT accessor — required by the four
  size-aware built-ins, ignored by the other two.

## Built-ins (`crucible/portfolio/constructors.py`, ADR-0029)
| Constructor | Treatment | Needs `history` | Notes |
|---|---|---|---|
| `EqualWeightConstructor` | — | no | 1/N across top `top_k` (or all) candidates by signal |
| `FixedFractionalConstructor` | — | no | every candidate gets the same fixed fraction; weights need not sum to 1 |
| `VolTargetConstructor` | diagonal | yes | `min(target_vol / vol_i, max_weight)` per symbol |
| `RiskParityConstructor` | diagonal | yes | inverse-vol, normalized to sum to 1 (capping can break that sum — documented, not renormalized) |
| `FractionalKellyConstructor` | diagonal | yes | `clip(fraction * mu_i / var_i, 0, max_weight)`, per-asset only |
| `MeanVarianceConstructor` | correlation-aware | yes | `w = (1/risk_aversion)·Σ⁻¹μ` via `numpy.linalg.solve` (ridge-regularized), then clipped to `[min_weight, max_weight]` — clipping approximates "with constraints," not a true QP |

Diagonal treatments ignore cross-asset covariance; only `MeanVarianceConstructor`
uses the full sample covariance matrix. No scipy/cvxpy dependency (CLAUDE.md's
core-library list) — see ADR-0029 for why this is two treatments, not six.

## Registry (`crucible/portfolio/registry.py`)
`build_constructor(key, **params)` — stable-key factories mirroring
`execution/registry.py`/`risk/registry.py`; keys: `equal_weight`,
`fixed_fractional`, `vol_target`, `risk_parity`, `fractional_kelly`,
`mean_variance`. Portfolio never imports the experiments layer. Not wired
into `ExperimentConfig` — a constructor is a library a strategy chooses to
call with its own `signals`, not something the engine applies automatically
(unlike execution models or the risk engine).

## Target resolution (`crucible/core/engine.py`, ADR-0029)
`BacktestEngine.resolve_target`/`resolve_targets` (the `TargetRouting`
surface `EngineTargetSetter` forwards to) turn a declared weight into a
real order **synchronously, immediately** — not deferred or batched:
1. Fold the ledger once; compute equity and current positions from that
   one snapshot (`resolve_targets`: every symbol in `weights` unioned with
   every symbol currently held a nonzero position in — "symbols absent
   mean weight 0"; `resolve_target`: only the one named symbol).
2. Per symbol: skip (log, no error) if there's no mark yet — sizing a
   trade with no price is impossible, not merely risky. Otherwise convert
   the weight's base-currency notional into the symbol's own currency
   (`accounting.fx.convert_from_base_at_mid`, ADR-0025's mid-rate marking
   role) and floor (`ROUND_DOWN`) into a target quantity.
3. Submit a market order for the delta against the current position
   through the exact same `submit_spec` path `ctx.orders.submit` uses —
   every pre-trade risk check (ADR-0027) and settlement-lag-aware sizing
   (ADR-0028) already applies with no special-casing.

All symbols in one `resolve_targets` call are sized against the same
snapshot taken at the call's start — deliberate "simultaneous rebalance"
semantics, not a staleness bug, even if an earlier symbol's order in the
same call fills instantly (Level 0).

## Extension points
New constructors implement `PortfolioConstructor` and register a stable
key in `crucible/portfolio/registry.py`. A future QP-based
`MeanVarianceConstructor` variant (or a true active-set solver) can replace
the clip-based approximation behind the same method with no caller change.

## Known gaps
No example strategy has been migrated from hand-rolled weight→order logic
(`examples/momentum/strategy.py`) to `ctx.targets` + a constructor —
neither is required to change; the momentum example's own logic keeps
working. Target resolution is single-strategy: how several strategies'
target books would compose on one portfolio is not defined (multi-strategy
runs use `MultiStrategy`, ADR-0030). `ctx.targets` places no long-only restriction beyond
what raw order submission already allows (a negative weight is legal,
mechanically identical to a strategy submitting the same SELL itself).
