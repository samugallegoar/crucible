"""Prop-firm simulation: sourced rulesets, bar-by-bar account overlay, attempts (ADR-0106/0107).

The engine knows rule kinds, never a firm. ``rules_schema`` holds the schema-version-2 rule
models, ``ruleset`` the ruleset, the content hash and the verification sidecar, ``scenarios`` the
sensitivity scenarios of a conflict, ``rules`` one evaluator per kind, ``overlay`` the
``AccountOverlay`` the futures simulation calls inside each bar, ``lifecycle`` the account state
machine, ``news`` the scheduled-event rows, ``attempt`` one attempt from one start trade date,
``coverage`` the rule coverage and the evaluation status, ``confirm`` the owner's TTY-only
verification and ``index`` the generated append-only hash lock.
"""

from __future__ import annotations

from crucible.prop.attempt import (
    AttemptResult,
    CommissionApplication,
    FeeBreakdown,
    PayoutRecord,
    PhaseOutcome,
    estimate_status,
    practical_eligibility,
    simulate_attempt,
)
from crucible.prop.coverage import (
    RuleCoverageRow,
    counterfactual_application,
    coverage_warnings,
    evaluation_status,
    material_unmodeled,
    rule_coverage,
)
from crucible.prop.index import build_index, render_index
from crucible.prop.lifecycle import EOD_ORDER, AccountState, Lifecycle, Transition
from crucible.prop.list import list_document
from crucible.prop.news import Coverage, NewsEvent, coverage_covers
from crucible.prop.overlay import PropAccountOverlay
from crucible.prop.ruleset import (
    Attribution,
    Commissions,
    Conflict,
    ConflictAlternative,
    NotModeled,
    PayoutRule,
    Phase,
    PropRuleset,
    Verification,
    VerificationRecord,
    is_pass_condition,
    load_registry,
    load_ruleset,
    read_verification_sidecar,
    sidecar_path,
    write_verification_sidecar,
)
from crucible.prop.scenarios import RulesetScenario, scenario, scenarios
from crucible.prop.validate import (
    attempt_json_schema,
    ruleset_document,
    ruleset_json_schema,
    schema_document,
    validate_ruleset_document,
)

__all__ = [
    "EOD_ORDER",
    "AccountState",
    "AttemptResult",
    "Attribution",
    "CommissionApplication",
    "Commissions",
    "Conflict",
    "ConflictAlternative",
    "Coverage",
    "FeeBreakdown",
    "Lifecycle",
    "NewsEvent",
    "NotModeled",
    "PayoutRecord",
    "PayoutRule",
    "Phase",
    "PhaseOutcome",
    "PropAccountOverlay",
    "PropRuleset",
    "RuleCoverageRow",
    "RulesetScenario",
    "Transition",
    "Verification",
    "VerificationRecord",
    "attempt_json_schema",
    "build_index",
    "counterfactual_application",
    "coverage_covers",
    "coverage_warnings",
    "estimate_status",
    "evaluation_status",
    "is_pass_condition",
    "list_document",
    "load_registry",
    "load_ruleset",
    "material_unmodeled",
    "practical_eligibility",
    "read_verification_sidecar",
    "render_index",
    "rule_coverage",
    "ruleset_document",
    "ruleset_json_schema",
    "scenario",
    "scenarios",
    "schema_document",
    "sidecar_path",
    "simulate_attempt",
    "validate_ruleset_document",
    "write_verification_sidecar",
]
