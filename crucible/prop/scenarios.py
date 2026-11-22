"""Sensitivity scenarios: the primary ruleset plus one per conflict alternative (ADR-0107 s7).

A conflict keeps the selected value and every alternative with its own source. Each alternative
becomes a *sensitivity scenario*: a full ``PropRuleset`` with that one field switched, a stable
``scenario_id`` and the label ``sensitivity``. A scenario is never an official plan and its result
is reported beside the primary, never instead of it.

The generation order is deterministic: the primary first, then conflicts in declaration order and
alternatives in declaration order, so the same ruleset always yields the same scenario list.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from pydantic import ValidationError

from crucible.core.errors import ConfigurationError
from crucible.prop.ruleset import Conflict, ConflictAlternative, PropRuleset

ScenarioLabel = Literal["official", "sensitivity"]
PRIMARY_SCENARIO_ID = "primary"


@dataclass(frozen=True, slots=True)
class RulesetScenario:
    """One scenario: a full ruleset, its id and whether it is official or a sensitivity."""

    scenario_id: str
    label: ScenarioLabel
    ruleset: PropRuleset
    conflict_id: str | None = None
    alternative_index: int | None = None
    rationale: str = ""

    @property
    def is_primary(self) -> bool:
        return self.scenario_id == PRIMARY_SCENARIO_ID


def scenario_id(conflict: Conflict, alternative_index: int) -> str:
    return f"{conflict.conflict_id}#{alternative_index}"


def _apply_alternative(
    raw: dict[str, object], conflict: Conflict, alternative: ConflictAlternative
) -> dict[str, object]:
    """Deep copy of the raw ruleset with the conflict's alternative applied on ``rule_id``.

    ``value: absent`` removes the rule from that scenario instead of switching a field: the
    alternative reading is that the rule does not exist, so the scenario carries no such rule
    (ADR-0107 section 7).
    """
    import copy

    switched = copy.deepcopy(raw)
    phases = switched.get("phases")
    if not isinstance(phases, list):
        msg = "ruleset phases must be a list to build a scenario"
        raise ConfigurationError(msg)
    found = False
    for phase in phases:
        if not isinstance(phase, dict):
            continue
        for collection in ("rules", "pass_conditions", "fees"):
            rules = phase.get(collection) or []
            kept: list[object] = []
            for rule in rules:
                if not isinstance(rule, dict) or rule.get("rule_id") != conflict.rule_id:
                    kept.append(rule)
                    continue
                if alternative.absent:
                    found = True
                    continue
                if conflict.field not in rule:
                    msg = (
                        f"conflict {conflict.conflict_id} names field {conflict.field!r} on rule "
                        f"{conflict.rule_id!r}, which the rule does not declare"
                    )
                    raise ConfigurationError(msg)
                kept.append({**rule, conflict.field: alternative.value})
                found = True
            if phase.get(collection) is not None:
                phase[collection] = kept
    if not found:
        msg = (
            f"conflict {conflict.conflict_id} names rule {conflict.rule_id!r}, which is not in "
            "the ruleset"
        )
        raise ConfigurationError(msg)
    if alternative.absent:
        # the conflict named a rule this reading does not have: keeping it would be a conflict
        # about nothing, and the ruleset refuses a conflict whose rule it does not declare
        remaining = switched.get("conflicts")
        if isinstance(remaining, list):
            switched["conflicts"] = [
                item
                for item in remaining
                if not isinstance(item, dict) or item.get("conflict_id") != conflict.conflict_id
            ]
    # a switched sensitivity is never the official record and carries no verification
    switched.pop("verification", None)
    return switched


def scenarios(ruleset: PropRuleset) -> list[RulesetScenario]:
    """The primary scenario, then one sensitivity scenario per (conflict, alternative)."""
    out = [
        RulesetScenario(
            scenario_id=PRIMARY_SCENARIO_ID,
            label="official",
            ruleset=ruleset,
            rationale="the selected value of every rule, as the owner would trade it",
        )
    ]
    raw = ruleset.model_dump(mode="json")
    for conflict in ruleset.conflicts:
        for index, alternative in enumerate(conflict.alternatives):
            switched = _apply_alternative(raw, conflict, alternative)
            try:
                candidate = PropRuleset.model_validate(switched)
            except ValidationError as exc:
                msg = (
                    f"conflict {conflict.conflict_id} alternative {index} "
                    f"({alternative.value!r}) does not make a valid ruleset: {exc}"
                )
                raise ConfigurationError(msg) from exc
            out.append(
                RulesetScenario(
                    scenario_id=scenario_id(conflict, index),
                    label="sensitivity",
                    ruleset=candidate,
                    conflict_id=conflict.conflict_id,
                    alternative_index=index,
                    rationale=conflict.rationale,
                )
            )
    return out


def scenario(ruleset: PropRuleset, wanted: str) -> RulesetScenario:
    """One scenario by id; an unknown id is refused with the ids that exist."""
    for candidate in scenarios(ruleset):
        if candidate.scenario_id == wanted:
            return candidate
    msg = (
        f"scenario {wanted!r} is not in ruleset {ruleset.ruleset_id} v{ruleset.version}; "
        f"scenarios are {[s.scenario_id for s in scenarios(ruleset)]}"
    )
    raise ConfigurationError(msg)
