"""Rule coverage and evaluation status: what is modeled, what is declared unmodeled (ADR-0106).

Unmodeled rules are never ignored. Every rule of the ruleset is one coverage row marked
``modeled``; every ``not_modeled`` entry is a row marked ``not_modeled`` with its materiality. The
status follows from the worst unmodeled materiality:

- ``complete``: nothing is unmodeled, or only immaterial rules are (they still warn);
- ``conditional_on_modeled_rules``: a material rule is unmodeled, so a claim is conditional on
  the modeled rules only;
- ``blocked``: a critical rule is unmodeled, so no definitive verdict is possible.

``counterfactual_application`` labels rules read now applied to a data window that starts before
the ruleset's ``effective_from``: every pre-2025 run under current rules.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Literal

from crucible.prop.ruleset import Attribution, PropRuleset

Materiality = Literal["immaterial", "material", "critical"]
EvaluationStatus = Literal["complete", "conditional_on_modeled_rules", "blocked"]


@dataclass(frozen=True, slots=True)
class RuleCoverageRow:
    """One firm rule: modeled or declared unmodeled, with its materiality and its source."""

    rule: str
    description: str
    materiality: Materiality
    modeled: bool
    source: Attribution


def rule_coverage(ruleset: PropRuleset) -> tuple[RuleCoverageRow, ...]:
    """One row per rule of every phase, then one per ``not_modeled`` entry."""
    rows: list[RuleCoverageRow] = []
    for phase in ruleset.phases:
        for rule in (*phase.rules, *phase.pass_conditions, *phase.fees):
            rows.append(
                RuleCoverageRow(
                    rule=f"{phase.phase_id}.{rule.rule_id}",
                    description=rule.description or rule.kind,
                    materiality="immaterial",
                    modeled=True,
                    source=rule.source,
                )
            )
    rows.extend(
        RuleCoverageRow(
            rule=entry.rule,
            description=entry.description,
            materiality=entry.materiality,
            modeled=False,
            source=entry.source,
        )
        for entry in ruleset.not_modeled
    )
    return tuple(rows)


def material_unmodeled(
    rows: tuple[RuleCoverageRow, ...] | list[RuleCoverageRow],
) -> tuple[str, ...]:
    """The unmodeled rules that weaken a claim (material or critical)."""
    return tuple(row.rule for row in rows if not row.modeled and row.materiality != "immaterial")


def evaluation_status(
    rows: tuple[RuleCoverageRow, ...] | list[RuleCoverageRow],
) -> EvaluationStatus:
    """The worst unmodeled materiality decides the status."""
    unmodeled = {row.materiality for row in rows if not row.modeled}
    if "critical" in unmodeled:
        return "blocked"
    if "material" in unmodeled:
        return "conditional_on_modeled_rules"
    return "complete"


def coverage_warnings(
    rows: tuple[RuleCoverageRow, ...] | list[RuleCoverageRow], ruleset: PropRuleset
) -> tuple[str, ...]:
    """Every declared gap, plus the ruleset's own labels. Warnings, never silent weakening."""
    warnings = [
        f"{row.rule} is not modeled ({row.materiality}): {row.description}"
        for row in rows
        if not row.modeled
    ]
    if not ruleset.verified:
        warnings.append(
            f"ruleset {ruleset.ruleset_id} v{ruleset.version} is unverified: no result computed "
            "from it may be presented as confirmed firm rules"
        )
    return tuple(warnings)


def counterfactual_application(data_start: dt.date, ruleset: PropRuleset) -> bool:
    """True when the data window starts before the ruleset took effect: current rules applied to
    an older market is a counterfactual application, and the result says so."""
    return data_start < ruleset.effective_from
