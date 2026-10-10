# Module: strategy

## What exists

The strategy-facing API. Detail sections follow.

- `interfaces.py` — the Protocols `Strategy`, `StatefulStrategy`, `Context`, `StrategyLogger`.
- `context.py` — `BacktestContext` (the concrete `ctx`), `EngineOrderSubmitter` (`ctx.orders`),
  `EngineTargetSetter` (`ctx.targets`) and the engine-side Protocols `OrderRouting`, `TargetRouting`.
- `multi.py` — `MultiStrategy` (N strategies in one portfolio, per-strategy attribution).
- Runnable strategies live in `examples/` (`docs/INVENTORY.md`, Strategies).

## Responsibility
The strategy-facing API: `Strategy` handler Protocol and the concrete
`Context`. One API across backtest/paper/live; the strategy cannot tell
which runtime it is in and cannot mutate portfolio/ledger state — nothing on
the Context surface mutates engine state directly.

## Implementations
- `interfaces.py`: `Strategy` (7 handlers), `Context`, `StrategyLogger`
  Protocols.
- `context.py`: `BacktestContext` — `clock` (read-only), `data`
  (PIT accessor; lookahead raises), `portfolio` (fresh read-only snapshot on
  every access), `orders` (submit/cancel routed through the engine), `log`
  (structured, sim-time), `state` (a plain dict), `params` (from
  config). `targets` (ADR-0029): `EngineTargetSetter` resolves a
  declared weight into a real order synchronously, through the engine's
  `TargetRouting` surface — see `docs/modules/portfolio.md` for the
  weight→order mechanics; no longer refuses. `clock`/`data`/`orders`/
  `targets`/`log` are typed by their Protocols (`Clock`/`PITAccessor`/
  `OrderSubmitter`/`TargetSetter`/`StrategyLogger`), not the concrete
  engine classes (ADR-0030) — needed so `multi.MultiStrategy`
  can build child contexts from a `Context` Protocol value alone.
  `OrderSubmitter`/`TargetSetter` gained `with_strategy_id(id)`, returning
  a tagged clone that stamps every order it places/resolves.
- `multi.py` (ADR-0030): `MultiStrategy` — itself satisfies
  `Strategy`; composes several independent `Strategy` objects (own
  params, own `ctx.state`) into the engine's one top-level strategy slot,
  all trading through the same shared portfolio. Builds one tagged
  `BacktestContext` per sub-strategy in `on_start`; every other handler
  broadcasts to every sub-strategy, unfiltered, in the `Mapping`'s
  (deterministic, insertion) order. See `docs/modules/analytics.md` for
  how the resulting `strategy_id`-tagged fills become per-strategy
  attribution.

## Timing semantics a strategy can rely on
- `on_market(bar)` fires at the bar's `available_at` (its close).
- Order acks and fills arrive via `on_order_update`/`on_fill` *after* the
  submitting handler returns, same simulation time.
- Orders never fill before the next bar of the symbol (ADR-0010).

## Extension points
Strategies implement the Protocol directly (see
`examples/momentum/strategy.py`); no base class required.

## Known gaps
`ctx.state` is checkpointed (ADR-0042): it may hold None, bool, int,
float, str, Decimal, tuple, list, dict[str, ...], set, frozenset and numpy
PCG64 generators; anything else makes `checkpoint()` raise naming
`$.ctx_state.<key>`. Attributes on the strategy object (`self.x`) are NOT
captured: a resumable strategy keeps its mutable state in `ctx.state`.
Resume never calls `on_start`. A strategy whose state lives elsewhere
implements the optional `StatefulStrategy` protocol
(`checkpoint_state()`/`restore_state(ctx, state)`, called in place of
`on_start`); `MultiStrategy` does (each sub-context's state plus its
children's). A class attribute `STATE_VERSION` (default 1) is recorded and a
mismatch refuses the resume.
`on_session` and `on_data` are never called at Level 0/1 (no session events,
no non-bar datasets in the loop yet). No universe accessor on the Context —
Strategies take their symbol list from params.
