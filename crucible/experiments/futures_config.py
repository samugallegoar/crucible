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
- a ``strategy.expression`` (DSL, ADR-0098) is compiled at load, so a type or window error, an
  unknown ``$`` parameter or a score that is not scale invariant surfaces at ``futures check``;
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
import hashlib
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

from crucible.core.canonical import canonical_json
from crucible.core.errors import ConfigurationError
from crucible.data.continuous import calendar_for
from crucible.data.futures_specs import futures_spec
from crucible.dsl.compile import CompiledSignal, compile_expression
from crucible.dsl.evaluate import cs_rank_nodes
from crucible.execution.futures_sim import CostSchedule, ExecutionPolicy
from crucible.experiments.config import canonical_yaml, config_hash
from crucible.experiments.futures_signals import FuturesSessionPolicy, SignalInput
from crucible.strategy_spec.models import parse_spec

if TYPE_CHECKING:
    from collections.abc import Mapping

BAR_SECONDS = 60
"""The bar length of the futures datasets this config names (one-minute bars, the C3 datasets).
The length a run actually simulates at is ``fidelity.bar_seconds`` (60 x the resolution): the
store's datasets stay one-minute and a coarser resolution resamples them causally
(``crucible.data.resample``)."""

FIDELITY_TABLE_VERSION = "1"
"""Version of the fidelity table (the presets below): bump it when a preset's mapping changes, so
an artifact that recorded a version is never read with different meanings")."""

FIDELITY_RESOLUTIONS = ("1m", "5m", "15m")
"""The bar resolutions a run can read: the source bars, or a causal aggregate of them."""

FIDELITY_COST_DETAIL = ("full", "commission_only")
"""How much of the cost model the run charges: every cost, or commission and fees only."""

FIDELITY_PRESETS: dict[str, tuple[str, str]] = {
    "screen": ("15m", "commission_only"),
    "standard": ("5m", "full"),
    "full": ("1m", "full"),
}
"""The named fidelity levels, as ``(resolution, cost_detail)``. ``screen`` is the cheap first
pass (coarse bars, spread and slippage off), ``standard`` the working level, ``full`` the source
resolution with every cost."""

FILL_MODES = ("next_eligible_bar_open", "signal_bar_close")
REENTRY_MODES = ("require_signal_reset", "allow_immediate")
ROLL_EXECUTIONS = ("causal", "reference_approximation")
CANDIDATE_PREFIX = "CND-"
"""Prefix of a candidate id (ADR-0103 decision 4)."""
CANDIDATE_ID_HEX = 16
"""Hex digits of the SHA-256 kept in a candidate id (64 bits, like every other id here)."""
ANNUALIZATION_PERIODS_PER_YEAR = 252
"""Trade dates a year, for the PRESENTATION-ONLY annualization of a daily Sharpe (ADR-0103)."""
MICRO = 1_000_000
"""Micro-dollars per dollar: money is kept in exact micro-dollars (6 decimals)."""


class _FrozenModel(BaseModel):
    """Frozen, and a typo in a config is an error rather than a silently ignored knob."""

    model_config = ConfigDict(frozen=True, extra="forbid")


def _parameter_bindings(params: Mapping[str, object]) -> dict[str, int | float]:
    """``params`` as the numeric bindings of an expression's ``$`` parameters."""
    out: dict[str, int | float] = {}
    for name, value in params.items():
        if isinstance(value, bool) or not isinstance(value, int | float):
            msg = (
                f"strategy.params[{name!r}] = {value!r} is not a number: an expression's `$` "
                "parameters are bound to int or float values (no strings, lists or booleans). "
                f"Bind ${name} to a number, e.g. {name}: 20"
            )
            raise ConfigurationError(msg)
        out[name] = value
    return out


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
    """The evaluation window as Globex TRADE DATES, inclusive on both ends.

    ``warmup_trade_dates`` lets the run READ the trade dates immediately before ``start`` to
    compute the signal (ADR-0101 decision 1). Those bars decide the target of the first window bar
    and nothing else: they produce no fill, no mark, no ledger row, no position and no roll, so the
    simulated window is exactly ``[start, end]`` whether the warm-up is 0 or 30. The warm-up is
    past data, so it introduces no lookahead; with ``0`` the run is exactly the one of ADR-0095.
    """

    start: dt.date = Field(description="First trade date whose bars are simulated.")
    end: dt.date = Field(description="Last trade date whose bars are simulated, inclusive.")
    warmup_trade_dates: int = Field(
        default=0,
        ge=0,
        description="Globex trade dates immediately before start whose bars are read to "
        "compute the signal: they are dropped before the simulator (no fill, mark, ledger row, "
        "position or roll), so the simulated window stays [start, end]. A run whose warm-up does "
        "not cover the expression's own warm-up is refused. With 0 the run is unchanged.",
    )

    @field_validator("warmup_trade_dates", mode="before")
    @classmethod
    def _warmup_is_whole(cls, value: object) -> object:
        return _no_bool(value, "window.warmup_trade_dates")

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
    """What decides the position: a spec sized by ``contracts``, a function, or a DSL expression."""

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
    expression: str | None = Field(
        default=None,
        min_length=1,
        description="A DSL expression (ADR-0096/0098): a condition (true is long) or a numeric "
        "score whose sign sets the side, sized by contracts. Its `$` parameters are bound from "
        "params, and it is compiled at load, so a bad expression surfaces at `futures check`.",
    )
    params: dict[str, object] = Field(
        default_factory=dict,
        description="Keyword parameters passed to the entrypoint function on every call, or the "
        "bindings of an expression's `$` parameters (by name, without the `$`).",
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
        given = [
            name
            for name, value in (
                ("spec", self.spec),
                ("entrypoint", self.entrypoint),
                ("expression", self.expression),
            )
            if value is not None
        ]
        if len(given) != 1:
            sources = ", ".join(given) if given else "none"
            msg = (
                "strategy needs exactly one of spec (a StrategySpec mapping), entrypoint "
                f"(module.path:function) or expression (a DSL expression); got {sources}. Keep "
                "one of them and remove the others"
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

    def compiled_signal(self, signal_input: SignalInput) -> CompiledSignal:
        """The DSL expression compiled for ``signal_input``: its ids, warm-up and features.

        Refuses an expression that does not compile, a parameter name the expression does not
        declare, a value of the wrong type or outside its bounds (``ExpressionError``), and a
        score that is not scale invariant on ratio-adjusted input (ADR-0086, ADR-0098).
        """
        if self.expression is None:
            msg = (
                "strategy.compiled_signal() needs strategy.expression; this config decides with "
                f"a {'spec' if self.spec is not None else 'entrypoint'}"
            )
            raise ConfigurationError(msg)
        return compile_expression(
            self.expression,
            params=_parameter_bindings(self.params),
            signal_input=signal_input,
        )


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
    other_fee: Decimal = Field(
        default=Decimal(0), ge=0, description="Any other per-side charge, USD."
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


class FuturesStatisticsConfig(_FrozenModel):
    """Which statistics a run reports and how their intervals are resampled (ADR-0103, C6a).

    The statistics themselves are not optional -- a sealed futures run always reports its
    per-period Sharpe, the annualized one, the mean daily return, PSR, DSR and (for a DSL
    expression) the information coefficient -- but the three knobs that decide the intervals are:
    the IC horizon, the number of bootstrap resamples and the confidence level. They are explicit
    so a report can be reproduced from its own config, and they join the config hash, so two runs
    that disagree about them are two runs.
    """

    ic_horizon_bars: int = Field(
        default=1,
        ge=1,
        description="Forward horizon, in BARS of the run's resolution, of the information "
        "coefficient: IC pairs a bar's score with the close-to-close return over the next N bars "
        "of the same session and contract.",
    )
    resamples: int = Field(
        default=1000,
        ge=200,
        description="Bootstrap resamples behind every confidence interval (>= 200: fewer cannot "
        "resolve a 95% percentile interval).",
    )
    confidence: float = Field(
        default=0.95,
        ge=0.5,
        le=0.999,
        description="Two-sided confidence level of the percentile intervals (0.5..0.999).",
    )

    @field_validator("ic_horizon_bars", "resamples", mode="before")
    @classmethod
    def _whole(cls, value: object) -> object:
        return _no_bool(value, "statistics")


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


class FuturesFidelityConfig(_FrozenModel):
    """How finely and how expensively a run reads its series (Fathom C5a).

    ``resolution`` is the bar length the run simulates: ``1m`` is the stored series itself, ``5m``
    and ``15m`` are causal aggregates of it (``crucible.data.resample``: a bucket never spans the
    maintenance break or a session boundary, and a bar is knowable when its last one-minute
    constituent is). ``cost_detail`` is how much of the cost model is charged: ``full`` charges
    spread and slippage as configured, ``commission_only`` charges commission and fees and zeroes
    both tick costs, which is OPTIMISTIC and is recorded as an approximation in the manifest.

    ``preset`` fills both fields from :data:`FIDELITY_PRESETS`; an explicit field that contradicts
    the preset it was given with is refused rather than silently overridden.
    """

    resolution: Literal["1m", "5m", "15m"] = Field(
        default="1m",
        description="Bar length the run simulates: 1m (the stored series), or 5m/15m, a causal "
        "aggregate of it. The raw per-contract bars and the rolls stay one-minute.",
    )
    cost_detail: Literal["full", "commission_only"] = Field(
        default="full",
        description="full: every configured cost (commission, fees, spread, slippage). "
        "commission_only: commission and fees only, spread and slippage zeroed (OPTIMISTIC, "
        "recorded as an approximation).",
    )
    preset: Literal["screen", "standard", "full"] | None = Field(
        default=None,
        description="A named fidelity level: screen = 15m + commission_only, standard = 5m + "
        "full, full = 1m + full. An explicit resolution or cost_detail that contradicts it is "
        "refused.",
    )

    @model_validator(mode="before")
    @classmethod
    def _apply_preset(cls, data: object) -> object:
        """Fill the fields the preset decides, refusing an explicit value that contradicts it."""
        if not isinstance(data, dict) or data.get("preset") is None:
            return data
        preset = data["preset"]
        level = FIDELITY_PRESETS.get(str(preset))
        if level is None:
            msg = (
                f"fidelity.preset {preset!r} is not a fidelity level; use one of "
                f"{list(FIDELITY_PRESETS)} (screen = 15m + commission_only, standard = 5m + "
                "full, full = 1m + full)"
            )
            raise ConfigurationError(msg)
        filled = dict(data)
        for name, value in zip(("resolution", "cost_detail"), level, strict=True):
            given = filled.get(name)
            if given is not None and given != value:
                msg = (
                    f"fidelity.preset {preset!r} is {value} for {name}, but {name} is given as "
                    f"{given!r}: a preset and a contradicting field cannot both stand. Drop the "
                    f"preset or change {name} to {value!r}"
                )
                raise ConfigurationError(msg)
            filled[name] = value
        return filled

    @property
    def minutes(self) -> int:
        """The resolution in minutes: 1, 5 or 15."""
        return {"1m": 1, "5m": 5, "15m": 15}[self.resolution]

    @property
    def bar_seconds(self) -> int:
        """The bar length the run simulates at, in seconds (60 x ``minutes``)."""
        return BAR_SECONDS * self.minutes

    @property
    def resampled(self) -> bool:
        """Whether the run aggregates the stored one-minute series before simulating it."""
        return self.minutes != 1

    def record(
        self, *, dropped_off_schedule: int = 0, partial_buckets: int = 0
    ) -> dict[str, object]:
        """The manifest's ``fidelity`` block: the level, whether it resampled and what that cost."""
        return {
            "resolution": self.resolution,
            "cost_detail": self.cost_detail,
            "preset": self.preset,
            "table_version": FIDELITY_TABLE_VERSION,
            "resampled": self.resampled,
            "dropped_off_schedule": dropped_off_schedule,
            "partial_buckets": partial_buckets,
        }


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
        description="Contracts per side a SPEC or an EXPRESSION is sized at (both decide the "
        "side; the size is this many contracts). Forbidden for an entrypoint, whose score is "
        "already signed whole contracts.",
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
    fidelity: FuturesFidelityConfig = Field(
        default_factory=FuturesFidelityConfig,
        description="How finely and how expensively the run reads the series (1m/5m/15m bars, "
        "full or commission-only costs).",
    )
    session: FuturesSessionConfig = Field(
        default_factory=FuturesSessionConfig, description="Globex session rules."
    )
    statistics: FuturesStatisticsConfig = Field(
        default_factory=FuturesStatisticsConfig,
        description="IC horizon, bootstrap resamples and confidence level of the run's "
        "statistics (C6a, ADR-0103). They join the config hash, so adding this section renamed "
        "every futures run id; results do not change.",
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
        if self.strategy.expression is not None:
            # compile at load: a type, window, parameter or scale error is a config error here
            signal = self.strategy.compiled_signal(self.signal.input)
            if cs_rank_nodes(signal.expression):
                msg = (
                    "cs_rank ranks across instruments; a futures run trades one root: the "
                    f"compiled expression {signal.canonical_text!r} cannot be evaluated here. "
                    "Evaluate it on a panel from the library (crucible.dsl.evaluate.evaluate), "
                    "or drop cs_rank from the expression"
                )
                raise ConfigurationError(msg)
        if self.strategy.spec is not None or self.strategy.expression is not None:
            if self.contracts is None:
                what = "spec" if self.strategy.spec is not None else "expression"
                msg = (
                    f"contracts is required: a strategy {what} decides the side (+1 long, "
                    "-1 short) and contracts sizes it. Pass contracts: 1 (or the size you want)"
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
        if self.fidelity.cost_detail == "commission_only":
            explicit = [
                name
                for name in ("spread_ticks", "slippage_ticks")
                if name in self.costs.model_fields_set and getattr(self.costs, name) != 0
            ]
            if explicit:
                fields = ", ".join(f"costs.{name}" for name in explicit)
                msg = (
                    f"fidelity.cost_detail=commission_only charges no tick cost, but {fields} "
                    "sets a non-zero value: the run would silently ignore what the config says. "
                    "Remove it, set it to 0, or use cost_detail=full"
                )
                raise ConfigurationError(msg)
        self.cost_schedule()
        self.execution_policy()
        self.session_policy()
        return self

    def cost_schedule(self) -> CostSchedule:
        """The simulator's cost schedule (no session overrides: one schedule for the run).

        ``fidelity.cost_detail=commission_only`` zeroes the spread and the slippage ticks and keeps
        commission and fees: the run is then OPTIMISTIC about the cost of trading and records the
        approximation in its manifest (``_approximations``).
        """
        costs = self.costs
        commission_only = self.fidelity.cost_detail == "commission_only"
        return CostSchedule(
            commission=costs.commission,
            exchange_fee=costs.exchange_fee,
            clearing_fee=costs.clearing_fee,
            regulatory_fee=costs.regulatory_fee,
            other_fee=costs.other_fee,
            spread_ticks=Decimal(0) if commission_only else costs.spread_ticks,
            slippage_ticks=Decimal(0) if commission_only else costs.slippage_ticks,
            spread_calibrated=costs.spread_calibrated,
            slippage_calibrated=costs.slippage_calibrated,
            prices_include_spread=costs.prices_include_spread,
        )

    def execution_policy(self) -> ExecutionPolicy:
        """The simulator's execution policy (brackets in whole ticks, ``bar_seconds`` from
        ``fidelity``)."""
        policy = self.execution
        return ExecutionPolicy(
            fill=policy.fill,
            stop_ticks=policy.stop_ticks,
            target_ticks=policy.target_ticks,
            target_fill_through_ticks=policy.target_fill_through_ticks,
            reentry=policy.reentry,
            roll_execution=policy.roll_execution,
            strict=policy.strict,
            bar_seconds=self.fidelity.bar_seconds,
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
    """Deterministic YAML rendering of the config, written as ``config.yaml`` in the run.

    The sealed ``config.yaml`` is the artifact's provenance AND an input: every reader of a
    finished run parses it back (a comparison member, its comparison key, the effective-trials
    report). It must therefore RELOAD into an equal model, which one combination would otherwise
    not do: under ``fidelity.cost_detail == "commission_only"`` the validator refuses an
    EXPLICITLY set non-zero ``costs.spread_ticks``/``costs.slippage_ticks`` (the run would
    silently ignore what the config says), and a full model dump writes those DEFAULTS explicitly,
    so the dump refused its own output. They are omitted here when they were not set: the reload
    then gives the same model with the same defaults, and a tick the caller DID set (a zero, or a
    non-zero one under ``full`` costs) is written as usual.

    ``config_hash`` -- and therefore the run id -- is computed from the MODEL
    (``futures_config_hash``), never from this text, so what is omitted here changes no identity; it
    changes the bytes of
    ``config.yaml`` for a ``commission_only`` run and nothing else (``docs/COMPATIBILITY.md`` §3).
    """
    if isinstance(config, FuturesRunConfig) and config.fidelity.cost_detail == "commission_only":
        raw = config.model_dump(mode="json")
        costs = raw.get("costs")
        if isinstance(costs, dict):
            explicit = config.costs.model_fields_set
            raw["costs"] = {
                str(name): value
                for name, value in costs.items()
                if name not in ("spread_ticks", "slippage_ticks") or name in explicit
            }
        return yaml.safe_dump(raw, sort_keys=True, default_flow_style=False)
    return canonical_yaml(config)


def candidate_id(config: FuturesRunConfig) -> str:
    """``CND-<16 hex>``: the identity of the CANDIDATE ``config`` evaluates (ADR-0103 decision 4).

    Two configs share a candidate id exactly when they evaluate the same thing under the same
    conditions, so a family can count distinct candidates instead of distinct run directories:

    - the strategy: a DSL expression contributes its canonical ``structure_id`` and
      ``parameterization_id`` (so a renamed parameter or a re-spelled, canonically equal
      expression is the same candidate, and a changed window or value is not); a spec its
      canonical dump; an entrypoint its dotted path and its ``params``;
    - the size (``contracts``), the root and the four dataset ids;
    - the execution and costs sections;
    - the fidelity's EFFECTIVE level (resolution, cost detail and the preset table's version, so
      ``preset: screen`` and the equivalent explicit fields are one candidate);
    - the session and signal sections.

    It excludes the window, the warm-up, ``run.name``, ``run.family`` and the ``statistics``
    section: one candidate evaluated on several windows or reported with another bootstrap is
    still one candidate, which is what ``total_trials`` has to count. ``capital`` is excluded too:
    it scales the P&L, not the strategy, and the daily returns are measured against it.
    """
    strategy: dict[str, object]
    if config.strategy.expression is not None:
        compiled = config.strategy.compiled_signal(config.signal.input)
        strategy = {
            "kind": "dsl",
            "structure_id": compiled.structure_id,
            "parameterization_id": compiled.parameterization_id,
            "contracts": config.contracts,
        }
    elif config.strategy.spec is not None:
        strategy = {
            "kind": "spec",
            "spec": parse_spec(config.strategy.spec).model_dump(mode="json"),
            "contracts": config.contracts,
        }
    else:
        strategy = {
            "kind": "entrypoint",
            "entrypoint": config.strategy.entrypoint,
            "params": config.strategy.params,
        }
    basis = {
        "root": config.root,
        "datasets": {
            "execution": config.datasets.execution,
            "signal": config.datasets.signal,
            "rolls": config.datasets.rolls,
            "raw": config.datasets.raw,
        },
        "strategy": strategy,
        "costs": config.costs.model_dump(mode="json"),
        "execution": config.execution.model_dump(mode="json"),
        "fidelity": {
            "resolution": config.fidelity.resolution,
            "cost_detail": config.fidelity.cost_detail,
            "table_version": FIDELITY_TABLE_VERSION,
        },
        "session": config.session.model_dump(mode="json"),
        "signal": config.signal.model_dump(mode="json"),
    }
    digest = hashlib.sha256(canonical_json(basis).encode("utf-8")).hexdigest()[:CANDIDATE_ID_HEX]
    return CANDIDATE_PREFIX + digest


__all__ = [
    "ANNUALIZATION_PERIODS_PER_YEAR",
    "BAR_SECONDS",
    "CANDIDATE_ID_HEX",
    "CANDIDATE_PREFIX",
    "FIDELITY_COST_DETAIL",
    "FIDELITY_PRESETS",
    "FIDELITY_RESOLUTIONS",
    "FIDELITY_TABLE_VERSION",
    "FILL_MODES",
    "REENTRY_MODES",
    "ROLL_EXECUTIONS",
    "FuturesCostsConfig",
    "FuturesDatasets",
    "FuturesExecutionConfig",
    "FuturesFidelityConfig",
    "FuturesRunConfig",
    "FuturesRunHeader",
    "FuturesSessionConfig",
    "FuturesSignalConfig",
    "FuturesStatisticsConfig",
    "FuturesStrategyConfig",
    "FuturesWindow",
    "candidate_id",
    "canonical_futures_yaml",
    "default_datasets",
    "futures_config_hash",
    "futures_config_json_schema",
    "load_futures_config",
    "parse_futures_config",
]
