"""``rulesets/prop/INDEX.json``: the append-only content-hash lock (ADR-0107 section 1).

``uv run python -m tools.docgen --write`` regenerates the index and ``--check`` fails when it is
stale. Every v2 ruleset file contributes its firm, id, version, content hash and verification
status; a file still on schema version 1, or a v2 file that does not validate yet (a declaration
this engine now REQUIRES is missing, which is the state a firm file is in until the migration
reaches it), is listed as ``pending_migration`` so the committed index stays stable while the
migration finishes. The index never invents a hash for such a file.

A **cost-assumption file** under ``rulesets/prop/cost_assumptions`` is registered here too, with
its own entry kind: it is versioned data like a ruleset (a change is a new ``*_v2`` file, never an
edit in place once merged) and its SHA-256 is the hash a run's artifact cites. It is not a ruleset:
it carries no firm, version or verification, and ``crucible prop list`` does not list it.

Append-only means an entry that already exists may not disappear and may not reuse a version
number, and a ``verified`` ruleset's hash may never change (the owner's confirmation is what makes
a version immutable data). An ``unverified`` file may still be corrected in place while the firm's
migration is unmerged, which is why its hash may change with it. The same holds for an assumption
file's hash once it is merged. The test compares the index with the copy in git history; this
module only builds the document.
"""

from __future__ import annotations

import json
from pathlib import Path

from crucible.core.errors import ConfigurationError, DataQualityError
from crucible.prop._yaml import safe_load
from crucible.prop.costs import COST_ASSUMPTIONS_DIRNAME, load_cost_assumption
from crucible.prop.ruleset import RULE_SCHEMA_VERSION, load_ruleset

INDEX_SCHEMA_VERSION = 1
INDEX_RELATIVE = Path("rulesets") / "prop" / "INDEX.json"

RULESET_ENTRY_KIND = "ruleset"
COST_ASSUMPTION_ENTRY_KIND = "cost_assumption"
"""The two kinds of entry the lock holds: a firm's ruleset, and a versioned assumption file."""


def is_cost_assumption(path: Path, root: Path) -> bool:
    """Whether ``path`` sits in ``root``'s ``cost_assumptions`` directory (not a ruleset)."""
    return COST_ASSUMPTIONS_DIRNAME in path.relative_to(root).parts[:-1]


def _files(root: Path) -> list[Path]:
    if not root.is_dir():
        return []
    return sorted(
        path
        for path in root.rglob("*")
        if path.is_file()
        and path.suffix in (".yaml", ".yml")
        and not path.name.endswith(".verification.yaml")
    )


def _pending_entry(path: Path, root: Path) -> dict[str, object]:
    raw = safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        msg = f"ruleset {path} must be a YAML mapping"
        raise ConfigurationError(msg)
    return {
        "firm": path.parent.name,
        "path": path.relative_to(root.parent.parent).as_posix(),
        "ruleset_id": raw.get("ruleset_id"),
        "version": raw.get("version"),
        "verification": "pending_migration",
    }


def build_index(root: str | Path) -> dict[str, object]:
    """The INDEX.json document for every ruleset and assumption file under ``rulesets/prop``."""
    prop_root = Path(root)
    entries: list[dict[str, object]] = []
    for path in _files(prop_root):
        if is_cost_assumption(path, prop_root):
            # an assumption file is versioned data with its own entry kind: it validates through
            # its own loader, and its SHA-256 is the one a run records
            assumption = load_cost_assumption(path)
            entries.append(
                {
                    "kind": COST_ASSUMPTION_ENTRY_KIND,
                    "name": assumption.name,
                    "assumption_kind": assumption.kind,
                    "path": path.relative_to(prop_root.parent.parent).as_posix(),
                    "sha256": assumption.sha256,
                }
            )
            continue
        raw = safe_load(path.read_text(encoding="utf-8"))
        version = raw.get("schema_version") if isinstance(raw, dict) else None
        if version != RULE_SCHEMA_VERSION:
            entries.append(_pending_entry(path, prop_root))
            continue
        try:
            ruleset = load_ruleset(path)
        except (ConfigurationError, DataQualityError):
            # a file that does not validate yet is migrating, not a broken index: list it without
            # a hash so ``docgen --check`` keeps working while the firm files catch up
            entries.append(_pending_entry(path, prop_root))
            continue
        entries.append(
            {
                "firm": path.parent.name,
                "path": path.relative_to(prop_root.parent.parent).as_posix(),
                "ruleset_id": ruleset.ruleset_id,
                "version": ruleset.version,
                "ruleset_sha256": ruleset.ruleset_sha256,
                "verification": ruleset.verification.status,
            }
        )
    entries.sort(key=lambda entry: str(entry["path"]))
    return {"schema_version": INDEX_SCHEMA_VERSION, "entries": entries}


def render_index(root: str | Path) -> str:
    return json.dumps(build_index(root), indent=2, sort_keys=True) + "\n"


def index_path(root: str | Path) -> Path:
    return Path(root) / "INDEX.json"
