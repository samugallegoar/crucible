"""Prop-firm ruleset schema version 2: typed rules, evidence, conflicts and commissions.

Every rule kind declares its own firm semantics explicitly: the metric and basis, the threshold,
the observation frequency, the reset boundary and its time zone. There is no default for any of
them, because a default would be the engine inventing a firm rule (ADR-0106 section 4,
ADR-0107 section 8).

Schema version 2 adds (ADR-0107 sections 7-12):

- ``evidence`` on every rule: ``official_quote``, ``owner_provided``, ``assumption`` or
  ``conflict_resolution``, with an ``Assumption`` when the value is an assumption.
- ``conflicts``: a genuine contradiction keeps both sources and its alternatives, each of which
  becomes a sensitivity scenario (``crucible.prop.scenarios``).
- explicit day units (``calendar_days``, ``trade_dates``, ``trading_days``, ``winning_days``).
- ``commissions`` per root and side, never assumed to be zero when unknown.
- ``compliance`` rules, which gate practical eligibility rather than the mechanical account.

A value is a number, ``unlimited`` (only where the source states it) or absent. A numeric sentinel
is refused: an unknown value belongs in ``not_modeled``, never in a rule.

The C7b vocabulary round 2 adds, additively and without changing the meaning of an existing
declaration (ADR-0107 sections 7-13):

- ``payout.max_usd`` and every ``max_usd_by_payout`` rung also accept ``unknown``: the engine pays
  what the other terms allow and labels the payout and cash statistics ``upper_bound``. ``unknown``
  is never ``unlimited`` (a source that states no cap says ``unlimited``).
- ``trailing_drawdown.lock.on`` is a LIST of triggers (``[hwm, first_payout]``); the lock happens at
  the first trigger that fires. A bare string is refused.
- ``payout.threshold_after_payout: set_threshold`` with ``set_threshold_to: start |
  start_plus_usd:<x> | zero_balance_offset:<x>`` sets the threshold to an explicit level instead
  of trailing it.
- ``news_restriction.effect: block | contract_cap`` (REQUIRED, with a weighted
  ``cap_contracts`` when the effect is ``contract_cap``).
- ``activity_requirement``: at least N qualifying rule-days in EVERY rolling window of M days.
- ``payout.min_new_profit_share_of_request``.
- ``consistency``'s numerator (best day) and denominator (profit) windows declared separately.
- ``commissions.components``: REQUIRED, with all four keys (``exchange``, ``clearing``, ``nfa``,
  ``other``), each ``{status: included|excluded|unknown, evidence, text}``. A component declared
  ``included`` or ``excluded`` needs a quotation that says so; ``unknown`` is never a zero cost.
- ``commissions.components``: REQUIRED, with all four keys (``exchange``, ``clearing``, ``nfa``,
  ``other``), each ``{status: included|excluded|unknown, evidence, text}``. A component declared
  ``included`` or ``excluded`` needs a quotation that says so; ``unknown`` is never a zero cost.
  The old ``includes_exchange_and_regulatory_fees`` flag is refused by name.

The owner-review round 2 adds, additively (ADR-0107, amendment of 2026-11-23):

- ``compliance.effect: condition`` with a REQUIRED ``condition`` text: an obligation the simulation
  cannot prove and the trader must meet. Practical eligibility becomes ``eligible_conditional`` and
  every condition is listed; a mechanical pass is then a CONDITIONAL valid pass.
- ``not_modeled.becomes_immaterial_if``: the audited fact that would change an entry's materiality.
  The declared materiality is unchanged by it.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_MONEY = Annotated[Decimal, Field(decimal_places=6)]
_MONEY_GE0 = Annotated[Decimal, Field(ge=0, decimal_places=6)]
_HEX64 = r"^[0-9a-f]{64}$"
SENTINEL_FLOOR_USD = Decimal(1_000_000)
"""A capability above this is a sentinel, not a firm rule; ``unlimited`` says it instead."""

Evidence = Literal["official_quote", "owner_provided", "assumption", "conflict_resolution"]
AssumptionKind = Literal["section7_default", "provisional_conservative", "owner_decision"]
"""What KIND of default an assumption is: a documented ADR-0107 section 7 default, a provisional
conservative reading of a silent or soft source, or the owner's own decision on it."""
COST_COMPONENT_NAME = Literal["exchange", "clearing", "nfa", "other"]
COST_COMPONENTS: tuple[COST_COMPONENT_NAME, ...] = ("exchange", "clearing", "nfa", "other")
"""The per-side cost components a firm's commission may or may not contain (ADR-0107 section 10).

``other`` is any other per-side charge the firm states; a component the sources do not state is
``unknown``, never zero."""
CostComponentStatus = Literal["included", "excluded", "unknown"]
"""What a firm says about one component: inside the commission, charged on top, or not stated."""
CostEvidence = Literal["official_quote", "owner_provided", "not_stated"]
"""How a component's status is evidenced: a quotation (``official_quote``/``owner_provided``), or
``not_stated`` with a note naming what was checked, which only ``unknown`` may use."""
ThresholdLevel = Literal["start", "start_plus_usd", "zero_balance_offset"]
"""The explicit level a payout may set a trailing threshold to (``set_threshold_to``)."""
LockTrigger = Literal["hwm", "first_payout"]
"""What fires a trailing lock. At least one; the lock happens at the first one that fires."""
DayUnit = Literal["calendar_days", "trade_dates", "trading_days", "winning_days"]
Observation = Literal["intraday", "eod", "on_request"]
Comparison = Literal["<=", "<", ">=", ">"]
BreachAction = Literal[
    "fail", "soft_lock_until_reset", "liquidate", "block_entries", "promote_phase", "none"
]
Materiality = Literal["immaterial", "material", "critical"]
ExecutionMode = Literal["automated", "manual"]


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Attribution(_Frozen):
    """Where a value comes from (ADR-0106 section 2, ADR-0107 section 7).

    ``provided_by: owner`` is the owner-supplied evidence: the URL is optional (the owner may
    have read a PDF or a mailbox) but the quotation and the hash of the saved text are required.
    ``synthetic`` marks invented test data, and a synthetic attribution can never verify.
    """

    url: str | None = None
    quote: str
    snapshot_sha256: str = Field(pattern=_HEX64)
    retrieved_at: dt.datetime
    section: str | None = None
    synthetic: bool = False
    provided_by: Literal["owner"] | None = None

    @model_validator(mode="after")
    def _utc(self) -> Attribution:
        if self.retrieved_at.tzinfo is None:
            msg = (
                "attribution.retrieved_at must carry a UTC offset: a naive timestamp cannot say "
                "when the source was read"
            )
            raise ValueError(msg)
        if self.provided_by != "owner" and not self.url:
            msg = (
                "attribution needs a url, or provided_by: owner for an owner-supplied value: an "
                "unsourced value is not a rule"
            )
            raise ValueError(msg)
        if not self.quote:
            msg = "attribution needs a non-empty quote: an unsourced value is not a rule"
            raise ValueError(msg)
        return self

    @property
    def complete(self) -> bool:
        """Whether the attribution carries every field an owner confirmation needs."""
        return bool(
            self.quote
            and len(self.snapshot_sha256) == 64
            and (self.url or self.provided_by == "owner")
        )


class Assumption(_Frozen):
    """A named default the owner accepted where the firm is silent (ADR-0107 section 7).

    ``assumption_kind`` is REQUIRED and says what KIND of default it is (ADR-0107, amendment of
    2026-11-23): ``section7_default`` (the documented default of that section), a
    ``provisional_conservative`` reading (the source is silent or soft, and the pessimistic reading
    is temporary: the owner may tighten it), or ``owner_decision`` (the owner ruled on it).
    """

    name: str
    rationale: str
    assumption_kind: AssumptionKind

    @model_validator(mode="after")
    def _text(self) -> Assumption:
        if not self.name.strip() or not self.rationale.strip():
            msg = "an assumption needs a non-empty name and rationale"
            raise ValueError(msg)
        return self


class Verification(_Frozen):
    """A fact ABOUT a content hash, never part of it (ADR-0107 sections 1-2).

    In a ruleset file only ``unverified`` is accepted: verification lives in the sidecar
    ``<file>.verification.yaml`` and the loader attaches it. ``rules_checked`` must name every rule
    before the status can become ``verified``.
    """

    status: Literal["unverified", "verified"] = "unverified"
    confirmed_by: str | None = None
    confirmed_at: dt.datetime | None = None
    confirmation_note: str | None = None
    rules_checked: tuple[str, ...] = ()


class ResetClock(_Frozen):
    """A rule-day boundary in its own time zone. Required, never defaulted (ADR-0107 section 8)."""

    time: dt.time
    tz: str

    @model_validator(mode="after")
    def _zone(self) -> ResetClock:
        _zone(self.tz, "reset.tz")
        return self


class Instrument(_Frozen):
    """A tradable root and its contract weight (1 mini, 0.1 micro)."""

    root: str
    contract_weight: Decimal = Field(gt=0, decimal_places=6)

    @model_validator(mode="after")
    def _root(self) -> Instrument:
        if self.root != self.root.upper() or not self.root:
            msg = f"instrument root {self.root!r} must be a non-empty upper-case root"
            raise ValueError(msg)
        return self


class NotModeled(_Frozen):
    """A firm rule the vocabulary cannot express. Declared, never silently dropped.

    ``becomes_immaterial_if`` names the audited fact that would change the entry's materiality: on a
    ``material`` (or ``critical``) entry the fact that would let it be read as immaterial, on an
    ``immaterial`` entry the fact that would make it bind. It is a CONDITION, never a downgrade: the
    declared ``materiality`` stays exactly as written until an audit shows the condition holds, so a
    ``material`` entry keeps weakening the estimate (ADR-0107, amendment of 2026-11-23).
    """

    rule: str
    description: str
    materiality: Materiality
    source: Attribution
    becomes_immaterial_if: str | None = None

    @field_validator("becomes_immaterial_if")
    @classmethod
    def _condition(cls, value: str | None) -> str | None:
        """A condition is text a reviewer can check, never an empty marker."""
        if value is None:
            return None
        if not value.strip():
            msg = (
                "not_modeled.becomes_immaterial_if is empty: either name the audited fact that "
                "would change the materiality, or omit the field"
            )
            raise ValueError(msg)
        return value


class CostComponentDeclaration(_Frozen):
    """What a firm says about ONE per-side cost component of its commission (ADR-0107 s10).

    ``status`` is ``included`` (the firm's per-side commission contains this component),
    ``excluded`` (the firm charges it on top of the commission) or ``unknown`` (the sources do not
    say). An ``included`` or ``excluded`` declaration needs a quote that says so, so ``evidence``
    is ``official_quote`` or ``owner_provided`` and ``text`` is that quotation. An ``unknown``
    declaration carries ``evidence: not_stated`` and ``text`` is a short note naming what was
    checked; an unknown component is never read as a zero cost.
    """

    status: CostComponentStatus
    evidence: CostEvidence
    text: str

    @model_validator(mode="after")
    def _stated(self) -> CostComponentDeclaration:
        if not self.text.strip():
            msg = (
                "a cost component needs non-empty text: the quotation that states its status, or "
                "the note naming what was checked when the sources are silent"
            )
            raise ValueError(msg)
        if self.status in ("included", "excluded"):
            if self.evidence not in ("official_quote", "owner_provided"):
                msg = (
                    f"a component declared {self.status} needs a quotation that says so: evidence "
                    f"must be official_quote or owner_provided, not {self.evidence!r}"
                )
                raise ValueError(msg)
        elif self.evidence != "not_stated":
            msg = (
                "a component declared unknown is a fact the sources do not state: evidence must "
                f"be not_stated, not {self.evidence!r}"
            )
            raise ValueError(msg)
        return self


class CostComponents(_Frozen):
    """Every per-side cost component of a commission, one declaration each (ADR-0107 s10).

    All four keys are REQUIRED and there are no defaults: a missing key would be the engine
    deciding a cost component the firm never declared (ADR-0107 section 8). There is no ``all_in``
    shortcut either, because firms that publish an all-in rate still do not say what is inside it.
    """

    exchange: CostComponentDeclaration
    clearing: CostComponentDeclaration
    nfa: CostComponentDeclaration
    other: CostComponentDeclaration

    def declaration(self, name: COST_COMPONENT_NAME) -> CostComponentDeclaration:
        """The declaration of one component (the fields above are exactly those four)."""
        by_name: dict[str, CostComponentDeclaration] = {
            "exchange": self.exchange,
            "clearing": self.clearing,
            "nfa": self.nfa,
            "other": self.other,
        }
        return by_name[name]

    def status(self, name: COST_COMPONENT_NAME) -> CostComponentStatus:
        """The declared status of one component."""
        return self.declaration(name).status

    def of_status(self, status: CostComponentStatus) -> tuple[COST_COMPONENT_NAME, ...]:
        """The components declared with ``status``, in report order."""
        return tuple(name for name in COST_COMPONENTS if self.status(name) == status)


class Commissions(_Frozen):
    """Per-side commissions by root (ADR-0107 section 10). Unknown is never zero.

    ``components`` says, per cost component (exchange, clearing, NFA, other), whether the firm's
    per-side commission contains it (``included``), excludes it (``excluded``, so the run adds the
    component from the fee dataset) or does not say (``unknown``). It is REQUIRED, with all four
    keys: the difference between an all-in and an ex-fees commission is a cost, and a default
    would be the engine inventing one (ADR-0107 section 8).

    ``evidence`` is the kind of evidence behind the commission figures themselves: a per-side
    table the owner supplied is ``owner_provided`` and pending independent verification, and it is
    never described as all-in.
    """

    status: Literal["known", "unknown"]
    components: CostComponents
    per_side_usd: dict[str, _MONEY_GE0] = Field(default_factory=dict)
    platform: str | None = None
    evidence: Evidence = "official_quote"
    source: Attribution

    @model_validator(mode="before")
    @classmethod
    def _no_all_in_flag(cls, data: object) -> object:
        if isinstance(data, dict) and "includes_exchange_and_regulatory_fees" in data:
            msg = (
                "commissions.includes_exchange_and_regulatory_fees is gone: declare each cost "
                "component instead in the required commissions.components block "
                "(exchange, clearing, nfa, other, each {status, evidence, text})"
            )
            raise ValueError(msg)
        return data

    @model_validator(mode="after")
    def _consistent(self) -> Commissions:
        if self.status == "known" and not self.per_side_usd:
            msg = (
                "commissions.status is known but no per_side_usd root is declared: a known "
                "commission table needs at least one root"
            )
            raise ValueError(msg)
        if self.status == "unknown" and self.per_side_usd:
            msg = (
                "commissions.status is unknown but per_side_usd values are declared: an unknown "
                "commission is never a number, use status known or omit the values"
            )
            raise ValueError(msg)
        for root, value in self.per_side_usd.items():
            if root != root.upper() or not root:
                msg = f"commission root {root!r} must be a non-empty upper-case root"
                raise ValueError(msg)
            if value >= SENTINEL_FLOOR_USD:
                msg = (
                    f"commission for {root} is {value} USD per side, which looks like a sentinel; "
                    "a real commission is a small number"
                )
                raise ValueError(msg)
        return self

    def per_side(self, root: str) -> Decimal | None:
        return self.per_side_usd.get(root)

    @property
    def excluded_components(self) -> tuple[str, ...]:
        """The components the firm charges on top of the commission, in report order."""
        return self.components.of_status("excluded")

    @property
    def unknown_components(self) -> tuple[str, ...]:
        """The components the sources do not state, in report order: never a zero cost."""
        return self.components.of_status("unknown")

    @property
    def all_in(self) -> bool:
        """``True`` only when every component is declared ``included`` by a quotation."""
        return not self.excluded_components and not self.unknown_components


ABSENT = "absent"
"""A conflict alternative's value meaning the rule does not exist under that reading.

``value: absent`` is the only string a conflict may use as a marker: no rule field accepts the
string ``"absent"``, and ``scenarios()`` drops the rule from that scenario instead of switching a
field (ADR-0107 section 7).
"""


class ConflictAlternative(_Frozen):
    """One value the source conflict also states, with its own attribution.

    ``value: absent`` says the rule does not exist under the alternative reading: the scenario
    built from it carries no such rule, rather than the rule with another value.
    """

    value: object
    source: Attribution

    @property
    def absent(self) -> bool:
        """Whether this alternative removes the rule instead of switching a value."""
        return self.value == ABSENT


class Conflict(_Frozen):
    """A genuine contradiction, its selected value and every alternative (ADR-0107 section 7)."""

    conflict_id: str
    rule_id: str
    field: str
    selected_value: object
    alternatives: tuple[ConflictAlternative, ...]
    selected_source: Attribution
    rationale: str
    applicability_checked: Literal[True]

    @model_validator(mode="after")
    def _alternatives(self) -> Conflict:
        if not self.alternatives:
            msg = f"conflict {self.conflict_id}: a conflict keeps at least one alternative"
            raise ValueError(msg)
        if any(alt.value == self.selected_value for alt in self.alternatives):
            msg = (
                f"conflict {self.conflict_id}: an alternative equals the selected value "
                f"{self.selected_value!r}, which is not a contradiction"
            )
            raise ValueError(msg)
        return self


class Promotion(_Frozen):
    """A better value for a limited offer, applied only when the RUN can show it qualifies.

    ``field`` names the numeric field of the rule it replaces (``max_usd``,
    ``max_usd_by_payout[0]``, ``amount_usd``); exactly one of ``value`` (the promoted value) and
    ``multiplier`` (the base value times it) is given. ``requires`` is checked against the run's
    participant profile, where account dimensions such as ``account_purchase: new`` or
    ``dll_selected_at_purchase: 'true'`` are ordinary profile entries, and the profile's
    ``purchase_date`` must fall in
    ``[starts_on, ends_on]``, where ``ends_on: unknown`` means the offer's end is not stated and the
    promotion is never assumed to continue past the ruleset's ``as_of``.

    A promotion that does not apply leaves the base value alone and is REPORTED
    (``promotion <id> not applied: <reason>``): eligibility is never assumed
    (ADR-0107, amendment of 2026-11-23).
    """

    id: str
    field: str
    value: _MONEY_GE0 | None = None
    multiplier: Annotated[Decimal, Field(gt=0, decimal_places=6)] | None = None
    starts_on: dt.date
    ends_on: dt.date | Literal["unknown"]
    purchase_on_or_after: dt.date | None = None
    requires: dict[str, str] = Field(default_factory=dict)
    source: Attribution | None = None

    @field_validator("requires", mode="before")
    @classmethod
    def _strings(cls, value: object) -> object:
        """Requirement values are strings: a YAML ``true`` becomes ``'true'``, a date ISO form."""
        if not isinstance(value, dict):
            return value
        out: dict[str, str] = {}
        for key, raw in value.items():
            name = str(key).strip()
            if isinstance(raw, bool):
                out[name] = "true" if raw else "false"
            elif isinstance(raw, dt.date):
                out[name] = raw.isoformat()
            else:
                out[name] = str(raw).strip()
        return out

    @model_validator(mode="after")
    def _shape(self) -> Promotion:
        if not self.id.strip():
            msg = "a promotion needs a non-empty id"
            raise ValueError(msg)
        if not self.field.strip():
            msg = f"promotion {self.id}: field is empty; name the numeric field it replaces"
            raise ValueError(msg)
        if (self.value is None) == (self.multiplier is None):
            msg = (
                f"promotion {self.id}: give exactly one of value (the promoted value) and "
                "multiplier (the base value times it)"
            )
            raise ValueError(msg)
        if isinstance(self.ends_on, dt.date) and self.ends_on < self.starts_on:
            msg = f"promotion {self.id}: ends_on is before starts_on"
            raise ValueError(msg)
        if not self.requires:
            msg = (
                f"promotion {self.id}: requires is empty; a promotion that depends on nothing is "
                "either the base value (so delete it) or is missing what it depends on"
            )
            raise ValueError(msg)
        return self


class _Rule(_Frozen):
    """Common rule identity, evidence and the optional rule-level effective dates."""

    rule_id: str
    description: str | None = None
    source: Attribution
    evidence: Evidence = "official_quote"
    assumption: Assumption | None = None
    promotions: tuple[Promotion, ...] = ()
    """Promotional values this rule may take, each applied only when the run qualifies for it."""
    effective_from: dt.date | None = None
    effective_to: dt.date | None = None

    @model_validator(mode="after")
    def _evidence(self) -> _Rule:
        if self.evidence == "assumption" and self.assumption is None:
            msg = (
                f"rule {self.rule_id}: evidence is assumption, so assumption {{name, rationale}} "
                "is required"
            )
            raise ValueError(msg)
        if (
            self.effective_to is not None
            and self.effective_from is not None
            and self.effective_to < self.effective_from
        ):
            msg = f"rule {self.rule_id}: effective_to is before effective_from"
            raise ValueError(msg)
        return self


# --------------------------------------------------------------------------- rule kinds


class ProfitTargetRule(_Rule):
    """Pass condition: the basis reaches ``starting_balance + amount``."""

    kind: Literal["profit_target"] = "profit_target"
    amount_usd: _MONEY_GE0
    basis: Literal["balance", "equity"]
    evaluated: Observation
    comparison: Comparison
    action: Literal["promote_phase"]
    require_flat: bool = False


class StaticDrawdownRule(_Rule):
    """Threshold ``starting_balance - amount``; never trails."""

    kind: Literal["static_drawdown"] = "static_drawdown"
    amount_usd: _MONEY_GE0
    basis: Literal["equity", "balance"]
    evaluated: Observation
    comparison: Comparison
    action: Literal["fail", "soft_lock_until_reset", "liquidate", "block_entries", "none"]


class TrailingLock(_Frozen):
    """Where a trailing threshold stops following the high-water mark.

    ``on`` lists the triggers: ``hwm`` fires on a high-water mark level, ``first_payout`` on the
    first withdrawal, whose trigger level the payout terms decide. The lock happens at the FIRST
    trigger that fires, so ``on: [hwm, first_payout]`` freezes the threshold at whichever comes
    first. The trigger list is REQUIRED and non-empty, and it is a LIST: a lock that does not say
    what engages it is the engine guessing, and ``on: hwm`` is not a declaration a firm makes.
    """

    on: tuple[LockTrigger, ...]
    at_balance_usd: _MONEY | None = None
    at_offset_usd: _MONEY | None = None
    locked_threshold_usd: _MONEY | None = None
    locked_offset_usd: _MONEY | None = None

    @model_validator(mode="after")
    def _one_of_each(self) -> TrailingLock:
        triggers = [v for v in (self.at_balance_usd, self.at_offset_usd) if v is not None]
        locked = [v for v in (self.locked_threshold_usd, self.locked_offset_usd) if v is not None]
        if not self.on:
            msg = (
                "trailing lock needs at least one trigger in on: a list of hwm and/or "
                "first_payout, because a lock that does not say what engages it is the engine "
                "guessing"
            )
            raise ValueError(msg)
        duplicated = sorted({str(trigger) for trigger in self.on if self.on.count(trigger) > 1})
        if duplicated:
            msg = f"trailing lock.on repeats {duplicated}: list each trigger once"
            raise ValueError(msg)
        if "hwm" in self.on and len(triggers) != 1:
            msg = (
                "trailing lock on the high-water mark needs exactly one of at_balance_usd and "
                f"at_offset_usd, got {len(triggers)}"
            )
            raise ValueError(msg)
        if "hwm" not in self.on and triggers:
            msg = (
                "trailing lock without the hwm trigger is fired by the payout, so it must not "
                "declare at_balance_usd or at_offset_usd"
            )
            raise ValueError(msg)
        if len(locked) != 1:
            msg = (
                "trailing lock needs exactly one of locked_threshold_usd and locked_offset_usd, "
                f"got {len(locked)}"
            )
            raise ValueError(msg)
        return self


class TrailingDrawdownRule(_Rule):
    """Threshold ``hwm - amount`` with the mark's basis separate from the tested basis."""

    kind: Literal["trailing_drawdown"] = "trailing_drawdown"
    amount_usd: _MONEY_GE0
    mode: Literal["intraday", "eod"]
    evaluated: Observation
    basis: Literal["equity", "balance"]
    hwm_basis: Literal["equity", "balance"]
    comparison: Comparison
    action: Literal["fail", "soft_lock_until_reset", "liquidate", "block_entries", "none"]
    lock: TrailingLock | None = None

    @property
    def mark_basis(self) -> Literal["equity", "balance"]:
        return self.hwm_basis


class DayBalanceTier(_Frozen):
    """A ``daily_loss`` amount by the balance tier it applies to (largest tier at or below)."""

    min_balance_usd: _MONEY_GE0
    amount_usd: _MONEY_GE0


class DailyLossRule(_Rule):
    """Threshold ``reference - amount`` with a declared hard fail or soft lock."""

    kind: Literal["daily_loss"] = "daily_loss"
    amount_usd: _MONEY_GE0 | None = None
    pct_of_reference: Annotated[Decimal, Field(gt=0, le=100, decimal_places=6)] | None = None
    amount_by_balance_tier: tuple[DayBalanceTier, ...] | None = None
    pct_of_peak_profit: Annotated[Decimal, Field(gt=0, le=100, decimal_places=6)] | None = None
    non_decreasing: bool = False
    reference: Literal["day_start_balance", "day_start_equity", "prior_eod_balance"]
    basis: Literal["equity", "balance"]
    evaluated: Observation
    comparison: Comparison
    action: Literal["fail", "soft_lock_until_reset"]
    reset: ResetClock

    @model_validator(mode="after")
    def _amount(self) -> DailyLossRule:
        present = [
            self.amount_usd is not None,
            self.pct_of_reference is not None,
            self.amount_by_balance_tier is not None,
            self.pct_of_peak_profit is not None,
        ]
        if sum(present) != 1:
            msg = (
                "daily_loss needs exactly one of amount_usd, pct_of_reference, "
                "amount_by_balance_tier and pct_of_peak_profit"
            )
            raise ValueError(msg)
        if self.amount_by_balance_tier is not None:
            tiers = list(self.amount_by_balance_tier)
            if not tiers:
                msg = "daily_loss.amount_by_balance_tier needs at least one tier"
                raise ValueError(msg)
            floors = [tier.min_balance_usd for tier in tiers]
            if floors != sorted(floors):
                msg = f"daily_loss tiers must be sorted by min_balance_usd, got {floors}"
                raise ValueError(msg)
        return self


class MaxContractsRule(_Rule):
    """Admission limit by contract weight (``limit``) or per contract (``per_instrument``)."""

    kind: Literal["max_contracts"] = "max_contracts"
    limit: Decimal | None = Field(default=None, gt=0, decimal_places=6)
    per_instrument: int | None = Field(default=None, ge=1)
    comparison: Comparison
    action: Literal["clip", "reject"]

    @model_validator(mode="after")
    def _limit(self) -> MaxContractsRule:
        if (self.limit is None) == (self.per_instrument is None):
            msg = "max_contracts needs exactly one of limit and per_instrument"
            raise ValueError(msg)
        return self


class ScalingStep(_Frozen):
    min_profit_usd: _MONEY
    max_contracts: Decimal = Field(gt=0, decimal_places=6)


class ScalingPlanRule(_Rule):
    """The contract limit for the next rule-day, from the rule-day's end-of-day basis."""

    kind: Literal["scaling_plan"] = "scaling_plan"
    steps: tuple[ScalingStep, ...]
    evaluated: Observation
    basis: Literal["balance", "equity"]
    comparison: Comparison
    action: Literal["clip", "reject"]

    @model_validator(mode="after")
    def _ordered(self) -> ScalingPlanRule:
        if not self.steps:
            msg = "scaling_plan needs at least one step"
            raise ValueError(msg)
        profits = [step.min_profit_usd for step in self.steps]
        if profits != sorted(profits):
            msg = f"scaling_plan steps must be sorted by min_profit_usd, got {profits}"
            raise ValueError(msg)
        return self


class FlatByRule(_Rule):
    """A forced-flat clock, either an absolute time or relative to the scheduled session end."""

    kind: Literal["flat_by"] = "flat_by"
    time: dt.time | None = None
    tz: str | None = None
    minutes_before_session_end: int | None = Field(default=None, ge=0)
    reopen: dt.time | None = None
    comparison: Comparison
    action: Literal["auto_liquidate", "fail"]

    @model_validator(mode="after")
    def _one_clock(self) -> FlatByRule:
        if (self.time is None) == (self.minutes_before_session_end is None):
            msg = (
                "flat_by needs exactly one of time and minutes_before_session_end: a fixed clock "
                "and a session-relative close are different firm semantics"
            )
            raise ValueError(msg)
        if self.time is not None:
            if self.tz is None:
                msg = "flat_by.time needs tz: an unzoned clock is not a firm rule"
                raise ValueError(msg)
            _zone(self.tz, "flat_by.tz")
        elif self.tz is not None:
            msg = "flat_by.tz belongs with a fixed time, not a session-relative close"
            raise ValueError(msg)
        return self


class DayCountsIf(_Frozen):
    """The predicate a rule-day must satisfy to count (exactly one, or both together)."""

    min_trades: int | None = Field(default=None, ge=0)
    min_abs_pnl_usd: _MONEY | None = None
    min_pnl_usd: _MONEY | None = None

    @model_validator(mode="after")
    def _some(self) -> DayCountsIf:
        present = [
            self.min_trades is not None,
            self.min_abs_pnl_usd is not None,
            self.min_pnl_usd is not None,
        ]
        if not any(present):
            msg = "day_counts_if needs at least one predicate"
            raise ValueError(msg)
        if self.min_abs_pnl_usd is not None and self.min_pnl_usd is not None:
            msg = "day_counts_if: min_abs_pnl_usd and min_pnl_usd are mutually exclusive"
            raise ValueError(msg)
        return self


class MinTradingDaysRule(_Rule):
    """Pass condition: at least ``days`` days counting in the declared unit."""

    kind: Literal["min_trading_days"] = "min_trading_days"
    days: int = Field(ge=1)
    unit: DayUnit
    day_counts_if: DayCountsIf
    comparison: Comparison
    action: Literal["promote_phase"]


class ConsistencyRule(_Rule):
    """The best day's share of total profit is at most ``max_day_share``.

    The numerator (which day is the best) and the denominator (which profit it is shared with) are
    separate windows, because a firm can measure the best day since the last payout against the
    whole account's profit. Declared separately they can differ; ``numerator_window`` and
    ``denominator_window`` are absent when the rule uses ``window`` for both.
    """

    kind: Literal["consistency"] = "consistency"
    max_day_share: Annotated[Decimal, Field(gt=0, le=1, decimal_places=6)]
    measure: Literal["best_day_profit/total_profit"]
    applies_to: Literal["pass", "payout"]
    window: Literal["all_time", "since_last_payout"]
    numerator_window: Literal["since_last_payout", "all_time"] | None = None
    denominator_window: Literal["since_last_payout", "all_time", "current_cycle"] | None = None
    comparison: Comparison
    action: Literal["promote_phase", "block_payout"]

    @property
    def best_day_window(self) -> Literal["all_time", "since_last_payout"]:
        """The window the best day is taken from: its own, or the shared ``window``."""
        return self.numerator_window or self.window

    @property
    def profit_window(self) -> Literal["all_time", "since_last_payout", "current_cycle"]:
        """The window the total profit is taken from: its own, or the shared ``window``."""
        return self.denominator_window or self.window


class PayoutRule(_Rule):
    """A withdrawal from a funded phase, evaluated at each rule-day's close."""

    kind: Literal["payout"] = "payout"
    min_days_since_last: int = Field(default=0, ge=0)
    min_profitable_days: int = Field(default=0, ge=0)
    min_traded_days: int = Field(default=0, ge=0)
    min_day_profit_usd: _MONEY_GE0 = Decimal(0)
    window: Literal["all_time", "since_last_payout"]
    buffer_usd: _MONEY_GE0
    split: Annotated[Decimal, Field(gt=0, le=1, decimal_places=6)]
    min_usd: _MONEY_GE0
    max_usd: _MONEY_GE0 | Literal["unlimited", "unknown"]
    max_usd_by_payout: tuple[_MONEY_GE0 | Literal["unlimited", "unknown"], ...] | None = None
    max_pct_of_balance: Annotated[Decimal, Field(gt=0, le=100, decimal_places=6)] | None = None
    max_share_of_withdrawable: Annotated[Decimal, Field(gt=0, le=1, decimal_places=6)] | None = None
    min_new_profit_share_of_request: (
        Annotated[Decimal, Field(gt=0, le=1, decimal_places=6)] | None
    ) = None
    min_profit_since_last_usd: _MONEY_GE0 = Decimal(0)
    cycle_goal_usd: _MONEY_GE0 | None = None
    first_payout_after_calendar_days: int | None = Field(default=None, ge=0)
    payout_group: str | None = None
    max_payouts: int | None = Field(default=None, ge=1)
    comparison: Comparison
    action: Literal["withdraw"]
    threshold_after_payout: Literal[
        "unchanged",
        "reset_to_start",
        "trail_from_new_balance",
        "lock_on_first_payout",
        "set_threshold",
    ]
    set_threshold_to: str | None = None
    """The explicit level ``threshold_after_payout: set_threshold`` sets: ``start``,
    ``start_plus_usd:<x>`` or ``zero_balance_offset:<x>`` (parsed by ``threshold_level``)."""

    @model_validator(mode="after")
    def _amounts(self) -> PayoutRule:
        if isinstance(self.max_usd, Decimal) and self.min_usd > self.max_usd:
            msg = (
                f"payout {self.rule_id}: min_usd {self.min_usd} is above max_usd {self.max_usd}, "
                "so no payout could ever be paid"
            )
            raise ValueError(msg)
        caps = self.max_usd_by_payout or ()
        if any(isinstance(cap, Decimal) and cap < self.min_usd for cap in caps):
            msg = (
                f"payout {self.rule_id}: a max_usd_by_payout cap is below min_usd "
                f"{self.min_usd}, so that payout could never be paid"
            )
            raise ValueError(msg)
        if (self.threshold_after_payout == "set_threshold") != (self.set_threshold_to is not None):
            msg = (
                f"payout {self.rule_id}: threshold_after_payout {self.threshold_after_payout!r} "
                "and set_threshold_to go together: set_threshold needs the explicit level, and a "
                "level is meaningless without it"
            )
            raise ValueError(msg)
        if self.set_threshold_to is not None:
            try:
                threshold_level(self.set_threshold_to)
            except ValueError as exc:
                msg = f"payout {self.rule_id}: set_threshold_to {self.set_threshold_to!r}: {exc}"
                raise ValueError(msg) from exc
        _refuse_sentinel(self.rule_id, "max_usd", self.max_usd)
        for index, cap in enumerate(caps):
            _refuse_sentinel(self.rule_id, f"max_usd_by_payout[{index}]", cap)
        return self

    @property
    def unknown_cap(self) -> bool:
        """Whether any of this rule's caps is ``unknown`` (the payouts are then upper bounds)."""
        caps: tuple[object, ...] = (self.max_usd, *(self.max_usd_by_payout or ()))
        return any(cap == "unknown" for cap in caps)


class TimeLimitRule(_Rule):
    """A phase without a pass within the limit times out."""

    kind: Literal["time_limit"] = "time_limit"
    max_calendar_days: int | None = Field(default=None, ge=1)
    max_trading_days: int | None = Field(default=None, ge=1)
    unit: DayUnit
    comparison: Comparison
    action: Literal["timeout"]

    @model_validator(mode="after")
    def _one(self) -> TimeLimitRule:
        if (self.max_calendar_days is None) == (self.max_trading_days is None):
            msg = "time_limit needs exactly one of max_calendar_days and max_trading_days"
            raise ValueError(msg)
        expected = "calendar_days" if self.max_calendar_days is not None else "trading_days"
        if self.unit != expected:
            msg = f"time_limit.unit {self.unit!r} contradicts the declared limit; use {expected!r}"
            raise ValueError(msg)
        return self


class FeeRule(_Rule):
    """Attempt cost accounting only: never written into the trading ledger."""

    kind: Literal["fee"] = "fee"
    fee_kind: Literal["evaluation", "activation", "reset", "monthly"]
    amount_usd: _MONEY_GE0
    when: Literal["at_start", "at_pass", "per_month", "on_reset"]
    comparison: Comparison
    action: Literal["charge"]

    @model_validator(mode="after")
    def _when(self) -> FeeRule:
        expected = {"monthly": "per_month", "reset": "on_reset"}.get(self.fee_kind)
        if expected is not None and self.when != expected:
            msg = (
                f"fee {self.rule_id}: a {self.fee_kind} fee is charged {expected!r}, not "
                f"{self.when!r}"
            )
            raise ValueError(msg)
        return self


class DailyProfitCapRule(_Rule):
    """A per-rule-day profit ceiling: forfeit the excess or promote the phase."""

    kind: Literal["daily_profit_cap"] = "daily_profit_cap"
    amount_usd: _MONEY_GE0
    basis: Literal["balance", "equity"]
    evaluated: Observation
    comparison: Comparison
    action: Literal["forfeit_excess", "promote_phase"]


class InactivityRule(_Rule):
    """A maximum gap between trading days, in the declared unit."""

    kind: Literal["inactivity"] = "inactivity"
    max_gap: int = Field(ge=1)
    unit: DayUnit
    rolling_window: bool = True
    observed: Observation
    comparison: Comparison
    action: Literal["fail"]


class NewsRestrictionRule(_Rule):
    """A scheduled-event trading window (ADR-0107 section 12).

    The calendar lives outside this package: the evaluator receives ``NewsEvent`` rows from
    ``crucible.prop.news`` and a coverage record from the caller. A window the calendar does not
    cover is never silently ignored.
    """

    kind: Literal["news_restriction"] = "news_restriction"
    event_types: tuple[str, ...]
    instruments: tuple[str, ...] = ()
    pre_minutes: int = Field(ge=0)
    post_minutes: int = Field(ge=0)
    scope: Literal["new_entries", "holding", "all_trading"]
    flatten: Literal["before_window", "none"]
    effect: Literal["block", "contract_cap"]
    cap_contracts: Decimal | None = Field(default=None, gt=0, decimal_places=6)
    comparison: Comparison
    action: Literal["block_entries", "flatten_and_block", "fail"]

    @model_validator(mode="after")
    def _text(self) -> NewsRestrictionRule:
        if not self.event_types:
            msg = f"news_restriction {self.rule_id} needs at least one event type"
            raise ValueError(msg)
        if self.scope == "holding" and self.flatten == "none":
            msg = (
                f"news_restriction {self.rule_id}: a holding restriction must declare flatten, "
                "otherwise it restricts nothing"
            )
            raise ValueError(msg)
        if (self.effect == "contract_cap") != (self.cap_contracts is not None):
            msg = (
                f"news_restriction {self.rule_id}: effect contract_cap needs cap_contracts (a "
                "contract WEIGHT, like max_contracts.limit) and a cap_contracts is meaningless "
                "without it"
            )
            raise ValueError(msg)
        return self

    @property
    def effective_effect(self) -> Literal["block", "contract_cap"]:
        """The declared effect (required: there is no engine-chosen default)."""
        return self.effect


class ActivityRequirementRule(_Rule):
    """At least ``days`` qualifying rule-days in EVERY rolling window of ``window`` days.

    The mirror image of ``inactivity`` (a maximum gap since the last traded day): a firm that
    requires a minimum number of qualifying days in a rolling window fails an account that trades
    rarely but never idles long enough to breach a gap. ``qualifies_if`` is the day predicate
    (trades and/or absolute or signed P&L); ``unit`` is ``calendar_days`` or ``trading_days``. A
    window is tested only once it is FULL, and the action says what a short window does.
    """

    kind: Literal["activity_requirement"] = "activity_requirement"
    days: int = Field(ge=1)
    window: int = Field(ge=1)
    unit: Literal["calendar_days", "trading_days"]
    qualifies_if: DayCountsIf
    observed: Observation
    comparison: Comparison
    action: Literal["fail", "close_account"]

    @model_validator(mode="after")
    def _reachable(self) -> ActivityRequirementRule:
        if self.days > self.window:
            msg = (
                f"activity_requirement {self.rule_id}: days {self.days} exceeds its window "
                f"{self.window}, so no window could ever satisfy it"
            )
            raise ValueError(msg)
        return self


class ComplianceRule(_Rule):
    """A conduct restriction that gates practical eligibility, not the mechanical account.

    ``effect`` says HOW the restriction limits eligibility: ``block`` is the mechanical reading (a
    rule the run cannot satisfy at all), while ``condition`` is an obligation the SIMULATION cannot
    prove and the trader must meet (automated trading only through the firm's API, orders placed
    from the trader's own device, no VPS/VPN order entry, high-frequency trading prohibited). A
    ``condition`` rule carries the ``condition`` text, which is listed verbatim in the report, and
    it never blocks: the ruleset's practical eligibility becomes ``eligible_conditional``.
    """

    kind: Literal["compliance"] = "compliance"
    restriction: str
    applies_to_execution: tuple[ExecutionMode, ...]
    materiality: Materiality
    comparison: Comparison
    action: Literal["block", "none"]
    effect: Literal["condition"] | None = None
    condition: str | None = None

    @model_validator(mode="after")
    def _text(self) -> ComplianceRule:
        if not self.restriction.strip():
            msg = f"compliance {self.rule_id} needs a non-empty restriction"
            raise ValueError(msg)
        if not self.applies_to_execution:
            msg = f"compliance {self.rule_id} needs at least one execution mode"
            raise ValueError(msg)
        if self.restriction.strip() == str(self.condition or "").strip():
            msg = (
                f"compliance {self.rule_id}: condition repeats restriction; the condition is the "
                "obligation the trader must meet, in words the report can list"
            )
            raise ValueError(msg)
        if (self.effect == "condition") != (self.condition is not None):
            msg = (
                f"compliance {self.rule_id}: effect: condition and the condition text go "
                "together: a condition nobody states is not a condition, and a text without the "
                "effect is not a declaration"
            )
            raise ValueError(msg)
        if self.condition is not None and not self.condition.strip():
            msg = f"compliance {self.rule_id}: the condition text is empty"
            raise ValueError(msg)
        if self.effect == "condition" and self.action == "block":
            msg = (
                f"compliance {self.rule_id}: a rule with effect: condition is an obligation the "
                "simulation cannot prove, not a mechanical blocker; declare action: none"
            )
            raise ValueError(msg)
        return self


AnyRule = Annotated[
    ProfitTargetRule
    | StaticDrawdownRule
    | TrailingDrawdownRule
    | DailyLossRule
    | MaxContractsRule
    | ScalingPlanRule
    | FlatByRule
    | MinTradingDaysRule
    | ConsistencyRule
    | PayoutRule
    | TimeLimitRule
    | FeeRule
    | DailyProfitCapRule
    | InactivityRule
    | NewsRestrictionRule
    | ActivityRequirementRule
    | ComplianceRule,
    Field(discriminator="kind"),
]

PASS_KINDS: frozenset[str] = frozenset({"profit_target", "min_trading_days", "consistency"})
"""Kinds that gate the phase pass; every other kind restricts or records (ADR-0106 section 4)."""


def is_pass_condition(rule: object) -> bool:
    """Whether a rule gates the phase pass (a payout-scoped consistency rule does not)."""
    kind = str(getattr(rule, "kind", ""))
    if kind not in PASS_KINDS:
        return False
    return not (kind == "consistency" and getattr(rule, "applies_to", "pass") == "payout")


class Phase(_Frozen):
    """One account of the attempt, with its own starting balance and its own rules."""

    phase_id: str
    kind: Literal["evaluation", "funded"]
    starting_balance_usd: _MONEY_GE0
    rules: tuple[AnyRule, ...] = ()
    pass_conditions: tuple[AnyRule, ...] = ()
    max_calendar_days: int | None = Field(default=None, ge=1)
    max_trading_days: int | None = Field(default=None, ge=1)
    fees: tuple[FeeRule, ...] = ()

    @model_validator(mode="after")
    def _kinds(self) -> Phase:
        wrong = sorted(r.kind for r in self.rules if is_pass_condition(r))
        if wrong:
            msg = (
                f"phase {self.phase_id}: {wrong} are pass conditions and belong in "
                "pass_conditions, not in rules"
            )
            raise ValueError(msg)
        misfit = sorted(r.kind for r in self.pass_conditions if not is_pass_condition(r))
        if misfit:
            msg = (
                f"phase {self.phase_id}: {misfit} are not pass conditions; ADR-0106 section 4 "
                f"allows only {sorted(PASS_KINDS)} there"
            )
            raise ValueError(msg)
        for collection in (self.rules, self.pass_conditions, self.fees):
            ids = [r.rule_id for r in collection]
            if len(ids) != len(set(ids)):
                msg = f"phase {self.phase_id}: duplicate rule ids in {ids}"
                raise ValueError(msg)
        return self


def _refuse_sentinel(rule_id: str, field: str, value: object) -> None:
    """A six-figure cap is a sentinel: ``unlimited`` or ``not_modeled`` says it instead."""
    if value == "unlimited" or not isinstance(value, Decimal):
        return
    if value >= SENTINEL_FLOOR_USD:
        msg = (
            f"rule {rule_id}: {field} = {value} USD is a sentinel, not a firm value; declare "
            '"unlimited" where the source says so, or put the unknown in not_modeled'
        )
        raise ValueError(msg)


def threshold_level(text: str) -> tuple[ThresholdLevel, Decimal]:
    """Parse ``set_threshold_to``: ``start``, ``start_plus_usd:<x>`` or ``zero_balance_offset:<x>``.

    ``start`` is the phase's starting balance, ``start_plus_usd`` that balance plus a fixed amount
    and ``zero_balance_offset`` an absolute level (an amount above a zero balance, the small floor
    some firms leave on the account). Nothing is defaulted: a malformed value is refused.
    """
    head, _, tail = text.partition(":")
    if head == "start":
        if tail:
            msg = f"start takes no amount, got {tail!r}"
            raise ValueError(msg)
        return "start", Decimal(0)
    if head not in ("start_plus_usd", "zero_balance_offset"):
        msg = (
            f"{text!r} is not a threshold level; use start, start_plus_usd:<usd> or "
            "zero_balance_offset:<usd>"
        )
        raise ValueError(msg)
    if not tail:
        msg = f"{head} needs an amount, as in {head}:1000"
        raise ValueError(msg)
    try:
        amount = Decimal(tail)
    except ArithmeticError as exc:
        msg = f"{text!r} carries {tail!r}, which is not a decimal amount"
        raise ValueError(msg) from exc
    if amount != amount.quantize(Decimal("0.000001")):
        msg = f"{text!r} carries more than 6 decimals; money is kept in exact micro-dollars"
        raise ValueError(msg)
    return ("start_plus_usd" if head == "start_plus_usd" else "zero_balance_offset"), amount


def _zone(name: str, what: str) -> None:
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

    try:
        ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        msg = f"{what} = {name!r} is not a known IANA time zone: {exc}"
        raise ValueError(msg) from exc
