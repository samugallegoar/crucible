# Contributing to Crucible

You are extending the engine, adding an indicator or a data source, or fixing a bug. The operating
manual is [`AGENTS.md`](../../AGENTS.md) (section numbers there are cited from code and ADRs), and
[`CONTRIBUTING.md`](../../CONTRIBUTING.md) is the short human version. This page indexes the rest
by what you are trying to do.

## Orient

| I want to know | Page |
|---|---|
| how the system is built and the layering rule | [`ARCHITECTURE.md`](../ARCHITECTURE.md) |
| where a kind of change goes, with anti-examples | [`WHERE_THINGS_GO.md`](../WHERE_THINGS_GO.md) |
| what already exists (components, metrics, order types, validators, commands) | [`INVENTORY.md`](../INVENTORY.md) (generated) and [`EXTENSION_POINTS.md`](../EXTENSION_POINTS.md) |
| one module's contract, extension points and known gaps | [`modules/`](../modules/) |
| why a decision was made | [`adr/`](../adr/README.md) |
| the shared vocabulary | [`GLOSSARY.md`](../GLOSSARY.md) |

## Rules the code holds

| Topic | Page |
|---|---|
| identities the engine must keep (and where they are checked) | [`INVARIANTS.md`](../INVARIANTS.md) |
| per-event call order and when things post | [`TIMING.md`](../TIMING.md) |
| units, signs, currencies, names, the exception catalogue | [`CONVENTIONS.md`](../CONVENTIONS.md) |
| input contracts and output artifacts, column by column | [`SCHEMAS.md`](../SCHEMAS.md) (generated) |
| what may change and how it is recorded (config hash, schema versions, goldens) | [`COMPATIBILITY.md`](../COMPATIBILITY.md) |
| every dependency and what may never be added | [`DEPENDENCIES.md`](../DEPENDENCIES.md) |
| tests: folders, markers, golden regeneration | [`tests/README.md`](../../tests/README.md) |
| datasets and importers | [`docs/data/`](../data/) |

## The product layer

The no-code path and the one-step backtest sit on top of the engine and add no engine behaviour:

| Page | Covers |
|---|---|
| [`modules/strategy_spec.md`](../modules/strategy_spec.md) | the spec language, indicators, position logic; how to add an indicator |
| [`modules/product.md`](../modules/product.md) | the one-step flow, the result document, the verdict guards |
| [`modules/mcp_server.md`](../modules/mcp_server.md) | the tools, cancellation, path rules |
| [ADR-0067](../adr/0067-strategy-spec.md), [ADR-0068](../adr/0068-product-layer.md), [ADR-0069](../adr/0069-documentation-by-audience.md) | the decisions, with alternatives |
| [`AGENT_GUIDE.md`](../../AGENT_GUIDE.md) | the user-facing agent contract; keep it true when behaviour changes |

A change that alters a number a user reads (a threshold in `product/summary.py`, an indicator's
definition) is a behaviour change: say so in the changelog and, if a golden moves, in the commit.

## Everyday commands

```bash
uv sync
uv run python -m tools.check             # the five gates in order, stops at the first failure
uv run python -m tools.check --fast      # same, with the fast test tier (no `slow` tests)
uv run pytest                                   # the full suite (about 10 minutes; run it in the background)
uv run mypy --strict crucible examples tools
uv run ruff check . && uv run ruff format --check crucible tests examples tools
uv run python -m tools.lint_imports             # the layering contract
uv run python -m tools.docgen --check           # generated docs current (--write to fix)
```

Format only `crucible tests examples tools`; never the repository root (it rewrites Markdown code
blocks under `docs/`).

`tools.check` writes each gate's full output to `.check_logs/` (gitignored). The fast tier is the
`slow` marker applied from `tests/slow_modules.txt`: it is opt-in (`-m "not slow"`), a plain `pytest`
runs everything, and `uv run python -m tools.slow_report <durations.log> --write` regenerates the list
from a `pytest --durations=0` log. Run the full suite before you hand work back.
