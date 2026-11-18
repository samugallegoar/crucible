"""Free parameters: ``$name`` values that are declared once and bound everywhere (ADR-0096).

Only ``$``-marked values are free; an unmarked literal is fixed and never extracted. A parameter
is declared on at least one occurrence (``$n:int[5,200]=20``) and every other occurrence binds to
that one binding; repeated declarations must be identical. ``optimizable`` means the declaration
carries bounds: an unbounded parameter can be bound to a value but not swept.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from types import MappingProxyType
from typing import TYPE_CHECKING

from crucible.dsl.errors import ExpressionError

if TYPE_CHECKING:
    from crucible.dsl.ast import Expr, ParamDecl
    from crucible.dsl.ast import Expression as ExpressionType

TYPE_NAMES = frozenset({"int", "float"})


@dataclass(frozen=True, slots=True)
class FreeParam:
    """One free parameter: its type, its current default and its optional optimization bounds."""

    name: str
    type: str
    """``"int"`` or ``"float"``."""

    default: int | float
    low: int | float | None = None
    high: int | float | None = None

    def __post_init__(self) -> None:
        if self.type not in TYPE_NAMES:
            msg = f"parameter {self.name!r}: type must be 'int' or 'float', got {self.type!r}"
            raise ExpressionError(msg)
        if (self.low is None) != (self.high is None):
            msg = (
                f"parameter {self.name!r}: low and high must both be present or both absent, "
                f"got low={self.low!r} high={self.high!r}"
            )
            raise ExpressionError(msg)
        if (
            self.low is not None
            and self.high is not None
            and not self.low <= self.default <= self.high
        ):
            msg = (
                f"parameter {self.name!r}: default {self.default!r} is outside its bounds "
                f"[{self.low!r}, {self.high!r}]"
            )
            raise ExpressionError(msg)

    @property
    def optimizable(self) -> bool:
        """A parameter with declared bounds can be swept; an unbounded one cannot."""
        return self.low is not None and self.high is not None

    @classmethod
    def from_decl(cls, name: str, decl: ParamDecl) -> FreeParam:
        """Normalize a parsed declaration into the one binding of that name."""
        return cls(name=name, type=decl.type, default=decl.default, low=decl.low, high=decl.high)

    def declaration_text(self) -> str:
        """The canonical declaration text, used by ``canonical_text``."""
        bounds = "" if self.low is None else f"[{_number(self.low)},{_number(self.high)}]"
        return f"${self.name}:{self.type}{bounds}={_number(self.default)}"


def _number(value: int | float | None) -> str:
    if value is None:
        return "null"
    if isinstance(value, int):
        return str(value)
    return repr(float(value))


def _refuse(message: str, *, column: int | None, token: str, hint: str) -> ExpressionError:
    return ExpressionError(message, column=column, token=token, hint=hint)


def _collect(expr: Expr) -> dict[str, FreeParam]:
    """Resolve every ``$name`` to its one binding, in first-occurrence (pre-order) order."""
    from crucible.dsl.ast import Param, walk_preorder

    declarations: dict[str, list[tuple[Param, ParamDecl]]] = {}
    for node in walk_preorder(expr):
        if isinstance(node, Param) and node.decl is not None:
            declarations.setdefault(node.name, []).append((node, node.decl))

    bindings: dict[str, FreeParam] = {}
    seen: set[str] = set()
    for node in walk_preorder(expr):
        if not isinstance(node, Param) or node.name in seen:
            continue
        seen.add(node.name)
        decls = declarations.get(node.name)
        if not decls:
            raise _refuse(
                f"undeclared free parameter ${node.name}: some occurrence must declare it with "
                "a type, default and optional bounds",
                column=node.column,
                token=f"${node.name}",
                hint=f"write e.g. ${node.name}:int[5,200]=20 on one occurrence",
            )
        first_node, first_decl = decls[0]
        signature = first_decl.signature()
        for other_node, other_decl in decls[1:]:
            if other_decl.signature() != signature:
                raise _refuse(
                    f"conflicting declarations of ${node.name}: "
                    f"{_decl_text(first_decl)} at column {first_node.column} vs "
                    f"{_decl_text(other_decl)} at column {other_node.column}",
                    column=other_node.column,
                    token=f"${node.name}",
                    hint="a parameter has exactly one type, default and range; make them identical",
                )
        bindings[node.name] = FreeParam.from_decl(node.name, first_decl)
    return bindings


def _decl_text(decl: ParamDecl) -> str:
    bounds = "" if decl.low is None else f"[{_number(decl.low)},{_number(decl.high)}]"
    return f":{decl.type}{bounds}={_number(decl.default)}"


def collect_bindings(expr: Expr) -> tuple[FreeParam, ...]:
    """The parameter bindings in first-occurrence order (internal; used by the parser)."""
    return tuple(_collect(expr).values())


def bindings_by_name(params: tuple[FreeParam, ...]) -> Mapping[str, FreeParam]:
    """A read-only ``name -> binding`` map for type checking."""
    return MappingProxyType({param.name: param for param in params})


def free_parameters(expr: ExpressionType) -> tuple[FreeParam, ...]:
    """Every free parameter, in canonical placeholder order (``canonical_form`` indices)."""
    from crucible.dsl.canonical import canonicalize

    return canonicalize(expr).params


def optimizable_parameters(expr: ExpressionType) -> tuple[FreeParam, ...]:
    """The free parameters that carry bounds, in canonical order, so a sweep may vary them."""
    return tuple(param for param in free_parameters(expr) if param.optimizable)


def bind(expr: ExpressionType, values: Mapping[str, int | float]) -> ExpressionType:
    """Rebind parameter defaults; the tree and its types do not change, only the values.

    Unknown names, a value of the wrong type and an out-of-bounds value are refused. A window
    parameter is re-validated after binding: a value that leaves ``[1, 2000]`` is refused.
    """
    from crucible.dsl.ast import Expression
    from crucible.dsl.types import type_map

    by_name = bindings_by_name(expr.params)
    unknown = sorted(set(values) - set(by_name))
    if unknown:
        known = ", ".join(f"${param.name}" for param in expr.params) or "none"
        raise ExpressionError(
            f"bind() names unknown parameter(s) {', '.join(unknown)}; known parameters: {known}",
            hint="use the names the expression declares",
        )

    updated: list[FreeParam] = []
    for param in expr.params:
        if param.name not in values:
            updated.append(param)
            continue
        value = values[param.name]
        if isinstance(value, bool):
            raise ExpressionError(
                f"bind() value for ${param.name} is a bool; it is a {param.type} parameter",
                hint="pass a number, not true/false",
            )
        if param.type == "int":
            if not isinstance(value, int):
                raise ExpressionError(
                    f"bind() value for ${param.name} is {value!r}; it is an int parameter",
                    hint="pass a whole number",
                )
            coerced: int | float = value
        else:
            if not isinstance(value, int | float):
                raise ExpressionError(
                    f"bind() value for ${param.name} is {value!r}; it is a float parameter",
                    hint="pass a number",
                )
            coerced = float(value)
        if (
            param.low is not None
            and param.high is not None
            and not (param.low <= coerced <= param.high)
        ):
            raise ExpressionError(
                f"bind() value {coerced!r} for ${param.name} is outside its bounds "
                f"[{param.low!r}, {param.high!r}]",
                hint="stay inside the declared bounds or widen them in the declaration",
            )
        updated.append(replace(param, default=coerced))

    params = tuple(updated)
    bindings = bindings_by_name(params)
    # Re-validates window positions against the new defaults (types must stay identical).
    types = type_map(expr.root, bindings)
    original = expr.types[expr.root]
    if types[expr.root] != original:
        from crucible.core.errors import InvariantViolation

        raise InvariantViolation(
            f"bind() changed the root type of the expression from {original!r} to "
            f"{types[expr.root]!r}: parameters must not affect types"
        )
    return Expression(
        root=expr.root,
        types=MappingProxyType(types),
        params=params,
        source_text=expr.source_text,
    )
