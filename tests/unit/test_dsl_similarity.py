"""Structural similarity (ADR-0099): the largest common complete subtree, hand-computed.

Every expected number below is counted by hand from the two trees written in the test: the node
count of each canonical AST, the node count of the largest complete subtree they share, and
``2 * common / (nodes_a + nodes_b)``. Nothing is read back from the engine.
"""

from __future__ import annotations

import pytest

from crucible.core.errors import ConfigurationError
from crucible.dsl import compile_expression, parse
from crucible.dsl.similarity import (
    SimilarityHit,
    common_subtree_nodes,
    max_similarity,
    pool_similarity,
    similarity,
)


def _pair(text: str) -> tuple[float, int]:
    """``(similarity, common nodes)`` of a text against itself."""
    expression = parse(text)
    return similarity(expression, expression), common_subtree_nodes(expression, expression)


# ----------------------------------------------------------------------- hand-computed pairs


def test_identical_expressions_are_perfectly_similar() -> None:
    # ts_mean(close, 5): the call + the feature + the literal = 3 nodes on each side, all shared
    assert _pair("ts_mean(close, 5)") == (1.0, 3)


def test_a_commutative_swap_is_the_same_structure() -> None:
    # close/open + volume/volume == volume/volume + close/open after canonicalization:
    # + (1) / close (1) open (1) / volume (1) volume (1) = 7 nodes each, all shared -> 14/14
    left = parse("close/open + volume/volume")
    right = parse("volume/volume + close/open")
    assert common_subtree_nodes(left, right) == 7
    assert similarity(left, right) == 1.0


def test_repeated_parameter_differs_from_two_independent_parameters() -> None:
    # A: (+ (ts_mean (close $0)) (ts_mean (close $0)))  -> 7 nodes, the same placeholder twice
    # B: (+ (ts_mean (close $0)) (ts_mean (close $1)))  -> 7 nodes, two placeholders
    # the two ts_mean(close, $) subtrees (3 nodes) match; the sums and the whole trees do not,
    # because the binding pattern differs -> 2 * 3 / (7 + 7)
    repeated = parse("ts_mean(close, $a=5) + ts_mean(close, $a=5)")
    independent = parse("ts_mean(close, $a=5) + ts_mean(close, $b=5)")
    assert common_subtree_nodes(repeated, independent) == 3
    assert similarity(repeated, independent) == pytest.approx(6 / 14)


def test_a_parameter_never_matches_a_fixed_literal() -> None:
    # ts_mean(close, 5) vs ts_mean(close, $n=5): only `close` is a shared complete subtree
    # -> 2 * 1 / (3 + 3)
    assert similarity(parse("ts_mean(close, 5)"), parse("ts_mean(close, $n=5)")) == pytest.approx(
        1 / 3
    )


def test_a_float_parameter_never_matches_an_int_parameter() -> None:
    # ts_rank(close, 2) + $a  vs  ts_rank(close, 2) + $b:float
    # each: + (1) ts_rank (1) close (1) literal 2 (1) param (1) = 5 nodes; the ts_rank subtree
    # (3 nodes) matches, the two parameter leaves do not -> 2 * 3 / 10
    integer = parse("ts_rank(close, 2) + $a=1")
    floating = parse("ts_rank(close, 2) + $a:float=1.0")
    assert common_subtree_nodes(integer, floating) == 3
    assert similarity(integer, floating) == pytest.approx(0.6)


def test_a_parameter_keeps_matching_itself_under_another_name() -> None:
    # ts_mean(close, $n=20) vs ts_mean(close, $m:int[5,50]=10): both ts_mean(close, $int)
    assert (
        similarity(parse("ts_mean(close, $n=20)"), parse("ts_mean(close, $m:int[5,50]=10)")) == 1.0
    )


def test_two_different_features_share_only_the_operator_topology_leaves() -> None:
    # ts_mean(close, 5) vs ts_mean(volume, 5): the feature differs, `5` is shared -> 2 * 1 / 6
    assert similarity(parse("ts_mean(close, 5)"), parse("ts_mean(volume, 5)")) == pytest.approx(
        1 / 3
    )


def test_similarity_is_symmetric_and_bounded() -> None:
    pairs = [
        ("ts_mean(close, 5)", "ts_rank(close, 2)"),
        ("close/open", "close/open + volume/volume"),
        ("sign(delta(close, 1))", "abs(delta(close, 2))"),
    ]
    for left, right in pairs:
        first = similarity(parse(left), parse(right))
        second = similarity(parse(right), parse(left))
        assert first == pytest.approx(second)
        assert 0.0 <= first <= 1.0


def test_no_common_complete_subtree_is_zero() -> None:
    # close vs volume: two different one-node subtrees, nothing shared
    assert common_subtree_nodes(parse("close"), parse("volume")) == 0
    assert similarity(parse("close"), parse("volume")) == 0.0
    assert similarity(parse("close"), parse("open")) == 0.0


# ------------------------------------------------------------------------------ pool queries


def test_pool_similarity_ranks_by_similarity_then_key() -> None:
    query = parse("ts_mean(close, 5)")  # 3 nodes
    pool = {
        "same": parse("ts_mean(close, 5)"),  # 3 nodes, 3 shared -> 6/6
        "extended": parse("ts_mean(close, 5) + close"),  # 5 nodes, 3 shared -> 6/8
        "renamed": parse("ts_mean(close, $n=20)"),  # 3 nodes, 1 shared -> 2/6
        "other feature": parse("ts_mean(volume, 5)"),  # 3 nodes, literal 5 shared -> 2/6
    }
    hits = pool_similarity(query, pool)
    assert [hit.key for hit in hits] == ["same", "extended", "other feature", "renamed"]
    assert hits[0].similarity == 1.0
    assert hits[0].common_nodes == 3
    assert hits[1].similarity == pytest.approx(0.75)
    assert hits[2].similarity == pytest.approx(1 / 3)
    assert hits[3].similarity == pytest.approx(1 / 3)
    # the ties are ordered by key, not by dict order
    assert hits[2].key < hits[3].key


def test_pool_similarity_reports_each_members_structure_id() -> None:
    query = parse("ts_mean(close, 5)")
    compiled = compile_expression("ts_mean(close, $n=20)", signal_input="unadjusted")
    hits = pool_similarity(query, {"compiled": compiled})
    assert hits[0].structure_id == compiled.structure_id
    assert hits[0].common_nodes == 1
    assert hits[0].similarity == pytest.approx(1 / 3)


def test_max_similarity_is_the_first_hit_or_none() -> None:
    query = parse("ts_mean(close, 5)")
    pool = {"same": parse("ts_mean(close, 5)"), "other": parse("ts_mean(volume, 5)")}
    best = max_similarity(query, pool)
    assert isinstance(best, SimilarityHit)
    assert best.key == "same"
    assert max_similarity(query, {}) is None


def test_a_pool_member_must_be_an_expression_or_a_compiled_signal() -> None:
    with pytest.raises(ConfigurationError, match="Expression or a CompiledSignal"):
        pool_similarity(parse("close"), {"bad": "ts_mean(close, 5)"})  # type: ignore[dict-item]
