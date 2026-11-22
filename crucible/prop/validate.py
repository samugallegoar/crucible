"""Prop-firm entry points: ruleset validation and the two JSON Schemas (ADR-0106 section 6).

``crucible prop validate <ruleset.yaml>`` and ``crucible schema --kind prop-ruleset|prop-attempt``
are thin wrappers over ``validate_ruleset_document``, ``ruleset_json_schema`` and
``attempt_json_schema``. Validating changes no file: it reports the ruleset's identity, its content
hash, its verification status, its rule coverage and the warnings that coverage implies.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import TypeAdapter

from crucible.core.errors import ConfigurationError
from crucible.prop.attempt import AttemptResult
from crucible.prop.coverage import (
    coverage_warnings,
    evaluation_status,
    material_unmodeled,
    rule_coverage,
)
from crucible.prop.ruleset import Attribution, PropRuleset, Verification, load_ruleset

_ATTEMPT_ADAPTER: TypeAdapter[AttemptResult] = TypeAdapter(AttemptResult)


def attribution_document(source: Attribution) -> dict[str, object]:
    """One attribution as JSON-ready values (the snapshot hash is the evidence)."""
    return {
        "url": source.url,
        "quote": source.quote,
        "snapshot_sha256": source.snapshot_sha256,
        "retrieved_at": source.retrieved_at.isoformat(),
        "section": source.section,
        "synthetic": source.synthetic,
    }


def verification_document(verification: Verification) -> dict[str, object]:
    return {
        "status": verification.status,
        "confirmed_by": verification.confirmed_by,
        "confirmed_at": (
            None if verification.confirmed_at is None else verification.confirmed_at.isoformat()
        ),
        "confirmation_note": verification.confirmation_note,
    }


def ruleset_document(ruleset: PropRuleset) -> dict[str, object]:
    """Everything ``crucible prop validate`` reports about one ruleset; changes nothing."""
    rows = rule_coverage(ruleset)
    return {
        "ruleset_id": ruleset.ruleset_id,
        "version": ruleset.version,
        "ruleset_sha256": ruleset.ruleset_sha256,
        "schema_version": ruleset.schema_version,
        "firm": ruleset.firm,
        "program": ruleset.program,
        "account_size_usd": str(ruleset.account_size_usd),
        "platform": ruleset.platform,
        "addons": list(ruleset.addons),
        "jurisdiction": ruleset.jurisdiction,
        "as_of": ruleset.as_of.isoformat(),
        "effective_from": ruleset.effective_from.isoformat(),
        "effective_to": (
            None if ruleset.effective_to is None else ruleset.effective_to.isoformat()
        ),
        "instruments": [
            {"root": item.root, "contract_weight": str(item.contract_weight)}
            for item in ruleset.instruments
        ],
        "verification": verification_document(ruleset.verification),
        "verified": ruleset.verified,
        "phases": [
            {
                "phase_id": phase.phase_id,
                "kind": phase.kind,
                "starting_balance_usd": str(phase.starting_balance_usd),
                "rules": [rule.rule_id for rule in (*phase.rules, *phase.pass_conditions)],
                "fees_usd": [str(fee.amount_usd) for fee in phase.fees],
            }
            for phase in ruleset.phases
        ],
        "rule_coverage": [
            {
                "rule": row.rule,
                "description": row.description,
                "modeled": row.modeled,
                "materiality": row.materiality,
                "source": attribution_document(row.source),
            }
            for row in rows
        ],
        "evaluation_status": evaluation_status(rows),
        "material_unmodeled": list(material_unmodeled(rows)),
        "warnings": list(coverage_warnings(rows, ruleset)),
    }


def validate_ruleset_document(path: str | Path) -> dict[str, object]:
    """Load and report one ruleset file. A file that does not validate is refused."""
    return ruleset_document(load_ruleset(Path(path)))


def ruleset_json_schema() -> dict[str, object]:
    """The JSON Schema of a ruleset file (``PropRuleset``)."""
    return PropRuleset.model_json_schema()


def attempt_json_schema() -> dict[str, object]:
    """The JSON Schema of an ``AttemptResult`` document."""
    return _ATTEMPT_ADAPTER.json_schema()


def schema_document(kind: str) -> dict[str, object]:
    """``crucible schema --kind prop-ruleset|prop-attempt``."""
    if kind == "prop-ruleset":
        return ruleset_json_schema()
    if kind == "prop-attempt":
        return attempt_json_schema()
    msg = f"unknown prop schema {kind!r}; use prop-ruleset or prop-attempt"
    raise ConfigurationError(msg)
