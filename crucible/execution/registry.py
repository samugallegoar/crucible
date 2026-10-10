"""Execution model registry (AGENTS.md §6).

Maps the stable string keys used by config (`type:` discriminators in
`experiments/config.py`) to model factories, and enforces which slots each
realism level may use (ADR-0012). The registry deliberately takes plain
keyword params, not config objects — execution never imports the
experiments layer.

Level gating:

| slot          | allowed from level | keys |
|---------------|--------------------|------|
| slippage      | 1 / 4 for impact   | none, fixed_bps, sqrt_impact, linear_impact |
| commission    | 1 | none, bps, per_share, maker_taker |
| spread        | 2 | none, static, dynamic, quoted |
| latency       | 2 | zero, constant, normal |
| participation | 3 | (config block, not keyed) |
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from crucible.core.errors import ConfigurationError
from crucible.core.types import NS_PER_MS, RealismLevel
from crucible.execution.ladder import (
    CommissionModelLike,
    LatencyModelLike,
    PriceAdjusterLike,
    SpreadModelLike,
)
from crucible.execution.models import (
    BpsCommission,
    ConstantLatency,
    DynamicSpread,
    FixedBpsSlippage,
    LinearImpact,
    MakerTakerCommission,
    NoCommission,
    NormalLatency,
    NoSlippage,
    NoSpread,
    PerShareCommission,
    QuotedSpread,
    SqrtImpact,
    StaticSpread,
    ZeroLatency,
)

if TYPE_CHECKING:
    from crucible.execution.models import MarketStats

_MIN_LEVEL: dict[tuple[str, str], RealismLevel] = {
    ("spread", "none"): RealismLevel.FRICTIONLESS,
    ("spread", "static"): RealismLevel.SPREAD_LATENCY,
    ("spread", "dynamic"): RealismLevel.SPREAD_LATENCY,
    ("spread", "quoted"): RealismLevel.SPREAD_LATENCY,
    ("latency", "zero"): RealismLevel.FRICTIONLESS,
    ("latency", "constant"): RealismLevel.SPREAD_LATENCY,
    ("latency", "normal"): RealismLevel.SPREAD_LATENCY,
    ("slippage", "none"): RealismLevel.FRICTIONLESS,
    ("slippage", "fixed_bps"): RealismLevel.BASIC_FRICTION,
    ("slippage", "sqrt_impact"): RealismLevel.IMPACT,
    ("slippage", "linear_impact"): RealismLevel.IMPACT,
    ("commission", "none"): RealismLevel.FRICTIONLESS,
    ("commission", "bps"): RealismLevel.BASIC_FRICTION,
    ("commission", "per_share"): RealismLevel.BASIC_FRICTION,
    ("commission", "maker_taker"): RealismLevel.BASIC_FRICTION,
}


def _check_level(slot: str, key: str, level: RealismLevel) -> None:
    try:
        minimum = _MIN_LEVEL[(slot, key)]
    except KeyError:
        known = sorted(k for s, k in _MIN_LEVEL if s == slot)
        msg = f"unknown {slot} model {key!r}; registered: {known}"
        raise ConfigurationError(msg) from None
    if level < minimum:
        msg = (
            f"{slot} model {key!r} requires realism level >= {int(minimum)} "
            f"({minimum.name}); configured level is {int(level)} ({level.name}). "
            "Raise experiment.realism_level or use a lower-rung model."
        )
        raise ConfigurationError(msg)


def build_spread(key: str, level: RealismLevel, **params: float) -> SpreadModelLike:
    _check_level("spread", key, level)
    if key == "none":
        return NoSpread()
    if key == "static":
        return StaticSpread(half_spread_bps=params["half_spread_bps"])
    if key == "quoted":
        return QuotedSpread()
    return DynamicSpread(base_bps=params["base_bps"], vol_mult=params["vol_mult"])


def build_latency(key: str, level: RealismLevel, **params: float) -> LatencyModelLike:
    _check_level("latency", key, level)
    if key == "zero":
        return ZeroLatency()
    if key == "constant":
        return ConstantLatency(round(params["ms"] * NS_PER_MS))
    return NormalLatency(mean_ns=params["mean_ms"] * NS_PER_MS, std_ns=params["std_ms"] * NS_PER_MS)


def build_slippage(
    key: str, level: RealismLevel, stats: MarketStats, **params: float
) -> PriceAdjusterLike:
    _check_level("slippage", key, level)
    if key == "none":
        return NoSlippage()
    if key == "fixed_bps":
        return FixedBpsSlippage(params["bps"])
    if key == "sqrt_impact":
        return SqrtImpact(params["coef"], stats)
    return LinearImpact(params["coef"], stats)


def build_commission(key: str, level: RealismLevel, **params: object) -> CommissionModelLike:
    _check_level("commission", key, level)
    if key == "none":
        return NoCommission()
    if key == "bps":
        return BpsCommission(float(str(params["bps"])))
    if key == "per_share":
        return PerShareCommission(rate=str(params["rate"]), minimum=str(params["minimum"]))
    return MakerTakerCommission(
        maker_bps=float(str(params["maker_bps"])), taker_bps=float(str(params["taker_bps"]))
    )
