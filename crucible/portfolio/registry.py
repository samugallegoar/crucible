"""Portfolio constructor registry (AGENTS.md §6, ADR-0029).

Maps the stable string keys used by config (`type:` discriminators) to
constructor factories. Takes plain keyword params, not config objects --
portfolio never imports the experiments layer (mirrors
`crucible/execution/registry.py` and `crucible/risk/registry.py`).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from crucible.core.errors import ConfigurationError
from crucible.portfolio.constructors import (
    EqualWeightConstructor,
    FixedFractionalConstructor,
    FractionalKellyConstructor,
    MeanVarianceConstructor,
    RiskParityConstructor,
    VolTargetConstructor,
)

if TYPE_CHECKING:
    from crucible.portfolio.interfaces import PortfolioConstructor

_KEYS = (
    "equal_weight",
    "fixed_fractional",
    "vol_target",
    "risk_parity",
    "fractional_kelly",
    "mean_variance",
)


def build_constructor(key: str, **params: object) -> PortfolioConstructor:
    if key == "equal_weight":
        top_k = params.get("top_k")
        return EqualWeightConstructor(top_k=int(str(top_k)) if top_k is not None else None)
    if key == "fixed_fractional":
        top_k = params.get("top_k")
        return FixedFractionalConstructor(
            fraction=float(str(params["fraction"])),
            top_k=int(str(top_k)) if top_k is not None else None,
        )
    if key == "vol_target":
        return VolTargetConstructor(
            target_vol=float(str(params["target_vol"])),
            max_weight=float(str(params.get("max_weight", 1.0))),
        )
    if key == "risk_parity":
        return RiskParityConstructor(max_weight=float(str(params.get("max_weight", 1.0))))
    if key == "fractional_kelly":
        return FractionalKellyConstructor(
            kelly_fraction=float(str(params.get("kelly_fraction", 0.5))),
            max_weight=float(str(params.get("max_weight", 1.0))),
        )
    if key == "mean_variance":
        return MeanVarianceConstructor(
            risk_aversion=float(str(params.get("risk_aversion", 1.0))),
            min_weight=float(str(params.get("min_weight", 0.0))),
            max_weight=float(str(params.get("max_weight", 1.0))),
            ridge=float(str(params.get("ridge", 1e-6))),
        )
    msg = f"unknown portfolio constructor {key!r}; registered: {list(_KEYS)}"
    raise ConfigurationError(msg)
