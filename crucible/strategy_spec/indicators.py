"""The indicators a strategy spec may use (ADR-0067).

Every indicator is a function of one symbol's bars **up to and including the current bar**: the
value at bar ``t`` is knowable at the close of ``t``. There is no forward-looking indicator and
no centered window. A strategy spec acts on a value at bar ``t`` through the vectorized engine's
mandatory one-bar lag (or the promoted event-driven strategy's next-bar fill), so a spec can never
trade on information it could not have had.

Units: prices and volume are in the dataset's own units; ``roc`` and ``rsi`` are in percent
points (``roc(20) > 5`` means "up more than 5 % over 20 bars"; ``rsi`` is 0-100).
Warm-up: until an indicator has its full window its value is null, and a rule that touches a null
is false. Nothing is back-filled.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import polars as pl

from crucible.core.errors import ConfigurationError

if TYPE_CHECKING:
    from collections.abc import Callable

PRICE_FIELDS: tuple[str, ...] = ("close", "open", "high", "low", "volume")
"""The bar fields a rule may read directly (and the ``field`` argument of an indicator)."""

MAX_PERIOD = 2000


@dataclass(frozen=True, slots=True)
class IndicatorDef:
    """One indicator: its arguments, how to build it and how much history it needs."""

    name: str
    signature: str  # shown in messages and docs, e.g. "sma(period[, field])"
    summary: str  # one sentence for the docs and the plain-language explanation
    kind: str  # "windowed" (period[, field]) or "band" (period[, k])
    build: Callable[[int, str, float], pl.Expr]  # (period, field, k) -> expression over a symbol
    warmup: Callable[[int], int]  # bars needed before the value is defined
    describe: Callable[[int, str, float], str]


def _over(expr: pl.Expr) -> pl.Expr:
    return expr.over("symbol")


def _after(period: int, expr: pl.Expr) -> pl.Expr:
    """``expr`` where the bar index within its symbol has reached ``period`` bars, else null."""
    index = pl.int_range(pl.len()).over("symbol")
    return pl.when(index >= period - 1).then(expr).otherwise(None)


def _sma(period: int, field: str, _k: float) -> pl.Expr:
    return _over(pl.col(field).rolling_mean(window_size=period))


def _ema(period: int, field: str, _k: float) -> pl.Expr:
    # recursive EMA (alpha = 2 / (period + 1)) seeded at the symbol's first bar, reported only
    # once `period` bars exist so every value rests on a full window of history
    return _after(period, _over(pl.col(field).ewm_mean(span=period, adjust=False)))


def _rsi(period: int, field: str, _k: float) -> pl.Expr:
    # Wilder's RSI: smoothed average gain / average loss with alpha = 1 / period
    delta = _over(pl.col(field).diff())
    gain = pl.when(delta > 0).then(delta).otherwise(0.0)
    loss = pl.when(delta < 0).then(-delta).otherwise(0.0)
    avg_gain = _over(gain.ewm_mean(alpha=1.0 / period, adjust=False, ignore_nulls=True))
    avg_loss = _over(loss.ewm_mean(alpha=1.0 / period, adjust=False, ignore_nulls=True))
    value = (
        pl.when(avg_loss == 0)
        .then(pl.when(avg_gain == 0).then(50.0).otherwise(100.0))
        .otherwise(100.0 - 100.0 / (1.0 + avg_gain / avg_loss))
    )
    # period bars of change need period + 1 bars of price
    return _after(period + 1, value)


def _roc(period: int, field: str, _k: float) -> pl.Expr:
    return (pl.col(field) / _over(pl.col(field).shift(period)) - 1.0) * 100.0


def _highest(period: int, field: str, _k: float) -> pl.Expr:
    # the highest value of the PREVIOUS `period` bars, today excluded: "close > highest(20)" is
    # a breakout above the prior 20-bar high, not a comparison of a bar with itself
    return _over(pl.col(field).shift(1).rolling_max(window_size=period))


def _lowest(period: int, field: str, _k: float) -> pl.Expr:
    return _over(pl.col(field).shift(1).rolling_min(window_size=period))


def _bb_upper(period: int, field: str, k: float) -> pl.Expr:
    mean = _over(pl.col(field).rolling_mean(window_size=period))
    std = _over(pl.col(field).rolling_std(window_size=period, ddof=0))
    return mean + k * std


def _bb_lower(period: int, field: str, k: float) -> pl.Expr:
    mean = _over(pl.col(field).rolling_mean(window_size=period))
    std = _over(pl.col(field).rolling_std(window_size=period, ddof=0))
    return mean - k * std


def _field_text(field: str) -> str:
    return {
        "close": "closing price",
        "open": "opening price",
        "high": "high",
        "low": "low",
        "volume": "volume",
    }[field]


INDICATORS: dict[str, IndicatorDef] = {
    d.name: d
    for d in (
        IndicatorDef(
            "sma",
            "sma(period[, field])",
            "simple moving average over the last `period` bars",
            "windowed",
            _sma,
            lambda p: p,
            lambda p, f, k: f"the {p}-bar simple moving average of the {_field_text(f)}",
        ),
        IndicatorDef(
            "ema",
            "ema(period[, field])",
            "exponential moving average (smoothing 2 / (period + 1))",
            "windowed",
            _ema,
            lambda p: p,
            lambda p, f, k: f"the {p}-bar exponential moving average of the {_field_text(f)}",
        ),
        IndicatorDef(
            "rsi",
            "rsi(period[, field])",
            "Wilder's relative strength index, 0-100 (above 70 is often read as overbought, "
            "below 30 as oversold)",
            "windowed",
            _rsi,
            lambda p: p + 1,
            lambda p, f, k: f"the {p}-bar RSI (0-100) of the {_field_text(f)}",
        ),
        IndicatorDef(
            "roc",
            "roc(period[, field])",
            "rate of change in percent over `period` bars (momentum)",
            "windowed",
            _roc,
            lambda p: p + 1,
            lambda p, f, k: f"the {p}-bar percentage change of the {_field_text(f)}",
        ),
        IndicatorDef(
            "highest",
            "highest(period[, field])",
            "highest value of the previous `period` bars, today excluded (breakout level)",
            "windowed",
            _highest,
            lambda p: p + 1,
            lambda p, f, k: f"the highest {_field_text(f)} of the previous {p} bars",
        ),
        IndicatorDef(
            "lowest",
            "lowest(period[, field])",
            "lowest value of the previous `period` bars, today excluded (breakdown level)",
            "windowed",
            _lowest,
            lambda p: p + 1,
            lambda p, f, k: f"the lowest {_field_text(f)} of the previous {p} bars",
        ),
        IndicatorDef(
            "bb_upper",
            "bb_upper(period[, k])",
            "upper Bollinger band: moving average + k standard deviations (k defaults to 2)",
            "band",
            _bb_upper,
            lambda p: p,
            lambda p, f, k: f"the upper Bollinger band ({p} bars, {k:g} standard deviations)",
        ),
        IndicatorDef(
            "bb_lower",
            "bb_lower(period[, k])",
            "lower Bollinger band: moving average - k standard deviations (k defaults to 2)",
            "band",
            _bb_lower,
            lambda p: p,
            lambda p, f, k: f"the lower Bollinger band ({p} bars, {k:g} standard deviations)",
        ),
    )
}


def resolve_indicator(
    name: str, args: tuple[float | str, ...], where: str
) -> tuple[int, str, float]:
    """Validates a call ``name(args)`` and returns ``(period, field, k)``.

    Raises ``ConfigurationError`` saying what is wrong at ``where`` and the valid signature."""
    definition = INDICATORS.get(name)
    if definition is None:
        known = ", ".join(sorted(INDICATORS))
        msg = (
            f"{where}: unknown indicator {name!r}. Indicators: {known}; bar fields: "
            f"{', '.join(PRICE_FIELDS)}"
        )
        raise ConfigurationError(msg)
    usage = f"use {definition.signature}"
    if not args or len(args) > 2:
        msg = f"{where}: {name}() takes 1 or 2 arguments, got {len(args)}; {usage}"
        raise ConfigurationError(msg)
    period_raw = args[0]
    if isinstance(period_raw, str) or float(period_raw) != int(period_raw) or period_raw < 1:
        msg = (
            f"{where}: the period of {name}() must be a whole number >= 1, got {period_raw!r}; "
            f"{usage}"
        )
        raise ConfigurationError(msg)
    period = int(period_raw)
    if period > MAX_PERIOD:
        msg = f"{where}: the period of {name}() is {period}; the maximum is {MAX_PERIOD} bars"
        raise ConfigurationError(msg)
    field, k = "close", 2.0
    if len(args) == 2:
        second = args[1]
        if definition.kind == "band":
            if isinstance(second, str) or float(second) <= 0:
                msg = (
                    f"{where}: the second argument of {name}() is the number of standard "
                    f"deviations and must be a number > 0, got {second!r}; {usage}"
                )
                raise ConfigurationError(msg)
            k = float(second)
        else:
            if not isinstance(second, str) or second not in PRICE_FIELDS:
                msg = (
                    f"{where}: the second argument of {name}() is the bar field and must be one "
                    f"of {', '.join(PRICE_FIELDS)}, got {second!r}; {usage}"
                )
                raise ConfigurationError(msg)
            field = second
    return period, field, k
