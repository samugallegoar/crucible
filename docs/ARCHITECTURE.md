# Architecture — as actually built

> Living document. If this file and the code disagree, one of them is a bug;
> fix whichever is wrong and say so in the commit.

**Status: complete for its scope** (the reference live adapter is a
*simulated venue*). A deterministic
Level 0-4 event-driven backtester runs end-to-end: PIT data → strategy → orders (incl. stops,
trailing, brackets/OCO/OTO, TWAP/VWAP/participation) → pluggable execution models (spread,
latency, slippage/impact, commissions, liquidity caps) → ledger → invariant-checked marks →
metrics → artifacts → report, plus execution-scenario fan-out, a deterministic debug stepper, the
statistical-validation suite, a vectorized fast path, checkpoint/resume, and paper/live runtimes.
The exact per-event call order is `docs/TIMING.md`; where a kind of change belongs is
`docs/WHERE_THINGS_GO.md`.

## Data flow (as wired)

```
ParquetDataStore (as-of reads only)
   └─ ReplayDataFeed (via DataFeed seam, ADR-0039): BarEvents (ts=available_at, open_time
      from the calendar's true session opens, prev-close fallback) +
      CorporateActionEvents (ts=effective_at), one sequence counter
        └─ PeekableFeed + engine queue (feed first at equal ts) ── SimulationClock.advance
             ├─ BarEvent: LadderExecutionSimulator.on_bar
             │     (arrival rules → trigger evaluation → OCO adverse
             │      resolution → participation-capped fills, ADR-0012)
             │     → ledger FILL/FEE txns → strategy.on_fill
             │     → mark price update → strategy.on_market (may submit)
             ├─ CorporateActionEvent(DELISTING): cancel pending, liquidate at
             │     last mark (CORPORATE_ACTION txn)
             ├─ after the last event of each timestamp: mark =
             │     ledger fold → PortfolioSnapshot → check_mark
             │     (I1/I3/I4) → equity row
             └─ observer hook (debug stepper) fires per event
```

Orders go SUBMITTED→ACCEPTED immediately; a seeded per-order latency then
governs *which bar* they may first interact with and whether that
interaction is full-bar or mid-bar (ADR-0012). Acks and fills are delivered
to strategy handlers after the current handler returns, at the same
simulation time. Fills never execute against a bar whose
`available_at <=` the order's creation time (no time travel).

Execution models are composed via `ExecutionSetup`, built from config by
`experiments/runner.build_execution_setup` through the level-gated
`execution/registry.py`. Scenario fan-out (`run_with_scenarios`) derives one
config per scenario (different config ⇒ different experiment id) and writes
`scenario_decay.{json,html}` into the base run's artifacts.

## Checkpoint/resume (ADR-0041/0042)

`BacktestEngine.run_until(ts)` stops after the last event of a timestamp was
fully handled (dispatched, callbacks flushed, marked): a session boundary.
`checkpoint(path)` writes canonical JSON built from each stateful component's
`snapshot()` (clock, queue, ledger, orders, simulator, `MarketStats`, risk
limits, logger) plus the engine's own counters, marks, RNG and `ctx.state`.
`resume_from(path)` on a fresh engine opens the replay feed (which re-stamps
event ids/seqs exactly as the original run did, ADR-0039), overwrites the
counters, and skips the feed through the saved cursor. Data hashes, setup
description, strategy `STATE_VERSION` and the cursor are verified first.

## Live runtime (ADR-0043/0044)

The engine drives an `ExecutionBackend`: the ladder simulator (backtest,
paper) or `VenueExecution` (live). `LiveRuntime` (behind `live.enabled`)
builds the engine with a `SimulatedVenue` (own order state and account; fill
pricing by a private ladder simulator sharing the engine's RNG and
`MarketStats`) and a lazily stamping `VenueDataFeed`. Per bar the feed steps
the venue, then yields the venue's fill events, closed-order events and the
bar, stamped at pull time; the engine books venue events through the same
`_book_fill`/`_handle_closures` a backtest uses, so the ledger stays derived
from booked fills. Checkpoints of a lazy feed store its state, the peeked
head and the venue snapshot; `resume_from(venue_state="external")`
reconciles against a venue that kept running (open orders and stream
position) and refuses any difference. The venue is a simulation: a real
vendor adapter is a later step behind the same seams.

## Layering rule

A module may import only from **its own package** or from a layer **below** it. Layers, top to
bottom (siblings in one layer must not import each other):

| # | Layer | Modules |
|---|-------|---------|
| 1 | entry | `mcp_server`, `cli` (`mcp_server` runs `cli` in process) |
| 2 | runtimes | `live.runtime` |
| 3 | orchestration | `experiments` |
| 4 | engine and gates | `core.engine`, `validation`, `vectorized`, `analytics` |
| 5 | domain services | `risk`, `strategy`, `live.venue`, `live.execution`, `live.interfaces`, `live.feed`, `live.paper`, `live.replay`, `live.venue_feed` |
| 6 | execution and portfolio | `execution`, `portfolio` |
| 7 | ledger, data, orders | `accounting`, `data`, `orders`, `live.rows` |
| 8 | kernel | `core.clock`, `core.queue`, `core.logging` above `core.checkpoint` above `core.events`, `core.interfaces`, `core.instruments` above `core.types`, `core.errors`, `core.invariants`, `core.setup_fingerprint` |

Why these directions: strategies and portfolio code sit *below* the engine, so a strategy can
never import the engine, the store or an artifact writer (`strategy` and `portfolio` are also
forbidden from importing `data.store` and `data.pit` outright: data reaches a strategy only
through the `PITAccessor` Protocol). Registries take plain keyword parameters, never config
objects, because `execution`, `risk` and `portfolio` are below `experiments`. `validation` and
`analytics` are pure statistics over arrays and frames and never import the runner; the runner
imports them. `core` is split by module: the kernel (types, errors, events, clock, queue, codec) is
the bottom layer, while `core/engine.py` is the one orchestrator and imports downward.

**Enforcement.** `import-linter` (`[tool.importlinter]` in `pyproject.toml`, run as
`uv run python -m tools.lint_imports`, a CI step, and again from
`tests/unit/test_architecture_conformance.py`) checks the layers and the data-store ban.
Imports under `if TYPE_CHECKING:` are ignored (no runtime edge); imports inside functions are
**not** ignored. A conformance test fails when a module is missing from the contract, so a new
module must be added to the right layer in the same commit.

**Allow-listed exceptions** (both are lazy cycles, listed with their reason in `pyproject.toml`):
`core.checkpoint` -> `accounting.ledger` (the codec rebuilds ledger records by name) and
`experiments.runner` -> `live.runtime` (the runner builds paper/live runtimes on demand). Adding
an exception needs an ADR.

**Changing the rule.** Edit the contract in `pyproject.toml`, this section and
`docs/WHERE_THINGS_GO.md` §3 together, say why in the commit, and write an ADR if a direction
reverses.

## What exists where

```
crucible/
  core/        kernel (types, errors, frozen slotted events, Clock/EventQueue/Snapshottable
               Protocols, SimulationClock, DeterministicEventQueue, invariant registry,
               RunLogger, FuturesSpec, checkpoint codec, setup fingerprint) and engine.py:
               BacktestEngine, the run loop (docs/TIMING.md)
  data/        contracts (BAR/UNIVERSE/CORPORATE_ACTION/FX_RATE schemas with event_time +
               available_at), ParquetDataStore + build_dataset (deterministic writes +
               manifests), StorePITAccessor (the information barrier; LookaheadError),
               calendars, the quality battery, TableUniverseProvider, null-test transforms,
               importers/ (spec-driven CSV/Parquet import for `crucible data build`, ADR-0052)
  strategy/    Strategy/StatefulStrategy/Context Protocols, BacktestContext, MultiStrategy
  orders/      state machine + validate_transition (I7), InMemoryOrderManager
  execution/   models.py (spreads, latency, slippage/impact, commissions, MarketStats),
               ladder.py (LadderExecutionSimulator Levels 0-4, ExecutionSetup), registry.py
               (string keys -> factories, level gating), backend.py (ExecutionBackend seam)
  accounting/  TransactionRecord, InMemoryLedger (append-only; fold = source of truth),
               PortfolioSnapshot, FX conversion, mark invariants I1/I3/I4/I12
  portfolio/   six PortfolioConstructors + registry; TargetSetter (ctx.targets)
  risk/        CompositeRiskEngine, seven limits, registry
  analytics/   compute_metrics (bootstrap CIs), build_trades, attribution, plots, render_report
  validation/  splitters, trial registry (DuckDB), DSR/PBO, sensitivity, Monte Carlo, null tests,
               factor regression, contamination flagging
  vectorized/  the shift-disciplined Level 0/1 engine
  experiments/ ExperimentConfig + canonical hash/yaml, run_experiment (quality gate -> engine ->
               artifacts), artifacts.py (artifact schemas, schema_version, load_experiment),
               scenario fan-out, sweeps, perturbation, null tests, promotion, vectorized runner
  live/        DataFeed/Broker Protocols, ReplayDataFeed, PaperBroker/PaperRuntime, SimulatedVenue,
               VenueDataFeed, VenueExecution, LiveRuntime (behind `live.enabled`)
  strategy_spec/ declarative strategy specs (YAML/JSON) compiled to a vectorized SignalFunction
               (ADR-0067)
  product/     the one-step backtest: data acquisition, buy-and-hold benchmark, null test,
               plain-language summary, readable report, home folder (ADR-0068)
  cli/         backtest, results, spec, config, run, run-vectorized, promote, report, debug,
               optimize, validate, compare, schema, data check|build|fetch|list
  mcp_server/  MCP tools (async, cancellable) over the --json CLI, a guide resource and prompt
               (ADR-0066, ADR-0068)
examples/      momentum (8-symbol GBM universe with a delisting), trend_demo (AR(1) edge; also the
               vectorized and live configs), overfit_demo (known-overfit RandomSignal), sma_cross
               (a strategy spec and the same rule by hand); every example is also a test
tools/         docgen.py: regenerates docs/INVENTORY.md, docs/SCHEMAS.md, docs/adr/README.md;
               lint_imports.py: runs import-linter with UTF-8 output on every platform
```

Registered components, CLI commands, schemas and errors are enumerated (and kept current by
tests) in `docs/INVENTORY.md`; Protocols and how to implement them in `docs/EXTENSION_POINTS.md`.

## Load-bearing decisions in force

- Time: UTC int64 ns everywhere; naive datetimes refused (ADR-0004).
- One sequence counter per run orders all events; ids are zero-padded
  counters; identical inputs ⇒ byte-identical artifacts (ADR-0011, golden).
- Information barrier: `StorePITAccessor` guards `as_of <= clock.now`
  (LookaheadError) and the store itself filters `available_at <= as_of`;
  no unfiltered read exists.
- Money: Decimal on the ledger; the single float→Decimal crossing is
  `accounting.ledger.price_to_decimal` (repr-based).
- The ledger fold is incremental (ADR-0054): a running state applies only newly
  appended transactions, `_fold_full` replays everything and is the property-test
  oracle, and the engine reuses the portfolio snapshot until the clock, the ledger
  version or the marks change. Measure before optimizing further (`docs/data/scale.md`).
- Fill semantics: ADR-0010 (next-bar open, adverse slippage, through-only
  limits, no time travel, delisting liquidation at last mark).
- Settlement lag: only sale proceeds delay joining spendable cash, a
  purchase debits immediately (ADR-0028); `available_cash` never enters
  `equity()`/I1 — liquidity, not valuation.
- Portfolio constructors: six built-ins map signals to target weights;
  `ctx.targets.set/set_all` resolves a weight into an order synchronously,
  through the same pre-trade/execution pipeline a raw order uses
  (ADR-0029). Two treatments, not a full per-constructor optimizer suite —
  diagonal (vol target, risk parity, Kelly) vs. correlation-aware
  (mean-variance via `numpy.linalg.solve`, box constraints by clipping,
  not a true QP).
- Multi-strategy: `strategy.multi.MultiStrategy` composes N independent
  strategies into the engine's one top-level strategy slot — no engine
  loop change, "sharing a portfolio" falls out for free (ADR-0030).
  Attribution is realized-cash-flow-only, tagged via `strategy_id`
  flowing through `OrderSpec`/`Order`/ledger `refs`/`fill_rows` — never
  splits an open shared-symbol position's unrealized PnL between
  strategies (no single owner to attribute it to). Each fill is valued in base
  currency at its fill-time FX mid rate and, for futures, at notional times the
  multiplier (fill rows carry `currency`/`multiplier`/`fx_to_base`, ADR-0047).
- Margin (ADR-0031): simplified Reg-T model — requirement =
  mark-to-market short notional × a configurable rate (initial to open/
  increase, maintenance to keep holding). `MarginRequirementLimit`
  (pre-trade, REJECT-only) and `MarginCallLimit` (mark, whole-book
  FLATTEN — not partial liquidation) reuse ADR-0027's existing risk-limit
  machinery unchanged; no engine-loop or ledger change was needed since
  `PositionState` already handled shorts correctly. Risk limits
  read base-currency, multiplier-scaled `PortfolioView.notional`, and both
  margin limits refuse futures symbols (ADR-0045).

## Scope and known limits

- `RiskEngine` is wired in (ADR-0027): `BacktestEngine._go_live` runs `pre_trade` before acceptance
  (REJECT/RESIZE) and `_mark` runs `on_mark` after every mark (HALT/FLATTEN). It is optional
  (`risk_engine: RiskEngine | None`, default `None`), with no behaviour change for a run that does not
  configure one. `PortfolioConstructor` is implemented (ADR-0029, six built-ins) and `ctx.targets` is
  wired; a constructor is a library a strategy calls with its own signals, not something the engine
  applies automatically. Multi-strategy is implemented (ADR-0030, `strategy.multi.MultiStrategy`) with
  per-strategy attribution (`analytics.attribution`).
- The vectorized path (ADR-0035/0036/0037/0038): `VectorizedBacktestEngine` (Level 0/1, engine-enforced
  shift discipline, a poison test, an agreement test against the event-driven engine), config-driven
  vectorized runs (`experiments.vectorized_runner`, with a parallel runner), promotion to the
  event-driven engine at Level >= 2 (`experiments.promotion`, which re-evaluates the signal under real
  friction rather than replaying a schedule), a multiprocessing sweep runner
  (`experiments.runner.run_experiment_parallel`, byte-identical to sequential execution because the
  registry-touching half of a run always finalizes serially, in caller order, in the parent process) and
  result-registry queries (`crucible compare`, `DuckDBTrialRegistry.all_trials`). Details:
  `docs/modules/vectorized.md`, `docs/modules/experiments.md`. The CLI surface (`run-vectorized`,
  `promote`) is ADR-0051.
- Live runtimes: `PaperRuntime` runs the engine through the `DataFeed` seam (paper parity);
  checkpoint/resume is a library API and a CLI (ADR-0041/0042/0058); `LiveRuntime` runs the engine
  against a simulated venue behind a feature flag (ADR-0043/0044). No real vendor adapter exists.
- Validation suite (ADR-0013 to 0023): splitters, trial registry, DSR/PBO, sensitivity, Monte Carlo,
  null tests, factor regression, contamination flagging (`docs/modules/validation.md`).
- Level 5 (order-book replay) is not supported; VWAP prices on a typical-price proxy and
  queue-awareness is a threshold, not a queue model (ADR-0012).
