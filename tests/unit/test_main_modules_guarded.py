"""A ``__main__.py`` must not do work at import time.

``tools.docgen`` (and any module walker) imports every module under ``crucible/``; an unguarded
``__main__`` that starts a server or reads standard input hangs that run (it once held a docs
generation for two hours). Every ``__main__.py`` must put its call under
``if __name__ == "__main__":``.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

MODULES = sorted(Path("crucible").rglob("__main__.py"))


def _is_main_guard(node: ast.stmt) -> bool:
    if not isinstance(node, ast.If) or not isinstance(node.test, ast.Compare):
        return False
    test = node.test
    return (
        isinstance(test.left, ast.Name)
        and test.left.id == "__name__"
        and len(test.comparators) == 1
        and isinstance(test.comparators[0], ast.Constant)
        and test.comparators[0].value == "__main__"
    )


def test_there_is_at_least_one_main_module_to_check() -> None:
    assert MODULES, "crucible/ no longer has a __main__.py; delete this test if that is intended"


@pytest.mark.parametrize("path", MODULES, ids=lambda p: p.as_posix())
def test_main_module_has_no_statement_that_runs_at_import_time(path: Path) -> None:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    allowed = (ast.Import, ast.ImportFrom, ast.FunctionDef, ast.ClassDef, ast.Pass)
    for node in tree.body:
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
            continue  # the module docstring
        if _is_main_guard(node):
            continue
        assert isinstance(node, allowed), (
            f"{path}: line {node.lineno} runs at import time; put it under "
            '`if __name__ == "__main__":` so a module walker can import this file'
        )
