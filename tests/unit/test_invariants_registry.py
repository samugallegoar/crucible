"""Invariant registry: registration is explicit and never silently replaced."""

from __future__ import annotations

import pytest

from crucible.core import invariants


class _DummyInvariant:
    def __init__(self, name: str) -> None:
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    def check(self, state: object) -> None:
        return None


def test_register_and_lookup(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(invariants, "_REGISTRY", {})
    inv = _DummyInvariant("cash_identity")
    invariants.register(inv)
    assert invariants.all_invariants() == {"cash_identity": inv}


def test_duplicate_registration_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(invariants, "_REGISTRY", {})
    invariants.register(_DummyInvariant("equity_identity"))
    with pytest.raises(ValueError, match="already registered"):
        invariants.register(_DummyInvariant("equity_identity"))


def test_snapshot_is_a_copy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(invariants, "_REGISTRY", {})
    invariants.register(_DummyInvariant("qty_identity"))
    snapshot = invariants.all_invariants()
    snapshot.clear()
    assert "qty_identity" in invariants.all_invariants()
