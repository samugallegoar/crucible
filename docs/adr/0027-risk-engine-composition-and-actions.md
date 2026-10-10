# ADR-0027: Risk engine composition and action semantics (Phase 4 priority 5)

- **Status**: accepted
- **Date**: 2026-09-19

## Context

`crucible/risk/interfaces.py::RiskEngine` (`pre_trade`/`on_mark` →
`RiskDecision`) has existed as a Protocol since Phase 1 with zero
implementations and, until this session, no wiring into `BacktestEngine`
at all — `docs/modules/risk.md` even claimed a pass-through engine that
didn't exist. The original requirements ask for a pre-trade gate on every order plus
continuous checks on every mark, five action kinds (allow, reject,
resize, flatten, halt), and "each limit is one small checkable unit"
(AGENTS.md §6's extension-point requirement).

Two design questions had no existing precedent to follow: how do many
independent limits compose into one `RiskEngine`, and what does each
non-ALLOW action concretely *do* to the engine's order/position state —
particularly FLATTEN and HALT, which are the first places anything in
the engine autonomously generates or blocks orders without a strategy
asking for it.

## Decision

**Composition**: `CompositeRiskEngine` (`crucible/risk/engine.py`) holds
an ordered list of `PreTradeLimit`s and `MarkLimit`s (Protocols distinct
from `RiskEngine` itself — a limit is not a full engine). Each is checked
in list order; the first non-ALLOW decision short-circuits the rest.
Order is caller-significant: put the most severe/important limits first.
New limit types never touch `CompositeRiskEngine` — they only need to
satisfy the `PreTradeLimit`/`MarkLimit` Protocol, per AGENTS.md §6.

**Pessimism cuts toward letting risk leave the book, never trapping a
strategy inside it**: every pre-trade limit that can compute "does this
order shrink the position" (`MaxGrossExposureLimit` today) allows a
risk-*reducing* order unconditionally, regardless of how far over its own
limit the book already is. The alternative — blocking an order because
gross exposure is already over cap, even though the order itself reduces
that exposure — would make a limit responsible for a position it created
under looser settings impossible to unwind under tighter ones. This is
the AGENTS.md §10 pessimism rule applied to the risk engine specifically:
the "worse outcome for the strategy" is never *blocking an exit*.

**RESIZE is legal only before `ACCEPTED`**: `OrderManager.resize()`
(new) raises outside `CREATED`/`SUBMITTED`. Pre-trade risk always runs
before acceptance (`BacktestEngine._go_live`), so this is always
satisfiable — a RESIZE decision is applied by mutating the order's `qty`
in place, then acceptance proceeds normally against the shrunk order. An
already-accepted order has no well-defined "resize a fill in progress"
semantics against the execution simulator, and none is needed since
nothing upstream of acceptance can still be resized.

**HALT is a one-way, whole-run stop, not a circuit breaker that can
reset**: `BacktestEngine._halted_reason` is set once and checked before
every subsequent `_go_live` (even before the risk engine's own
`pre_trade` runs) — every order submitted after a HALT is REJECTED with
the halt's reason, for the rest of the run. There is no unhalt path.
This is the conservative default (AGENTS.md §10): nothing in the current
design (no strategy-facing "resume trading" signal, no the original requirements language
suggesting halts are resumable) argues for auto-recovery, and a silently
resuming halt would be a much easier bug to introduce than a halt that
simply never lifts. Revisit if a future limit needs a cooldown-based
resume.

**FLATTEN closes every position via real market orders that bypass risk
entirely** (`BacktestEngine._flatten_all`, `_go_live(..., bypass_risk=True)`).
Bypassing is deliberate, not a hole: a risk-mandated remedial action is
never re-subject to the same risk checks it exists to satisfy — doing so
could deadlock a flatten against the very exposure limit that's already
breached, or against a HALT set by a different limit in the same
`on_mark` pass. FLATTEN does **not** set `_halted_reason`; unlike HALT it
does not stop future trading on its own — `DailyLossFlattenLimit` can
fire again on a later day if the strategy reopens positions and loses
again. HALT and FLATTEN are orthogonal: a limit that wants "close
everything and never trade again" must return HALT, not FLATTEN, or must
be paired with a separate `DrawdownHaltLimit`-style limit.

**Every non-ALLOW decision is logged** (`_log_risk_decision`, structured,
includes stage/action/reason/order_id) — the original requirements's "every action is a
logged `RiskEvent`" — satisfied via the existing structured run logger
rather than a new `RiskEvent` type/ledger entry, since nothing currently
consumes risk events as data (no analytics table reads them yet); revisit
if/when risk-event analytics are built.

**Config/registry wiring mirrors `execution/registry.py` exactly**:
`crucible/risk/registry.py::build_pre_trade_limit`/`build_mark_limit` are
stable-string-keyed factories taking plain kwargs (risk never imports the
experiments layer); `experiments/config.py` gained `RiskConfig(pre_trade,
mark)` built from discriminated unions per limit type (`type:` literal =
registry key), following `ExecutionConfig`'s existing shape one-for-one.
Unlike execution models, risk limits have no realism-level gating — the original requirements doesn't tie risk to the realism ladder, and nothing about a limit's
correctness depends on how richly costs/latency are modeled.

**Built-in limits this session** (`crucible/risk/limits.py`):
`MaxOrderNotionalLimit` (RESIZE-capable — caps one order's own notional,
no existing-position math), `MaxGrossExposureLimit` (REJECT-only —
computing a safe RESIZE under a potential direction flip against an
existing position was judged not worth the complexity yet),
`DrawdownHaltLimit` (peak-tracking, HALT), `DailyLossFlattenLimit`
(UTC-day-boundary loss tracking via `ts // DAY_NS` — a documented
simplification, not exchange-session-aware, FLATTEN). Sector/asset
concentration, beta/factor exposure, VaR, and volatility limits from
The original requirements's full list remain unimplemented — deferred as straightforward
additions to `PreTradeLimit`/`MarkLimit` under this same composition, not
a design gap.

## Alternatives considered

- **One monolithic `RiskEngine` implementation per run** instead of
  composable limits: rejected — fails AGENTS.md §6's "each limit is one
  small checkable unit" requirement outright, and would force every new
  limit type to touch a shared, growing class.
- **Re-checking risk after a fill and unwinding it if a limit is
  breached**: rejected — the engine never reverses a booked fill
  (determinism/pessimism); pre-trade is the only point a REJECT/RESIZE
  can still act, so risk *must* run before acceptance, not after fills.
- **Resumable HALT** (e.g., auto-clears once equity recovers above some
  fraction of peak): rejected for now — no consumer or the original requirements language
  motivates it yet; a silent, wrong auto-resume is worse than a hard stop
  a future session can deliberately soften.
- **FLATTEN re-subject to pre-trade limits**: rejected — a flatten order
  that gets REJECTed or RESIZEd by the very exposure limit it's resolving
  defeats its own purpose; bypassing is the only coherent semantics.

## Consequences

`BacktestEngine` gained one constructor parameter (`risk_engine:
RiskEngine | None`, default `None` — no behavior change for any existing
caller/golden fixture) and `_halted_reason` state. `OrderManager` gained
`resize()`. `PortfolioView` gained `mark(symbol) -> Decimal | None` (read
access to the same marks `equity()` already uses, needed so a limit can
project an order's notional without duplicating the marking logic).
`ExperimentConfig` gained an optional `risk:` block; omitting it is
identical to today's behavior. Tests: `tests/unit/test_risk_limits.py`
(12, hand-computed, no engine) and `tests/integration/test_risk_engine.py`
(4, real engine runs proving RESIZE/REJECT/HALT/FLATTEN each actually
change engine behavior, not just the standalone limit's return value).

No example config sets `risk:` yet, but the new optional
`ExperimentConfig.risk: RiskConfig | None` field still serializes (as
`null`) into every `config.yaml`, which **did** shift the momentum
example's golden `config.yaml` hash and therefore its `experiment_id`
(`EXP-1e0c6a4049bb` → `EXP-39bcac077c21`). Every actual simulation
artifact — ledger, orders, fills, trades, equity, metrics — stayed
byte-identical; regenerated with `--regen-golden` and recorded in
CHANGELOG.md, same pattern as ADR-0025/0026.

Known gaps carried forward: `MaxGrossExposureLimit` has no RESIZE mode;
no sector/factor/VaR/vol limits yet; `RiskDecision`s are logged but not
yet materialized as a queryable table (no `risk_events.parquet`); HALT
has no resume mechanism. `docs/modules/risk.md`'s stale "Phase 1 runs
with a pass-through risk engine" claim is corrected as part of this
session, not left for a future one.
