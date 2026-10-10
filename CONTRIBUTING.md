# Contributing

Thanks for your interest in Crucible. Bug reports, questions and pull requests are welcome.

## Set up

```bash
uv sync --all-extras
```

Use `uv` for everything; do not `pip install` into the project environment.

## Before you open a pull request

Run these from the repository root (CI runs the same):

```bash
uv run pytest
uv run mypy --strict crucible examples tools
uv run ruff check . && uv run ruff format --check crucible tests examples tools
uv run python -m tools.lint_imports
uv run python -m tools.docgen --check      # `--write` regenerates the generated docs
```

Format only `crucible tests examples tools`: formatting the repository root rewrites the Markdown
code blocks under `docs/`. On Windows use `python -m tools.lint_imports`, not the bare
`lint-imports` command.

## What a good change looks like

- **A short design note first** in the PR description or the issue: the problem, where it belongs
  (`docs/WHERE_THINGS_GO.md`), the interfaces touched, the tests and the compatibility impact
  (`docs/COMPATIBILITY.md`).
- **Tests with the code**: unit and property tests for behaviour, a golden test if results move, the
  lookahead harness if you touch data access or signals (`tests/README.md`). Expected values for
  accounting edge cases are computed by hand, not by the engine.
- **Docs are part of the change**: the module page, the generated docs, an ADR for any decision
  another engineer might question, and a line under "Unreleased" in `CHANGELOG.md`.
- **Never silently update a golden fixture.** If one changes, say why in the commit message.

## Principles the project holds itself to

Correctness before speed; the engine enforces rules in code rather than by convention;
identical inputs give identical outputs; when the simulator cannot know it assumes the worse
outcome for the strategy; suspicious states raise with an actionable message instead of warning.
The full list, with the checklists, is in [`AGENTS.md`](AGENTS.md) (written for coding agents, and
just as readable by people).

## Reporting a security problem

Please do not open a public issue for a vulnerability or an exposed credential; contact the
maintainer privately.
