# WHERE THINGS GO — which module owns which kind of change

> Read this after `docs/INVENTORY.md` and `docs/EXTENSION_POINTS.md` (does it already exist?
> is there a registry to hang it on?) and before you create a file. The import rules that make
> the placement checkable are in `docs/ARCHITECTURE.md` ("Layering rule", enforced by
> `import-linter` in CI).

## 1. Decision procedure

1. **Does it exist?** `docs/INVENTORY.md` (registered things), `docs/EXTENSION_POINTS.md`
   (Protocols), `docs/GLOSSARY.md` (vocabulary). Extend, don't duplicate.
2. **Which kind of change is it?** Find the row in §2. The *Home* column is the module (and file)
   that owns it; the *Also touch* column lists everything that must change with it.
3. **Is the import legal?** A module may import only from its own package or from packages
   *below* it (§3). If you need an import going up, the code is in the wrong place: move it down,
   or pass the thing in (registries take plain keyword params, never config objects).
4. **Which tests?** `tests/README.md` §1 picks the folder; the row lists the ones that must exist.
5. **Which docs?** The row lists the pages; the checklist is AGENTS.md §8.

## 2. Kind of change -> home

Anti-examples are real temptations, each of which breaks a rule stated in `AGENTS.md`.

| Kind of change | Home | Also touch | Example | Anti-example |
|----------------|------|------------|---------|--------------|
| A trading strategy | `examples/<name>/strategy.py` (+ `config.yaml`, `build_data.py`) | a `tests/lookahead/` file, the resume matrix if stateful, `examples/README.md` | `examples/momentum` (`Momentum`) | Putting it under `crucible/` (the library ships mechanisms, not alpha), or keeping state on `self` instead of `ctx.state` |
| A strategy that composes others | `crucible/strategy/multi.py` | attribution in `analytics/attribution.py`, resume matrix | `MultiStrategy` | A second run loop; a strategy that reaches into another's context |
| A vectorized signal | `examples/<name>/vectorized_signal.py` (`SignalFunction`) | vectorized agreement/poison tests | `trend_follower_signal` | Lagging the score yourself (the engine applies the mandatory shift) |
| Read data inside a strategy | through `ctx.data` (`PITAccessor`) with `as_of` | lookahead test | `ctx.data.history(...)` | Importing `data.store` from strategy code, or reading a Parquet file (import-linter forbids the former; the harness catches the latter) |
| A spread / latency / slippage / commission model | `execution/models.py` + key in `execution/registry.py` | config model in `experiments/config.py`, `docs/modules/execution.md`, unit + property + golden at its level, ADR if defaults change | `FixedBpsSlippage` | Hard-coding bps in `ladder.py`; importing `experiments` from `execution`; a model that helps the strategy |
| A new order type | `core/types.py::OrderType`, validation in `orders/manager.py::ManagedOrder`, an evaluation arm in `execution/ladder.py::_evaluate`, `OrderSpec` fields in `orders/interfaces.py` | ADR-0012-style pessimism note, `docs/modules/execution.md`, property test (fills within bar) | `TRAILING_STOP` | Emulating it in a strategy with cancels and re-submits |
| A risk limit | `risk/limits.py` + key in `risk/registry.py` | `PreTradeLimitConfig`/`MarkLimitConfig` union in `experiments/config.py`, `docs/modules/risk.md`, `Snapshottable` if stateful + resume matrix | `MaxGrossExposureLimit` | Checking limits inside the strategy; a limit that silently clips without a logged decision |
| A portfolio constructor | `portfolio/constructors.py` + key in `portfolio/registry.py` | property test, `docs/modules/portfolio.md` | `VolTargetConstructor` | Reading the data layer from inside `construct` (it only sees what the strategy passed) |
| A metric | `analytics/metrics.py::compute_metrics` (pure function, with a bootstrap CI unless it is an identity) | `docs/modules/analytics.md`, regenerate `docs/INVENTORY.md`; a golden change if `metrics.json` moves | `sharpe` | Computing a headline number in `cli/` or `runner.py`, or reporting one without CI, trial count and DSR/PBO |
| A statistic that judges results (DSR-like, resampling, null test) | `validation/<name>.py`: pure functions, explicit `rng` | `docs/modules/validation.md`; if it must **re-simulate**, its orchestrator goes in `experiments/` | `deflated_sharpe_ratio` | `validation/` importing `experiments` (layering); a global RNG |
| A data-quality check | `data/quality.py` + `DEFAULT_BAR_CHECKS` | `docs/modules/data.md`, unit test with a failing frame | `OhlcBounds` | A warning instead of `DataQualityError` |
| A dataset contract or column | `data/contracts.py` (schema + a `# comment` per column) | regenerate `docs/SCHEMAS.md`, `docs/COMPATIBILITY.md` §3, importers and quality checks that read it | `CORPORATE_ACTION_SCHEMA.pay_at` | Adding a column in an importer only |
| A new input file format / source | a `kind` in `data/importers/spec.py` + an importer + `importers/build.py` dispatch | `docs/data/<source>.md` (AGENTS.md §14), `examples/imports/<spec>.yaml`, `docs/modules/data.md` | `ohlcv_csv` | Loading raw files in a strategy; modifying the raw source; adjusted prices as raw truth |
| A corporate action | `core/engine.py::_handle_corporate_action` (+ `core/events.py` if a new event) | fold rule in `accounting/ledger.py` if it changes positions, `docs/TIMING.md` §2.3, a **hand-computed** expected ledger | `CASH_DIVIDEND` | Adjusting the price series instead of posting ledger transactions |
| A ledger transaction type | `core/types.py::TransactionType` + a fold rule in `accounting/ledger.py` | hand-computed ledger test, `docs/modules/accounting.md`, an invariant if it can break one | `BORROW`, `FINANCING` | Mutating balances outside the ledger |
| An invariant | `accounting/invariants.py` (registry) or inline where it can be violated | a row in `docs/INVARIANTS.md`, a test that violates it | I3 `cash_identity` | A comment that says "should always hold" |
| FX behaviour | `accounting/fx.py` | ADR-0009/0025 stay authoritative; `docs/CONVENTIONS.md` §4 | `convert_at_adverse` | Converting inside a strategy |
| A calendar | `data/calendars.py` (`get_trading_calendar`) | `docs/modules/data.md` | `AlwaysOpenCalendar` | Passing timezone-aware datetimes into the engine |
| A config field | `experiments/config.py` (frozen model, default that preserves old behaviour) | **hash impact**: `docs/COMPATIBILITY.md` §2, golden README line, regenerate `docs/SCHEMAS.md` | `DataConfig.futures_margins` | A module-level constant or environment variable that changes results |
| A run artifact or a column in one | `experiments/artifacts.py` (schema constant with `# comment`s) + the writer in `experiments/runner.py` | `SCHEMA_VERSION` rule (`docs/COMPATIBILITY.md` §3), regenerate `docs/SCHEMAS.md`, golden if bytes move | `fills.parquet` `fx_to_base` | Writing a file the schema module does not describe |
| A CLI command or flag | `cli/main.py`: a thin handler that calls `experiments`/`data` | `docs/modules/cli.md`, regenerate `docs/INVENTORY.md`, `tests/unit/test_cli.py` | `compare` | Business logic in the handler |
| An MCP tool | `mcp_server/server.py`: a thin function that builds the argv of an existing `--json` command with `build_argv` (the command needs `--json` first) | `docs/modules/mcp_server.md`, `EXPECTED_TOOLS` in `tests/integration/test_mcp_server.py` | `crucible_compare` | Logic in the tool; importing `experiments` directly (a second path that can diverge from the CLI) |
| A research orchestrator (sweeps, perturbation, promotion) | `experiments/<name>.py` on top of `run_experiment` | trial-counting rules (ADR-0014/0016/0018), `docs/modules/experiments.md` | `optimize_1d` | Recording trials from inside `validation/` |
| Engine loop behaviour: a new event kind, a new dispatch, a change of call order | `core/events.py` + `core/interfaces.py` + `core/engine.py` | **ADR**, `docs/TIMING.md` and its diagram, golden and parity tests, resume matrix | dividend pay-date events | A branch in a strategy; reading the wall clock |
| A stateful component | next to its owner, implementing `Snapshottable` | listed in `BacktestEngine._snapshot_payload`, resume-equivalence matrix (`tests/README.md` §7) | `MarketStats` | State outside `snapshot()` (the engine refuses to checkpoint it, ADR-0048) |
| A live / paper venue or feed | `live/` behind the `Broker`, `DataFeed` or `ExecutionBackend` seam and the `live.enabled` flag | live-parity and reconciliation tests, `docs/modules/live.md`, ADR | `SimulatedVenue` | Wall-clock or timezone code outside the I/O boundary; bypassing `_book_fill` |
| A helper used by several packages | the **lowest** package all its users may import (usually `core/`) | a unit test | `price_to_decimal` in `accounting/ledger.py` | A `utils.py`; copying the helper into each package |
| A doc generator or repo tool | `tools/` (not the `crucible` package) | `docs/DEPENDENCIES.md` if it needs a package | `tools/docgen.py` | Adding it to the shipped package |
| A decision someone will question | `docs/adr/NNNN-title.md` | `docs/adr/README.md` (regenerated), `CHANGELOG.md` | ADR-0012 | Recording it only in a commit message |

## 3. Layers at a glance

Allowed imports point **down** this list (the full contract, with the exact modules, is the
`[tool.importlinter]` section of `pyproject.toml`; the explanation is `docs/ARCHITECTURE.md`):

| Layer (top to bottom) | Packages / modules | May import |
|-----------------------|--------------------|-----------|
| 1. Entry | `cli` | everything below |
| 2. Runtimes | `live.runtime` | 3 and below |
| 3. Orchestration | `experiments` | 4 and below |
| 4. Engine and gates | `core.engine`, `validation`, `vectorized`, `analytics` | 5 and below (siblings do not import each other) |
| 5. Domain services | `risk`, `strategy`, `live.*` (venue, feeds, paper) | 6 and below |
| 6. Execution and portfolio | `execution`, `portfolio` | 7 and below |
| 7. Ledger, data, orders | `accounting`, `data`, `orders`, `live.rows` | 8 and below |
| 8. Kernel | `core.clock`, `core.queue`, `core.logging`, `core.checkpoint`, `core.events`, `core.interfaces`, `core.instruments`, `core.types`, `core.errors`, `core.invariants`, `core.setup_fingerprint` | only lower kernel modules |

Two lazy cycles are allow-listed with a comment in `pyproject.toml`: the checkpoint codec builds
ledger records by name (`core.checkpoint` -> `accounting.ledger`), and the runner builds paper/live
runtimes on demand (`experiments.runner` -> `live.runtime`).

## 4. Where a *document* goes

| You are documenting | Page |
|---------------------|------|
| What a module provides, how to extend it, what it lacks | `docs/modules/<module>.md` (*What exists* first, *Known gaps* last) |
| The order things happen in a run | `docs/TIMING.md` |
| A column, key or file format | the code (`# comment` on the schema column) and `docs/SCHEMAS.md` (generated) |
| A unit, sign, name or error rule | `docs/CONVENTIONS.md` |
| A decision with alternatives | `docs/adr/NNNN-*.md` |
| An identity the engine must hold | `docs/INVARIANTS.md` + `core/invariants.py` |
| A vocabulary term | `docs/GLOSSARY.md` |
| A dataset | `docs/data/<source>.md` |
| A change to what may move a golden hash | `docs/COMPATIBILITY.md` |

## Known gaps

- Placement of pure-analysis notebooks/reports is undefined (there is no `notebooks/`).
- `crucible.core` mixes the kernel and the orchestrating `core/engine.py`; the layering rule
  splits them by module, but the package name suggests otherwise.
