"""Property tests for canonicalization (ADR-0096): idempotent, re-parsable, order independent.

Expressions are generated as small dimensionless series (z-scores, ranks, ratios), so every
generated tree is well typed by construction. Deterministic: ``derandomize=True``.
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from crucible.dsl import (
    canonical_form,
    canonical_text,
    canonicalize,
    parse,
    structure_id,
)

SERIES_ATOMS = (
    "ts_zscore(close, 20)",
    "ts_rank(volume, 10)",
    "close / delay(close, 1)",
    "volume / ts_mean(volume, 20)",
)
LITERALS = ("0.5", "1", "2")


def _series_tree() -> st.SearchStrategy[str]:
    atom = st.sampled_from(SERIES_ATOMS)
    literal = st.sampled_from(LITERALS)

    def extend(children: st.SearchStrategy[str]) -> st.SearchStrategy[str]:
        return st.one_of(
            children.map(lambda child: f"-{child}"),
            children.map(lambda child: f"abs({child})"),
            children.map(lambda child: f"sign({child})"),
            st.tuples(children, children).map(lambda pair: f"({pair[0]} + {pair[1]})"),
            st.tuples(children, children).map(lambda pair: f"({pair[0]} - {pair[1]})"),
            st.tuples(children, children).map(lambda pair: f"({pair[0]} * {pair[1]})"),
            st.tuples(children, literal).map(lambda pair: f"({pair[0]} * {pair[1]})"),
            st.tuples(children, children).map(lambda pair: f"min({pair[0]}, {pair[1]})"),
            st.tuples(children, children).map(lambda pair: f"max({pair[0]}, {pair[1]})"),
        )

    return st.recursive(atom, extend, max_leaves=6)


_PROPERTY_SETTINGS = settings(max_examples=25, derandomize=True, deadline=None)
SERIES_TEXT = _series_tree()


@_PROPERTY_SETTINGS
@given(SERIES_TEXT)
def test_canonicalize_is_idempotent(text: str) -> None:
    once = canonicalize(parse(text))
    twice = canonicalize(once)
    assert canonical_form(once) == canonical_form(twice)
    assert canonical_text(once) == canonical_text(twice)


@_PROPERTY_SETTINGS
@given(SERIES_TEXT)
def test_canonical_text_reparses_to_the_same_form(text: str) -> None:
    expression = parse(text)
    canonical = canonicalize(expression)
    reparsed = parse(canonical_text(canonical))
    assert canonical_form(reparsed) == canonical_form(canonical)


@_PROPERTY_SETTINGS
@given(SERIES_TEXT, SERIES_TEXT)
def test_commutative_swaps_share_a_structure_id(left: str, right: str) -> None:
    forward = parse(f"({left} + {right})")
    reverse = parse(f"({right} + {left})")
    assert structure_id(forward) == structure_id(reverse)
    assert canonical_form(forward) == canonical_form(reverse)


@_PROPERTY_SETTINGS
@given(SERIES_TEXT)
def test_canonicalization_preserves_the_type(text: str) -> None:
    expression = parse(text)
    canonical = canonicalize(expression)
    assert canonical.root_type == expression.root_type
