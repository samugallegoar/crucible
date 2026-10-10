"""Experiment configuration models and hashing.

Everything that affects results flows from these models (no hardcoded engine
parameters). The config hash identifies an experiment; identical hash + code
commit + data manifests + seed must reproduce byte-identical outputs.

All models are frozen and refuse unknown fields: a typo in a config is an
error, never a silently ignored knob.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Literal

import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_serializer,
    field_validator,
    model_validator,
)

from crucible.core.errors import ConfigurationError
from crucible.core.types import RealismLevel, RunMode, TimestampNs, to_timestamp_ns

if TYPE_CHECKING:
    from collections.abc import Sequence


class _FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ExperimentHeader(_FrozenModel):
    """The identity block of every run (the ``experiment:`` block)."""

    name: str = Field(min_length=1)
    family: str = Field(min_length=1, description="Trial-counting scope (ADR-0008).")
    mode: RunMode
    seed: int = Field(ge=0)
    realism_level: RealismLevel


class FuturesMarginConfig(_FrozenModel):
    """Per-contract futures margin in the contract's currency (ADR-0050)."""

    initial: Decimal
    maintenance: Decimal


class DataConfig(_FrozenModel):
    """Datasets a run consumes; their manifest hashes go into the run manifest."""

    store: Path
    bars: str = Field(min_length=1)
    corporate_actions: str | None = None
    universe: str | None = None
    calendar: str = Field(min_length=1, description="exchange_calendars name or '24/7'")
    base_currency: str = Field(pattern=r"^[A-Z]{3}$", default="USD")
    symbol_currency: dict[str, str] = Field(
        default_factory=dict,
        description="Per-symbol trading currency (ADR-0009); "
        "symbols absent here trade in base_currency.",
    )
    fx_rates: str | None = Field(
        default=None,
        description="FX rate dataset id (FX_RATE_SCHEMA); required if symbol_currency "
        "names any non-base currency.",
    )
    futures_multipliers: dict[str, Decimal] = Field(
        default_factory=dict,
        description="Per-symbol futures contract multiplier (ADR-0033); "
        "symbols absent here are equities (no multiplier, full-notional cash on fill).",
    )
    futures_margins: dict[str, FuturesMarginConfig] = Field(
        default_factory=dict,
        description="Per-symbol futures margins (ADR-0050); each symbol must also appear in "
        "futures_multipliers.",
    )
    quality_skip: tuple[str, ...] = ()
    quality_skip_reason: str = ""

    @field_serializer("store")
    def _store_as_posix(self, value: Path) -> str:
        """Forward slashes on every OS: the canonical config, its hash and the experiment id must
        not depend on the platform's path separator (ADR-0055)."""
        return value.as_posix()

    @field_validator("symbol_currency")
    @classmethod
    def _valid_currency_codes(cls, value: dict[str, str]) -> dict[str, str]:
        for symbol, ccy in value.items():
            if not re.fullmatch(r"[A-Z]{3}", ccy):
                msg = f"symbol_currency[{symbol!r}] = {ccy!r} is not a 3-letter ISO currency code"
                raise ConfigurationError(msg)
        return value

    @model_validator(mode="after")
    def _margins_need_multipliers_and_order(self) -> DataConfig:
        for symbol, margin in self.futures_margins.items():
            if symbol not in self.futures_multipliers:
                msg = (
                    f"futures_margins[{symbol!r}] has no futures_multipliers entry; "
                    "declare the contract multiplier first"
                )
                raise ConfigurationError(msg)
            if margin.maintenance <= 0:
                msg = f"futures_margins[{symbol!r}] maintenance {margin.maintenance} must be > 0"
                raise ConfigurationError(msg)
            if margin.initial < margin.maintenance:
                msg = (
                    f"futures_margins[{symbol!r}] initial {margin.initial} must be >= "
                    f"maintenance {margin.maintenance}"
                )
                raise ConfigurationError(msg)
        return self

    @field_validator("futures_multipliers")
    @classmethod
    def _positive_multipliers(cls, value: dict[str, Decimal]) -> dict[str, Decimal]:
        for symbol, multiplier in value.items():
            if multiplier <= 0:
                msg = f"futures_multipliers[{symbol!r}] = {multiplier} must be > 0"
                raise ConfigurationError(msg)
        return value


class StrategyConfig(_FrozenModel):
    entrypoint: str = Field(
        pattern=r"^[\w.]+:[\w]+$", description="module.path:ClassName, importable"
    )
    params: dict[str, object] = Field(default_factory=dict)


# ------------------------------------------------- execution model configs
# One Pydantic model per pluggable execution model (AGENTS.md §6). The
# `type` literal is the stable registry key; the discriminated unions keep
# YAML typos fatal instead of silently ignored.


class NoSpreadConfig(_FrozenModel):
    type: Literal["none"] = "none"


class StaticSpreadConfig(_FrozenModel):
    type: Literal["static"]
    half_spread_bps: float = Field(ge=0.0)


class QuotedSpreadConfig(_FrozenModel):
    type: Literal["quoted"]


class DynamicSpreadConfig(_FrozenModel):
    type: Literal["dynamic"]
    base_bps: float = Field(ge=0.0)
    vol_mult: float = Field(ge=0.0)


SpreadModelConfig = Annotated[
    NoSpreadConfig | StaticSpreadConfig | DynamicSpreadConfig | QuotedSpreadConfig,
    Field(discriminator="type"),
]


class ZeroLatencyConfig(_FrozenModel):
    type: Literal["zero"] = "zero"


class ConstantLatencyConfig(_FrozenModel):
    type: Literal["constant"]
    ms: float = Field(ge=0.0)


class NormalLatencyConfig(_FrozenModel):
    type: Literal["normal"]
    mean_ms: float = Field(ge=0.0)
    std_ms: float = Field(ge=0.0)


LatencyModelConfig = Annotated[
    ZeroLatencyConfig | ConstantLatencyConfig | NormalLatencyConfig,
    Field(discriminator="type"),
]


class NoSlippageConfig(_FrozenModel):
    type: Literal["none"] = "none"


class FixedBpsSlippageConfig(_FrozenModel):
    type: Literal["fixed_bps"]
    bps: float = Field(ge=0.0)


class SqrtImpactConfig(_FrozenModel):
    """Level 4: ``coef * sigma * sqrt(Q/ADV)`` adverse impact."""

    type: Literal["sqrt_impact"]
    coef: float = Field(ge=0.0)


class LinearImpactConfig(_FrozenModel):
    """Level 4: ``coef * (Q/ADV)`` adverse impact."""

    type: Literal["linear_impact"]
    coef: float = Field(ge=0.0)


SlippageModelConfig = Annotated[
    NoSlippageConfig | FixedBpsSlippageConfig | SqrtImpactConfig | LinearImpactConfig,
    Field(discriminator="type"),
]


class NoCommissionConfig(_FrozenModel):
    type: Literal["none"] = "none"


class BpsCommissionConfig(_FrozenModel):
    type: Literal["bps"]
    bps: float = Field(ge=0.0)


class PerShareCommissionConfig(_FrozenModel):
    type: Literal["per_share"]
    rate: Annotated[Decimal, Field(ge=0)]
    minimum: Annotated[Decimal, Field(ge=0)]


class MakerTakerCommissionConfig(_FrozenModel):
    """Maker rebates (negative maker_bps) are a real schedule; taker fees
    must be non-negative."""

    type: Literal["maker_taker"]
    maker_bps: float
    taker_bps: float = Field(ge=0.0)


CommissionModelConfig = Annotated[
    NoCommissionConfig
    | BpsCommissionConfig
    | PerShareCommissionConfig
    | MakerTakerCommissionConfig,
    Field(discriminator="type"),
]


class ParticipationConfig(_FrozenModel):
    """Level 3+ liquidity caps (R3.4) and queue-awareness (queue_bps)."""

    max_bar_vol: float | None = Field(default=None, gt=0.0, le=1.0)
    max_adv: float | None = Field(default=None, gt=0.0, le=1.0)
    queue_bps: float = Field(ge=0.0, default=0.0)


class ScenarioOverride(_FrozenModel):
    """Per-scenario replacements for execution slots (R3.10). ``None`` keeps
    the base setting for that slot."""

    spread: SpreadModelConfig | None = None
    latency: LatencyModelConfig | None = None
    slippage: SlippageModelConfig | None = None
    commission: CommissionModelConfig | None = None
    participation: ParticipationConfig | None = None


class ExecutionConfig(_FrozenModel):
    """Execution knobs across the ladder.

    ``slippage_bps``/``commission_bps`` are the Level 0/1 shorthand
    (ADR-0010); the model slots configure Levels 2-4. A shorthand and its
    model slot are mutually exclusive — one source of truth per slot.
    Which slots a run may use is gated by ``experiment.realism_level``
    (checked by the runner's builder, ADR-0012).
    """

    slippage_bps: float = Field(ge=0.0, default=0.0)
    commission_bps: float = Field(ge=0.0, default=0.0)
    spread: SpreadModelConfig | None = None
    latency: LatencyModelConfig | None = None
    slippage: SlippageModelConfig | None = None
    commission: CommissionModelConfig | None = None
    participation: ParticipationConfig | None = None
    stats_window: int = Field(ge=2, default=20)
    scenarios: dict[str, ScenarioOverride] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _one_source_per_slot(self) -> ExecutionConfig:
        if self.slippage_bps and self.slippage is not None:
            msg = "set either slippage_bps (shorthand) or slippage (model), not both"
            raise ConfigurationError(msg)
        if self.commission_bps and self.commission is not None:
            msg = "set either commission_bps (shorthand) or commission (model), not both"
            raise ConfigurationError(msg)
        if "base" in self.scenarios:
            msg = "scenario name 'base' is reserved for the unmodified run"
            raise ConfigurationError(msg)
        return self


class MaxOrderNotionalLimitConfig(_FrozenModel):
    type: Literal["max_order_notional"]
    max_notional: Annotated[Decimal, Field(gt=0)]


class MaxGrossExposureLimitConfig(_FrozenModel):
    type: Literal["max_gross_exposure"]
    max_ratio: float = Field(gt=0.0)


class InsufficientCashLimitConfig(_FrozenModel):
    type: Literal["insufficient_cash"]


class MarginRequirementLimitConfig(_FrozenModel):
    type: Literal["margin_requirement"]
    initial_margin_rate: float = Field(ge=1.0, default=1.5)


PreTradeLimitConfig = Annotated[
    MaxOrderNotionalLimitConfig
    | MaxGrossExposureLimitConfig
    | InsufficientCashLimitConfig
    | MarginRequirementLimitConfig,
    Field(discriminator="type"),
]


class DrawdownHaltLimitConfig(_FrozenModel):
    type: Literal["drawdown_halt"]
    max_drawdown: float = Field(gt=0.0, lt=1.0)


class DailyLossFlattenLimitConfig(_FrozenModel):
    type: Literal["daily_loss_flatten"]
    max_daily_loss: float = Field(gt=0.0, lt=1.0)


class MarginCallLimitConfig(_FrozenModel):
    type: Literal["margin_call"]
    maintenance_margin_rate: float = Field(ge=1.0, default=1.3)


MarkLimitConfig = Annotated[
    DrawdownHaltLimitConfig | DailyLossFlattenLimitConfig | MarginCallLimitConfig,
    Field(discriminator="type"),
]


class RiskConfig(_FrozenModel):
    """Composes into a `CompositeRiskEngine` (ADR-0027); checked
    in list order, pre-trade on every order and mark on every bar."""

    pre_trade: tuple[PreTradeLimitConfig, ...] = ()
    mark: tuple[MarkLimitConfig, ...] = ()


class LiveConfig(_FrozenModel):
    """Feature flag for the live runtime (ADR-0043).
    ``LiveRuntime`` refuses to construct unless ``enabled`` is true."""

    enabled: bool = False
    venue: Literal["simulated"] = "simulated"


class ExperimentConfig(_FrozenModel):
    experiment: ExperimentHeader
    data: DataConfig
    strategy: StrategyConfig
    execution: ExecutionConfig = ExecutionConfig()
    risk: RiskConfig | None = None
    live: LiveConfig | None = None
    initial_cash: Annotated[Decimal, Field(gt=0)]
    start: str = Field(description="ISO date (UTC midnight) or ISO datetime with tz")
    end: str
    periods_per_year: float = Field(gt=0, default=252.0)
    settlement_lag_days: int = Field(
        ge=0,
        default=0,
        description="T+N settlement (ADR-0028): delays sale proceeds joining "
        "available cash by N calendar days; never affects equity. 0 = T+0 (unchanged).",
    )
    short_borrow_rate: float = Field(
        ge=0.0,
        default=0.0,
        description="Annualized stock-loan fee on short notional (Actual/365, "
        "ADR-0032), accrued at every mark. 0 = no borrow cost (unchanged).",
    )
    margin_financing_rate: float = Field(
        ge=0.0,
        default=0.0,
        description="Annualized interest on a negative (margin) cash balance (Actual/365, "
        "ADR-0032), accrued at every mark. 0 = no financing cost (unchanged).",
    )

    @field_validator("start", "end")
    @classmethod
    def _parseable(cls, value: str) -> str:
        _parse_when(value)
        return value

    @property
    def start_ns(self) -> TimestampNs:
        return _parse_when(self.start)

    @property
    def end_ns(self) -> TimestampNs:
        end = _parse_when(self.end)
        if end <= self.start_ns:
            msg = f"end {self.end!r} must be after start {self.start!r}"
            raise ConfigurationError(msg)
        return end


def parse_when(value: str) -> TimestampNs:
    """Public alias of the config time parser (used by the debug CLI)."""
    return _parse_when(value)


_INTERVAL_SECONDS = {"s": 1, "m": 60, "h": 3_600, "d": 86_400, "w": 604_800}


def parse_interval(value: str) -> int:
    """A span of *simulated* time such as ``30s``, ``4h``, ``1d`` or ``2w`` in nanoseconds.

    A whole number of at least 1 and one fixed-length unit (months and years vary in length, so
    they are refused). Used for the checkpoint cadence: it is measured on the simulation clock,
    never the wall clock (ADR-0058).
    """
    match = re.fullmatch(r"([1-9][0-9]*)([smhdw])", value.strip())
    if match is None:
        msg = (
            f"cannot parse {value!r} as an interval; use a whole number and one unit of "
            "s, m, h, d, w (for example 4h, 1d, 2w)"
        )
        raise ConfigurationError(msg)
    return int(match.group(1)) * _INTERVAL_SECONDS[match.group(2)] * 1_000_000_000


def _parse_when(value: str) -> TimestampNs:
    """ISO date -> UTC midnight; ISO datetime must carry a timezone."""
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        msg = f"cannot parse {value!r} as ISO date/datetime: {exc}"
        raise ConfigurationError(msg) from exc
    if parsed.tzinfo is None:
        if parsed.time() != parsed.min.time():
            msg = f"datetime {value!r} has a time but no timezone; add one (e.g. +00:00)"
            raise ConfigurationError(msg)
        parsed = parsed.replace(tzinfo=UTC)
    return to_timestamp_ns(parsed)


def _parse_override_value(text: str) -> object:
    """YAML scalar/flow parsing of an override value (``60`` -> int, ``true`` -> bool).
    A date-like value stays the string the config expects (``start: 2020-01-01``)."""
    try:
        value = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        msg = f"override value {text!r} is not valid YAML: {exc}"
        raise ConfigurationError(msg) from exc
    if isinstance(value, date):  # datetime is a subclass of date
        return text.strip()
    return value


def apply_overrides(raw: dict[str, object], overrides: Sequence[str]) -> dict[str, object]:
    """Returns a copy of the parsed config mapping with each ``PATH=VALUE`` applied, in order.

    ``PATH`` is dot-separated; a list element is addressed by its integer index
    (``execution.scenarios.0.name``). The edit happens on the raw mapping, before validation, so
    ``config_hash``, the experiment id and the stored ``config.yaml`` all describe the overridden
    run. Refused, never guessed: an empty or malformed override, a path whose parent does not
    exist, a parent that is neither a mapping nor a list, an out-of-range list index. A new leaf
    under an existing mapping is allowed (strategy params); unknown model fields are still refused
    by validation (``extra="forbid"``).
    """
    result: dict[str, object] = copy.deepcopy(raw)
    for override in overrides:
        path, sep, text = override.partition("=")
        path = path.strip()
        if not sep or not path or any(not part for part in path.split(".")):
            msg = (
                f"override {override!r} must look like PATH=VALUE, e.g. strategy.params.lookback=60"
            )
            raise ConfigurationError(msg)
        parts = path.split(".")
        node: object = result
        walked: list[str] = []
        for part in parts[:-1]:
            walked.append(part)
            node = _descend(node, part, ".".join(walked), override)
        _assign(node, parts[-1], _parse_override_value(text), path, override)
    return result


def _descend(node: object, part: str, walked: str, override: str) -> object:
    if isinstance(node, dict):
        if part not in node:
            msg = (
                f"override {override!r}: {walked!r} does not exist in the config; "
                f"available here: {', '.join(sorted(map(str, node))) or '(none)'}"
            )
            raise ConfigurationError(msg)
        return node[part]
    if isinstance(node, list):
        return node[_list_index(node, part, walked, override)]
    msg = f"override {override!r}: {walked!r} is a scalar, so it has nothing inside it to set"
    raise ConfigurationError(msg)


def _assign(node: object, key: str, value: object, path: str, override: str) -> None:
    if isinstance(node, dict):
        node[key] = value
    elif isinstance(node, list):
        node[_list_index(node, key, path, override)] = value
    else:
        msg = (
            f"override {override!r}: the parent of {path!r} is a scalar, so it cannot hold {key!r}"
        )
        raise ConfigurationError(msg)


def _list_index(node: list[object], part: str, walked: str, override: str) -> int:
    if not part.isdigit() or int(part) >= len(node):
        msg = (
            f"override {override!r}: {walked!r} must be a list index from 0 to "
            f"{len(node) - 1}, got {part!r}"
        )
        raise ConfigurationError(msg)
    return int(part)


def load_config(path: Path, overrides: Sequence[str] = ()) -> ExperimentConfig:
    """Loads and validates a config; ``overrides`` (``PATH=VALUE``) are applied first, see
    ``apply_overrides``."""
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        msg = f"config {path} did not parse to a mapping"
        raise ConfigurationError(msg)
    return ExperimentConfig.model_validate(apply_overrides(raw, overrides) if overrides else raw)


def config_json_schema() -> dict[str, object]:
    """The JSON Schema of ``ExperimentConfig``: every field, type, default and description a
    valid config may use. Deterministic, so a diff shows a config change."""
    return ExperimentConfig.model_json_schema()


def config_hash(config: BaseModel) -> str:
    """SHA-256 over the canonical JSON serialization of a config model.

    Canonical means: pydantic JSON mode, keys sorted, no whitespace — so the
    hash is stable across processes and platforms.
    """
    payload = json.dumps(
        config.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def canonical_yaml(config: BaseModel) -> str:
    """Deterministic YAML rendering of a config, for the artifact store."""
    dumped: str = yaml.safe_dump(
        config.model_dump(mode="json"), sort_keys=True, default_flow_style=False
    )
    return dumped
