# Module: risk

## What exists

Pre-trade and per-mark checks. Detail sections follow.

- `engine.py` — `CompositeRiskEngine` and the limit Protocols `PreTradeLimit`, `MarkLimit`.
- `limits.py` — pre-trade `MaxOrderNotionalLimit`, `MaxGrossExposureLimit`, `InsufficientCashLimit`,
  `MarginRequirementLimit`; mark `DrawdownHaltLimit`, `DailyLossFlattenLimit`, `MarginCallLimit`.
- `registry.py` — `build_pre_trade_limit`, `build_mark_limit`.
- `interfaces.py` — `RiskAction`, `RiskDecision` and the `RiskEngine` Protocol.

## Responsibility
Pre-trade checks on every order and continuous checks on every mark. Every
non-ALLOW action (reject/resize/flatten/halt) is logged, never silent
(ADR-0027).

## Interfaces (`crucible/risk/interfaces.py`)
- `RiskEngine.pre_trade(order, portfolio) -> RiskDecision` — never mutates
  anything; called before an order is accepted.
- `RiskEngine.on_mark(portfolio, ts) -> RiskDecision` — called after every
  mark.
- `RiskDecision(action, reason, resized_qty)`; `RiskAction` enum: `ALLOW`,
  `REJECT`, `RESIZE`, `FLATTEN`, `HALT`. `resized_qty` is set only for
  `RESIZE`.

## Composition (`crucible/risk/engine.py`)
`CompositeRiskEngine` satisfies `RiskEngine` by composing an ordered list
of small limits, each its own Protocol:
- `PreTradeLimit.check(order, portfolio, base_currency) -> RiskDecision`
- `MarkLimit.check(portfolio, ts, base_currency) -> RiskDecision`

Checked in list order; the first non-ALLOW decision short-circuits the
rest — put the most severe/important limits first. A new limit type never
touches `CompositeRiskEngine`, only the relevant Protocol (AGENTS.md §6).

## Built-in limits (`crucible/risk/limits.py`)
| Limit | Kind | Action | Notes |
|---|---|---|---|
| `MaxOrderNotionalLimit` | pre-trade | ALLOW / RESIZE / REJECT | caps one order's own base-currency, multiplier-scaled notional (`PortfolioView.notional`, ADR-0045); RESIZE-capable since it needs no existing-position math |
| `MaxGrossExposureLimit` | pre-trade | ALLOW / REJECT | caps Σ\|position value\| at `max_ratio * equity`; REJECT-only (a safe RESIZE under a direction flip isn't implemented yet); **never blocks a risk-reducing order**, regardless of how over-limit the book already is (pessimism rule, ADR-0027) |
| `DrawdownHaltLimit` | mark | ALLOW / HALT | peak-tracking; once tripped, every later `pre_trade` call is REJECTed for the rest of the run — no resume path |
| `DailyLossFlattenLimit` | mark | ALLOW / FLATTEN | UTC-day boundary (`ts // DAY_NS`, not exchange-session-aware); does not halt future trading — can fire again on a later day |
| `InsufficientCashLimit` | pre-trade | ALLOW / RESIZE / REJECT | caps a BUY's base-currency notional at `PortfolioView.available_cash_total(base)` (settlement-lag-aware available cash summed across currencies and converted to base, ADR-0028/ADR-0049); always ALLOWs a SELL and a futures BUY (no cash is paid to open one, ADR-0033) |
| `MarginRequirementLimit` | pre-trade | ALLOW / REJECT | ADR-0031/ADR-0050: REJECTs an order that would raise `initial_margin_rate x short-equity notional + sum of futures initial margins` above equity (mark-to-market, default rate 1.5); REJECT-only; never restricts an order that reduces exposure |
| `MarginCallLimit` | mark | ALLOW / FLATTEN | ADR-0031/ADR-0050: FLATTENs the whole book when equity falls below `maintenance_margin_rate x short-equity notional + sum of futures maintenance margins` (default rate 1.3); not partial liquidation; does not halt future trading |

## Engine wiring (`crucible/core/engine.py`, ADR-0027)
- `BacktestEngine(..., risk_engine: RiskEngine | None = None)` — `None`
  (default) means no risk engine at all; zero behavior change.
- `_go_live` runs `pre_trade` before acceptance. REJECT rejects the order
  outright; RESIZE mutates the order's `qty` via `OrderManager.resize()`
  (legal only before `ACCEPTED`) then proceeds with the shrunk order. A
  `HALT` already in effect (`_halted_reason` set) short-circuits *before*
  `pre_trade` even runs — every order after a halt is rejected.
- `_mark` runs `on_mark` after every mark. HALT sets `_halted_reason`
  (one-way, no unhalt). FLATTEN calls `_flatten_all`, which submits a
  real market order per open position through the normal order pipeline
  but with `bypass_risk=True` — a risk-mandated remedial action is never
  re-subject to the risk checks it exists to satisfy.
- Every non-ALLOW decision is logged via `_log_risk_decision` (structured:
  stage, action, reason, order_id) — every action is logged, implemented via the existing run logger rather than a
  dedicated ledger/analytics event type (nothing consumes risk events as
  data yet).

## Config (`crucible/experiments/config.py`, `crucible/risk/registry.py`)
Optional `ExperimentConfig.risk: RiskConfig | None`. `RiskConfig(pre_trade,
mark)` holds discriminated-union limit configs keyed by `type:` (the
registry's stable string key) — `max_order_notional`,
`max_gross_exposure`, `insufficient_cash`, `margin_requirement`,
`drawdown_halt`, `daily_loss_flatten`, `margin_call`. Unset `risk:`
is identical to today's behavior. `crucible/risk/registry.py::
build_pre_trade_limit`/`build_mark_limit` map keys to limit instances from
plain kwargs — mirrors `execution/registry.py`'s pattern; risk never
imports the experiments layer. No realism-level gating (unlike execution
models) — risk is not tied to the realism ladder.

## Extension points
Sector/asset concentration, beta/factor exposure, VaR, and volatility
limits are not implemented — add each as one more
`PreTradeLimit`/`MarkLimit` and a registry key; no change to
`CompositeRiskEngine` or the engine wiring is needed.

## Checkpoint/resume (E7, ADR-0041)
Only `DrawdownHaltLimit` (`peak`) and `DailyLossFlattenLimit`
(`day`, `day_start_equity`) hold run state and implement `Snapshottable`;
the other limits are stateless. `CompositeRiskEngine.snapshot()` returns
index-aligned `pre_trade`/`mark` lists with `None` for stateless limits;
restore refuses a different limit count and is atomic (a refusal rolls every
limit back, ADR-0048). `CompositeRiskEngine.pre_trade_limits`/`mark_limits`
expose the configured limits read-only. The engine's HALT (`halted_reason`)
is saved with the engine state.

## Tests
- `tests/unit/test_risk_limits.py` — each limit against a real
  `PortfolioSnapshot`, hand-computed, no engine (26 tests).
- `tests/integration/test_risk_engine.py` — real `BacktestEngine` runs
  proving RESIZE/REJECT/HALT/FLATTEN each change engine behavior, not
  just the standalone limit's return value (4 tests).
- `tests/integration/test_settlement_lag.py` — real `BacktestEngine` run
  proving `InsufficientCashLimit` actually rejects a buy funded by
  unsettled sale proceeds, then allows it once settlement lands.
- `tests/integration/test_margin.py` (ADR-0031) — hand-computed
  ledgers through a real engine: a profitable short round trip, a short
  rejected for insufficient initial margin, and a margin call forcing a
  loss-making cover at a hand-derived price.

## Known gaps
- `MaxGrossExposureLimit` has no RESIZE mode (REJECT-only).
- No resume path for a `HALT` — it lasts the rest of the run.
- Risk decisions are logged but not yet materialized as a queryable
  table (no `risk_events.parquet`).
- No example config sets `risk:` yet, so no golden fixture exercises this
  path end-to-end through the CLI/runner.
- `InsufficientCashLimit` sums available cash across currencies rather than
  checking one balance (ADR-0049). (The FX and futures-multiplier gaps in the
  other limits were closed by ADR-0045: they use `PortfolioView.notional`.)
- `MarginRequirementLimit` has no RESIZE mode (REJECT-only, same
  precedent as `MaxGrossExposureLimit`). `MarginCallLimit` liquidates
  the whole book, not a partial/targeted amount. No long-side margin
  check exists (`InsufficientCashLimit` prevents overspending cash but
  isn't a margin-specific initial/maintenance check the way the
  short-side limits are) (ADR-0031). Futures are margined per contract
  (`FuturesSpec.initial_margin`/`maintenance_margin`, config
  `data.futures_margins`, `PortfolioView.margin_required`, ADR-0050); a futures
  symbol without margins under either limit is refused at engine construction
  (ADR-0048/ADR-0050) and at check time. Deferred: percent or SPAN margin and
  partial liquidation.
