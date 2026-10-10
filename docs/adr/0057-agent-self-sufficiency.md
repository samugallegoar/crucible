# ADR-0057: Docs that cannot drift: generated references, conformance tests, a layering contract

- **Status**: accepted
- **Date**: 2026-09-28

## Context

The goal: an agent with no prior context can add a feature correctly using only what is in the
repository. An audit (the project notes, session 2026-09-28) found that the repository
described *what* to build (the original requirements), *how to work* (AGENTS.md) and each module in prose, but nothing
answered the questions an agent asks first: where does this change belong, what already exists,
in what order do things run, what is the exact format of this file, which unit is this number,
what may I change without breaking reproducibility. Where a doc did exist it had drifted:
`ARCHITECTURE.md` still described Phase 2, the CLI section said commands were unimplemented,
`examples/README.md` said the vectorized and live paths had no CLI, one Protocol (`Ledger`) named a
method the implementation did not have, and ten Protocols had no implementation and no note saying
so. No import rule existed beyond a sentence in `docs/modules/core.md`.

## Decision

1. **Generate what can be generated, and test the rest against the code.**
   `tools/docgen.py` renders `docs/INVENTORY.md` (registries, enums, CLI, metrics, validators,
   errors), the column tables of `docs/SCHEMAS.md` (Polars schemas, pydantic JSON Schema, DuckDB
   DDL, `MANIFEST_FIELDS`) and `docs/adr/README.md` between `GENERATED` markers in hand-written
   files. `tests/unit/test_generated_docs.py` fails when a block is stale. A schema column's
   documentation is the `# comment` beside it in code, and a missing comment fails the build.
2. **Machine-check the hand-written tables.** `docs/EXTENSION_POINTS.md` has one row per Protocol;
   `tests/unit/test_architecture_conformance.py` requires a row for every Protocol under
   `crucible/`, resolves every listed implementation and checks it defines every Protocol member,
   requires `stub` rows to list none and to be named in the module's *Known gaps*, and executes the
   minimal-implementation blocks. Module pages must open with *What exists* and close with *Known
   gaps*; every registered component must be named on its module page.
3. **A layering contract enforced by import-linter** (`[tool.importlinter]`): eight layers, imports
   point down, `TYPE_CHECKING` imports ignored, function-level imports counted, two allow-listed
   lazy cycles, and a `forbidden` contract keeping strategy-facing code away from `data.store` and
   `data.pit`. It runs in CI, in pre-commit and from the conformance tests; a test fails when a
   module is missing from the contract.
4. **Artifact schemas live in one module.** `experiments/artifacts.py` holds the ledger, order,
   fill and equity schemas, `MANIFEST_FIELDS`, `SCHEMA_VERSION` (written to `manifest.json`), and a
   read-only `load_experiment` / `compare_metrics`. The runner builds its frames from the constants;
   golden hashes are unchanged (`manifest.json` is outside the golden surface).
5. **Fix the drift found:** the `Ledger` Protocol now describes `append` / `__iter__` / `fold`;
   `docs/ARCHITECTURE.md`, `examples/README.md` and the roadmap's known gaps were corrected.
6. **Record policy, not just mechanism:** `docs/COMPATIBILITY.md` states the config-hash rule
   (additions only, prove inertness in the golden diff), `schema_version` bump rules, the 0.x
   versioning rule, and how to classify a golden change (inert addition, bugfix, behaviour change,
   representation change, regression).

Not decided here (flagged for the owner): whether `config_hash` should hash only non-default fields
(see `docs/COMPATIBILITY.md` §2); what to do with the ten stub Protocols; whether `pyarrow` stays a
core dependency.

## Alternatives considered

- **Hand-maintained inventory and schema pages.** Cheapest to write, and exactly what drifted.
- **mkdocs / autodoc API pages.** Deferred by the original requirements; they document signatures, not the decisions,
  timing or units an agent needs, and add a build dependency.
- **One `layers` contract at package granularity.** Fails immediately: `crucible.core` contains both
  the kernel and `core/engine.py`, which imports every domain package. Module-level layers express the
  real structure.
- **Change `config_hash` now to survive field additions.** Correct in principle, but it renames
  every experiment id once and is a compatibility decision the owner should make.
- **Deleting the stub Protocols.** They may be needed (`MetricsComputer`, `ArtifactStore`); deleting
  is an owner decision. Marking them stubs and testing the mark is reversible.

## Consequences

- A new package, registered component, Protocol, CLI command, schema column, config field or ADR
  fails a fast test until the matching doc is updated: the checklist in AGENTS.md §8 is now mostly
  enforced.
- Adding a config field or a component means running `uv run python -m tools.docgen --write` and
  committing the result; on Windows use `uv run python -m tools.lint_imports` (the bare `lint-imports` crashes on a legacy console code page).
- The generator imports the whole package, so an import error anywhere breaks the doc tests too
  (acceptable: it is also broken everywhere else).
- Generated text depends on pinned library versions (pydantic's JSON Schema, DuckDB's information
  schema); a dependency upgrade may require regenerating `docs/SCHEMAS.md`.
- `tools/` is checked by ruff and `mypy --strict` like the package but is not shipped.
