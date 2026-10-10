"""docs/DEPENDENCIES.md must list every declared dependency, and the code may import only what
is declared (and nothing forbidden). Adding a dependency means a row in that file, in the same
commit (docs/DEPENDENCIES.md §5)."""

from __future__ import annotations

import ast
import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent

# distribution name -> import name, where they differ
_IMPORT_NAME = {"pyyaml": "yaml", "exchange-calendars": "exchange_calendars"}

# never imported anywhere under crucible/, examples/ or tools/ (docs/DEPENDENCIES.md §4)
_FORBIDDEN = (
    "pandas",
    "scipy",
    "sklearn",
    "statsmodels",
    "numba",
    "requests",
    "httpx",
    "aiohttp",
    "ib_insync",
    "dask",
    "torch",
    "tensorflow",
)


def _name(requirement: str) -> str:
    return re.split(r"[<>=!~\[; ]", requirement, maxsplit=1)[0].strip().lower()


def _declared() -> tuple[list[str], list[str]]:
    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    runtime = [_name(req) for req in config["project"]["dependencies"]]
    runtime += [
        _name(req)
        for reqs in config["project"].get("optional-dependencies", {}).values()
        for req in reqs
    ]
    dev = [_name(req) for req in config["dependency-groups"]["dev"]]
    return runtime, dev


def _third_party_imports(folder: str) -> dict[str, list[str]]:
    found: dict[str, list[str]] = {}
    for path in sorted((ROOT / folder).rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                names = [node.module]
            elif isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            for name in names:
                top = name.split(".")[0]
                if top in sys.stdlib_module_names or top in (
                    "crucible",
                    "examples",
                    "tools",
                    "tests",
                ):
                    continue
                found.setdefault(top, []).append(path.relative_to(ROOT).as_posix())
    return found


def test_every_declared_dependency_is_documented() -> None:
    doc = (ROOT / "docs" / "DEPENDENCIES.md").read_text(encoding="utf-8")
    runtime, dev = _declared()
    missing = [name for name in (*runtime, *dev) if f"`{name}`" not in doc]
    assert not missing, f"add these to docs/DEPENDENCIES.md §2/§3 with why and where: {missing}"


def test_the_code_imports_only_declared_runtime_dependencies() -> None:
    runtime, _ = _declared()
    allowed = {_IMPORT_NAME.get(name, name.replace("-", "_")) for name in runtime}
    for folder in ("crucible", "examples", "tools"):
        undeclared = {
            module: files[:2]
            for module, files in _third_party_imports(folder).items()
            if module not in allowed
        }
        assert not undeclared, (
            f"{folder}/ imports packages that are not runtime dependencies: {undeclared}. "
            "Declare them with `uv add` and document them in docs/DEPENDENCIES.md, "
            "or drop the import."
        )


def test_no_forbidden_package_is_declared_or_imported() -> None:
    runtime, dev = _declared()
    declared = {_IMPORT_NAME.get(name, name.replace("-", "_")) for name in (*runtime, *dev)}
    assert not declared & set(_FORBIDDEN), (
        f"forbidden packages declared: {sorted(declared & set(_FORBIDDEN))} "
        "(docs/DEPENDENCIES.md §4: needs an ADR first)"
    )
    for folder in ("crucible", "examples", "tools"):
        used = set(_third_party_imports(folder)) & set(_FORBIDDEN)
        assert not used, f"{folder}/ imports forbidden packages {sorted(used)}"


def test_the_forbidden_list_is_the_documented_one() -> None:
    doc = (ROOT / "docs" / "DEPENDENCIES.md").read_text(encoding="utf-8")
    for name in ("pandas", "numba", "scipy", "Rust/C++"):
        assert name in doc, f"{name} missing from the forbidden/gated table in docs/DEPENDENCIES.md"
