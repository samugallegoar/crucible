"""Prop-firm rulesets: sourced, versioned rule data, never firm values in code (ADR-0106/0107).

A ruleset is a YAML file that validates into ``PropRuleset``: identity (firm, program, account
size, platform, add-ons, jurisdiction), the instruments with their contract weights, the ordered
phases with their typed rules, per-side commissions, and an attribution for every rule value. The
engine knows rule *kinds*, never a firm: no firm name, URL or firm-specific number appears under
``crucible/``.

**Schema version 2** (ADR-0107 sections 7-13) adds evidence, conflicts and sensitivity
scenarios, explicit day units, commissions, compliance rules and the hash lock:

- ``ruleset_sha256`` hashes the content WITHOUT the ``verification`` block, so confirming a
  ruleset never changes its identity.
- Verification lives in a sidecar ``<file>.verification.yaml`` and only ``crucible prop confirm``
  (an interactive TTY step) writes it. An in-file ``verification`` block is refused unless it is
  ``unverified``.
- A ruleset is ``verified`` only when the sidecar exists, its hash matches the content, its
  ``rules_checked`` names every rule and every attribution is complete and non-synthetic.

Old versions are immutable: ``load_registry`` refuses two files with the same
``(ruleset_id, version)``.
"""

from __future__ import annotations

import datetime as dt
import hashlib
from decimal import Decimal
from pathlib import Path

import yaml
from pydantic import BaseModel, Field, model_validator

from crucible.core.canonical import canonical_json
from crucible.core.errors import ConfigurationError, DataQualityError
from crucible.prop._yaml import safe_load
from crucible.prop.rules_schema import (
    ABSENT,
    PASS_KINDS,
    ActivityRequirementRule,
    AnyRule,
    Assumption,
    Attribution,
    BreachAction,
    Commissions,
    Comparison,
    ComplianceRule,
    Conflict,
    ConflictAlternative,
    ConsistencyRule,
    DailyLossRule,
    DailyProfitCapRule,
    DayBalanceTier,
    DayCountsIf,
    DayUnit,
    Evidence,
    ExecutionMode,
    FeeRule,
    FlatByRule,
    InactivityRule,
    Instrument,
    Materiality,
    MaxContractsRule,
    MinTradingDaysRule,
    NewsRestrictionRule,
    NotModeled,
    Observation,
    PayoutRule,
    Phase,
    ProfitTargetRule,
    ResetClock,
    ScalingPlanRule,
    ScalingStep,
    StaticDrawdownRule,
    TimeLimitRule,
    TrailingDrawdownRule,
    TrailingLock,
    Verification,
    is_pass_condition,
    threshold_level,
)

__all__ = [
    "ABSENT",
    "PASS_KINDS",
    "RULE_SCHEMA_VERSION",
    "ActivityRequirementRule",
    "AnyRule",
    "Assumption",
    "Attribution",
    "BreachAction",
    "Commissions",
    "Comparison",
    "ComplianceRule",
    "Conflict",
    "ConflictAlternative",
    "ConsistencyRule",
    "DailyLossRule",
    "DailyProfitCapRule",
    "DayBalanceTier",
    "DayCountsIf",
    "DayUnit",
    "Evidence",
    "ExecutionMode",
    "FeeRule",
    "FlatByRule",
    "InactivityRule",
    "Instrument",
    "Materiality",
    "MaxContractsRule",
    "MinTradingDaysRule",
    "NewsRestrictionRule",
    "NotModeled",
    "Observation",
    "PayoutRule",
    "Phase",
    "ProfitTargetRule",
    "PropRuleset",
    "ResetClock",
    "ScalingPlanRule",
    "ScalingStep",
    "StaticDrawdownRule",
    "TimeLimitRule",
    "TrailingDrawdownRule",
    "TrailingLock",
    "Verification",
    "VerificationRecord",
    "is_pass_condition",
    "load_registry",
    "load_ruleset",
    "read_verification_sidecar",
    "sidecar_path",
    "threshold_level",
    "write_verification_sidecar",
]

RULE_SCHEMA_VERSION = 2
_HEX64 = r"^[0-9a-f]{64}$"
SIDECAR_SUFFIX = ".verification.yaml"


class PropRuleset(BaseModel):
    """One versioned ruleset of one program and account size (schema version 2)."""

    model_config = {"frozen": True, "extra": "forbid"}

    schema_version: int = 2
    ruleset_id: str
    version: int = Field(ge=1)
    firm: str
    program: str
    account_size_usd: Decimal = Field(ge=0, decimal_places=6)
    platform: str | None = None
    addons: tuple[str, ...] = ()
    jurisdiction: str | None = None
    as_of: dt.date
    effective_from: dt.date
    effective_to: dt.date | None = None
    instruments: tuple[Instrument, ...]
    reset: ResetClock
    commissions: Commissions
    conflicts: tuple[Conflict, ...] = ()
    verification: Verification = Field(default_factory=Verification)
    phases: tuple[Phase, ...]
    not_modeled: tuple[NotModeled, ...] = ()

    @model_validator(mode="before")
    @classmethod
    def _schema_version(cls, raw: object) -> object:
        if not isinstance(raw, dict):
            return raw
        version = raw.get("schema_version", RULE_SCHEMA_VERSION)
        if version != RULE_SCHEMA_VERSION:
            msg = (
                f"ruleset schema_version {version} is refused: this engine reads schema_version "
                f"{RULE_SCHEMA_VERSION}. Migrate every rule to declare evidence, commissions and "
                "explicit day units (ADR-0107 section 7); a v1 file is not silently upgraded"
            )
            raise ValueError(msg)
        return raw

    @model_validator(mode="after")
    def _content(self) -> PropRuleset:
        if self.schema_version != RULE_SCHEMA_VERSION:
            msg = f"schema_version must be {RULE_SCHEMA_VERSION}"
            raise ValueError(msg)
        if self.effective_to is not None and self.effective_to < self.effective_from:
            msg = (
                f"ruleset {self.ruleset_id} v{self.version}: effective_to "
                f"{self.effective_to} is before effective_from {self.effective_from}"
            )
            raise ValueError(msg)
        if not self.instruments:
            msg = f"ruleset {self.ruleset_id}: at least one instrument is required"
            raise ValueError(msg)
        roots = [i.root for i in self.instruments]
        if len(roots) != len(set(roots)):
            msg = f"ruleset {self.ruleset_id}: duplicate instrument roots {roots}"
            raise ValueError(msg)
        if not self.phases:
            msg = f"ruleset {self.ruleset_id}: at least one phase is required"
            raise ValueError(msg)
        ids = [p.phase_id for p in self.phases]
        if len(ids) != len(set(ids)):
            msg = f"ruleset {self.ruleset_id}: duplicate phase ids {ids}"
            raise ValueError(msg)
        if self.addons != tuple(sorted(self.addons)):
            msg = f"ruleset {self.ruleset_id}: addons must be sorted, got {self.addons}"
            raise ValueError(msg)
        if self.verification.status != "unverified":
            msg = (
                f"ruleset {self.ruleset_id} v{self.version} declares verification in the file: "
                "verification is a fact about the content hash, not part of it (ADR-0107 section "
                "2). Keep the file unverified and run `crucible prop confirm <file>` from a TTY"
            )
            raise ValueError(msg)
        self._check_rule_effective_dates()
        self._check_conflicts()
        self._refuse_numeric_sentinels()
        return self

    # ------------------------------------------------------------------------ validation

    def _all_rules(self) -> list[tuple[str, AnyRule]]:
        return [
            (f"{phase.phase_id}.{rule.rule_id}", rule)
            for phase in self.phases
            for rule in (*phase.rules, *phase.pass_conditions, *phase.fees)
        ]

    def rule_ids(self) -> tuple[str, ...]:
        """Every rule id an owner must have checked, including fees (ADR-0107 section 2)."""
        return tuple(rule_id for rule_id, _ in self._all_rules())

    def _check_rule_effective_dates(self) -> None:
        """A rule whose effective_to is before the ruleset's as_of is expired in a current file.

        Per-rule effective dates are informational (a version carries the change); refusing an
        expired rule keeps a stale value from being silently enforced now.
        """
        for rule_id, rule in self._all_rules():
            if rule.effective_to is not None and rule.effective_to < self.as_of:
                msg = (
                    f"rule {rule_id}: effective_to {rule.effective_to} is before the ruleset's "
                    f"as_of {self.as_of}; an expired rule cannot sit in a current ruleset (a "
                    "change is a new version)"
                )
                raise ValueError(msg)

    def _check_conflicts(self) -> None:
        known = set(self.rule_ids())
        plain = {rule.rule_id for _, rule in self._all_rules()}
        seen: set[str] = set()
        for conflict in self.conflicts:
            if conflict.conflict_id in seen:
                msg = f"ruleset {self.ruleset_id}: duplicate conflict id {conflict.conflict_id}"
                raise ValueError(msg)
            seen.add(conflict.conflict_id)
            if conflict.rule_id not in known and conflict.rule_id not in plain:
                msg = (
                    f"conflict {conflict.conflict_id} names rule {conflict.rule_id!r}, which is "
                    f"not in the ruleset; rules are {sorted(known)}"
                )
                raise ValueError(msg)

    def _refuse_numeric_sentinels(self) -> None:
        suspicious: list[str] = []
        cap_fields = {
            "max_usd",
            "max_usd_by_payout",
            "max_pct_of_balance",
            "max_share_of_withdrawable",
        }
        for rule_id, rule in self._all_rules():
            data = rule.model_dump(mode="python")
            for name in cap_fields & set(data):
                value = data[name]
                values = value if isinstance(value, tuple) else (value,)
                for item in values:
                    if isinstance(item, Decimal) and item >= Decimal(1_000_000):
                        suspicious.append(
                            f"{rule_id}.{name} = {item} USD is a sentinel, declare 'unlimited' "
                            "or put the unknown in not_modeled"
                        )
        if suspicious:
            raise ValueError(f"ruleset {self.ruleset_id}: " + "; ".join(suspicious))

    def _require_verified(self) -> None:
        v = self.verification
        missing = [
            name
            for name in ("confirmed_by", "confirmed_at", "confirmation_note")
            if getattr(v, name) in (None, "")
        ]
        if missing:
            msg = (
                f"ruleset {self.ruleset_id} v{self.version} is marked verified but lacks "
                f"{missing}: only the owner's explicit confirmation can verify it"
            )
            raise ValueError(msg)
        expected = set(self.rule_ids())
        checked = set(v.rules_checked)
        unchecked = sorted(
            rid for rid in expected if rid not in checked and rid.split(".", 1)[-1] not in checked
        )
        if unchecked:
            msg = (
                f"ruleset {self.ruleset_id} v{self.version} cannot be verified: the owner did "
                f"not check every rule, missing {unchecked}"
            )
            raise ValueError(msg)
        sources = [(rule_id, rule.source) for rule_id, rule in self._all_rules()]
        sources += [(f"not_modeled {n.rule}", n.source) for n in self.not_modeled]
        sources += [(f"conflict {c.conflict_id}", c.selected_source) for c in self.conflicts]
        problems = [
            f"{where}: synthetic attribution" for where, source in sources if source.synthetic
        ]
        problems += [
            f"{where}: incomplete attribution" for where, source in sources if not source.complete
        ]
        if problems:
            msg = f"ruleset {self.ruleset_id} v{self.version} cannot be verified: " + "; ".join(
                sorted(set(problems))
            )
            raise ValueError(msg)

    # --------------------------------------------------------------------------- identity

    @property
    def ruleset_sha256(self) -> str:
        """The canonical hash of the content EXCLUDING verification (ADR-0107 section 1)."""
        payload = self.model_dump(mode="json", exclude={"verification"})
        return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()

    @property
    def verified(self) -> bool:
        if self.verification.status != "verified":
            return False
        return set(self.verification.rules_checked) >= set(self.rule_ids())

    @property
    def verification_status(self) -> str:
        return self.verification.status

    def phase(self, phase_id: str) -> Phase:
        for phase in self.phases:
            if phase.phase_id == phase_id:
                return phase
        msg = (
            f"ruleset {self.ruleset_id} v{self.version} has no phase {phase_id!r}; phases are "
            f"{[p.phase_id for p in self.phases]}"
        )
        raise ConfigurationError(msg)

    def weight(self, root: str) -> Decimal:
        """The contract weight of ``root`` (ADR-0106 section 2: 1 mini, 0.1 micro)."""
        for instrument in self.instruments:
            if instrument.root == root:
                return instrument.contract_weight
        msg = (
            f"root {root!r} is not in ruleset {self.ruleset_id} v{self.version}; the ruleset "
            f"covers {[i.root for i in self.instruments]}"
        )
        raise ConfigurationError(msg)

    def news_rules(self) -> tuple[NewsRestrictionRule, ...]:
        return tuple(rule for _, rule in self._all_rules() if isinstance(rule, NewsRestrictionRule))

    def compliance_rules(self) -> tuple[ComplianceRule, ...]:
        return tuple(rule for _, rule in self._all_rules() if isinstance(rule, ComplianceRule))


class VerificationRecord(BaseModel):
    """The sidecar document: a hash-bound statement by the owner (ADR-0107 section 2)."""

    model_config = {"frozen": True, "extra": "forbid"}

    ruleset_sha256: str = Field(pattern=_HEX64)
    status: str = "verified"
    confirmed_by: str
    confirmed_at: dt.datetime
    confirmation_note: str
    rules_checked: tuple[str, ...]

    @model_validator(mode="after")
    def _complete(self) -> VerificationRecord:
        if self.status != "verified":
            msg = "a verification sidecar can only say status: verified"
            raise ValueError(msg)
        if self.confirmed_at.tzinfo is None:
            msg = "verification.confirmed_at must carry a UTC offset"
            raise ValueError(msg)
        if not self.confirmed_by or not self.confirmation_note:
            msg = "verification needs confirmed_by and confirmation_note"
            raise ValueError(msg)
        return self


def sidecar_path(path: str | Path) -> Path:
    """``<file>.verification.yaml`` beside the ruleset file (ADR-0107 section 2)."""
    ruleset = Path(path)
    return ruleset.with_name(ruleset.name + SIDECAR_SUFFIX)


def read_verification_sidecar(path: str | Path) -> VerificationRecord | None:
    """The sidecar document, or None when there is none. A malformed sidecar is refused."""
    sidecar = sidecar_path(path)
    if not sidecar.is_file():
        return None
    try:
        raw = safe_load(sidecar.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        msg = f"cannot read verification sidecar {sidecar}: {exc}"
        raise DataQualityError(msg) from exc
    if not isinstance(raw, dict):
        msg = f"verification sidecar {sidecar} must be a YAML mapping"
        raise DataQualityError(msg)
    if raw.get("status") != "verified":
        msg = f"verification sidecar {sidecar}: status must be 'verified'"
        raise DataQualityError(msg)
    try:
        return VerificationRecord.model_validate(raw)
    except ValueError as exc:
        msg = f"verification sidecar {sidecar} does not validate: {exc}"
        raise DataQualityError(msg) from exc


def write_verification_sidecar(
    path: str | Path,
    ruleset: PropRuleset,
    *,
    confirmed_by: str,
    confirmation_note: str,
    confirmed_at: dt.datetime | None = None,
) -> Path:
    """Write the sidecar for ``ruleset``. Only ``crucible prop confirm`` calls this."""
    record = VerificationRecord(
        ruleset_sha256=ruleset.ruleset_sha256,
        status="verified",
        confirmed_by=confirmed_by,
        confirmed_at=confirmed_at or dt.datetime.now(dt.UTC),
        confirmation_note=confirmation_note,
        rules_checked=ruleset.rule_ids(),
    )
    sidecar = sidecar_path(path)
    sidecar.write_text(
        yaml.safe_dump(record.model_dump(mode="json"), sort_keys=True, allow_unicode=True),
        encoding="utf-8",
        newline="\n",
    )
    return sidecar


def verified_copy(ruleset: PropRuleset, path: str | Path) -> PropRuleset:
    """The ruleset with the sidecar attached when — and only when — it is valid for the content.

    A sidecar whose hash no longer matches (a tampered ruleset) leaves the ruleset unverified; it
    is never repaired and never silently ignored.
    """
    record = read_verification_sidecar(path)
    if record is None or record.ruleset_sha256 != ruleset.ruleset_sha256:
        return ruleset
    candidate = ruleset.model_copy(
        update={
            "verification": Verification(
                status="verified",
                confirmed_by=record.confirmed_by,
                confirmed_at=record.confirmed_at,
                confirmation_note=record.confirmation_note,
                rules_checked=record.rules_checked,
            )
        }
    )
    try:
        candidate._require_verified()
    except ValueError:
        return ruleset
    return candidate


def _read(path: Path, *, with_sidecar: bool = True) -> PropRuleset:
    try:
        raw = safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        msg = f"cannot read ruleset {path}: {exc}"
        raise DataQualityError(msg) from exc
    if not isinstance(raw, dict):
        msg = f"ruleset {path} must be a YAML mapping, got {type(raw).__name__}"
        raise DataQualityError(msg)
    try:
        ruleset = PropRuleset.model_validate(raw)
    except ValueError as exc:
        msg = f"ruleset {path} does not validate: {exc}"
        raise ConfigurationError(msg) from exc
    if not with_sidecar:
        return ruleset
    return verified_copy(ruleset, path)


def load_ruleset(path: str | Path) -> PropRuleset:
    """One ruleset file, with its sidecar verification when the sidecar matches."""
    return _read(Path(path))


def load_registry(directory: str | Path) -> list[PropRuleset]:
    """Every v2 ruleset file in a directory, sorted by ``(ruleset_id, version)``.

    Refuses two files that claim the same ``(ruleset_id, version)``: an old version is immutable,
    so a change is a new version.
    """
    root = Path(directory)
    if not root.is_dir():
        msg = f"ruleset registry {root} is not a directory"
        raise ConfigurationError(msg)
    files = sorted(p for p in root.iterdir() if p.suffix in (".yaml", ".yml") and p.is_file())
    files = [p for p in files if not p.name.endswith(SIDECAR_SUFFIX)]
    if not files:
        msg = f"ruleset registry {root} holds no YAML ruleset"
        raise ConfigurationError(msg)
    seen: dict[tuple[str, int], tuple[str, Path]] = {}
    out: list[tuple[tuple[str, int], PropRuleset]] = []
    for path in files:
        ruleset = _read(path)
        key = (ruleset.ruleset_id, ruleset.version)
        digest = ruleset.ruleset_sha256
        if key in seen:
            other_hash, other_path = seen[key]
            msg = (
                f"ruleset {key[0]} v{key[1]} appears twice: {other_path.name} "
                f"({other_hash[:12]}) and {path.name} ({digest[:12]}). An old version is "
                "immutable; a change is a new version with a new number"
            )
            raise DataQualityError(msg)
        seen[key] = (digest, path)
        out.append((key, ruleset))
    return [ruleset for _, ruleset in sorted(out, key=lambda item: item[0])]
