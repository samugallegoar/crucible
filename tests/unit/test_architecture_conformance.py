"""Architecture-conformance tests: the docs, the registries, the Protocols and the layering
rule must agree with the code (AGENTS.md §4, §8; docs/EXTENSION_POINTS.md,
docs/INVENTORY.md, docs/ARCHITECTURE.md "Layering rule").

Each failure message says what to fix. These run on every push, so an agent that adds a
package, a registered component, a Protocol or an import that breaks the layering finds out
in the same session, not in review.
"""

from __future__ import annotations

import importlib
import inspect
import pkgutil
import re
import tomllib
from pathlib import Path
from typing import Any

import pytest

import crucible
from tools import docgen, lint_imports

ROOT = Path(__file__).resolve().parent.parent.parent
MODULE_DOCS = ROOT / "docs" / "modules"


def _read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def _packages() -> list[str]:
    return sorted(
        path.name
        for path in (ROOT / "crucible").iterdir()
        if path.is_dir() and (path / "__init__.py").is_file()
    )


# ------------------------------------------------------------------ module doc pages


def test_every_package_has_a_module_doc_and_every_module_doc_has_a_package() -> None:
    documented = sorted(path.stem for path in MODULE_DOCS.glob("*.md"))
    assert documented == _packages(), (
        "docs/modules/<package>.md must exist for every crucible/<package>/ and vice versa; "
        "add the page (start from an existing one) or remove the orphan"
    )


@pytest.mark.parametrize("package", _packages())
def test_module_doc_opens_with_what_exists_and_closes_with_known_gaps(package: str) -> None:
    headings = re.findall(
        r"^## (.+?)\s*$", (MODULE_DOCS / f"{package}.md").read_text("utf-8"), re.M
    )
    assert headings, f"docs/modules/{package}.md has no sections"
    assert headings[0] == "What exists", (
        f"docs/modules/{package}.md must open with '## What exists' (first section is "
        f"{headings[0]!r}): list the concrete things the module provides today"
    )
    assert headings[-1] == "Known gaps", (
        f"docs/modules/{package}.md must close with '## Known gaps' (last section is "
        f"{headings[-1]!r}): list what is missing, even if it is 'none known'"
    )


# --------------------------------------------------------------------- the inventory


def test_every_registered_component_is_in_its_module_doc() -> None:
    missing: list[str] = []
    for section in docgen.inventory_sections():
        for row in section.rows:
            if row.doc is None or row.term is None:
                continue
            text = _read(row.doc)
            if row.term not in text:
                missing.append(f"{section.title}: {row.term!r} not in {row.doc}")
    assert not missing, (
        "registered components must be documented where they live (add them to the page's "
        "'What exists' section):\n  " + "\n  ".join(missing)
    )


def test_inventory_lists_every_registered_component() -> None:
    inventory = _read("docs/INVENTORY.md")
    absent = [
        f"{section.title}: {row.cells[0]}"
        for section in docgen.inventory_sections()
        for row in section.rows
        if row.cells[0] not in inventory
    ]
    assert not absent, f"docs/INVENTORY.md is stale ({absent[:3]}...): run tools.docgen --write"


# ------------------------------------------------------------------------ protocols

_ROW_CELLS = 8


def _extension_rows() -> list[dict[str, str]]:
    rows = []
    for line in _read("docs/EXTENSION_POINTS.md").splitlines():
        if not line.startswith("| `crucible."):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split(" | ")]
        assert len(cells) == _ROW_CELLS, f"malformed EXTENSION_POINTS row: {line[:80]}"
        rows.append(
            dict(
                zip(
                    (
                        "protocol",
                        "module",
                        "registry",
                        "config",
                        "minimal",
                        "doc",
                        "impls",
                        "status",
                    ),
                    cells,
                    strict=True,
                )
            )
        )
    return rows


def _resolve(dotted: str) -> Any:
    module_name, _, attr = dotted.rpartition(".")
    return getattr(importlib.import_module(module_name), attr)


def _has_member(obj: Any, name: str) -> bool:
    """Class attribute, annotation, or an attribute the class assigns in ``__init__``."""
    if hasattr(obj, name):
        return True
    if any(name in inspect.get_annotations(base) for base in getattr(obj, "__mro__", ())):
        return True
    try:
        init_source = inspect.getsource(obj.__init__)
    except (OSError, TypeError):
        return False
    return re.search(rf"self\.{re.escape(name)}\s*(?::[^=\n]+)?=", init_source) is not None


def _missing_members(implementation: Any, protocol: type) -> list[str]:
    if not inspect.isclass(implementation):
        return [] if callable(implementation) else ["__call__"]
    return sorted(
        name for name in docgen.protocol_members(protocol) if not _has_member(implementation, name)
    )


def test_every_protocol_has_exactly_one_row_in_extension_points() -> None:
    documented = [row["protocol"].strip("`") for row in _extension_rows()]
    assert len(documented) == len(set(documented)), "duplicate Protocol rows in EXTENSION_POINTS"
    in_code = set(docgen.protocols())
    assert not in_code - set(documented), (
        "Protocols without a row in docs/EXTENSION_POINTS.md (add one; mark it `stub` if nothing "
        f"implements it): {sorted(in_code - set(documented))}"
    )
    assert not set(documented) - in_code, (
        f"rows for Protocols that no longer exist: {sorted(set(documented) - in_code)}"
    )


def test_every_protocol_has_an_implementation_or_is_marked_a_stub() -> None:
    protocols = docgen.protocols()
    problems: list[str] = []
    for row in _extension_rows():
        name = row["protocol"].strip("`")
        implementations = re.findall(r"`([\w.]+)`", row["impls"])
        status = row["status"]
        if status not in ("implemented", "stub"):
            problems.append(f"{name}: status must be `implemented` or `stub`, not {status!r}")
        elif status == "stub" and implementations:
            problems.append(f"{name}: marked stub but lists implementations {implementations}")
        elif status == "implemented" and not implementations:
            problems.append(f"{name}: marked implemented but lists no implementation")
        for dotted in implementations:
            try:
                implementation = _resolve(dotted)
            except (ImportError, AttributeError):
                problems.append(f"{name}: implementation {dotted} does not exist")
                continue
            absent = _missing_members(implementation, protocols[name])
            if absent:
                problems.append(f"{name}: {dotted} lacks members {absent}")
    assert not problems, "docs/EXTENSION_POINTS.md disagrees with the code:\n  " + "\n  ".join(
        problems
    )


def test_stub_protocols_are_named_in_their_module_known_gaps() -> None:
    unlisted = []
    for row in _extension_rows():
        if row["status"] != "stub":
            continue
        doc = row["doc"].strip("`")
        short = row["protocol"].strip("`").rsplit(".", 1)[-1]
        gaps = _read(doc).split("## Known gaps", 1)[-1]
        if short not in gaps:
            unlisted.append(f"{short} (in {doc})")
    assert not unlisted, (
        "a stub Protocol must be named in its module doc's 'Known gaps' so nobody assumes it "
        f"works: {unlisted}"
    )


def test_each_extension_row_points_at_a_doc_page_that_mentions_it() -> None:
    problems = []
    for row in _extension_rows():
        doc = row["doc"].strip("`")
        short = row["protocol"].strip("`").rsplit(".", 1)[-1]
        if not (ROOT / doc).is_file():
            problems.append(f"{short}: page {doc} does not exist")
        elif short not in _read(doc):
            problems.append(f"{short}: not mentioned in {doc}")
    assert not problems, "\n  ".join(["extension-point doc pages:", *problems])


def _minimal_blocks() -> list[tuple[str, str]]:
    text = _read("docs/EXTENSION_POINTS.md")
    blocks = re.findall(r"```python minimal\n(.*?)```", text, re.S)
    out = []
    for block in blocks:
        match = re.match(r"# implements: ([\w.]+)\n", block)
        assert match, f"minimal block must start with '# implements: <Protocol>':\n{block[:80]}"
        out.append((match.group(1), block))
    return out


def test_there_are_minimal_implementations_for_the_pluggable_protocols() -> None:
    covered = {protocol for protocol, _ in _minimal_blocks()}
    linked = {
        row["protocol"].strip("`") for row in _extension_rows() if row["minimal"].startswith("[")
    }
    assert linked <= covered, (
        f"rows link a minimal implementation that has no code block: {sorted(linked - covered)}"
    )


@pytest.mark.parametrize(("protocol", "block"), _minimal_blocks(), ids=lambda v: v[:60])
def test_minimal_implementations_run_and_satisfy_their_protocol(protocol: str, block: str) -> None:
    namespace: dict[str, Any] = {"__name__": "minimal_block"}
    exec(compile(block, f"<minimal {protocol}>", "exec"), namespace)
    defined = [
        obj
        for obj in namespace.values()
        if (inspect.isclass(obj) or inspect.isfunction(obj)) and obj.__module__ == "minimal_block"
    ]
    assert defined, f"the {protocol} block defines nothing"
    absent = _missing_members(defined[0], docgen.protocols()[protocol])
    assert not absent, f"{defined[0].__name__} lacks {absent} required by {protocol}"


# --------------------------------------------------------------------------- layering


def _layer_entries() -> list[str]:
    config = tomllib.loads(_read("pyproject.toml"))
    contract = next(c for c in config["tool"]["importlinter"]["contracts"] if c["type"] == "layers")
    return [entry.strip() for layer in contract["layers"] for entry in layer.split("|")]


def test_every_module_belongs_to_a_layer() -> None:
    """A module missing from the layers contract would be exempt from the layering rule."""
    layers = _layer_entries()
    uncovered = []
    for info in pkgutil.walk_packages(crucible.__path__, "crucible."):
        if info.ispkg:
            continue
        if not any(info.name == layer or info.name.startswith(layer + ".") for layer in layers):
            uncovered.append(info.name)
    assert not uncovered, (
        "modules not covered by the [tool.importlinter] layers contract in pyproject.toml "
        f"(add each to the right layer, docs/ARCHITECTURE.md 'Layering rule'): {uncovered}"
    )


def test_layers_name_only_existing_modules() -> None:
    known = {info.name for info in pkgutil.walk_packages(crucible.__path__, "crucible.")}
    stale = [layer for layer in _layer_entries() if layer not in known]
    assert not stale, f"layers name modules that do not exist: {stale}"


def test_import_linter_contracts_pass(capfd: pytest.CaptureFixture[str]) -> None:
    """The same command CI and pre-commit run (`uv run python -m tools.lint_imports`)."""
    code = lint_imports.main([])
    output = capfd.readouterr().out
    assert code == 0, (
        "import-linter contracts broken (or not installed: `uv sync`):\n" + output[-3000:]
    )


# ------------------------------------------------------------ examples and the harness


def test_every_example_strategy_is_in_the_lookahead_harness() -> None:
    lookahead = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (ROOT / "tests" / "lookahead").glob("test_*.py")
    )
    missing = [
        path.parent.name
        for path in sorted((ROOT / "examples").glob("*/strategy.py"))
        if f"examples.{path.parent.name}" not in lookahead
        and f"examples/{path.parent.name}" not in lookahead
    ]
    assert not missing, (
        f"examples without a lookahead test: {missing}; add them to tests/lookahead "
        "(tests/README.md 'Adding to the lookahead matrix')"
    )
