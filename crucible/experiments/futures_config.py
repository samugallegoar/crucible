"""The futures-run config: one YAML file that says what to trade, on which data, at what cost.

A futures run (Fathom C3b, ADR-0095) is one continuous CME series, one strategy, a trade-date
window and an explicit cost and execution policy. This module is the *only* place those decisions
are written down: every field maps onto an existing simulator dataclass
(``crucible.execution.futures_sim.CostSchedule`` / ``ExecutionPolicy``), the signal bridge's
session policy (``crucible.experiments.futures_signals.FuturesSessionPolicy``) or the bridge's
``SignalInput``, so a config cannot invent semantics the engine does not implement.

Two rules make the config hash (and therefore the run id) an identity of the *content*:

- a ``strategy.spec`` given as a path is **loaded** by :func:`load_futures_config` and the loaded
  mapping is what the model holds, so editing the spec file changes the hash (the path does not);
- ``datasets`` defaults are resolved from ``root`` at parse time, so the canonical config always
  names the four datasets it read.

The config refuses, with an actionable message, what the engine cannot honour: no calendar or
contract spec for ``root``, a spec and an entrypoint together (or neither), ``contracts`` for a
function that already decides the size, an unadjusted signal read from a different series than the
one that executes, and any cost/execution combination ``CostSchedule``/``ExecutionPolicy`` refuse.

Units: ``capital`` in USD (``Decimal``, at most 6 decimals: money is exact micro-dollars),
``costs`` per contract per side (``commission`` in USD, ticks for spread/slippage), ``window`` in
Globex trade dates (inclusive), ``contracts`` a whole number of contracts.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Literal

import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from crucible.core.errors import ConfigurationError
from crucible.data.continuous import calendar_for
from crucible.data.futures_specs import futures_spec
from crucible.execution.futures_sim import CostSchedule, ExecutionPolicy
from crucible.experiments.config import canonical_yaml, config_hash
from crucible.experiments.futures_signals import FuturesSessionPolicy, SignalInput
from crucible.strategy_spec.models import parse_spec

if TYPE_CHECKING:
    from collections.abc import Mapping

BAR_SECONDS = 60
"""The bar length of the futures datasets this config names (one-minute bars, the C3 datasets)."""

FILL_MODES = ("next_eligible_bar_open", "signal_bar_close")
REENTRY_MODES = ("require_signal_reset", "allow_immediate")
ROLL_EXECUTIONS = ("causal", "reference_approximation")
MICRO = 1_000_000
"""Micro-dollars per dollar: money is kept in exact micro-dollars (6 decimals)."""


class _FrozenModel(BaseModel):
    """Frozen, and a typo in a config is an error rather than a silently ignored knob."""

    model_config = ConfigDict(frozen=True, extra="forbid")


def _no_bool(value: object, what: str) -> object:
    """``True``/``False`` are not whole numbers here: a bool is a mistake in an int field."""
    if isinstance(value, bool):
        msg = f"{what} = {value!r} is a bool; give a whole number instead"
        raise ConfigurationError(msg)
    return value


def default_datasets(root: str) -> dict[str, str]:
    """The four dataset ids the C3 continuous build writes for ``root`` (ADR-0086)."""
    key = root.strip().lower()
    return {
        "execution": f"{key}_1m_cont_v3",
        "signal": f"{key}_1m_cont_ratio_v3",
        "rolls": f"{key}_1m_rolls_v3",
        "raw": f"{key}_1m_raw",
    }


class FuturesRunHeader(_FrozenModel):
    """The run's name and its trial family (ADR-0008): every config of one family shares a trial
    count, so a sweep cannot hide its own size."""

    name: str = Field(
        min_length=1,
        description="Human-readable run name, recorded in the manifest (the run id is a hash).",
    )
    family: str = Field(
        min_length=1,
        description="Trial-counting scope (ADR-0008). A second config of the same family adds "
        "one trial to its count, which is what the deflation of a headline statistic reads.",
    )


class FuturesDatasets(_FrozenModel):
    """The four datasets of one continuous build (ADR-0086), by dataset id in the store."""

    execution: str = Field(
        min_length=1,
        description="Unadjusted continuous series: the prices fills and P&L are computed on "
        "(price_basis=raw).",
    )
    signal: str = Field(
        min_length=1,
        description="The series the strategy reads: the ratio-adjusted one by default, the "
        "execution one when signal.input=unadjusted.",
    )
    rolls: str = Field(min_length=1, description="Rows of one contract switch per roll.")
    raw: str = Field(
        min_length=1,
        description="Per-contract bars the causal roll legs come from (symbol = the contract).",
    )


class FuturesWindow(_FrozenModel):
    """The evaluation window as Globex TRADE DATES, inclusive on both ends."""

    start: dt.date = Field(description="First trade date whose bars are simulated.")
    end: dt.date = Field(description="Last trade date whose bars are simulated, inclusive.")

    @model_validator(mode="after")
    def _ordered(self) -> FuturesWindow:
        if self.end < self.start:
            msg = (
                f"window.end {self.end} is before window.start {self.start}: the window is a "
                "range of Globex trade dates, inclusive on both ends"
            )
            raise ConfigurationError(msg)
        return self


class FuturesStrategyConfig(_FrozenModel):
    """What decides the position: a declarative spec sized by ``contracts``, or a function."""

    spec: dict[str, object] | str | None = Field(
        default=None,
        description="A strategy spec as a mapping, or a path to a YAML/JSON spec file (resolved "
        "against the config file's directory by load_futures_config, then stored loaded).",
    )
    entrypoint: str | None = Field(
        default=None,
        pattern=r"^[\w.]+:[\w]+$",
        description="module.path:function of a FuturesSignalFunction (returns signed whole "
        "contracts per bar and decides its own size).",
    )
    params: dict[str, object] = Field(
        default_factory=dict,
        description="Keyword parameters passed to the entrypoint function on every call.",
    )

    @model_validator(mode="after")
    def _one_source_of_decisions(self) -> FuturesStrategyConfig:
        if isinstance(self.spec, str):
            msg = (
                f"strategy.spec {self.spec!r} is a path, and a path is resolved against the "
                "config file's directory, which a mapping does not have: load the file with "
                "load_futures_config(path), or inline the spec as a mapping"
            )
            raise ConfigurationError(msg)
        if (self.spec is None) == (self.entrypoint is None):
            msg = (
                "strategy needs exactly one of spec (a StrategySpec mapping) or entrypoint "
                "(module.path:function); both were given"
                if self.spec is not None
                else "strategy has neither spec nor entrypoint: give one of them"
            )
            raise ConfigurationError(msg)
        if self.spec is not None:
            if self.params:
                msg = (
                    f"strategy.params = {sorted(self.params)} was given with a spec: params are "
                    "forwarded to a FuturesSignalFunction, and a spec carries its own literals. "
                    "Move the values into the spec or use an entrypoint"
                )
                raise ConfigurationError(msg)
            parse_spec(self.spec)
        return self


class FuturesCostsConfig(_FrozenModel):
    """Costs per contract per side, against the trader (``CostSchedule``, ADR-0090 decision 3)."""

    commission: Decimal = Field(
        gt=0,
        description="All-in commission per contract per side, USD. Required: there is no "
        "default, because a zero would be silently optimistic.",
    )
    exchange_fee: Decimal = Field(
        default=Decimal(0), ge=0, description="Exchange fee per contract per side, USD."
    )
    clearing_fee: Decimal = Field(
        default=Decimal(0), ge=0, description="Clearing fee per contract per side, USD."
    )
    regulatory_fee: Decimal = Field(
        default=Decimal(0), ge=0, description="Regulatory fee per contract per side, USD."
    )
    spread_ticks: Decimal = Field(
        default=Decimal(1),
        ge=0,
        description="The full bid-ask spread in ticks; half is paid per side. Uncalibrated "
        "unless spread_calibrated.",
    )
    slippage_ticks: Decimal = Field(
        default=Decimal(1),
        ge=0,
        description="Adverse slippage per side in ticks, on top of the half spread.",
    )
    spread_calibrated: bool = Field(
        default=False,
        description="True only when spread_ticks was measured on this instrument and period; "
        "otherwise the run records the assumption as an approximation.",
    )
    slippage_calibrated: bool = Field(
        default=False,
        description="True only when slippage_ticks was measured; otherwise it is recorded as an "
        "approximation.",
    )
    prices_include_spread: bool = Field(
        default=False,
        description="True when the execution prices already carry the spread, which then must "
        "be 0 (the spread would otherwise be paid twice).",
    )


class FuturesExecutionConfig(_FrozenModel):
    """How a decided target becomes a fill (``ExecutionPolicy``, ADR-0090 decisions 2, 5, 6)."""

    fill: Literal["next_eligible_bar_open", "signal_bar_close"] = Field(
        default="next_eligible_bar_open",
        description="next_eligible_bar_open: the target decided at a bar's close trades at the "
        "open of the next bar the held contract trades. signal_bar_close is OPTIMISTIC and is "
        "labelled as such in the manifest.",
    )
    stop_ticks: int | None = Field(
        default=None,
        description="Per-lot stop distance in whole ticks from that lot's own fill price; null "
        "for no stop.",
    )
    target_ticks: int | None = Field(
        default=None,
        description="Per-lot profit-target distance in whole ticks from that lot's own fill "
        "price; null for no target.",
    )
    target_fill_through_ticks: int = Field(
        default=1,
        ge=0,
        description="A limit target fills only after a trade that many ticks through it.",
    )
    reentry: Literal["require_signal_reset", "allow_immediate"] = Field(
        default="require_signal_reset",
        description="require_signal_reset: after a bracket exit the same decided target may not "
        "re-enter until it changes (no silent re-entry loop).",
    )
    roll_execution: Literal["causal", "reference_approximation"] = Field(
        default="causal",
        description="causal: each roll trades at the first minute at or after its decision in "
        "which both contracts traded. reference_approximation values the roll at the reference "
        "prices and is recorded as an approximation.",
    )
    strict: bool = Field(
        default=True,
        description="True refuses a roll that cannot be executed causally instead of valuing it "
        "at reference prices.",
    )


class FuturesSignalConfig(_FrozenModel):
    """Which series the strategy reads (ADR-0086 decision 8)."""

    input: SignalInput = Field(
        default="ratio_adjusted",
        description="ratio_adjusted: the ratio-adjusted series, whose levels depend on later "
        "rolls, so only scale-invariant logic may read it. unadjusted: the contracts' own "
        "prices, for level-based logic (the signal dataset must then be the execution one).",
    )


class FuturesSessionConfig(_FrozenModel):
    """Session rules evaluated on the CME Globex calendar (``FuturesSessionPolicy``, ADR-0091)."""

    flat_by_close: bool = Field(
        default=False,
        description="True is flat from the session's penultimate scheduled bar on: the exit is "
        "decided there and fills at the final scheduled bar's open.",
    )
    exit_at: str | None = Field(
        default=None,
        description="HH:MM Chicago on the trade-date clock: flat from the first bar ending at or "
        "after it, and no entry after it.",
    )
    entry_window: tuple[str, str] | None = Field(
        default=None,
        description="(start, end) HH:MM on the trade-date clock, inclusive: new positions only "
        "on bars ending inside it. Exits and reductions are always allowed.",
    )
    allow_unverified_sessions: bool = Field(
        default=False,
        description="True accepts trade dates whose schedule no transcribed CME source covers "
        "(their times are the regime's, unconfirmed). The run records it as an approximation.",
    )


class FuturesRunConfig(_FrozenModel):
    """One futures run: the data, the window, the strategy and every cost and timing decision."""

    kind: Literal["futures_run"] = Field(
        default="futures_run", description="Config kind discriminator (a futures run)."
    )
    run: FuturesRunHeader = Field(description="Run name and trial family.")
    root: str = Field(
        min_length=1,
        description="CME root (ES, NQ, YM, RTY): must have a Globex session calendar and a "
        "contract specification (tick size and point value).",
    )
    datasets: FuturesDatasets = Field(
        description="Dataset ids the run reads; omitted fields default from root "
        "(<root>_1m_cont_v3, <root>_1m_cont_ratio_v3, <root>_1m_rolls_v3, <root>_1m_raw)."
    )
    window: FuturesWindow = Field(description="The Globex trade dates simulated, inclusive.")
    strategy: FuturesStrategyConfig = Field(description="Exactly one of spec or entrypoint.")
    contracts: int | None = Field(
        default=None,
        ge=1,
        description="Contracts per side a SPEC is sized at (a spec decides the side, +-1). "
        "Forbidden for an entrypoint, whose score is already signed whole contracts.",
    )
    capital: Decimal = Field(
        gt=0, description="Starting capital in USD (at most 6 decimals: exact micro-dollars)."
    )
    costs: FuturesCostsConfig = Field(description="Costs per contract per side.")
    execution: FuturesExecutionConfig = Field(
        default_factory=FuturesExecutionConfig, description="How targets become fills."
    )
    signal: FuturesSignalConfig = Field(
        default_factory=FuturesSignalConfig, description="Which series the strategy reads."
    )
    session: FuturesSessionConfig = Field(
        default_factory=FuturesSessionConfig, description="Globex session rules."
    )

    @field_validator("root")
    @classmethod
    def _root_upper(cls, value: str) -> str:
        root = value.strip().upper()
        if not root:
            msg = "root must name a CME root (ES, NQ, YM, RTY)"
            raise ConfigurationError(msg)
        return root

    @field_validator("contracts", mode="before")
    @classmethod
    def _contracts_are_whole(cls, value: object) -> object:
        return _no_bool(value, "contracts")

    @field_validator("capital", mode="before")
    @classmethod
    def _capital_is_decimal(cls, value: object) -> object:
        if isinstance(value, float):
            msg = (
                f"capital = {value!r} is a float: money is exact, so write it as a string "
                '("50000") or a whole number, and give the decimals explicitly'
            )
            raise ConfigurationError(msg)
        return value

    @field_validator("capital")
    @classmethod
    def _capital_is_exact(cls, value: Decimal) -> Decimal:
        if value * MICRO != (value * MICRO).to_integral_value():
            msg = (
                f"capital = {value} has more than 6 decimals; money is kept in exact "
                "micro-dollars, so round it to at most 6 decimals"
            )
            raise ConfigurationError(msg)
        return value

    @model_validator(mode="before")
    @classmethod
    def _fill_dataset_defaults(cls, data: object) -> object:
        """Resolve ``datasets`` from ``root`` before validation: the canonical config and the
        config hash then always name the four datasets the run read."""
        if not isinstance(data, dict):
            return data
        raw = dict(data)
        given = raw.get("datasets")
        root = raw.get("root")
        if not isinstance(root, str) or not root.strip():
            return raw
        names = default_datasets(root)
        signal = raw.get("signal")
        if isinstance(given, dict):
            merged = {**names, **given}
        else:
            if isinstance(signal, dict) and signal.get("input") == "unadjusted":
                names["signal"] = names["execution"]
            merged = names
        raw["datasets"] = merged
        return raw

    @model_validator(mode="after")
    def _coherent(self) -> FuturesRunConfig:
        calendar_for(self.root)  # refuses a root without a Globex session table
        futures_spec(self.root)  # refuses a root without tick size and point value
        if self.signal.input == "unadjusted" and self.datasets.signal != self.datasets.execution:
            msg = (
                f"signal.input=unadjusted reads the contracts' own prices, but datasets.signal "
                f"is {self.datasets.signal} and datasets.execution is {self.datasets.execution}: "
                "the signal series must be the series that executes (same prices, same rolls). "
                "Set datasets.signal to the execution dataset, or use signal.input="
                "ratio_adjusted with the ratio-adjusted series"
            )
            raise ConfigurationError(msg)
        if self.strategy.spec is not None:
            if self.contracts is None:
                msg = (
                    "contracts is required: a strategy spec decides the side (+1 long, -1 short) "
                    "and contracts sizes it. Pass contracts: 1 (or the size you want)"
                )
                raise ConfigurationError(msg)
        elif self.contracts is not None:
            msg = (
                f"contracts={self.contracts} is forbidden with an entrypoint: a "
                "FuturesSignalFunction returns signed whole contracts as its score, so it "
                "already decides the size. Remove contracts"
            )
            raise ConfigurationError(msg)
        # build every derived object now, so its own checks refuse a bad combination at load
        self.cost_schedule()
        self.execution_policy()
        self.session_policy()
        return self

    def cost_schedule(self) -> CostSchedule:
        """The simulator's cost schedule (no session overrides: one schedule for the run)."""
        costs = self.costs
        return CostSchedule(
            commission=costs.commission,
            exchange_fee=costs.exchange_fee,
            clearing_fee=costs.clearing_fee,
            regulatory_fee=costs.regulatory_fee,
            spread_ticks=costs.spread_ticks,
            slippage_ticks=costs.slippage_ticks,
            spread_calibrated=costs.spread_calibrated,
            slippage_calibrated=costs.slippage_calibrated,
            prices_include_spread=costs.prices_include_spread,
        )

    def execution_policy(self) -> ExecutionPolicy:
        """The simulator's execution policy (brackets in whole ticks, ``bar_seconds`` = 60)."""
        policy = self.execution
        return ExecutionPolicy(
            fill=policy.fill,
            stop_ticks=policy.stop_ticks,
            target_ticks=policy.target_ticks,
            target_fill_through_ticks=policy.target_fill_through_ticks,
            reentry=policy.reentry,
            roll_execution=policy.roll_execution,
            strict=policy.strict,
            bar_seconds=BAR_SECONDS,
        )

    def session_policy(self) -> FuturesSessionPolicy:
        """The bridge's Globex session rules."""
        session = self.session
        return FuturesSessionPolicy(
            flat_by_close=session.flat_by_close,
            exit_at=session.exit_at,
            entry_window=session.entry_window,
            allow_unverified_sessions=session.allow_unverified_sessions,
        )


def _resolved_spec(raw: dict[str, object], base: Path) -> dict[str, object]:
    """``raw`` with a ``strategy.spec`` path replaced by the spec file's content."""
    strategy = raw.get("strategy")
    if not isinstance(strategy, dict) or not isinstance(strategy.get("spec"), str):
        return raw
    path = Path(strategy["spec"])
    if not path.is_absolute():
        path = base / path
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        msg = (
            f"strategy.spec {strategy['spec']!r} does not exist (looked at {path}): a spec path "
            "is relative to the config file's directory; check the path"
        )
        raise ConfigurationError(msg) from None
    except OSError as exc:
        msg = f"cannot read strategy.spec {path}: {exc}"
        raise ConfigurationError(msg) from exc
    try:
        loaded = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        msg = f"strategy.spec {path} is not valid YAML: {exc}"
        raise ConfigurationError(msg) from exc
    if not isinstance(loaded, dict):
        msg = f"strategy.spec {path} did not parse to a mapping (a spec is a mapping)"
        raise ConfigurationError(msg)
    resolved = dict(raw)
    resolved["strategy"] = {**strategy, "spec": loaded}
    return resolved


def _validated(mapping: Mapping[str, object]) -> FuturesRunConfig:
    """``FuturesRunConfig`` from a mapping, with pydantic's errors as a ``ConfigurationError``."""
    try:
        return FuturesRunConfig.model_validate(mapping)
    except ValidationError as exc:
        problems = "; ".join(
            f"{'.'.join(str(part) for part in error['loc']) or '(root)'}: {error['msg']}"
            for error in exc.errors()
        )
        msg = f"the futures run config is invalid: {problems}"
        raise ConfigurationError(msg) from exc


def parse_futures_config(mapping: Mapping[str, object]) -> FuturesRunConfig:
    """Validate an already-parsed config mapping (``strategy.spec`` must be inlined here)."""
    return _validated(mapping)


def load_futures_config(path: Path) -> FuturesRunConfig:
    """Load and validate a futures-run config from YAML.

    A ``strategy.spec`` that is a path is loaded relative to ``path``'s directory and stored as
    the loaded mapping, so the config hash covers the spec's content, not its location.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        msg = f"cannot read the futures run config {path}: {exc}"
        raise ConfigurationError(msg) from exc
    try:
        raw = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        msg = f"the futures run config {path} is not valid YAML: {exc}"
        raise ConfigurationError(msg) from exc
    if not isinstance(raw, dict):
        msg = f"the futures run config {path} did not parse to a mapping"
        raise ConfigurationError(msg)
    return parse_futures_config(_resolved_spec(raw, path.parent))


def futures_config_json_schema() -> dict[str, object]:
    """The JSON Schema of ``FuturesRunConfig``: every field, type, default and description."""
    return FuturesRunConfig.model_json_schema()


def futures_config_hash(config: BaseModel) -> str:
    """SHA-256 of the canonical JSON of the config (``config_hash``): the run's input identity."""
    return config_hash(config)


def canonical_futures_yaml(config: BaseModel) -> str:
    """Deterministic YAML rendering of the config, written as ``config.yaml`` in the run."""
    return canonical_yaml(config)


__all__ = [
    "BAR_SECONDS",
    "FILL_MODES",
    "REENTRY_MODES",
    "ROLL_EXECUTIONS",
    "FuturesCostsConfig",
    "FuturesDatasets",
    "FuturesExecutionConfig",
    "FuturesRunConfig",
    "FuturesRunHeader",
    "FuturesSessionConfig",
    "FuturesSignalConfig",
    "FuturesStrategyConfig",
    "FuturesWindow",
    "canonical_futures_yaml",
    "default_datasets",
    "futures_config_hash",
    "futures_config_json_schema",
    "load_futures_config",
    "parse_futures_config",
]
