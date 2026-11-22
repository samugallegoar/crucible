"""Prop-firm simulation: sourced rulesets, bar-by-bar account overlay, attempts (ADR-0106).

The engine knows rule kinds, never a firm. ``ruleset`` holds the versioned data models and the
loader, ``rules`` one evaluator per kind, ``overlay`` the ``AccountOverlay`` the futures
simulation calls inside each bar, ``attempt`` one attempt from one start trade date, and
``coverage`` the rule coverage and the evaluation status.
"""

from __future__ import annotations

from crucible.prop.attempt import AttemptResult, PayoutRecord, PhaseOutcome, simulate_attempt
from crucible.prop.coverage import (
    RuleCoverageRow,
    counterfactual_application,
    coverage_warnings,
    evaluation_status,
    material_unmodeled,
    rule_coverage,
)
from crucible.prop.overlay import PropAccountOverlay
from crucible.prop.ruleset import (
    Attribution,
    NotModeled,
    PayoutRule,
    Phase,
    PropRuleset,
    Verification,
    is_pass_condition,
    load_registry,
    load_ruleset,
)
from crucible.prop.validate import (
    attempt_json_schema,
    ruleset_document,
    ruleset_json_schema,
    schema_document,
    validate_ruleset_document,
)

__all__ = [
    "AttemptResult",
    "Attribution",
    "NotModeled",
    "PayoutRecord",
    "PayoutRule",
    "Phase",
    "PhaseOutcome",
    "PropAccountOverlay",
    "PropRuleset",
    "RuleCoverageRow",
    "Verification",
    "attempt_json_schema",
    "counterfactual_application",
    "coverage_warnings",
    "evaluation_status",
    "is_pass_condition",
    "load_registry",
    "load_ruleset",
    "material_unmodeled",
    "rule_coverage",
    "ruleset_document",
    "ruleset_json_schema",
    "schema_document",
    "simulate_attempt",
    "validate_ruleset_document",
]
