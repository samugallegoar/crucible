"""Generated documentation must match the code (docs/SCHEMAS.md, docs/INVENTORY.md,
docs/adr/README.md): fails when a registry, schema, config model, CLI command or ADR changed
without ``uv run python -m tools.docgen --write`` in the same commit."""

from __future__ import annotations

from pathlib import Path

from tools import docgen

ROOT = Path(__file__).resolve().parent.parent.parent


def test_generated_blocks_are_up_to_date() -> None:
    stale = [
        rel
        for rel, text in docgen.render_files().items()
        if (ROOT / rel).read_text(encoding="utf-8") != text
    ]
    assert not stale, (
        f"generated docs are stale: {stale}. Run `uv run python -m tools.docgen --write` "
        "and commit the result with your change."
    )


def test_every_schema_column_has_a_documenting_comment() -> None:
    undocumented = docgen.undocumented_columns()
    assert not undocumented, (
        f"schema columns without a trailing `# comment`: {undocumented}. The comment beside the "
        "column is its documentation (start it with `nullable` if the column may be null)."
    )


def test_every_adr_file_is_in_the_index() -> None:
    index = (ROOT / "docs" / "adr" / "README.md").read_text(encoding="utf-8")
    missing = [path.name for path in docgen.adr_files() if path.name not in index]
    assert not missing, f"ADRs missing from docs/adr/README.md: {missing}; run tools.docgen --write"


def test_adr_numbers_are_unique_and_titles_carry_their_number() -> None:
    numbers = [path.name[:4] for path in docgen.adr_files()]
    assert len(numbers) == len(set(numbers)), "duplicate ADR number"
    for path in docgen.adr_files():
        first = path.read_text(encoding="utf-8").splitlines()[0]
        assert first.startswith(f"# ADR-{path.name[:4]}:"), f"{path.name}: title line is {first!r}"
