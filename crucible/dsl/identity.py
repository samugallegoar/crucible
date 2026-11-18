"""The three expression identities (ADR-0096): structure, parameterization, compiled.

Two expressions share a ``structure_id`` when they differ only in parameter *names*, defaults or
ranges: the id hashes the canonical topology plus the binding pattern (which placeholder is the
same as which) and each placeholder's type. Renaming ``$n`` to ``$m`` or changing ``[5,50]=10``
keeps it; changing a fixed literal, a feature, an operator or the binding pattern (``$a + $a`` vs
``$a + $b``) changes it.

``parameterization_id`` adds the current values: defaults and bounds. ``compiled_id_basis`` adds
the compiler version, the semantic version of every operator used and the input dataset hashes;
C4b hashes that dict into the ``DSC-`` id.
"""

from __future__ import annotations

from hashlib import sha256
from typing import TYPE_CHECKING, Final

from crucible.core.canonical import canonical_json
from crucible.dsl.canonical import canonical_form, canonicalize
from crucible.dsl.grammar import GRAMMAR_VERSION
from crucible.dsl.operators import OPERATOR_TABLE_VERSION, OPERATORS

if TYPE_CHECKING:
    from collections.abc import Mapping

    from crucible.dsl.ast import Expression

STRUCTURE_PREFIX: Final[str] = "DSX-"
PARAMETERIZATION_PREFIX: Final[str] = "DSP-"
COMPILED_PREFIX: Final[str] = "DSC-"
ID_HEX: Final[int] = 16
"""Hex digits kept from the SHA-256 (64 bits: collisions are negligible at this scale)."""


def _hash(basis: object) -> str:
    return sha256(canonical_json(basis).encode("utf-8")).hexdigest()[:ID_HEX]


def structure_id(expr: Expression) -> str:
    """``DSX-`` + the hash of grammar, operator-table version and the canonical form."""
    basis = {
        "grammar": GRAMMAR_VERSION,
        "operators": OPERATOR_TABLE_VERSION,
        "form": canonical_form(canonicalize(expr)),
    }
    return STRUCTURE_PREFIX + _hash(basis)


def _parameter_rows(expr: Expression) -> list[list[object]]:
    canonical = canonicalize(expr)
    return [[param.type, param.default, param.low, param.high] for param in canonical.params]


def parameterization_id(expr: Expression) -> str:
    """``DSP-`` + the hash of the structure id and each placeholder's value and bounds."""
    basis = {"structure": structure_id(expr), "params": _parameter_rows(expr)}
    return PARAMETERIZATION_PREFIX + _hash(basis)


def _operators_used(expr: Expression) -> tuple[str, ...]:
    from crucible.dsl.ast import Call, walk_preorder

    names = {node.name for node in walk_preorder(canonicalize(expr).root) if isinstance(node, Call)}
    return tuple(sorted(names))


def compiled_id_basis(
    expr: Expression,
    *,
    compiler_version: str,
    operator_versions: Mapping[str, str],
    inputs: Mapping[str, str],
) -> dict[str, object]:
    """The canonical dict C4b hashes into ``DSC-``: what was compiled, with what and on what.

    ``operator_versions`` overrides the table's semantic version per operator name (e.g. an
    experimental build); every operator actually used appears in the result, no unused one does.
    """
    used = _operators_used(expr)
    return {
        "parameterization": parameterization_id(expr),
        "compiler": compiler_version,
        "operators": {
            name: operator_versions.get(name, OPERATORS[name].semantic_version) for name in used
        },
        "inputs": dict(inputs),
    }


def compiled_id(
    expr: Expression,
    *,
    compiler_version: str,
    operator_versions: Mapping[str, str],
    inputs: Mapping[str, str],
) -> str:
    """``DSC-`` + the hash of :func:`compiled_id_basis`. No caller yet: C4b builds on it."""
    basis = compiled_id_basis(
        expr,
        compiler_version=compiler_version,
        operator_versions=operator_versions,
        inputs=inputs,
    )
    return COMPILED_PREFIX + _hash(basis)
