"""Walk-forward folds and the walk-forward file's contract (Fathom C5b, ADR-0101 decision 2).

Every fold boundary here is written out by hand from the rule in the ADR: fold k tests on trade
dates ``[N + k*M, N + (k+1)*M)`` and trains on the N dates before that (``rolling``) or on every
date from the first one (``anchored``). A trailing remainder shorter than the test window is
reported, never evaluated on a shorter window, and a window that cannot hold one complete fold is
refused.

No store is touched: ``walkforward_folds`` reads trade dates, and ``load_futures_walkforward``
reads two YAML files.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest
import yaml

from crucible.core.errors import ConfigurationError
from crucible.experiments.futures_walkforward import (
    FOLD_STATUSES,
    SCHEMES,
    load_futures_walkforward,
    walkforward_folds,
    walkforward_id,
)

BASE = """kind: futures_run
run: {name: base, family: wf-unit}
root: ES
window: {start: 2024-01-02, end: 2024-06-28}
strategy: {expression: "sign(ts_zscore(close, 2))"}
contracts: 1
capital: "50000"
costs: {commission: "2.00"}
"""

Z60 = "if(ts_zscore(close, $n:int[10,240]=60) < -2, 1, if(ts_zscore(close, $n) > 2, -1, 0))"


def dates(count: int, *, first: str = "2024-03-04") -> tuple[dt.date, ...]:
    """``count`` consecutive Globex trade dates (weekdays: the label, not the session table)."""
    day = dt.date.fromisoformat(first)
    out: list[dt.date] = []
    while len(out) < count:
        if day.weekday() < 5:
            out.append(day)
        day += dt.timedelta(days=1)
    return tuple(out)


def _write(directory: Path, payload: dict[str, object], name: str = "wf.yaml") -> Path:
    path = directory / name
    path.write_text(yaml.safe_dump(payload), encoding="utf-8")
    return path


def _base(directory: Path) -> Path:
    path = directory / "base.yaml"
    path.write_text(BASE, encoding="utf-8")
    return path


def _file(directory: Path, **overrides: object) -> Path:
    """A valid walk-forward file on top of ``base.yaml``, with ``overrides`` merged in."""
    _base(directory)
    payload: dict[str, object] = {
        "kind": "futures_walkforward",
        "base": "base.yaml",
        "candidates": [{"name": "z60", "expression": Z60}],
        "train_trade_dates": 4,
        "test_trade_dates": 3,
        "scheme": "rolling",
        "constraints": {"max_intraday_drawdown_usd": "5000"},
    }
    payload.update(overrides)
    return _write(directory, payload)


# ---------------------------------------------------------------------------------------------
# the fold geometry


def test_rolling_folds_are_the_n_dates_before_each_test_window() -> None:
    trade_dates = dates(12)
    folds, unused = walkforward_folds(
        trade_dates, train_trade_dates=4, test_trade_dates=3, scheme="rolling"
    )
    assert len(folds) == 2
    assert [fold.index for fold in folds] == [0, 1]
    # fold 0: train dates 0..3, test dates 4..6
    assert folds[0].train == trade_dates[0:4]
    assert folds[0].test == trade_dates[4:7]
    # fold 1: train dates 3..6 (the four immediately before), test dates 7..9
    assert folds[1].train == trade_dates[3:7]
    assert folds[1].test == trade_dates[7:10]
    # the two trailing dates cannot fill a 3-date test window: reported, not evaluated
    assert unused == trade_dates[10:12]
    # the test windows are contiguous and never overlap
    assert folds[0].test[-1] < folds[1].test[0]
    assert folds[0].test[0] != folds[1].test[0]


def test_anchored_folds_train_on_every_date_from_the_first_one() -> None:
    trade_dates = dates(12)
    folds, unused = walkforward_folds(
        trade_dates, train_trade_dates=4, test_trade_dates=3, scheme="anchored"
    )
    assert [fold.test for fold in folds] == [
        trade_dates[4:7],
        trade_dates[7:10],
    ]
    assert folds[0].train == trade_dates[0:4]
    assert folds[1].train == trade_dates[0:7]  # every date before its test window
    assert unused == trade_dates[10:12]


def test_no_remainder_leaves_no_unused_dates() -> None:
    trade_dates = dates(10)
    folds, unused = walkforward_folds(
        trade_dates, train_trade_dates=4, test_trade_dates=3, scheme="rolling"
    )
    assert len(folds) == 2
    assert unused == ()


def test_a_window_that_cannot_hold_one_fold_is_refused() -> None:
    with pytest.raises(ConfigurationError, match="fewer"):
        walkforward_folds(dates(6), train_trade_dates=4, test_trade_dates=3, scheme="rolling")
    # exactly one complete fold is enough
    folds, unused = walkforward_folds(
        dates(7), train_trade_dates=4, test_trade_dates=3, scheme="rolling"
    )
    assert len(folds) == 1
    assert unused == ()


def test_an_unknown_scheme_and_empty_windows_are_refused() -> None:
    with pytest.raises(ConfigurationError, match="not a walk-forward scheme"):
        walkforward_folds(dates(9), train_trade_dates=2, test_trade_dates=2, scheme="expanding")
    with pytest.raises(ConfigurationError, match="at least one trade date"):
        walkforward_folds(dates(9), train_trade_dates=0, test_trade_dates=2, scheme="rolling")
    with pytest.raises(ConfigurationError, match="at least one trade date"):
        walkforward_folds(dates(9), train_trade_dates=2, test_trade_dates=0, scheme="rolling")


# ---------------------------------------------------------------------------------------------
# the file


def test_the_file_loads_and_its_scheme_must_be_known(tmp_path: Path) -> None:
    loaded = load_futures_walkforward(_file(tmp_path))
    assert loaded.file.scheme == "rolling"
    assert not hasattr(loaded.file, "unexpected")
    assert [candidate.name for candidate in loaded.candidates] == ["z60"]
    assert loaded.base.run.family == "wf-unit"
    # the warm-up is the file's, and the base's when the file leaves it null
    assert loaded.warmup_trade_dates == 0
    with pytest.raises(ConfigurationError, match="scheme"):
        load_futures_walkforward(_file(tmp_path, scheme="diagonal"))


def test_the_warmup_overrides_the_base(tmp_path: Path) -> None:
    base = tmp_path / "base.yaml"
    base.write_text(
        BASE.replace(
            "window: {start: 2024-01-02, end: 2024-06-28}",
            "window: {start: 2024-01-02, end: 2024-06-28, warmup_trade_dates: 3}",
        ),
        encoding="utf-8",
    )
    payload: dict[str, object] = {
        "kind": "futures_walkforward",
        "base": "base.yaml",
        "candidates": [{"name": "z60", "expression": Z60}],
        "train_trade_dates": 4,
        "test_trade_dates": 3,
        "scheme": "rolling",
        "constraints": {"max_intraday_drawdown_usd": "5000"},
    }
    path = _write(tmp_path, payload)
    # null keeps the base's warm-up
    assert load_futures_walkforward(path).warmup_trade_dates == 3
    # an explicit value overrides it
    payload["warmup_trade_dates"] = 5
    assert load_futures_walkforward(_write(tmp_path, payload)).warmup_trade_dates == 5


def test_an_extra_key_anywhere_is_refused(tmp_path: Path) -> None:
    for extra in ({"slippage": 1}, {"train_dates": 20}, {"constraints_extra": {}}):
        with pytest.raises(ConfigurationError, match="invalid"):
            load_futures_walkforward(_file(tmp_path, **extra))
    with pytest.raises(ConfigurationError, match="invalid"):
        load_futures_walkforward(
            _file(tmp_path, constraints={"max_intraday_drawdown_usd": "5000", "max_leverage": 2})
        )


def test_the_drawdown_ceiling_is_required(tmp_path: Path) -> None:
    path = _file(tmp_path, constraints={"max_fills": 10})
    with pytest.raises(ConfigurationError, match="max_intraday_drawdown_usd"):
        load_futures_walkforward(path)
    path = _file(tmp_path, constraints={})
    with pytest.raises(ConfigurationError, match="max_intraday_drawdown_usd"):
        load_futures_walkforward(path)


def test_a_constraint_that_is_not_a_sane_number_is_refused(tmp_path: Path) -> None:
    for constraints in (
        {"max_intraday_drawdown_usd": 0},
        {"max_intraday_drawdown_usd": "-1"},
        {"max_intraday_drawdown_usd": "1.0000001"},
        {"max_intraday_drawdown_usd": "5000", "max_time_in_market": 0},
        {"max_intraday_drawdown_usd": "5000", "max_time_in_market": 1.5},
        {"max_intraday_drawdown_usd": "5000", "min_equity_usd": 0},
        {"max_intraday_drawdown_usd": "5000", "max_fills": True},
    ):
        with pytest.raises(ConfigurationError):
            load_futures_walkforward(_file(tmp_path, constraints=constraints))
    # a float amount is refused: money is exact
    with pytest.raises(ConfigurationError, match="exact"):
        load_futures_walkforward(_file(tmp_path, constraints={"max_intraday_drawdown_usd": 5000.0}))


def test_a_trade_date_count_that_is_a_bool_is_refused(tmp_path: Path) -> None:
    for key in ("train_trade_dates", "test_trade_dates"):
        with pytest.raises(ConfigurationError, match="bool"):
            load_futures_walkforward(_file(tmp_path, **{key: True}))


def test_a_candidate_that_would_change_the_conditions_is_refused(tmp_path: Path) -> None:
    path = _file(tmp_path, candidates=[{"name": "c", "expression": Z60, "contracts": 3}])
    with pytest.raises(ConfigurationError, match="exactly name, expression and params"):
        load_futures_walkforward(path)


def test_two_candidates_cannot_share_a_name(tmp_path: Path) -> None:
    path = _file(
        tmp_path,
        candidates=[
            {"name": "same", "expression": Z60},
            {"name": "same", "expression": Z60, "params": {"n": 120}},
        ],
    )
    with pytest.raises(ConfigurationError, match="more than once"):
        load_futures_walkforward(path)


def test_a_missing_base_config_is_refused(tmp_path: Path) -> None:
    path = _file(tmp_path, base="no_such_base.yaml")
    with pytest.raises(ConfigurationError, match=r"no_such_base\.yaml"):
        load_futures_walkforward(path)


def test_the_walkforward_id_covers_the_submission_not_the_path(tmp_path: Path) -> None:
    first = load_futures_walkforward(_file(tmp_path))
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    second = load_futures_walkforward(_file(elsewhere))
    assert walkforward_id(first.base, first.file) == walkforward_id(second.base, second.file)
    other = load_futures_walkforward(_file(tmp_path, test_trade_dates=4))
    assert walkforward_id(other.base, other.file) != walkforward_id(first.base, first.file)


def test_the_closed_sets_are_the_adr_s() -> None:
    assert SCHEMES == ("rolling", "anchored")
    assert FOLD_STATUSES == ("selected", "no_eligible_candidate")
