# ADR-0030: Multi-strategy composition and per-strategy attribution (Phase 4, final priority)

- **Status**: accepted
- **Date**: 2026-09-19

## Context

The original requirements ask for "multiple strategies sharing a portfolio with
per-strategy attribution"; the original requirements's Phase 4 acceptance criterion is
"strategy correlation and marginal risk contribution reported." Before
this priority, `BacktestEngine.__init__` took exactly one `strategy:
Strategy`, and nothing in the ledger/order/fill machinery distinguished
who submitted what — there was no way to run two independent strategies
in one engine call, let alone attribute their results separately.

Two design questions had no precedent: how do *N* independent `Strategy`
implementations run inside *one* engine loop against *one* shared
portfolio, and how does "per-strategy attribution" work at all when every
strategy trades into the same ledger, the same per-symbol positions, and
the same cash pool — there is no separate sub-ledger to read a
strategy's PnL off of directly.

## Decision

**Composition, not a new engine loop.** `crucible/strategy/multi.py::
MultiStrategy` itself satisfies the `Strategy` Protocol — `BacktestEngine`
still runs exactly one top-level strategy, completely unchanged. Passing
a `MultiStrategy` instance as that one strategy is how several independent
`Strategy` objects (their own params, their own `ctx.state`) run inside a
single engine call, all trading through the same ledger. This reuses
100% of the existing pipeline (risk engine, execution, settlement lag,
portfolio constructors) with zero changes to `BacktestEngine`'s loop —
"sharing a portfolio" falls out for free the instant two strategies run
inside the same engine instance; the only genuinely new work is (1)
dispatching to N sub-strategies deterministically and (2) tagging who did
what for attribution.

`MultiStrategy.on_start` builds one `BacktestContext` per sub-strategy,
sharing the parent context's `clock`/`data`/`log`, wrapping `ctx.portfolio`
in a fresh zero-arg provider (full shared visibility — no sub-strategy
gets a restricted view of the book), and giving each sub-strategy its own
`orders`/`targets` facade tagged with its `StrategyId` (below) and its own
`params` (falls back to the parent's shared `params` if none given for
that id) — meaning each sub-strategy's `ctx.state` is independent by
construction (`BacktestContext.__init__` always starts a fresh `{}`).
Dispatch order follows the `Mapping[StrategyId, Strategy]`'s iteration
order (a plain `dict`, insertion-ordered and therefore deterministic —
AGENTS.md §1.3) — every handler loops over every sub-strategy in that
same order, every run.

**Every event broadcasts to every sub-strategy, unfiltered.** A
sub-strategy that only trades symbol X still receives `on_market` for
symbol Y's bars, and `on_fill`/`on_order_update` for every fill/order
update in the run, not just its own. This is a deliberate simplification:
sub-strategies already see the *entire* shared portfolio through
`ctx.portfolio` (every position, all cash, regardless of who opened it),
so also seeing every event is consistent with that, not a new
information leak. Building real event-routing (only deliver a
sub-strategy's own fills) would need `FillEvent`/`OrderUpdateEvent` to
carry `strategy_id` for filtering anyway — which they now do
(`strategy_id: StrategyId | None`, informational) — so a sub-strategy
that wants to filter itself can (`if event.strategy_id != self.my_id:
return`), without the engine forcing that discipline on every strategy
that doesn't need it. `examples/momentum/strategy.py`-style single-symbol
strategies (this session's `OneSymbolTrader` test fixture) already filter
by `event.symbol` for the same reason, so this pattern isn't new.

**Attribution flows through the ledger, not through events.**
`OrderSpec` gained `strategy_id: StrategyId | None = None`; `Order`/
`ManagedOrder`/`InMemoryOrderManager.create` carry it through order
creation; `_book_fill` reads the filled order's `strategy_id` and stamps
it into the FILL and FEE `TransactionRecord.refs` (only when set — a
single-strategy run's `refs` are byte-identical to before this priority)
and into the structured `fill_rows`/`order_rows` output (a real
`"strategy_id"` column, not just a `refs` string to parse — the direct
consumption path for analytics). `EngineOrderSubmitter`/
`EngineTargetSetter` gained `with_strategy_id(id) -> <same type>`,
returning a tagged clone sharing the same routing — this is how
`MultiStrategy` gets one tagged submitter/target-setter per sub-strategy
without the engine needing to know anything about "sessions" or
"contexts." `submit_bracket`'s two engine-synthesized child orders
(take-profit/stop-loss) inherit the parent entry order's `strategy_id`
explicitly — they're not separately submitted by the strategy, so
nothing else would tag them. An engine-generated order the risk engine
creates on its own (a FLATTEN's closing orders, ADR-0027) is
**deliberately left untagged** (`strategy_id=None`): a flatten closes a
position that may have been built by multiple strategies' orders over
time (they share one position per symbol), so attributing its close to
any single one would be a fabrication, not a fact.

**`Context.orders`/`Context.targets`/`Context.clock`/`Context.data`/
`Context.log` widen from `BacktestContext`'s concrete engine types to
their Protocols** (`OrderSubmitter`, `TargetSetter`, `Clock`,
`PITAccessor`, `StrategyLogger`) so `MultiStrategy.on_start` — which only
ever sees the `Context` Protocol, never the concrete `BacktestContext` —
can call `with_strategy_id` and construct child contexts without an
unsafe cast. This is a strict widening (every existing concrete value
already satisfies its Protocol), so no call site anywhere in `crucible`
or `examples` needed to change.

**Attribution itself is realized cash flow only, never unrealized
mark-to-market** (`crucible/analytics/attribution.py`). A strategy's
attributed PnL for a period is the sum of its tagged fills' `qty*price`
(signed by side) minus commission, bucketed onto the same `ts` grid as
`equity_rows` (one bucket per mark, `(period_ts[i-1], period_ts[i]]`).
This is *exact* whenever a strategy trades a symbol no other strategy
touches (the case this module is built for, and the case the acceptance
test demonstrates) — a round trip's PnL nets to the same number whether
you compute it from the fills or from the position. It deliberately
never attempts to split an *open* position's unrealized PnL between
strategies that traded the same symbol, because a shared per-symbol
position has no single owner to attribute unrealized value to — inventing
a split (e.g. by trade count, or by notional-weighted average) would be
exactly the kind of "the simulator can't know, so it assumes" case
AGENTS.md §1.4 exists for, except here there is no conservative default
that isn't also an invention. This is a documented, named gap
(`Known gaps`, below), not a silent one.

**Correlation and marginal risk contribution operate on raw dollar PnL
deltas, not normalized returns.** There is no natural "notional" to
divide by — strategies share one capital pool with no separate
per-strategy allocation, so there's no "weight" to compute a return
against. Pearson correlation is scale-invariant, so this makes no
difference to `strategy_correlation`'s output. `marginal_risk_
contribution` defines `portfolio_pnl = sum of the strategy columns`
(the `UNATTRIBUTED` bucket excluded) and computes `MRC_i =
Cov(pnl_i, portfolio_pnl) / SD(portfolio_pnl)` — the standard
covariance-decomposition risk contribution, applied at $ PnL scale
instead of % return scale. By construction, `sum_i MRC_i ==
SD(portfolio_pnl)` exactly (the acceptance test asserts this identity
directly) — every marginal contribution accounts for exactly its share
of portfolio risk, nothing left over, nothing double-counted.

## Alternatives considered

- **A genuinely N-strategy engine loop** (`BacktestEngine(strategies:
  Mapping[...])` instead of composition): rejected — would touch every
  dispatch site in `core/engine.py` for a capability `MultiStrategy`
  already delivers by composition, with a much larger surface for new
  bugs (ADR-0027/0028/0029's pipeline would all need re-verifying against
  N-strategy semantics instead of just working unchanged).
- **Event routing** (a sub-strategy only receives its own fills/order
  updates): rejected as the default — no the original requirements requirement forces it, it
  would need new engine-side bookkeeping (which context "belongs" to
  which order), and a sub-strategy that wants it can already filter by
  `event.strategy_id` itself, which is strictly more flexible than an
  engine-enforced filter (a sub-strategy that *wants* cross-strategy
  visibility, e.g. a meta-strategy watching its siblings, couldn't get it
  under enforced routing).
- **Splitting unrealized PnL between strategies sharing a symbol** (e.g.
  proportional to each strategy's share of total notional traded, or a
  synthetic per-strategy FIFO lot queue): rejected for this priority —
  every scheme considered either invents an allocation the ledger has no
  basis for, or requires building a full per-strategy lot-tracking
  system (effectively a parallel accounting engine). Realized-cash-flow
  attribution is exact in the common case and honestly incomplete
  (not silently wrong) in the shared-symbol case.
- **Normalizing PnL deltas by notional/equity before correlating**:
  rejected — there is no per-strategy capital allocation to normalize
  against in a shared-pool design; raw $ deltas are exact for
  correlation (scale-invariant) and the natural unit for a risk
  decomposition that must sum to the portfolio's own $ risk.

## Consequences

New: `crucible/strategy/multi.py::MultiStrategy`,
`crucible/analytics/attribution.py` (`per_strategy_pnl_deltas`,
`strategy_correlation`, `marginal_risk_contribution`,
`UNATTRIBUTED`), `core.types.StrategyId`. Changed (all additive,
default-`None`/backward-compatible): `OrderSpec.strategy_id`,
`Order.strategy_id`/`ManagedOrder.strategy_id`/
`InMemoryOrderManager.create(..., strategy_id=...)`,
`FillEvent.strategy_id`/`OrderUpdateEvent.strategy_id`,
`BacktestEngine._order_rows`/`_fill_rows` gain a `strategy_id` column,
`OrderSubmitter`/`TargetSetter` Protocols gain `with_strategy_id`,
`BacktestContext`'s `clock`/`data`/`orders`/`targets`/`log` widen to
their Protocol types (`Clock`/`PITAccessor`/`OrderSubmitter`/
`TargetSetter`/`StrategyLogger`) from concrete engine types — a strict,
safe widening; no existing call site changed behavior.

`crucible/experiments/runner.py`'s `orders.parquet`/`fills.parquet`
Polars schemas gained a `strategy_id: pl.String()` column (nullable —
`None` for every fill/order in a single-strategy run). This shifted
those two files' content hash in the momentum example's golden fixture;
`ledger.parquet`, `trades.parquet`, `equity.parquet`, `metrics.json`, and
`config.yaml`/`experiment_id` were verified byte-identical file-by-file
before regenerating with `--regen-golden`, justified here and in
CHANGELOG.md, same pattern as every prior Phase 4 priority.

Tests: `tests/unit/test_attribution.py` (11, hand-computed —
`per_strategy_pnl_deltas`'s period bucketing, `strategy_correlation`'s
perfectly-(anti)correlated cases, `marginal_risk_contribution`'s
hand-derived covariance decomposition and its sum-to-portfolio-SD
identity), `tests/integration/test_multi_strategy_attribution.py` (1 —
**the Phase 4 acceptance demonstration**: two strategies, disjoint
symbols, constant prices; every fill attributed to exactly the strategy
that traded its symbol; hand-computed per-period PnL deltas; correlation
exactly 1.0 by construction (one strategy's delta is always a fixed
multiple of the other's); marginal risk contribution matches a
hand-derived covariance calculation and the two contributions sum
exactly to the portfolio's own standard deviation).

Known gaps carried forward: attribution is realized-cash-flow-only —
two strategies trading the *same* symbol have their round-trip PnL
correctly split (each fill is one order, one order has one owner) but
their *unrealized* (open-position) PnL is never split, which
underestimates (never overestimates — a form of pessimism) a strategy's
true contribution while it holds a shared-symbol position open; this is
the module's central, load-bearing simplification, not an oversight.
`crucible/analytics/trades.py`'s FIFO round-trip trade log does not
carry `strategy_id` yet (nothing in this priority consumes it there;
`per_strategy_pnl_deltas` reads `fill_rows` directly) — a natural
follow-up if trade-level (not just fill-level) per-strategy analytics are
needed. No config/registry wiring for `MultiStrategy` itself — a
strategy composition is Python-level (construct `MultiStrategy({...})`
and pass it as `strategy=` the same way a single strategy is today), not
a discriminated-union config concern, since nothing about *which*
strategies compose or *what signals they use* is expressible as a stable
string key the way an execution model or risk limit is.

This closes Phase 4's acceptance criterion: "invariants hold
under multi-currency" was demonstrated across priorities 1/2/4 (I1, I12);
"strategy correlation and marginal risk contribution reported" is
demonstrated by this priority's acceptance test. the roadmap's
Phase 4 row moves to **done**.
