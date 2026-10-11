# AGENTS.md — Operating manual for agents working on Crucible

> Canonical instructions for **any** coding agent (Claude Code, Codex, Cursor, Copilot, Gemini CLI, Aider, …). `CLAUDE.md` and `.gemini/settings.json` just point here — edit this file, not the shims. Section numbers (§1–§14) are cited from code comments and ADRs as `AGENTS.md §N`, so do not renumber.

You are working on **Crucible**, a quant backtesting engine designed to be driven by agents as much as by people (a machine-readable CLI and an MCP server sit on top of the library). Read `README.md`, then `docs/ARCHITECTURE.md` and the module page of the area you touch. This file tells you *how* to work here.

## 1. Prime directives

1. **Correctness over speed, always.** Never optimize a code path that lacks a golden or property test.
2. **The engine enforces; conventions don't.** If a rule matters (lookahead, invariants, fill bounds), it must be code that raises, not a comment.
3. **Determinism is a feature.** Any change that makes identical inputs produce different outputs is a bug, even if the numbers look "better".
4. **When the simulator can't know, it assumes the worse outcome for the strategy.**
5. **Refuse, don't warn.** Suspicious states raise exceptions with actionable messages.
6. **Never silently update golden fixtures.** If a golden test changes, the PR/commit must say why, and an ADR or changelog entry must justify it.
7. **Docs are part of the deliverable.** Code without updated docs is not done.

## 2. Stack and commands

- Python ≥ 3.12, `uv` for everything. Never `pip install` directly.
- `uv sync` — install. `uv run pytest` — tests. `uv run ruff check . && uv run ruff format crucible tests examples tools` — lint/format. `uv run mypy --strict crucible examples tools` — types.
- `uv run python -m tools.lint_imports` — the layering rule (`docs/ARCHITECTURE.md`, "Layering rule"). `uv run python -m tools.docgen --write` — regenerate the generated docs (`docs/INVENTORY.md`, `docs/SCHEMAS.md`, `docs/adr/README.md`); `--check` fails if they are stale.
- Format only `crucible tests examples tools`; formatting the repository root rewrites the Markdown code blocks under `docs/` and corrupts them.
- `uv run crucible --help` — CLI.
- Pre-commit is configured; CI runs lint, mypy, import-linter, the doc generator check, the full test suite on Ubuntu, Windows and macOS, and a clean install of the built wheel with runtime dependencies only, on every push. Keep it green.
- `uv run python -m tools.check` runs the five gates below in order of cost and stops at the first failure (`--keep-going` summarizes instead, `--no-tests` is the static gates only, `--list` prints them); a failure prints the tail of its output and writes the full output to `.check_logs/` (gitignored). `--fast` runs the tests with `-m "not slow"`, the fast tier for the inner loop; the tests run on up to four worker processes (pytest-xdist, ADR-0075), `--serial` runs one; a plain `pytest` and the default `tools.check` always run **everything**, and the full run is what you hand back.

Core libraries: Polars, NumPy, DuckDB, PyArrow, Pydantic v2, `exchange_calendars`, Numba (hot paths only, later), pytest, hypothesis. Every dependency, why it is there, and what may never be added: `docs/DEPENDENCIES.md`.

## 3. Repository map

```
crucible/          library code (one page per module in docs/modules/); `strategy_spec/` and
                   `product/` are the no-code path and the one-step backtest users meet first
docs/
  ARCHITECTURE.md  the system as actually built + the layering rule — keep it truthful
  WHERE_THINGS_GO.md  kind of change -> owning module, with anti-examples
  INVENTORY.md     GENERATED list of every registered component, metric, order type, validator, CLI command
  EXTENSION_POINTS.md  every Protocol: registry, config key, minimal implementation, implementations
  TIMING.md        the per-event call order, when things post (sequence diagrams)
  CONVENTIONS.md   units, signs, currencies, time, names, Decimal/float, exception catalogue
  SCHEMAS.md       every input contract and output artifact (columns generated from code)
  USAGE.md         run a backtest (CLI and Python), the result objects, load and compare runs
  COMPATIBILITY.md config-hash stability, schema_version, semver, golden bugfix vs behaviour change
  DEPENDENCIES.md  every dependency: why, where, pinning, forbidden additions
  INVARIANTS.md    identities the engine must hold; mirrors crucible/core/invariants.py
  GLOSSARY.md      shared vocabulary
  adr/             NNNN-title.md, one decision per file; README.md is the generated index
  modules/         one page per module: What exists, responsibility, interfaces, extension points, Known gaps
  data/            one page per dataset source (section 14)
CHANGELOG.md       append-only history of released changes (never rewritten)
tests/             unit/ property/ golden/ integration/ lookahead/ — see tests/README.md
examples/          runnable strategies + configs; every example is also a test
tools/             doc generators and the import-linter wrapper (not part of the crucible package)
experiments/       artifact store (gitignored except manifests of reference runs)
```

## 4. Working loop for any task

1. **Start with a design note in the PR description or issue.** For anything beyond a trivial fix (a typo, a one-line bug with an obvious test), write down, **before writing code**: the problem, where it belongs, the interfaces touched, the tests, the docs and the compatibility impact. Orient yourself first: `docs/WHERE_THINGS_GO.md`, the relevant `docs/modules/*.md`, `docs/TIMING.md`/`docs/CONVENTIONS.md`/`docs/SCHEMAS.md` where they apply, and any ADR touching the area.
2. **Before adding anything, check `docs/INVENTORY.md` and `docs/EXTENSION_POINTS.md`.** The first lists every registered component, metric, order type, validator, error and CLI command; the second every Protocol with its registry, config key and existing implementations. If it exists, extend it; if a registry exists, use it; never write a second one of something that is listed. Say in the design note what you looked for.
3. **Confirm the baseline**: run the full suite before you build, so a later failure is yours.
4. **Interfaces first**: if adding a component, define/extend the Protocol in the module's `interfaces.py`, then implement. Put code where `docs/WHERE_THINGS_GO.md` says; imports point down only (`docs/ARCHITECTURE.md`, Layering rule).
5. **Tests with the code**: unit + property tests for behavior; golden test if it affects results (classify the change with `docs/COMPATIBILITY.md` §6); lookahead harness if it touches data access or signals. How: `tests/README.md`.
6. **Run the full suite**, not just your tests. Run `mypy --strict`, the layering check (`tools.lint_imports`), and regenerate the generated docs (`uv run python -m tools.docgen --write`).
7. **Docs**: the checklist in section 8 — module page, `ARCHITECTURE.md` if structure changed, `INVARIANTS.md` if an identity was added, and an ADR if you made a decision another engineer might question.
8. **Report**: summarize what changed, what's tested, what's deferred, and any open questions — in that order.

## 5. Coding conventions

- Full type annotations; `mypy --strict` clean. No `Any` without a comment explaining why.
- Events, transactions, and config objects are immutable. Portfolio state is derived from the ledger, never mutated in place.
- Every stateful component (anything that changes during a run) implements `Snapshottable` (`snapshot()`/`restore()`, `crucible/core/interfaces.py`) so a checkpoint can resume it (E7, ADR-0041). Strategy state lives in `ctx.state` or in a `StatefulStrategy` (ADR-0042), never in attributes on `self`: the engine refuses to checkpoint a strategy or risk limit whose attributes changed during the run (ADR-0048).
- Time: internal timestamps are UTC `int64` nanoseconds. Timezones appear only at I/O boundaries and in calendars.
- Every stochastic component takes an explicit `rng: numpy.random.Generator`; never call global RNG.
- Every data accessor takes `as_of` and filters `available_at <= as_of`. If you find yourself needing a full array, you are on the vectorized path and must go through its shift-disciplined API.
- Money: `Decimal` for ledger amounts and fees; floats for prices/returns/analytics. Document the boundary in `accounting/`.
- Errors: subclass `CrucibleError`. `LookaheadError`, `InvariantViolation`, `DataQualityError`, `IllegalOrderTransition`, etc. Messages must say what, where (timestamp, symbol, order id), and how to fix. Which error when, and what the message must contain: `docs/CONVENTIONS.md` §9. Units (bps vs fraction), signs, currencies and naming: the rest of that page.
- Layering: a module imports only from its own package or a layer below it (`docs/ARCHITECTURE.md`, "Layering rule"); `import-linter` enforces it in CI. Strategy-facing code never imports `data.store` or `data.pit`.
- Logging: structured (JSON lines) via the project logger; include event/order/trade ids.
- No hardcoded parameters in engine code; everything flows from Pydantic config.
- Public functions have docstrings stating units, timing semantics (when is this value knowable?), and pessimism assumptions.
- Prefer small modules with one responsibility over large "engine.py" files.

## 6. Adding a new pluggable component (e.g., a slippage model)

0. **Check first**: `docs/INVENTORY.md` (is it already there?) and `docs/EXTENSION_POINTS.md` (the Protocol's row gives the registry, the config key and a minimal implementation you can copy). Write the design note (section 4, step 1).
1. Implement the Protocol from `crucible/execution/interfaces.py`.
2. Register it in the module's registry (`execution/registry.py`) with a stable string key used by config.
3. Add a Pydantic config model; add it to the discriminated union in `experiments/config.py`.
4. Tests: unit, property (e.g., fill within bar, monotone in size), and a golden run on `examples/` at the relevant realism level.
5. Add a section to `docs/modules/execution.md` (assumptions, parameters, references).
6. If the model changes default behavior, write an ADR.
7. If the component holds state that changes during a run, implement `Snapshottable` and add it to the resume-equivalence matrix (section 7).
8. Regenerate the generated docs (`uv run python -m tools.docgen --write`) and add or update its row in `docs/EXTENSION_POINTS.md`; `tests/unit/test_architecture_conformance.py` fails if the component is missing from its module page or the inventory.

## 7. Testing rules

- `tests/lookahead/` must pass for every built-in strategy and every example. If you add a strategy or an accessor, add it to the harness matrix.
- A new stateful component or strategy joins the resume-equivalence matrix (`tests/integration/test_checkpoint_resume_equivalence.py`, invariant I13); anything on the order path is also covered by the live parity tests (`tests/integration/test_live_parity.py`, invariant I14).
- Property tests use `hypothesis`; keep them fast (`max_examples` tuned) and deterministic (`derandomize=True` in CI).
- Golden fixtures live under `tests/golden/fixtures/` with a `README` stating how each was produced. Regeneration requires a `--regen-golden` flag and a justification in the commit.
- Accounting edge cases (splits, dividends on shorts, FX, margin calls, futures rolls) have hand-computed expected ledgers; do not derive expected values from the engine.
- Benchmarks are opt-in (`-m bench`) and never gate correctness work.

## 8. Documentation obligations (checklist before finishing)

- [ ] The design note (PR description) written first and updated with what was actually built.
- [ ] `docs/modules/<module>.md` reflects new/changed interfaces and extension points; it still opens with **What exists** and closes with **Known gaps** (a test enforces both).
- [ ] `docs/INVENTORY.md`, `docs/SCHEMAS.md`, `docs/adr/README.md` regenerated with `uv run python -m tools.docgen --write` (generated from code; tests fail if stale). A schema column needs its `# comment` in code.
- [ ] `docs/EXTENSION_POINTS.md` row added or updated for any Protocol or pluggable component; `docs/WHERE_THINGS_GO.md` if you introduced a new kind of change.
- [ ] `docs/ARCHITECTURE.md` updated if a component, data flow, or layer changed (and the `[tool.importlinter]` contract in `pyproject.toml` with it).
- [ ] `docs/TIMING.md` updated if the call order or the posting time of anything changed; `docs/CONVENTIONS.md` if a unit, sign, naming or error rule changed.
- [ ] `docs/COMPATIBILITY.md` followed for any config-field, artifact-schema or golden-fixture change (a `schema_version` bump, a fixtures README line).
- [ ] `docs/DEPENDENCIES.md` row added for any new dependency; `tests/README.md` updated if you added a test folder, marker or synthetic-data generator; `docs/USAGE.md` if the user-facing API or CLI changed.
- [ ] `docs/INVARIANTS.md` updated if an identity was added/changed, and the invariant is registered in code and tested.
- [ ] ADR written for any non-obvious decision (template: `docs/adr/0000-template.md`). Include: context, decision, alternatives considered, consequences.
- [ ] The README's "Known limitations & future improvements" section updated if a limitation was added, lifted or changed.
- [ ] `docs/GLOSSARY.md` updated for new terms.
- [ ] `CHANGELOG.md` entry under "Unreleased". **`CHANGELOG.md` is append-only**: add entries, never rewrite or delete past ones.
- [ ] Example/config updated if user-facing behavior changed.

## 9. Things to never do

- Never access data without an `as_of`.
- Never fill an order at a price outside the bar's `[low, high]` or before the order could have reached the market.
- Never let a strategy mutate portfolio/ledger state.
- Never read wall-clock time inside the simulation.
- Never store adjusted prices as the raw source of truth.
- Never report a Sharpe (or any headline metric) without CI, trial count, DSR/PBO, and realism level in the same report.
- Never add a Rust/C++ dependency to the core; hot-path ports go behind existing Python interfaces and are optional.
- Never claim a capability in the README or docs without a test (and, for user-facing behaviour, an example) that demonstrates it.

## 10. When uncertain

- Ambiguity that affects results (timing semantics, pessimism rules, accounting conventions): stop, write the options in an ADR draft, choose the more conservative option, and flag it in your summary.
- Ambiguity that is purely stylistic: pick one, stay consistent with the neighboring code, move on.
- If an ADR and the code disagree, the ADR wins unless a newer ADR supersedes it; if there is none, write one or fix the code.

## 11. Definition of done

Code + tests (unit/property/golden/lookahead as applicable) + full suite green + `mypy --strict` clean + layering check clean + generated docs current + docs checklist complete (`CHANGELOG.md` appended) + a summary of what changed, what is tested, what is deferred and any open question.

## 12. Agent quick reference

Fast checks before you hand work back (all from the repo root). `uv run python -m tools.check` runs
the five gates below in this order and stops at the first failure; `--fast` swaps the full test run
for the fast tier while you iterate, and the full run is the one that counts:

```bash
uv run python -m tools.check                      # all gates, fail fast (add --fast while iterating)
uv run pytest                     # full suite, not just your tests
uv run mypy --strict crucible examples tools
uv run ruff check . && uv run ruff format --check crucible tests examples tools
uv run python -m tools.lint_imports   # layering rule
uv run python -m tools.docgen --check   # generated docs are current (--write to fix)
```

- **Where things are:** what exists in `docs/INVENTORY.md` and `docs/EXTENSION_POINTS.md`; where a change belongs in `docs/WHERE_THINGS_GO.md`; module contracts in `docs/modules/<module>.md`; decisions in `docs/adr/` (index in `docs/adr/README.md`); invariants in `docs/INVARIANTS.md` ↔ `crucible/core/invariants.py`; call order in `docs/TIMING.md`; units and errors in `docs/CONVENTIONS.md`; column-level formats in `docs/SCHEMAS.md`; how to run and read a result in `docs/USAGE.md`; what may change and how to record it in `docs/COMPATIBILITY.md`; vocabulary in `docs/GLOSSARY.md`.
- **Commits:** one logical step per commit, an imperative subject that says what changed (name the ADR when there is one). Golden-fixture changes must say why in the message. Do not push to `main`.
- **Cross-session memory:** nothing but the repository itself travels between sessions: decisions go in ADRs, history in `CHANGELOG.md` and git. Tool-local scratch (`.claude/`, `.superpowers/`, `.hypothesis/`) is gitignored and must never be the only record of a decision.

## 13. Environment pitfalls

- **Windows / PowerShell:** never rewrite repo files with `Get-Content`/`Set-Content` (or `>`): it introduces a BOM and UTF-8 mojibake. Use your editor/patch tool, or Python with `encoding="utf-8"`. Files are LF (`.gitattributes`).
- Never run the formatter over the repository root; scope it to `crucible tests examples tools` (Markdown code blocks under `docs/` are rewritten and corrupted otherwise).
- **Windows console encoding:** the bare `lint-imports` command prints box-drawing characters and crashes with `UnicodeEncodeError` on a legacy code page before it reports anything. Use the wrapper `uv run python -m tools.lint_imports` (it sets `PYTHONUTF8=1`), never the bare command, on Windows.
- Use `uv run …` so the pinned interpreter and lockfile are used; never `pip install`.
- Parallel or background agents should work in a separate `git worktree` so they do not clobber each other's working copy.
- Tests are deterministic too: fixed timestamps and seeded `numpy.random.Generator`, never wall-clock time or global RNG.
- **Edit scripts:** a bash heredoc turns a backslash-n inside a Python string into a real newline and breaks the script. Write scripts that contain one with your editor/Write tool, or build the character with `chr(10)`.
- **`__main__.py`:** keep the call under `if __name__ == "__main__":`. `tools.docgen` imports every module under `crucible/`; an unguarded one runs at import time (it once held a docs run for two hours). `tests/unit/test_main_modules_guarded.py` enforces it.
- **Long runs:** run the full suite in the background with its output in a file and one pytest at a time; the harness stops background jobs when memory is critically low. `tools.check` runs the tests on up to four worker processes (ADR-0075, about 4-5 minutes); `--serial` runs one process (about 9-10 minutes, less memory).
- **uv noise:** `UV_LINK_MODE=copy` silences the hardlink warning on another drive; a stale `VIRTUAL_ENV` only prints a warning (`tools.check` and the MCP server clear it for children).
- **Worktrees** contain tracked files only: untracked or git-excluded files (private notes, `.env`, built datasets) are not there. Rebuild a venv per worktree (`uv sync --locked --all-extras`).

## 14. Data ingestion

1. **Trigger.** Before working with any dataset or data source, check `docs/data/` for a doc describing it (`docs/data/<source-name>.md`). If one exists, follow it and do not re-ingest.
2. **No doc yet? Ingest first.**
   - Locate the raw source and record where it came from (path or URL, when it was obtained, what produced it).
   - Inspect schema, types, row counts and sample records.
   - Note data-quality issues: nulls, duplicates, odd formats, outliers, timezones, and price basis (raw vs adjusted).
   - Load/clean it into `data/processed/` (gitignored local store) as Parquet: use `crucible data build <spec>` if that command supports the format (see `docs/modules/cli.md`), otherwise `crucible.data.store.build_dataset` with the contracts in `crucible/data/contracts.py` (`event_time`, `available_at`).
   - Never modify the raw source; only read it.
3. **Then document it.** Create `docs/data/<source-name>.md` covering: source, schema, known issues, cleaning steps applied (with counts of rows dropped or repaired), and the exact command to re-run the ingestion.
4. **Stop and ask the user** if the source is ambiguous, or if ingestion would be destructive or expensive (overwriting data, very large files, paid or metered API calls).
