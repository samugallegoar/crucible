"""Property tests for the DSL evaluator (ADR-0098): canonicalization never changes a value, and a
decision at a bar is a function of the bars up to and including it.

Expressions are generated as small dimensionless series, so every tree is well typed by
construction; the frame is one fixed, gap-free random series (deterministic: no wall clock, no
global RNG). The prefix property is the lookahead guarantee at the value level: evaluating
``frame[:t + 1]`` gives the same value at ``t`` as evaluating the whole frame.

The first property is the one ``evaluate`` relies on when it canonicalizes before evaluating
(``evaluate(expr)`` and ``evaluate(canonicalize(expr))`` agree bitwise). Because both sides run
through the same canonical form, the second property is what makes it a real test: two texts that
canonicalize to the same tree (``a + b`` and ``b + a``, ``x * 1`` and ``x``) must *evaluate* the
same, so a rewrite that changed a value would be caught.
"""

from __future__ import annotations

import numpy as np
import polars as pl
from hypothesis import given, settings
from hypothesis import strategies as st

from crucible.dsl import canonical_form, canonicalize, parse
from crucible.dsl.evaluate import evaluate

ROWS = 30
_MINUTE = 60_000_000_000

SERIES_ATOMS = (
    "ts_zscore(close, 20)",
    "ts_rank(volume, 10)",
    "close / delay(close, 1)",
    "volume / ts_mean(volume, 20)",
    "ema(close, 15) / close",
    "delay(close, 3) / close",
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


def _frame() -> pl.DataFrame:
    rng = np.random.default_rng(7)
    steps = rng.normal(0.0, 0.01, ROWS)
    closes = 100.0 * np.cumprod(1.0 + steps)
    volumes = 1000.0 + 100.0 * rng.random(ROWS)
    times = np.arange(ROWS, dtype=np.int64) * _MINUTE
    return pl.DataFrame(
        {
            "event_time": times,
            "available_at": times + 1,
            "open": closes,
            "high": closes,
            "low": closes,
            "close": closes,
            "volume": volumes,
        }
    )


FRAME = _frame()
SERIES_TEXT = _series_tree()
_PROPERTY_SETTINGS = settings(max_examples=30, derandomize=True, deadline=None)


@_PROPERTY_SETTINGS
@given(SERIES_TEXT)
def test_canonicalize_preserves_evaluation_bitwise(text: str) -> None:
    expression = parse(text)
    direct = evaluate(expression, FRAME)
    canonical = evaluate(canonicalize(expression), FRAME)
    assert direct.dtype == canonical.dtype
    assert direct.equals(canonical)


@_PROPERTY_SETTINGS
@given(SERIES_TEXT, st.integers(min_value=1, max_value=ROWS))
def test_the_value_at_a_bar_depends_only_on_the_bars_up_to_it(text: str, end: int) -> None:
    expression = parse(text)
    full = evaluate(expression, FRAME)
    prefix = evaluate(expression, FRAME.head(end))
    assert prefix.to_list() == full.head(end).to_list()


@_PROPERTY_SETTINGS
@given(SERIES_TEXT)
def test_re_evaluating_the_same_expression_is_deterministic(text: str) -> None:
    expression = parse(text)
    assert evaluate(expression, FRAME).equals(evaluate(expression, FRAME))


@_PROPERTY_SETTINGS
@given(SERIES_TEXT, SERIES_TEXT)
def test_two_texts_with_one_canonical_form_evaluate_the_same(left: str, right: str) -> None:
    forward = parse(f"({left} + {right})")
    reverse = parse(f"({right} + {left})")
    assert canonical_form(forward) == canonical_form(reverse)
    assert evaluate(forward, FRAME).equals(evaluate(reverse, FRAME))
    assert evaluate(parse(f"({left} * 1)"), FRAME).equals(evaluate(parse(left), FRAME))
    assert evaluate(parse(f"({left} - 0)"), FRAME).equals(evaluate(parse(left), FRAME))
