"""``crucible prop list``: the rulesets, their hashes and their evidence (ADR-0107 section 6).

The listing is read-only. A file still on schema version 1, and a v2 file that does not validate
yet (missing a declaration this engine now requires), is reported as ``pending_migration`` rather
than refused, so the command keeps working while the migration workers finish. ``crucible prop
validate <file>`` is the command that refuses, and it still does.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from crucible.core.errors import ConfigurationError, DataQualityError
from crucible.prop.ruleset import RULE_SCHEMA_VERSION, load_ruleset
from crucible.prop.validate import listing_document

LIST_SCHEMA_VERSION = 1


def default_root() -> Path:
    """``rulesets/prop`` beside the repository that holds this package."""
    return Path(__file__).resolve().parents[2] / "rulesets" / "prop"


def _files(root: Path) -> list[Path]:
    return sorted(
        path
        for path in root.rglob("*.yaml")
        if path.is_file() and not path.name.endswith(".verification.yaml")
    )


def list_document(root: str | Path | None = None, *, firm: str | None = None) -> dict[str, object]:
    base = default_root() if root is None else Path(root)
    if not base.is_dir():
        msg = (
            f"ruleset root {base} is not a directory: pass --root pointing at rulesets/prop "
            "(the rulesets live outside the installed package)"
        )
        raise ConfigurationError(msg)
    entries: list[dict[str, object]] = []
    for path in _files(base):
        if firm is not None and path.parent.name != firm:
            continue
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        version = raw.get("schema_version") if isinstance(raw, dict) else None
        if version != RULE_SCHEMA_VERSION:
            entries.append(
                {
                    "ruleset_id": raw.get("ruleset_id") if isinstance(raw, dict) else None,
                    "version": raw.get("version") if isinstance(raw, dict) else None,
                    "firm": path.parent.name,
                    "ruleset_sha256": None,
                    "verified": False,
                    "verification_status": "pending_migration",
                    "evidence_counts": {},
                    "conflicts": 0,
                    "not_modeled_by_materiality": {},
                    "evaluation_status": "not_modeled",
                }
            )
            continue
        try:
            row = listing_document(load_ruleset(path))
        except (ConfigurationError, DataQualityError):
            entries.append(
                {
                    "ruleset_id": raw.get("ruleset_id") if isinstance(raw, dict) else None,
                    "version": raw.get("version") if isinstance(raw, dict) else None,
                    "firm": path.parent.name,
                    "path": path.relative_to(base).as_posix(),
                    "ruleset_sha256": None,
                    "verified": False,
                    "verification_status": "pending_migration",
                    "evidence_counts": {},
                    "conflicts": 0,
                    "not_modeled_by_materiality": {},
                    "evaluation_status": "not_modeled",
                }
            )
            continue
        row["path"] = path.relative_to(base).as_posix()
        entries.append(row)
    entries.sort(key=lambda item: (str(item["firm"]), str(item["ruleset_id"]), item["version"]))
    return {
        "schema_version": LIST_SCHEMA_VERSION,
        "rulesets": entries,
        "count": len(entries),
    }
