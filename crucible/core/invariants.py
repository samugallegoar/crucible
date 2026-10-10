"""Invariant registry: identities the engine must hold at every mark.

Mirrors docs/INVARIANTS.md. Each invariant is registered here by name and
checked by the engine at every mark; a failed check raises
``InvariantViolation`` — it never warns (AGENTS.md §1).

Invariants are registered by the components that can violate them.
docs/INVARIANTS.md tracks which identities are registered and tested.
"""

from __future__ import annotations

from typing import Protocol


class Invariant(Protocol):
    """A named identity checked against engine state.

    ``check`` raises ``InvariantViolation`` with what/where/how-to-fix; it
    never returns a boolean to be ignored.
    """

    @property
    def name(self) -> str: ...

    def check(self, state: object) -> None: ...


_REGISTRY: dict[str, Invariant] = {}


def register(invariant: Invariant) -> None:
    """Register an invariant. Re-registering a name raises: silent replacement
    of a correctness check is exactly the kind of change this repo refuses."""
    if invariant.name in _REGISTRY:
        msg = (
            f"invariant {invariant.name!r} is already registered; "
            "rename it or remove the old one explicitly"
        )
        raise ValueError(msg)
    _REGISTRY[invariant.name] = invariant


def all_invariants() -> dict[str, Invariant]:
    """Snapshot of the registry (name -> invariant)."""
    return dict(_REGISTRY)
