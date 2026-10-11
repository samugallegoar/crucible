"""The strategy spec: a declarative, versioned description of a trading rule (ADR-0067).

A spec is data (YAML or JSON), never code. It is validated here, compiled to a vectorized signal
function (``compile.py``) and from there runs on the vectorized engine and, unchanged, through the
promotion path on the event-driven engine. Whatever is ambiguous is refused with a message that
says what is wrong, where in the spec, and what to write instead (AGENTS.md section 5).

Example::

    spec_version: 1
    name: SMA 10/30 crossover
    direction: long_only
    entry: {long: "sma(10) crosses_above sma(30)"}
    exit:  {long: "sma(10) crosses_below sma(30)"}
    sizing: {type: all_in}
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from crucible.core.errors import ConfigurationError
from crucible.strategy_spec.indicators import PRICE_FIELDS, resolve_indicator

SPEC_VERSION = 1

COMPARATORS = (">=", "<=", ">", "<", "crosses_above", "crosses_below")

# ------------------------------------------------------------------ the condition language


@dataclass(frozen=True, slots=True)
class Num:
    """A literal number."""

    value: float


@dataclass(frozen=True, slots=True)
class BarField:
    """A bar field read directly (``close``)."""

    name: str


@dataclass(frozen=True, slots=True)
class Call:
    """An indicator call, already validated: ``(period, field, k)`` are final."""

    name: str
    period: int
    field: str
    k: float


@dataclass(frozen=True, slots=True)
class TimeOfDay:
    """``time``: when the bar ends, in minutes after midnight, exchange local time (ADR-0074)."""


@dataclass(frozen=True, slots=True)
class ClockTime:
    """A clock literal (``10:30``), in minutes after midnight; compared with ``time`` only."""

    minutes: int
    text: str


Operand = Num | BarField | Call | TimeOfDay | ClockTime


@dataclass(frozen=True, slots=True)
class Comparison:
    left: Operand
    op: str
    right: Operand


@dataclass(frozen=True, slots=True)
class Always:
    """The condition that is true on every bar (``always``): buy and hold."""


@dataclass(frozen=True, slots=True)
class Group:
    kind: Literal["all", "any"]
    items: tuple[Node, ...]


Node = Comparison | Always | Group

_CALL = re.compile(r"^([a-z_][a-z0-9_]*)\s*\(([^()]*)\)$")
_CLOCK = re.compile(r"^([01][0-9]|2[0-3]):([0-5][0-9])$")
_OPERATOR = re.compile(r"\s*(>=|<=|>|<)\s*|\s+(crosses[_ ]above|crosses[_ ]below)\s+")


def _parse_operand(text: str, where: str) -> Operand:
    text = text.strip()
    if not text:
        msg = f"{where}: an operand is missing; write e.g. `sma(10) > sma(30)`"
        raise ConfigurationError(msg)
    try:
        return Num(float(text))
    except ValueError:
        pass
    if text == "time":
        return TimeOfDay()
    clock = _CLOCK.match(text)
    if clock is not None:
        return ClockTime(int(clock.group(1)) * 60 + int(clock.group(2)), text)
    if text in PRICE_FIELDS:
        return BarField(text)
    match = _CALL.match(text)
    if match is None:
        msg = (
            f"{where}: cannot read {text!r}. An operand is a number (30), a bar field "
            f"({', '.join(PRICE_FIELDS)}), an indicator call such as sma(10), rsi(14), "
            "roc(20), highest(20), bb_lower(20, 2), or on intraday bars `time` compared with a "
            "clock time such as 10:30"
        )
        raise ConfigurationError(msg)
    raw_args = [a.strip() for a in match.group(2).split(",") if a.strip()]
    args: list[float | str] = []
    for arg in raw_args:
        try:
            args.append(float(arg))
        except ValueError:
            args.append(arg)
    period, field, k = resolve_indicator(match.group(1), tuple(args), where)
    return Call(match.group(1), period, field, k)


def parse_condition_text(text: str, where: str) -> Node:
    """Parses ``"<operand> <comparator> <operand>"`` (or ``"always"``)."""
    stripped = text.strip()
    if stripped == "always":
        return Always()
    parts = _OPERATOR.split(stripped)
    # split with two groups yields [left, op1, op2, right, ...]; exactly one comparator allowed
    operators = [p for i, p in enumerate(parts) if i % 3 in (1, 2) and p]
    operands = [p for i, p in enumerate(parts) if i % 3 == 0]
    if len(operators) != 1 or len(operands) != 2:
        msg = (
            f"{where}: {text!r} is not a single comparison. Write exactly one of "
            f"{', '.join(COMPARATORS)} between two operands, e.g. `sma(10) crosses_above "
            "sma(30)` or `rsi(14) < 30`; combine several with {all: [...]} or {any: [...]}"
        )
        raise ConfigurationError(msg)
    op = operators[0].replace(" ", "_")
    left = _parse_operand(operands[0], where)
    right = _parse_operand(operands[1], where)
    timed = [isinstance(o, TimeOfDay | ClockTime) for o in (left, right)]
    if any(timed):
        kinds = {type(left), type(right)}
        if kinds != {TimeOfDay, ClockTime} or op not in (">", ">=", "<", "<="):
            msg = (
                f"{where}: {text!r}: `time` (when the bar ends, exchange time) is compared with a "
                "clock time using >, >=, < or <=, e.g. `time >= 10:30` or `time < 15:00`; it "
                "cannot cross, and a clock time cannot be compared with a price"
            )
            raise ConfigurationError(msg)
        return Comparison(left, op, right)
    if isinstance(left, Num) and isinstance(right, Num):
        msg = f"{where}: {text!r} compares two constants, which is always the same answer"
        raise ConfigurationError(msg)
    if (
        op in ("crosses_above", "crosses_below")
        and isinstance(right, Num)
        and isinstance(left, Num)
    ):
        msg = f"{where}: a crossing needs a series on at least one side"
        raise ConfigurationError(msg)
    return Comparison(left, op, right)


# ------------------------------------------------------------------ pydantic models


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class AllOf(_Frozen):
    """True when every item is true."""

    all: Annotated[list[Condition], Field(min_length=1)]


class AnyOf(_Frozen):
    """True when at least one item is true."""

    any: Annotated[list[Condition], Field(min_length=1)]


Condition = str | AllOf | AnyOf
AllOf.model_rebuild()
AnyOf.model_rebuild()


def parse_condition(condition: Condition, where: str) -> Node:
    """Condition (text or group) to its validated AST."""
    if isinstance(condition, str):
        return parse_condition_text(condition, where)
    if isinstance(condition, AllOf):
        return Group(
            "all",
            tuple(
                parse_condition(item, f"{where}.all[{i}]") for i, item in enumerate(condition.all)
            ),
        )
    return Group(
        "any",
        tuple(parse_condition(item, f"{where}.any[{i}]") for i, item in enumerate(condition.any)),
    )


class Rules(_Frozen):
    """A condition per side. ``long``/``short`` are conditions: a string such as
    ``"sma(10) crosses_above sma(30)"`` or a group ``{all: [...]}`` / ``{any: [...]}``."""

    long: Condition | None = None
    short: Condition | None = None


class Sizing(_Frozen):
    """How much of the capital a position uses.

    ``all_in``: the whole capital (split equally over the symbols). ``fixed_fraction``: that
    fraction of it (``fraction`` between 0 and 1); the rest stays in cash."""

    type: Literal["all_in", "fixed_fraction"] = "all_in"
    fraction: float | None = Field(default=None, gt=0.0, le=1.0)

    @model_validator(mode="after")
    def _fraction_matches_type(self) -> Sizing:
        if self.type == "fixed_fraction" and self.fraction is None:
            msg = (
                "sizing.type is fixed_fraction but sizing.fraction is missing; "
                "add e.g. fraction: 0.5"
            )
            raise ConfigurationError(msg)
        if self.type == "all_in" and self.fraction is not None:
            msg = (
                "sizing.fraction is set but sizing.type is all_in; use type: fixed_fraction or "
                "remove fraction"
            )
            raise ConfigurationError(msg)
        return self

    @property
    def weight(self) -> float:
        return 1.0 if self.type == "all_in" else float(self.fraction or 0.0)


class RiskRules(_Frozen):
    """Optional exits that do not depend on the indicators.

    Percentages are in percent (``stop_loss_pct: 5`` is 5 %), measured from the closing price of
    the bar the position was entered on, and checked on each later close: a daily-bar backtest
    cannot see an intrabar stop, so a stop can only trigger at a close (and the exit happens at
    the following bar's price). ``max_holding_bars`` closes a position after that many bars."""

    stop_loss_pct: float | None = Field(default=None, gt=0.0, lt=100.0)
    take_profit_pct: float | None = Field(default=None, gt=0.0)
    max_holding_bars: int | None = Field(default=None, ge=1)


_HHMM = re.compile(r"^([01][0-9]|2[0-3]):[0-5][0-9]$")


class EntryWindow(_Frozen):
    """New positions are opened only when the deciding bar **ends** between ``start`` and
    ``end`` (inclusive, ``HH:MM``, the exchange's local time; UTC on a 24/7 calendar). Exits are
    never restricted. On hourly US bars, the first hour is ``{start: "10:30", end: "10:30"}``
    (the 09:30-10:30 bar ends at 10:30) and "not in the last hour" is ``end: "15:00"``."""

    start: str
    end: str

    @model_validator(mode="after")
    def _times(self) -> EntryWindow:
        for name in ("start", "end"):
            value = getattr(self, name)
            if not _HHMM.match(value):
                msg = (
                    f"session.entry_window.{name} {value!r} is not a time; write it as HH:MM in "
                    "the exchange's local time, for example 09:45 or 15:00"
                )
                raise ConfigurationError(msg)
        if self.start > self.end:
            msg = (
                f"session.entry_window starts at {self.start} after it ends at {self.end}; a "
                "window cannot cross midnight. Use start <= end"
            )
            raise ConfigurationError(msg)
        return self


def check_clock_time(value: str, where: str) -> str:
    """``HH:MM`` or a ``ConfigurationError`` naming ``where``."""
    if not _HHMM.match(value):
        msg = (
            f"{where} {value!r} is not a time; write it as HH:MM in the exchange's local time, "
            "for example 09:45 or 15:00"
        )
        raise ConfigurationError(msg)
    return value


class SessionRules(_Frozen):
    """Time-of-day rules for intraday bars (ADR-0073, ADR-0074); refused on daily bars.

    ``flat_by_close``: no position is held from one session into the next. How it is closed is
    ``close_with``:

    - ``next_to_last_bar`` (default): the position is closed by the decision of the session's
      next-to-last bar, so the headline engine exits at that bar's close and the event-driven
      engine (which trades at the next bar) at the last bar's open. No entry on the last two bars.
      Gives up the last bar's move but needs no closing auction.
    - ``market_on_close``: the position is held through the last bar and closed at the session's
      closing price. The headline engine decides flat on the last bar (its fill is that bar's
      close); the event-driven engine sends a market-on-close order on the next-to-last bar, which
      fills at the same close. No entry on the last bar. Needs an exchange with a closing auction
      (refused on 24/7).

    ``exit_at``: ``HH:MM`` exchange time; the position is closed on the first bar ending at or
    after it and nothing is opened again until the session ends. ``entry_window``: see
    ``EntryWindow``."""

    flat_by_close: bool = False
    close_with: Literal["next_to_last_bar", "market_on_close"] = "next_to_last_bar"
    exit_at: str | None = None
    entry_window: EntryWindow | None = None

    @model_validator(mode="after")
    def _coherent(self) -> SessionRules:
        if self.exit_at is not None:
            check_clock_time(self.exit_at, "session.exit_at")
        if self.close_with == "market_on_close" and not self.flat_by_close:
            msg = (
                "session.close_with: market_on_close only applies with flat_by_close: true; set "
                "flat_by_close or remove close_with"
            )
            raise ConfigurationError(msg)
        return self


class StrategySpec(_Frozen):
    """A trading rule as data. See the module docstring for an example."""

    spec_version: Literal[1] = 1
    name: str | None = Field(default=None, max_length=120)
    direction: Literal["long_only", "long_short"] = "long_only"
    entry: Rules
    exit: Rules = Rules()
    sizing: Sizing = Sizing()
    risk: RiskRules = RiskRules()
    session: SessionRules | None = None

    @model_validator(mode="after")
    def _coherent(self) -> StrategySpec:
        check_spec(self)
        return self


def _is_always(condition: Condition | None) -> bool:
    return isinstance(condition, str) and condition.strip() == "always"


def check_spec(spec: StrategySpec) -> None:
    """Refuses incoherent specs: sides that contradict the direction, positions that would never
    close, and any condition that does not parse."""
    if spec.direction == "long_only":
        for block, rules in (("entry", spec.entry), ("exit", spec.exit)):
            if rules.short is not None:
                msg = (
                    f"{block}.short is set but direction is long_only; set direction: long_short "
                    f"to trade the short side, or remove {block}.short"
                )
                raise ConfigurationError(msg)
        if spec.entry.long is None:
            msg = 'entry.long is missing: say when to buy, e.g. entry: {long: "rsi(14) < 30"}'
            raise ConfigurationError(msg)
    elif spec.entry.long is None and spec.entry.short is None:
        msg = "neither entry.long nor entry.short is set; a long_short spec needs at least one"
        raise ConfigurationError(msg)
    for block, rules in (("entry", spec.entry), ("exit", spec.exit)):
        for side in ("long", "short"):
            condition = getattr(rules, side)
            if condition is not None:
                parse_condition(condition, f"{block}.{side}")
    for side in ("long", "short"):
        if getattr(spec.exit, side) is not None and getattr(spec.entry, side) is None:
            msg = (
                f"exit.{side} is set but entry.{side} is not: there is no {side} position to "
                f"close; add entry.{side} or remove exit.{side}"
            )
            raise ConfigurationError(msg)
    flips = spec.entry.long is not None and spec.entry.short is not None
    if spec.session is not None and not (
        spec.session.flat_by_close
        or spec.session.entry_window is not None
        or spec.session.exit_at is not None
    ):
        msg = (
            "session is empty; set session.flat_by_close: true, a session.exit_at time or a "
            "session.entry_window"
        )
        raise ConfigurationError(msg)
    has_generic_exit = (
        spec.risk.stop_loss_pct is not None
        or spec.risk.take_profit_pct is not None
        or spec.risk.max_holding_bars is not None
        or (
            spec.session is not None
            and (spec.session.flat_by_close or spec.session.exit_at is not None)
        )
    )
    for side in ("long", "short"):
        entry = getattr(spec.entry, side)
        if entry is None or _is_always(entry):
            continue
        if getattr(spec.exit, side) is None and not has_generic_exit and not flips:
            msg = (
                f"entry.{side} has no way out: a position would be held forever. Add "
                f"exit.{side} (e.g. the opposite crossing), or a risk.stop_loss_pct / "
                "take_profit_pct / max_holding_bars, or session.flat_by_close. To hold from the "
                "first bar, use "
                "entry: {long: always}"
            )
            raise ConfigurationError(msg)
    if _is_always(spec.entry.long) and (spec.entry.short is not None):
        msg = "entry.long is `always`, so a short entry could never trigger; remove entry.short"
        raise ConfigurationError(msg)


# ------------------------------------------------------------------ loading and errors


def _format_validation_error(exc: ValidationError) -> str:
    lines: list[str] = []
    for error in exc.errors():
        where = ".".join(str(p) for p in error["loc"]) or "(top level)"
        kind = error["type"]
        message = error["msg"]
        if kind == "extra_forbidden":
            message = (
                "unknown field; allowed fields are spec_version, name, direction, entry, exit, "
                "sizing, risk, session (and, inside them: long/short, type/fraction, "
                "stop_loss_pct/take_profit_pct/max_holding_bars, flat_by_close/close_with/"
                "exit_at/entry_window with start/end)"
            )
        elif kind == "missing":
            message = "this field is required"
        elif kind == "literal_error":
            message = f"{message}; check the spelling"
        lines.append(f"  - {where}: {message}")
    return "\n".join(lines)


def parse_spec(raw: object) -> StrategySpec:
    """Validates a mapping (parsed YAML/JSON) into a ``StrategySpec``.

    Raises ``ConfigurationError`` listing every problem with its location in the spec."""
    if isinstance(raw, StrategySpec):
        return raw
    if not isinstance(raw, dict):
        msg = (
            "a strategy spec must be a mapping with at least `entry`, e.g. "
            '{entry: {long: "sma(10) crosses_above sma(30)"}, '
            'exit: {long: "sma(10) crosses_below sma(30)"}}'
        )
        raise ConfigurationError(msg)
    version = raw.get("spec_version", SPEC_VERSION)
    if version != SPEC_VERSION:
        msg = (
            f"spec_version {version!r} is not supported by this Crucible (it reads version "
            f"{SPEC_VERSION}); upgrade Crucible or rewrite the spec for version {SPEC_VERSION}"
        )
        raise ConfigurationError(msg)
    try:
        return StrategySpec.model_validate(raw)
    except ValidationError as exc:
        # (a ConfigurationError raised inside a validator is not a ValueError, so pydantic lets
        # it through unchanged; only field-level problems arrive here)
        msg = f"the strategy spec is invalid:\n{_format_validation_error(exc)}"
        raise ConfigurationError(msg) from exc


def load_spec(source: str | Path | dict[str, Any]) -> StrategySpec:
    """A spec from a YAML/JSON file, a YAML/JSON text or a mapping."""
    if isinstance(source, dict):
        return parse_spec(source)
    if isinstance(source, Path) or (
        "\n" not in source and Path(source).suffix in (".yaml", ".yml", ".json")
    ):
        path = Path(source)
        try:
            text = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            msg = f"strategy spec file {path} does not exist; check the path (absolute is safest)"
            raise ConfigurationError(msg) from None
        except UnicodeDecodeError as exc:
            msg = f"strategy spec file {path} is not UTF-8 text: {exc}"
            raise ConfigurationError(msg) from exc
    else:
        text = str(source)
    try:
        raw = json.loads(text) if text.lstrip().startswith("{") else yaml.safe_load(text)
    except (ValueError, yaml.YAMLError) as exc:
        msg = f"the strategy spec is not valid YAML or JSON: {exc}"
        raise ConfigurationError(msg) from exc
    return parse_spec(raw)


def spec_json_schema() -> dict[str, object]:
    """The JSON Schema of the spec (``crucible schema --kind strategy-spec``)."""
    return StrategySpec.model_json_schema()


def canonical_spec(spec: StrategySpec) -> dict[str, object]:
    """The spec as a plain, key-stable mapping (what a run records and hashes)."""
    return spec.model_dump(mode="json", exclude_none=True)
