"""Every module's interfaces import cleanly: the shape of the system exists."""

from __future__ import annotations

import importlib

import pytest

MODULES = [
    "crucible.core.types",
    "crucible.core.errors",
    "crucible.core.interfaces",
    "crucible.core.invariants",
    "crucible.data.interfaces",
    "crucible.strategy.interfaces",
    "crucible.portfolio.interfaces",
    "crucible.risk.interfaces",
    "crucible.orders.interfaces",
    "crucible.execution.interfaces",
    "crucible.accounting.interfaces",
    "crucible.analytics.interfaces",
    "crucible.validation.interfaces",
    "crucible.vectorized.interfaces",
    "crucible.experiments.interfaces",
    "crucible.experiments.config",
    "crucible.live.interfaces",
    "crucible.cli.main",
]


@pytest.mark.parametrize("module_name", MODULES)
def test_module_imports(module_name: str) -> None:
    importlib.import_module(module_name)
