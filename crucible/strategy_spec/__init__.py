"""Declarative strategy specs: validated data that compiles to a vectorized signal (ADR-0067)."""

from crucible.strategy_spec.compile import spec_signal, uses_time, warmup_bars
from crucible.strategy_spec.describe import describe_spec
from crucible.strategy_spec.models import (
    SPEC_VERSION,
    StrategySpec,
    canonical_spec,
    load_spec,
    parse_spec,
    spec_json_schema,
)

__all__ = [
    "SPEC_VERSION",
    "StrategySpec",
    "canonical_spec",
    "describe_spec",
    "load_spec",
    "parse_spec",
    "spec_json_schema",
    "spec_signal",
    "uses_time",
    "warmup_bars",
]
