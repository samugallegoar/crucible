# Module: execution

## What exists

The realism ladder (Levels 0-4) and its pluggable models. Detail sections follow.

- `models.py` — `MarketStats`; spreads `NoSpread`, `StaticSpread`, `DynamicSpread`, `QuotedSpread`; latency
  `ZeroLatency`, `ConstantLatency`, `NormalLatency`; slippage `NoSlippage`, `FixedBpsSlippage`,
  `SqrtImpact`, `LinearImpact`; commissions `NoCommission`, `BpsCommission`, `PerShareCommission`,
  `MakerTakerCommission`; `InsufficientHistory`.
- `ladder.py` — `LadderExecutionSimulator`, `ExecutionSetup`, `ParticipationLimits`,
  `validate_fill_within_bar` (I5), the bar-typed slot Protocols `SpreadModelLike`, `LatencyModelLike`,
  `PriceAdjusterLike`, `CommissionModelLike` (twins of the `interfaces.py` ones).
- `registry.py` — `build_spread`, `build_latency`, `build_slippage`, `build_commission`, with
  level gating (keys and minimum levels in `docs/INVENTORY.md`).
- `backend.py` — the `ExecutionBackend` Protocol and `ExecutionContext`.
- `interfaces.py` — `ProposedFill` and the Protocols `SpreadModel`, `LatencyModel`, `SlippageModel`,
  `CommissionModel` and `FillModel` (a stub, see Known gaps).

## Responsibility
The realism ladder, Levels 0-4. Enforces in code: fills within
the bar's fill range (`[low, high]`, widened to its quotes when it has them; I5 raises), aggregate participation caps (I6), adverse
adjustments, through-only limit fills, arrival rules under latency, and
adverse OCO resolution. Level 5 (order-book replay) is deferred.

## Execution modes and validated scope (ADR-0070)

Every result names its engine and realism level; the one-step result also carries
`provenance.execution_assumptions`. The modes do **not** share one set of assumptions, so a
vectorized result and an event-driven result of the same rules are different claims.

| | vectorized (`run-vectorized`, the one-step `backtest`) | event-driven Level 0 / Level 1 | Level 2 | Level 3 | Level 4 |
|---|---|---|---|---|---|
| Orders | target position only | market, limit, stop, stop-limit, trailing, bracket/OCO, TWAP/VWAP | same | same | same |
| Signal → fill | the weight is lagged one bar against close-to-close returns: in effect the position is taken at the signal bar's close (ADR-0035) | Level 0: the current bar's close; Level 1: the next bar's open for market orders, limits/stops on that bar's path (ADR-0010) | + latency (arrival rules, ADR-0012) | same | same |
| Price source | bar close | Level 0: close; Level 1: open / limit / stop, clamped to `[low, high]` | + half-spread (static, dynamic or quoted) | same | same |
| Costs | fixed bps slippage + commission | Level 1: fixed bps | + spread | + participation caps, partial fills | + square-root impact |
| Liquidity | none | none | none | `max_bar_vol`, `max_adv` (I6) | same |
| Rejections | none | risk limits, insufficient cash/margin | same | same | same |
| Corporate actions | none (adjusted prices only) | cash dividends, delistings; others refused | same | same | same |
| End of run | open position marked, not traded | same | same | same | same |

Where OHLC cannot say what happened inside a bar the ladder takes the worse case: a stop
that the open gaps through fills at the open; a limit must trade *through*, not touch; when
both legs of an OCO trigger in one bar the adverse leg executes; a mid-bar arrival gets no
intrabar credit. These are tested in `tests/unit/test_execution_ladder*.py`.

**Validated scope.** Bar-based simulation only. No fill model has been compared with real
quotes, trade prints or order-book data (none is available to the project), so fill realism is
*assumed conservative*, not *empirically validated*. Level 5 (order-book replay) does not exist:
there is no order-book sequencing, queue position, cancellation dynamics, latency distribution
calibrated to a venue, venue fee/rebate schedule or routing model. Crucible therefore makes no
claim about high-frequency or intraday-microstructure strategies; results for them are outside
the validated scope.

## Structure
- `models.py` — the pluggable pieces, all deterministic under the seeded
  run rng:
  - `MarketStats`: trailing close/volume window; updated *after* each bar's
    fills, so models only ever see pre-bar history.
  - Spreads: `NoSpread`, `StaticSpread(bps of close)`, `DynamicSpread`
    (base_bps widened by the bar's own range), `QuotedSpread` (half of the wider of the bar's
    open and close bid/ask spread, ADR-0060).
  - Latency: `ZeroLatency`, `ConstantLatency`, `NormalLatency` (truncated
    at 0, seeded).
  - Price adjusters: `NoSlippage`, `FixedBpsSlippage`, `SqrtImpact`
    (`coef·σ·√(Q/ADV)`), `LinearImpact` (`coef·Q/ADV`) — always adverse,
    monotone in size, `InsufficientHistory` when the window is too short.
  - Commissions: `NoCommission`, `BpsCommission`, `PerShareCommission`
    (rate + minimum), `MakerTakerCommission` (passive fills are makers;
    rebates allowed).
- `ladder.py` — `LadderExecutionSimulator`: full semantics in **ADR-0012**
  (arrival rules, triggers, OCO adversity, caps, partial fills, algos);
  `ExecutionSetup` (the model bundle incl. the shared `MarketStats`);
  `ParticipationLimits`; `why_not_filled(order_id)` reason trails.
- `registry.py` — stable string keys → factories with per-level gating:
  spread/latency ≥ L2, participation ≥ L3, impact ≥ L4. Config models live
  in `experiments/config.py` (discriminated unions on `type`).

## Quoted spread (ADR-0060)
`QuotedSpread` (`execution.spread.type: quoted`, level 2 or higher) prices a market or aggressive
fill from the executing bar's own top-of-book quotes: the half-spread is
`max(ask_open - bid_open, ask_close - bid_close) / 2`, added to the reference price for a buy and
subtracted for a sell, so with a mid reference a buy pays the ask and a sell gets the bid. The
wider of the two quotes is used because the simulator cannot know which one the order met
(pessimism). A bar with a missing, partial or crossed quote raises `DataQualityError` naming the
symbol and timestamp (no fallback to the mid); a zero bid is a valid one-sided book and gives a wide
spread. A `quoted` run on a dataset without the four quote columns is refused at run start. The
aggressive-fill clamp and invariant I5 use `BarEvent.fill_range()`: `[low, high]` widened to the
bar's quotes when it carries all four, because mid-priced bars have `high == low` and would erase
the spread. A limit order on a bar that carries quotes is measured against the quote a taker
would meet (ask for a buy, bid for a sell) instead of the mid: it crosses at the open only if the
open ask is below a buy limit (open bid above a sell limit), and otherwise fills passively at its
limit only when the ask (bid) trades through it; a limit between the mid and the quote does not fill
as if the mid were tradable. Stops and algos use the mid reference plus the quoted spread. Quotes are read from the
executing bar only (knowable with the bar), the model is stateless, and the venue backend reuses
it, so paper and backtest match (I14).

## Order types simulated
MARKET, LIMIT, STOP, STOP_LIMIT, TRAILING_STOP, TWAP, VWAP, PARTICIPATION,
MARKET_ON_CLOSE, plus composite BRACKET/OCO/OTO via order-manager links (children activate on
parent fill; dead parents cancel dormant children).

MARKET_ON_CLOSE (ADR-0074) carries `close_at`, a session close. It fills on the bar ending at
`close_at`, at that bar's close adjusted adversely (spread, slippage) and clamped into the bar (I5).
It must arrive by `close_at - MOC_CUTOFF_NS` (ten minutes, the NYSE/Nasdaq 15:50 cutoff), else it is
rejected; if no bar ends at `close_at` it expires. Level 0 refuses it.

## Execution backend (ADR-0043)
`backend.py`: the engine drives an `ExecutionBackend` (Protocol:
`supports_composite_orders`, `on_order_submitted`, `on_bar`, `remove_pending`,
`parent_died`, `why_not_filled`, `snapshot`, `restore`), exactly the surface it
called on the simulator before. `LadderExecutionSimulator` is the default
(`supports_composite_orders = True`); `BacktestEngine` accepts
`execution_backend_factory(ExecutionContext)` where the context carries the
engine's level, order manager, `ExecutionSetup`, `MarketStats` and RNG, which a
backend must share (never copy). The venue backend is
`crucible/live/execution.py` (see `docs/modules/live.md`).

## Adding a model (AGENTS.md §6)
Implement the model in `models.py`, add its key to `registry.py`'s
`_MIN_LEVEL` + builder, add a config model to the discriminated union in
`experiments/config.py`, tests (unit + property + golden at the relevant
level), a row here, ADR if defaults change.

## Checkpoint/resume (E7, ADR-0041)
`LadderExecutionSimulator.snapshot()` captures, per pending order, its arrival time,
bars rested, stop-armed flag, trailing stop/extreme and algo slices done,
plus the why-not-filled trail; `MarketStats` captures its window and the
per-symbol close/volume histories. The five pluggable models (spread, latency,
slippage, commission, participation) are configuration by default, but a model that
implements `Snapshottable` has its state saved under `models` and restored in place,
all-or-nothing (a different model set or state for a stateless model is refused, and any
`CheckpointError` rolls every model back; ADR-0056). A model that is not `Snapshottable`
and changes state during a run is refused at `checkpoint()` by name. Restore is in place:
the engine and simulator share one RNG object, so its state is restored into that object.

## Known gaps
- A spread or slippage that would put a fill outside the bar's range is clamped into it (I5),
  so the cost is erased when the open is the bar's extreme: slightly optimistic. Pinned by
  `test_known_gap_cost_beyond_the_bar_range_is_clamped_away` (ADR-0070).
- The engine's only random draw is latency. On daily bars a sub-second latency never changes
  which bar an order reaches, so a Level 2-4 run on daily data is effectively deterministic in
  its seed (a latency of about a day does change it; ADR-0070).
- `FillModel` (`execution/interfaces.py`) is a stub Protocol: fills are produced inside `LadderExecutionSimulator`, not by a pluggable model.
- VWAP slices equally and prices at (H+L+C)/3 — an approximation until
  intrabar data exists (ADR-0012).
- `queue_bps` is a threshold proxy, not a queue-position model (Level 5).
- Quotes: no tick-level quotes (a bar has its first and last) and no queue position; stop triggers
  still use the mid; the vectorized engine, null tests and a quoted scenario on a store without
  quotes refuse `quoted` up front (ADR-0060).
- Almgren-Chriss impact is not implemented.
- Maker/taker tiers by monthly volume not modeled (flat maker/taker only).
- IOC/FOK/GTD TIFs still refused (need intrabar semantics).
