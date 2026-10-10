"""The import spec: every assumption about a source is declared here (ADR-0052).

Risky choices have no default: ``price_basis`` (raw vs adjusted) must be declared,
and OHLC repair is opt-in. Unknown keys are refused.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from crucible.core.errors import ConfigurationError

_INTERVAL = re.compile(r"^[1-9][0-9]*(m|h|d|w|mo)$")


class _Frozen(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ColumnsSpec(_Frozen):
    timestamp: str
    open: str
    high: str
    low: str
    close: str
    volume: str | None = None


class SymbolSpec(_Frozen):
    column: str | None = None
    from_filename: bool = False
    fixed: str | None = None

    @model_validator(mode="after")
    def _exactly_one(self) -> SymbolSpec:
        chosen = [self.column is not None, self.from_filename, self.fixed is not None]
        if sum(chosen) != 1:
            msg = "symbol needs exactly one of column, from_filename, fixed"
            raise ValueError(msg)
        return self


class TimestampSpec(_Frozen):
    format: str
    timezone: str = "UTC"
    meaning: Literal["bar_open", "bar_close", "session_close"]
    interval: str | None = None
    calendar: str | None = None

    @model_validator(mode="after")
    def _meaning_options(self) -> TimestampSpec:
        if ("%z" in self.format or "%Z" in self.format) and self.timezone != "UTC":
            msg = (
                "a format with %z/%Z already carries the offset; set timezone: UTC (re-labelling "
                "an absolute time with another zone would shift it)"
            )
            raise ValueError(msg)
        if self.meaning == "bar_open":
            if self.interval is None or not _INTERVAL.match(self.interval):
                msg = "meaning bar_open needs an interval such as 15m, 1h, 1d, 1w or 1mo"
                raise ValueError(msg)
            if self.calendar is not None:
                msg = "calendar applies to session_close only (use quality_calendar)"
                raise ValueError(msg)
        elif self.meaning == "session_close":
            if self.calendar is None:
                msg = "meaning session_close needs a calendar (an exchange_calendars name)"
                raise ValueError(msg)
            if self.calendar == "24/7":
                msg = "session_close is not defined for the 24/7 calendar; use bar_open with 1d"
                raise ValueError(msg)
            if self.interval is not None:
                msg = "interval applies to bar_open only"
                raise ValueError(msg)
        elif self.interval is not None or self.calendar is not None:
            msg = "meaning bar_close takes neither interval nor calendar"
            raise ValueError(msg)
        return self


class RowsSpec(_Frozen):
    on_incomplete: Literal["drop", "refuse"] = "drop"
    ohlc_repair: Literal["refuse", "clamp"] = "refuse"
    max_dropped_fraction: float = Field(default=0.05, ge=0.0, le=1.0)


class OhlcvSpec(_Frozen):
    kind: Literal["ohlcv_csv"]
    dataset: str = Field(min_length=1)
    input: str = Field(min_length=1)
    price_basis: Literal["raw", "adjusted"]
    delimiter: str = Field(default=",", min_length=1, max_length=1)
    columns: ColumnsSpec
    symbol: SymbolSpec
    timestamp: TimestampSpec
    feed_latency_s: int = Field(default=0, ge=0)
    rows: RowsSpec = RowsSpec()
    quality_calendar: str | None = None
    quality_skip: tuple[str, ...] = ()
    quality_skip_reason: str = ""


class PolymarketSpec(_Frozen):
    kind: Literal["polymarket_csv", "polymarket_parquet"]
    dataset: str = Field(min_length=1)
    input: str = Field(min_length=1)
    outcomes: str | None = None
    bar_seconds: int = Field(default=1, ge=1)
    window_seconds: int = Field(default=300, ge=1)
    settlement_floor: float = Field(default=0.001, gt=0.0, lt=1.0)
    spot_source: Literal["binance", "coinbase", "kraken"] = "binance"
    spot_symbol: str = Field(default="BTCUSD", min_length=1)
    max_dropped_fraction: float = Field(default=0.30, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def _parquet_needs_outcomes(self) -> PolymarketSpec:
        if self.kind == "polymarket_parquet" and self.outcomes is None:
            msg = "kind polymarket_parquet needs an outcomes file (winner per contract)"
            raise ValueError(msg)
        return self


_MODELS: dict[str, type[OhlcvSpec] | type[PolymarketSpec]] = {
    "ohlcv_csv": OhlcvSpec,
    "polymarket_csv": PolymarketSpec,
    "polymarket_parquet": PolymarketSpec,
}


def load_spec(path: Path) -> OhlcvSpec | PolymarketSpec:
    """Reads and validates an import spec; every problem is a ``ConfigurationError``."""
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        msg = f"import spec {path} does not exist"
        raise ConfigurationError(msg) from None
    except (UnicodeDecodeError, yaml.YAMLError) as exc:
        msg = f"import spec {path} is not valid UTF-8 YAML: {exc}"
        raise ConfigurationError(msg) from exc
    if not isinstance(raw, dict):
        msg = f"import spec {path} must be a YAML mapping"
        raise ConfigurationError(msg)
    model = _MODELS.get(str(raw.get("kind")))
    if model is None:
        msg = (
            f"import spec {path}: unknown kind {raw.get('kind')!r}; use ohlcv_csv, "
            "polymarket_csv or polymarket_parquet"
        )
        raise ConfigurationError(msg)
    try:
        return model.model_validate(raw)
    except ValidationError as exc:
        msg = f"import spec {path} is invalid: {exc}"
        raise ConfigurationError(msg) from exc
