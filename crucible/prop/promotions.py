"""Promotional values that depend on what the participant bought (ADR-0107, amendment 2026-11-23).

A firm's page sometimes publishes a better value for a limited offer: a doubled payout cap for an
account bought during the offer, with the discount chosen at purchase. That value is not the
ruleset's value and it is not inferable either: it applies only when the RUN can show it bought the
account in that window. So a numeric rule field may carry ``promotions``, and each one states the
value (or the multiplier), the offer window, and the facts the purchase must satisfy
(``requires``, checked against the run's participant profile, plus ``purchase_date``).

**Never assume eligibility.** A promotion is applied only when EVERY requirement is declared in the
profile and matches, and the purchase date the profile declares falls in
``[starts_on, ends_on]``. ``ends_on: unknown`` means the offer's end is not stated, so it is never
assumed to continue past the ruleset's ``as_of``: a purchase date after ``as_of`` does not qualify.
Anything missing or ``unknown`` leaves the base value in place and the summary says why
(``promotion <id> not applied: <reason>``).

The resolution is a pure function of the ruleset and the profile: no clock, no network.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from decimal import Decimal
from typing import TYPE_CHECKING

from crucible.core.errors import ConfigurationError
from crucible.data.exchange_fees import CLASSIFICATION_VALUE_UNKNOWN, ParticipantProfile

if TYPE_CHECKING:
    from collections.abc import Sequence

    from crucible.prop.rules_schema import Promotion, _Rule
    from crucible.prop.ruleset import PropRuleset

PURCHASE_DIMENSION = "purchase_date"
"""The profile dimension that dates the purchase (``YYYY-MM-DD``): the window is checked on it."""


@dataclass(frozen=True, slots=True)
class PromotionOutcome:
    """What the promotions did: the ones applied, and the reason each of the others was not."""

    applied: tuple[str, ...] = ()
    not_applied: tuple[str, ...] = ()
    promoted: dict[str, str] = field(default_factory=dict)
    """``{rule_id.field: value}`` for every field a promotion replaced, for the report."""

    @property
    def applied_ids(self) -> tuple[str, ...]:
        """The ids of the promotions that applied, in declaration order."""
        return tuple(entry.split(":", 1)[0] for entry in self.applied)


def promotion_reason(
    promotion: Promotion, profile: ParticipantProfile | None, *, as_of: dt.date
) -> str | None:
    """``None`` when the promotion applies, else the reason it does not (pessimistic by default)."""
    if profile is None:
        return "no participant profile was declared"
    for dimension, required in sorted(promotion.requires.items()):
        stated = profile.lookup(dimension)
        if stated is None:
            return f"{dimension} not declared"
        if stated == CLASSIFICATION_VALUE_UNKNOWN:
            return f"{dimension} is unknown"
        if stated != required:
            return f"{dimension} is {stated!r}, not {required!r}"
    raw = profile.lookup(PURCHASE_DIMENSION)
    if raw is None:
        return f"{PURCHASE_DIMENSION} not declared"
    if raw == CLASSIFICATION_VALUE_UNKNOWN:
        return f"{PURCHASE_DIMENSION} is unknown"
    try:
        purchased = dt.date.fromisoformat(raw)
    except ValueError:
        return f"{PURCHASE_DIMENSION} {raw!r} is not YYYY-MM-DD"
    if promotion.purchase_on_or_after is not None and purchased < promotion.purchase_on_or_after:
        return (
            f"the purchase on {purchased.isoformat()} is before "
            f"{promotion.purchase_on_or_after.isoformat()}"
        )
    if purchased < promotion.starts_on:
        return (
            f"the purchase on {purchased.isoformat()} is before the offer start "
            f"{promotion.starts_on.isoformat()}"
        )
    if promotion.ends_on == "unknown":
        if purchased > as_of:
            return (
                f"the purchase on {purchased.isoformat()} is after the ruleset's as_of "
                f"{as_of.isoformat()} and the offer's end is unknown"
            )
    elif purchased > promotion.ends_on:
        return (
            f"the purchase on {purchased.isoformat()} is after the offer end "
            f"{promotion.ends_on.isoformat()}"
        )
    return None


def _number(base: object, *, where: str) -> Decimal:
    if isinstance(base, bool) or not isinstance(base, Decimal | int):
        msg = (
            f"{where}: the promoted field's base value {base!r} is not a number, so no multiplier "
            "or value can be applied to it"
        )
        raise ConfigurationError(msg)
    return Decimal(base)


def promoted_value(promotion: Promotion, base: object, *, where: str) -> Decimal:
    """The value a promotion puts in place of ``base`` (its own, or ``base`` x its multiplier)."""
    if promotion.value is not None:
        return promotion.value
    assert promotion.multiplier is not None
    return _number(base, where=where) * promotion.multiplier


def apply_promotion(rule: _Rule, promotion: Promotion) -> _Rule:
    """``rule`` with the promotion's field replaced; ``field`` may name a sequence element."""
    where = f"promotion {promotion.id} on rule {rule.rule_id}"
    name, _, element = promotion.field.partition("[")
    if not hasattr(rule, name):
        msg = f"{where}: field {name!r} is not a field of this {rule.rule_id} rule"
        raise ConfigurationError(msg)
    current = getattr(rule, name)
    if element:
        try:
            index = int(element.rstrip("]"))
        except ValueError as exc:
            msg = f"{where}: field {promotion.field!r} does not name a sequence element"
            raise ConfigurationError(msg) from exc
        if not isinstance(current, tuple | list):
            msg = f"{where}: field {name!r} is not a list, so {promotion.field!r} cannot index it"
            raise ConfigurationError(msg)
        if not 0 <= index < len(current):
            msg = f"{where}: field {name!r} has {len(current)} entries, not {index + 1}"
            raise ConfigurationError(msg)
        replaced = list(current)
        replaced[index] = promoted_value(promotion, current[index], where=where)
        return rule.model_copy(update={name: tuple(replaced)})
    return rule.model_copy(update={name: promoted_value(promotion, current, where=where)})


def _resolve_rule(
    rule: _Rule, profile: ParticipantProfile | None, *, as_of: dt.date
) -> tuple[_Rule, list[str], list[str], dict[str, str]]:
    """One rule with its applicable promotions applied, plus what was applied and skipped."""
    applied: list[str] = []
    skipped: list[str] = []
    promoted: dict[str, str] = {}
    used: set[str] = set()
    for promotion in rule.promotions:
        reason = promotion_reason(promotion, profile, as_of=as_of)
        if reason is not None:
            skipped.append(f"promotion {promotion.id} not applied: {reason}")
            continue
        if promotion.field in used:
            msg = (
                f"promotion {promotion.id} on rule {rule.rule_id}: two promotions apply to "
                f"{promotion.field!r} at once, so the value would depend on declaration order"
            )
            raise ConfigurationError(msg)
        used.add(promotion.field)
        rule = apply_promotion(rule, promotion)
        shown = getattr(rule, promotion.field.partition("[")[0])
        applied.append(f"{promotion.id}:{rule.rule_id}:{promotion.field}={shown}")
        promoted[f"{rule.rule_id}.{promotion.field}"] = str(shown)
    return rule, applied, skipped, promoted


def resolve_promotions(
    ruleset: PropRuleset, profile: ParticipantProfile | None
) -> tuple[PropRuleset, PromotionOutcome]:
    """``ruleset`` with every APPLICABLE promotion applied, and what happened to each of them.

    A promotion that does not apply leaves the base value in place and its reason travels with the
    result, so the summary can say ``promotion <id> not applied: <reason>`` rather than silently
    using the worse (or the better) number.
    """
    applied: list[str] = []
    skipped: list[str] = []
    promoted: dict[str, str] = {}
    as_of = ruleset.as_of
    phases = []
    for phase in ruleset.phases:
        updates: dict[str, object] = {}
        for name in ("rules", "pass_conditions", "fees"):
            entries: Sequence[_Rule] = getattr(phase, name)
            resolved: list[_Rule] = []
            changed = False
            for rule in entries:
                if not getattr(rule, "promotions", ()):
                    resolved.append(rule)
                    continue
                new, done, missed, values = _resolve_rule(rule, profile, as_of=as_of)
                resolved.append(new)
                changed = True
                applied.extend(done)
                skipped.extend(missed)
                promoted.update(values)
            if changed:
                updates[name] = tuple(resolved)
        phases.append(phase.model_copy(update=updates) if updates else phase)
    outcome = PromotionOutcome(
        applied=tuple(applied),
        not_applied=tuple(skipped),
        promoted=promoted,
    )
    if not applied and not skipped:
        return ruleset, outcome
    return ruleset.model_copy(update={"phases": tuple(phases)}), outcome


__all__ = [
    "PURCHASE_DIMENSION",
    "PromotionOutcome",
    "apply_promotion",
    "promoted_value",
    "promotion_reason",
    "resolve_promotions",
]
