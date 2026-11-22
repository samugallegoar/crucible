"""Prop-firm rulesets: sourced, versioned rule data, never firm values in code (ADR-0106).

A ruleset is a YAML file that validates into ``PropRuleset``: identity (firm, program, account
size, platform, add-ons, jurisdiction), the instruments with their contract weights, the ordered
phases with their typed rules, and an attribution for every rule value. The engine knows rule
*kinds*, never a firm: no firm name, URL or firm-specific number appears under ``crucible/``.

Verification is data, not engine state. Only an edit of a ruleset file by the owner sets
``verification.status: verified``, and a verified ruleset requires a confirmation and a complete,
non-synthetic attribution for every rule, pass condition and fee. A ruleset carrying any
synthetic attribution can never be verified.

Old versions are immutable: ``ruleset_sha256`` is the canonical hash of the content, and
``load_registry`` refuses two files with the same ``(ruleset_id, version)`` and different hashes
or a repeated version number.
"""

from __future__ import annotations

import datetime as dt
import hashlib
from decimal import Decimal
from pathlib import Path
from typing import Annotated, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from crucible.core.canonical import canonical_json
from crucible.core.errors import ConfigurationError, DataQualityError

_MONEY = Annotated[Decimal, Field(decimal_places=6)]
_MONEY_GE0 = Annotated[Decimal, Field(ge=0, decimal_places=6)]
_HEX64 = r"^[0-9a-f]{64}$"
RULE_SCHEMA_VERSION = 1
DEFAULT_RESET_TIME = dt.time(17, 0)
DEFAULT_RESET_TZ = "America/Chicago"

RuleKind = Literal[
    "profit_target",
    "static_drawdown",
    "trailing_drawdown",
    "daily_loss",
    "max_contracts",
    "scaling_plan",
    "flat_by",
    "min_trading_days",
    "consistency",
    "payout",
    "time_limit",
    "fee",
]
PASS_KINDS: frozenset[str] = frozenset({"profit_target", "min_trading_days", "consistency"})
"""Kinds that gate the phase pass; every other kind restricts or records, never passes a
phase (ADR-0106 section 4)."""


def is_pass_condition(rule: object) -> bool:
    """Whether a rule gates the phase pass. A ``consistency`` rule with ``applies_to: payout``
    is a payout condition, not a pass condition, so it sits in the phase's ``rules``."""
    kind = str(getattr(rule, "kind", ""))
    if kind not in PASS_KINDS:
        return False
    return not (kind == "consistency" and getattr(rule, "applies_to", "pass") == "payout")


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ResetClock(_Frozen):
    """When a rule's day starts, in its own time zone (the rule-day boundary)."""

    time: dt.time = DEFAULT_RESET_TIME
    tz: str = DEFAULT_RESET_TZ

    @model_validator(mode="after")
    def _zone(self) -> ResetClock:
        _zone(self.tz, "reset.tz")
        return self


class Attribution(_Frozen):
    """Where a rule value comes from: the official page, the exact quotation, the page snapshot
    and when it was read (ADR-0106 section 2). ``synthetic`` marks invented test data."""

    url: str
    quote: str
    snapshot_sha256: str = Field(pattern=_HEX64)
    retrieved_at: dt.datetime
    section: str | None = None
    synthetic: bool = False

    @model_validator(mode="after")
    def _utc(self) -> Attribution:
        if self.retrieved_at.tzinfo is None:
            msg = (
                "attribution.retrieved_at must carry a UTC offset: a naive timestamp cannot say "
                "when the page was read"
            )
            raise ValueError(msg)
        if not self.url or not self.quote:
            msg = "attribution needs a non-empty url and quote: an unsourced value is not a rule"
            raise ValueError(msg)
        return self

    @property
    def complete(self) -> bool:
        """Whether the attribution carries every field an owner confirmation needs."""
        return bool(self.url and self.quote and len(self.snapshot_sha256) == 64)


class Instrument(_Frozen):
    """A tradable root and its contract weight for mini/micro equivalence (1 mini, 0.1 micro)."""

    root: str
    contract_weight: Decimal = Field(gt=0, decimal_places=6)

    @model_validator(mode="after")
    def _root(self) -> Instrument:
        if self.root != self.root.upper() or not self.root:
            msg = f"instrument root {self.root!r} must be a non-empty upper-case root"
            raise ValueError(msg)
        return self


class Verification(_Frozen):
    """``unverified`` until the owner confirms the whole ruleset; the engine never sets it."""

    status: Literal["unverified", "verified"] = "unverified"
    confirmed_by: str | None = None
    confirmed_at: dt.datetime | None = None
    confirmation_note: str | None = None


class NotModeled(_Frozen):
    """A firm rule the vocabulary cannot express. Declared, never silently dropped."""

    rule: str
    description: str
    materiality: Literal["immaterial", "material", "critical"]
    source: Attribution


class _Rule(_Frozen):
    rule_id: str
    description: str | None = None
    source: Attribution


class ProfitTargetRule(_Rule):
    """Pass condition: the basis reaches ``starting_balance + amount`` (``require_flat``: only
    with no open position)."""

    kind: Literal["profit_target"] = "profit_target"
    amount_usd: _MONEY_GE0
    basis: Literal["balance", "equity"] = "equity"
    evaluated: Literal["eod", "intraday"] = "eod"
    require_flat: bool = False


class StaticDrawdownRule(_Rule):
    """Threshold ``starting_balance - amount``; never trails.

    ``evaluated`` is REQUIRED and says when the threshold is tested: ``intraday`` continuously
    (a breach price inside the bar, and the gap test at the open), ``eod`` only at the rule-day's
    last scheduled close. It is a firm's rule, so it is always declared, never defaulted.
    """

    kind: Literal["static_drawdown"] = "static_drawdown"
    amount_usd: _MONEY_GE0
    basis: Literal["equity", "balance"] = "equity"
    evaluated: Literal["intraday", "eod"]


class TrailingLock(_Frozen):
    """Where a trailing threshold stops following the high-water mark. Exactly one trigger and
    one locked value: ``at_balance_usd``/``at_offset_usd`` say when the lock engages,
    ``locked_threshold_usd``/``locked_offset_usd`` where the threshold then stays."""

    at_balance_usd: _MONEY | None = None
    at_offset_usd: _MONEY | None = None
    locked_threshold_usd: _MONEY | None = None
    locked_offset_usd: _MONEY | None = None

    @model_validator(mode="after")
    def _one_of_each(self) -> TrailingLock:
        triggers = [v for v in (self.at_balance_usd, self.at_offset_usd) if v is not None]
        locked = [v for v in (self.locked_threshold_usd, self.locked_offset_usd) if v is not None]
        if len(triggers) != 1 or len(locked) != 1:
            msg = (
                "trailing lock needs exactly one of at_balance_usd/at_offset_usd and exactly one "
                f"of locked_threshold_usd/locked_offset_usd, got {len(triggers)} and {len(locked)}"
            )
            raise ValueError(msg)
        return self


class TrailingDrawdownRule(_Rule):
    """Threshold ``hwm - amount``.

    ``mode`` is when the high-water mark MOVES: intrabar on the favourable extreme, or at the
    rule-day's close. ``evaluated`` is when the threshold is TESTED: continuously intrabar or only
    at the rule-day's close. They are separate firm declarations (an EOD-updated mark can still
    be tested intrabar), so neither has a default.
    """

    kind: Literal["trailing_drawdown"] = "trailing_drawdown"
    amount_usd: _MONEY_GE0
    mode: Literal["intraday", "eod"]
    evaluated: Literal["intraday", "eod"]
    basis: Literal["equity", "balance"] = "equity"
    lock: TrailingLock | None = None


class DailyLossRule(_Rule):
    """Threshold ``reference - amount`` (or a percentage of the reference). Soft: liquidate and
    lock until the reset. Hard: fail."""

    kind: Literal["daily_loss"] = "daily_loss"
    amount_usd: _MONEY_GE0 | None = None
    pct_of_reference: Annotated[Decimal, Field(gt=0, le=100, decimal_places=6)] | None = None
    reference: Literal["day_start_balance", "day_start_equity", "prior_eod_balance"] = (
        "day_start_balance"
    )
    basis: Literal["equity", "balance"] = "equity"
    evaluated: Literal["intraday", "eod"]
    reset: ResetClock = Field(default_factory=ResetClock)
    severity: Literal["soft", "hard"] = "soft"

    @model_validator(mode="after")
    def _amount(self) -> DailyLossRule:
        if (self.amount_usd is None) == (self.pct_of_reference is None):
            msg = "daily_loss needs exactly one of amount_usd and pct_of_reference"
            raise ValueError(msg)
        return self


class MaxContractsRule(_Rule):
    """Admission limit by contract weight (``limit``) or per contract (``per_instrument``)."""

    kind: Literal["max_contracts"] = "max_contracts"
    limit: Decimal | None = Field(default=None, gt=0, decimal_places=6)
    per_instrument: int | None = Field(default=None, ge=1)
    on_excess: Literal["clip", "reject"] = "clip"

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
    evaluated: Literal["eod"] = "eod"
    basis: Literal["balance", "equity"] = "equity"

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
    """Step 6: liquidate at the open of the first bar reaching ``time`` and admit no entry until
    ``reopen``; ``consequence: fail`` fails the account instead of liquidating."""

    kind: Literal["flat_by"] = "flat_by"
    time: dt.time
    tz: str = DEFAULT_RESET_TZ
    reopen: dt.time | None = None
    consequence: Literal["auto_liquidate", "fail"] = "auto_liquidate"

    @model_validator(mode="after")
    def _zone(self) -> FlatByRule:
        _zone(self.tz, "flat_by.tz")
        return self


class DayCountsIf(_Frozen):
    min_trades: int | None = Field(default=None, ge=0)
    min_abs_pnl_usd: _MONEY | None = None

    @model_validator(mode="after")
    def _one(self) -> DayCountsIf:
        if (self.min_trades is None) == (self.min_abs_pnl_usd is None):
            msg = "day_counts_if needs exactly one of min_trades and min_abs_pnl_usd"
            raise ValueError(msg)
        return self


class MinTradingDaysRule(_Rule):
    """Pass condition: at least ``days`` rule-days that count."""

    kind: Literal["min_trading_days"] = "min_trading_days"
    days: int = Field(ge=1)
    day_counts_if: DayCountsIf = Field(default_factory=lambda: DayCountsIf(min_trades=1))


class ConsistencyRule(_Rule):
    """Pass or payout condition: the best day's share of total profit is at most ``max_day_share``
    (a fraction: 0.5 is half)."""

    kind: Literal["consistency"] = "consistency"
    max_day_share: Annotated[Decimal, Field(gt=0, le=1, decimal_places=6)] = Decimal("0.5")
    measure: Literal["best_day_profit/total_profit"] = "best_day_profit/total_profit"
    applies_to: Literal["pass", "payout"] = "pass"


class PayoutRule(_Rule):
    """A payout from a funded phase, evaluated at each rule-day's close (ADR-0106 section 4).

    ``withdrawable = balance - (threshold_base + buffer_usd)`` where ``threshold_base`` starts as
    the phase's starting balance. ``gross = min(max_usd, withdrawable)`` and there is a payout only
    when ``gross >= min_usd``; the balance falls by ``gross`` and the trader receives
    ``split * gross``. ``threshold_after_payout``: ``unchanged`` keeps the base where it was (the
    account must earn the buffer again from scratch); ``trail_from_new_balance`` moves the base to
    the post-payout balance. ``min_days_since_last`` counts trading days since the previous payout
    (or the phase start), ``min_profitable_days`` counts rule-days whose P&L is at least
    ``min_day_profit_usd``, and a ``consistency`` rule with ``applies_to: payout`` also has to
    hold. Taking the payout is the trader's choice, not a firm rule:
    ``simulate_attempt(..., payout_policy=...)`` decides it, and the choice is recorded.
    """

    kind: Literal["payout"] = "payout"
    min_days_since_last: int = Field(default=0, ge=0)
    min_profitable_days: int = Field(default=0, ge=0)
    min_day_profit_usd: _MONEY_GE0 = Decimal(0)
    buffer_usd: _MONEY_GE0
    split: Annotated[Decimal, Field(gt=0, le=1, decimal_places=6)]
    min_usd: _MONEY_GE0
    max_usd: _MONEY_GE0
    max_payouts: int | None = Field(default=None, ge=1)
    threshold_after_payout: Literal["unchanged", "trail_from_new_balance"] = "unchanged"

    @model_validator(mode="after")
    def _amounts(self) -> PayoutRule:
        if self.min_usd > self.max_usd:
            msg = (
                f"payout {self.rule_id}: min_usd {self.min_usd} is above max_usd {self.max_usd}, "
                "so no payout could ever be paid"
            )
            raise ValueError(msg)
        return self


class TimeLimitRule(_Rule):
    """A phase without a pass within the limit times out."""

    kind: Literal["time_limit"] = "time_limit"
    max_calendar_days: int | None = Field(default=None, ge=1)
    max_trading_days: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def _one(self) -> TimeLimitRule:
        if (self.max_calendar_days is None) == (self.max_trading_days is None):
            msg = "time_limit needs exactly one of max_calendar_days and max_trading_days"
            raise ValueError(msg)
        return self


class FeeRule(_Rule):
    """Attempt cost accounting only: never written into the trading ledger."""

    kind: Literal["fee"] = "fee"
    fee_kind: Literal["evaluation", "activation", "reset", "monthly"]
    amount_usd: _MONEY_GE0
    when: Literal["at_start", "at_pass", "per_month"] = "at_start"


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
    | FeeRule,
    Field(discriminator="kind"),
]


class Phase(_Frozen):
    """One account of the attempt: ``evaluation`` or ``funded``, with its own starting balance."""

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


class PropRuleset(_Frozen):
    """One versioned ruleset of one program and account size (ADR-0106 section 2)."""

    schema_version: Literal[1] = 1
    ruleset_id: str
    version: int = Field(ge=1)
    firm: str
    program: str
    account_size_usd: _MONEY_GE0
    platform: str | None = None
    addons: tuple[str, ...] = ()
    jurisdiction: str | None = None
    as_of: dt.date
    effective_from: dt.date
    effective_to: dt.date | None = None
    instruments: tuple[Instrument, ...]
    verification: Verification = Field(default_factory=Verification)
    phases: tuple[Phase, ...]
    not_modeled: tuple[NotModeled, ...] = ()

    @model_validator(mode="after")
    def _content(self) -> PropRuleset:
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
        if self.verification.status == "verified":
            self._require_verified()
        return self

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
        sources = [
            (f"phase {phase.phase_id} rule {rule.rule_id}", rule.source)
            for phase in self.phases
            for rule in (*phase.rules, *phase.pass_conditions, *phase.fees)
        ]
        sources += [
            (f"phase {phase.phase_id} pass condition {rule.rule_id}", rule.source)
            for phase in self.phases
            for rule in phase.pass_conditions
        ]
        sources += [(f"not_modeled {n.rule}", n.source) for n in self.not_modeled]
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

    @property
    def ruleset_sha256(self) -> str:
        """The canonical hash of the content: two versions differ, a rewritten file that changes
        only key order does not."""
        return hashlib.sha256(
            canonical_json(self.model_dump(mode="json")).encode("utf-8")
        ).hexdigest()

    @property
    def verified(self) -> bool:
        return self.verification.status == "verified"

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


def _zone(name: str, what: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        msg = f"{what} = {name!r} is not a known IANA time zone: {exc}"
        raise ValueError(msg) from exc


def _read(path: Path) -> PropRuleset:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        msg = f"cannot read ruleset {path}: {exc}"
        raise DataQualityError(msg) from exc
    if not isinstance(raw, dict):
        msg = f"ruleset {path} must be a YAML mapping, got {type(raw).__name__}"
        raise DataQualityError(msg)
    try:
        return PropRuleset.model_validate(raw)
    except ValueError as exc:
        msg = f"ruleset {path} does not validate: {exc}"
        raise ConfigurationError(msg) from exc


def load_ruleset(path: str | Path) -> PropRuleset:
    """One ruleset file. A file that does not validate is refused, never repaired."""
    return _read(Path(path))


def load_registry(directory: str | Path) -> list[PropRuleset]:
    """Every ruleset file in a directory, sorted by ``(ruleset_id, version)``.

    Refuses two files that claim the same ``(ruleset_id, version)`` with different content hashes,
    and a repeated version number: an old version is immutable, so a change is a new version.
    """
    root = Path(directory)
    if not root.is_dir():
        msg = f"ruleset registry {root} is not a directory"
        raise ConfigurationError(msg)
    files = sorted(p for p in root.iterdir() if p.suffix in (".yaml", ".yml") and p.is_file())
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
