"""The agent manual must carry the rules the checkpoint work taught us and must
not tell agents to format the repo root (it corrupts Markdown code blocks)."""

from __future__ import annotations

import re
from pathlib import Path

MANUAL = Path("AGENTS.md")


def _text() -> str:
    return MANUAL.read_text(encoding="utf-8")


def test_the_manual_never_tells_agents_to_format_the_repo_root() -> None:
    for line in _text().splitlines():
        assert "ruff format ." not in line, line
        assert "ruff format --check ." not in line, line


def test_the_manual_requires_snapshottable_for_stateful_components() -> None:
    text = _text()
    assert "Snapshottable" in text
    assert "StatefulStrategy" in text


def test_the_manual_requires_the_resume_equivalence_matrix() -> None:
    text = _text()
    assert "test_checkpoint_resume_equivalence" in text
    assert "test_live_parity" in text


def test_ci_does_not_format_the_repo_root() -> None:
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert "ruff format --check ." not in workflow


def test_the_readme_does_not_format_the_repo_root() -> None:
    for line in Path("README.md").read_text(encoding="utf-8").splitlines():
        assert "ruff format ." not in line, line
        assert "ruff format --check ." not in line, line


def test_the_manual_tells_agents_to_check_the_data_docs_before_ingesting() -> None:
    text = _text()
    assert "## 14. Data ingestion" in text
    assert "docs/data/" in text


def _section(number: int) -> str:
    text = _text()
    start = text.index(f"## {number}. ")
    following = re.search(rf"^## {number + 1}\. ", text[start:], re.M)
    return text[start : start + following.start()] if following else text[start:]


def test_the_working_loop_starts_with_a_design_note() -> None:
    loop = _section(4)
    first_step = loop.split("\n1. ", 1)[1].split("\n2. ", 1)[0]
    assert "design note" in first_step
    assert "before writing code" in first_step


def test_the_manual_says_to_check_the_inventory_and_extension_points_before_adding_anything() -> (
    None
):
    for section in (4, 6):
        text = _section(section)
        assert "docs/INVENTORY.md" in text, f"section {section}"
        assert "docs/EXTENSION_POINTS.md" in text, f"section {section}"
    assert "Before adding anything" in _section(4)


def test_the_documentation_checklist_names_every_new_doc() -> None:
    checklist = _section(8)
    for doc in (
        "docs/INVENTORY.md",
        "docs/SCHEMAS.md",
        "docs/EXTENSION_POINTS.md",
        "docs/WHERE_THINGS_GO.md",
        "docs/TIMING.md",
        "docs/CONVENTIONS.md",
        "docs/COMPATIBILITY.md",
        "docs/DEPENDENCIES.md",
        "docs/USAGE.md",
        "tests/README.md",
        "docs/adr/README.md",
    ):
        assert doc in checklist, f"{doc} missing from the section 8 checklist"


def test_the_changelog_is_append_only() -> None:
    assert "append-only" in _section(8)


def test_the_quick_reference_runs_the_layering_and_doc_gates() -> None:
    quick = _section(12)
    assert "tools.lint_imports" in quick
    assert "tools.docgen --check" in quick
    assert "mypy --strict crucible examples tools" in quick


def test_ci_runs_the_layering_and_doc_gates() -> None:
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert "tools.lint_imports" in workflow
    assert "tools.docgen --check" in workflow
    assert "mypy --strict crucible examples tools" in workflow
