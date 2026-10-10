"""Cost presets for the one-step backtest (ADR-0068).

A preset is the Level 0/1 shorthand (``slippage_bps`` + ``commission_bps``; ADR-0010): costs are
charged on every unit of turnover. Units are basis points of traded notional (1 bp = 0.01 %).
Choosing a preset by name keeps a non-coder from having to know what a basis point is; the
numbers are always echoed in the result.
"""

from __future__ import annotations

from dataclasses import dataclass

from crucible.core.errors import ConfigurationError


@dataclass(frozen=True, slots=True)
class CostPreset:
    name: str
    slippage_bps: float
    commission_bps: float
    description: str


PRESETS: dict[str, CostPreset] = {
    p.name: p
    for p in (
        CostPreset("none", 0.0, 0.0, "no costs at all; an upper bound that no real account gets"),
        CostPreset(
            "standard",
            1.0,
            0.5,
            "1 bp slippage + 0.5 bp commission per trade: a liquid large-cap stock or ETF "
            "traded in normal size on a low-cost broker",
        ),
        CostPreset(
            "conservative",
            5.0,
            2.0,
            "5 bps slippage + 2 bps commission: thinner or more volatile instruments, or a "
            "pessimistic view of fills",
        ),
    )
}
DEFAULT_PRESET = "standard"


def resolve_costs(
    preset: str | None, slippage_bps: float | None, commission_bps: float | None
) -> tuple[str, float, float]:
    """``(label, slippage_bps, commission_bps)``. Explicit bps override the preset's values."""
    name = preset or DEFAULT_PRESET
    base = PRESETS.get(name)
    if base is None:
        msg = (
            f"unknown cost preset {name!r}; choose one of {', '.join(PRESETS)} or give "
            "slippage_bps and commission_bps explicitly"
        )
        raise ConfigurationError(msg)
    slip = base.slippage_bps if slippage_bps is None else float(slippage_bps)
    comm = base.commission_bps if commission_bps is None else float(commission_bps)
    if slip < 0 or comm < 0:
        msg = f"costs cannot be negative (slippage_bps={slip}, commission_bps={comm})"
        raise ConfigurationError(msg)
    custom = slippage_bps is not None or commission_bps is not None
    return ("custom" if custom else name), slip, comm
