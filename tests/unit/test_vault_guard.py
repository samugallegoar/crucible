"""The holdout vault's data-layer guard (C6c, ADR-0105 decision 3).

Every test uses a THROWAWAY store root and a THROWAWAY home: nothing here touches a real dataset,
the real store or the real Crucible home. The datasets are synthetic bars named after a declared
root (``es_bars``), because the guard matches by ROOT, not by content, and that is the whole point
of a family-wide lock.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import duckdb
import polars as pl
import pytest

from crucible.core.errors import ConfigurationError, VaultLockedError
from crucible.core.types import DatasetId, TimestampNs
from crucible.data.contracts import BAR_SCHEMA, BAR_SORT_KEYS
from crucible.data.store import ParquetDataStore, build_dataset
from crucible.data.vault import (
    DECLARATION_FILE,
    VaultDeclaration,
    VaultGuard,
    VaultSession,
    clear_guard_cache,
    close_vault_session,
    declare_vault,
    first_protected_session,
    home_root,
    load_declaration,
    open_vault_session,
    protected_datasets,
    refuse_protected_window,
    vault_start_ns,
)

ROOTS = ("ES", "NQ", "YM", "RTY", "NKD")
START = dt.date(2025, 1, 1)
"""The declared start of the C6c vault (ADR-0105 decision 1)."""
VAULT_START_NS = 1_735_686_000_000_000_000
"""2024-12-31T23:00:00Z: the scheduled 17:00 CT open of the first protected Globex trade date."""


def _bars(name: str, store: Path, times: list[int]) -> None:
    rows = {
        "symbol": ["ES"] * len(times),
        "event_time": times,
        "available_at": times,
        "open": [4400.0] * len(times),
        "high": [4401.0] * len(times),
        "low": [4399.0] * len(times),
        "close": [4400.0] * len(times),
        "volume": [10.0] * len(times),
    }
    build_dataset(
        store,
        DatasetId(name),
        pl.DataFrame(rows),
        schema=BAR_SCHEMA,
        sort_keys=BAR_SORT_KEYS,
        source="test;synthetic",
    )


@pytest.fixture
def store(tmp_path: Path) -> Path:
    root = tmp_path / "store"
    root.mkdir()
    _bars("es_bars", root, [VAULT_START_NS - 60, VAULT_START_NS + 60])
    _bars("px", root, [VAULT_START_NS - 60, VAULT_START_NS + 60])
    return root


@pytest.fixture
def home(tmp_path: Path) -> Path:
    return tmp_path / "home"


def _declare(
    store: Path,
    home: Path,
    *,
    universe: tuple[str, ...] = ROOTS,
    start: dt.date = START,
    scope: str = "family",
    both: bool = True,
) -> VaultDeclaration:
    declaration = declare_vault(
        store_root=store,
        home=home,
        universe=list(universe),
        start_trade_date=start,
        scope=scope,  # type: ignore[arg-type]
        audit_ref="the exposure audit of 2026-11-19 (ADR-0105)",
    )
    if not both:
        (store / DECLARATION_FILE).unlink()
    clear_guard_cache()
    return declaration


def _store(store: Path, home: Path) -> ParquetDataStore:
    clear_guard_cache()
    return ParquetDataStore(store, home=home)


# ------------------------------------------------------------------------------- the start


def test_the_vault_starts_at_the_open_of_the_first_protected_session() -> None:
    """2025-01-01's Globex session opens at 17:00 CT on 2024-12-31, which is 23:00 UTC."""
    declaration = VaultDeclaration(
        vault_id="VLT-0000000000000000",
        universe=ROOTS,
        start_trade_date=START,
        end_trade_date=None,
        scope="family",
        declared_at="2026-11-21T00:00:00Z",
        audit_ref="audit",
        protected_datasets=(),
    )
    day, start_ns = first_protected_session(declaration)
    assert day == dt.date(2025, 1, 1)
    assert start_ns == VAULT_START_NS
    assert vault_start_ns(declaration) == VAULT_START_NS
    assert (
        dt.datetime.fromtimestamp(start_ns / 1e9, tz=dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        == "2024-12-31T23:00:00Z"
    )


# ------------------------------------------------------------------------------- reads


def test_a_read_before_the_start_is_admitted_and_logged(store: Path, home: Path) -> None:
    _declare(store, home)
    frame = _store(store, home).read(DatasetId("es_bars"), TimestampNs(VAULT_START_NS - 1))
    assert frame.collect().height == 1  # the one bar before the start
    rows = _access_log(home)
    assert [row["outcome"] for row in rows] == ["allowed"]
    assert rows[0]["dataset"] == "es_bars"
    assert rows[0]["as_of"] == VAULT_START_NS - 1


@pytest.mark.parametrize("as_of", [VAULT_START_NS, VAULT_START_NS + 1, 2**63 - 1])
def test_a_read_at_or_after_the_start_is_refused_and_logged(
    store: Path, home: Path, as_of: int
) -> None:
    _declare(store, home)
    with pytest.raises(VaultLockedError) as caught:
        _store(store, home).read(DatasetId("es_bars"), TimestampNs(as_of)).collect()
    message = str(caught.value)
    assert "futures holdout vault" in message
    assert "crucible vault register" in message
    assert "crucible vault authorize" in message
    rows = _access_log(home)
    assert rows[-1]["outcome"] == "refused"
    assert rows[-1]["as_of"] == as_of


def test_a_whole_file_access_is_refused_unless_it_is_metadata(store: Path, home: Path) -> None:
    _declare(store, home)
    data = _store(store, home)
    with pytest.raises(VaultLockedError):
        data.data_path(DatasetId("es_bars"))
    assert _access_log(home)[-1]["outcome"] == "refused"
    # the metadata view is allowed, logged, and returns no row of the protected period
    path = data.data_path(DatasetId("es_bars"), purpose="metadata")
    assert path.is_file()
    assert _access_log(home)[-1]["outcome"] == "allowed_metadata"


def test_a_metadata_read_never_returns_a_protected_row(store: Path, home: Path) -> None:
    _declare(store, home)
    frame = (
        _store(store, home)
        .read(DatasetId("es_bars"), TimestampNs(2**63 - 1), purpose="metadata")
        .collect()
    )
    assert frame["event_time"].to_list() == [VAULT_START_NS - 60]
    assert _access_log(home)[-1]["outcome"] == "allowed_metadata"


def test_an_unrelated_dataset_is_neither_locked_nor_logged(store: Path, home: Path) -> None:
    _declare(store, home)
    frame = _store(store, home).read(DatasetId("px"), TimestampNs(2**63 - 1))
    assert frame.collect().height == 2
    assert _access_log(home) == []


# ------------------------------------------------------------------------------- the copies


def test_either_copy_enforces_the_vault(store: Path, home: Path) -> None:
    _declare(store, home)
    # the store copy alone locks the period
    (home / DECLARATION_FILE).unlink()
    clear_guard_cache()
    with pytest.raises(VaultLockedError):
        _store(store, home).read(DatasetId("es_bars"), TimestampNs(VAULT_START_NS)).collect()
    # now the HOME copy alone locks it: copying the store somewhere else does not lift it
    _declare(store, home)
    (store / DECLARATION_FILE).unlink()
    clear_guard_cache()
    with pytest.raises(VaultLockedError):
        _store(store, home).read(DatasetId("es_bars"), TimestampNs(VAULT_START_NS)).collect()
    other = store.parent / "copied-store"
    other.mkdir()
    _bars("es_bars", other, [VAULT_START_NS])
    clear_guard_cache()
    with pytest.raises(VaultLockedError):
        _store(other, home).read(DatasetId("es_bars"), TimestampNs(VAULT_START_NS)).collect()
    # switching home lifts nothing either
    _declare(store, home)
    with pytest.raises(VaultLockedError):
        _store(store, store.parent / "another-home").read(
            DatasetId("es_bars"), TimestampNs(VAULT_START_NS)
        ).collect()


def test_two_disagreeing_copies_are_refused(store: Path, home: Path) -> None:
    _declare(store, home)
    document = json.loads((home / DECLARATION_FILE).read_text(encoding="utf-8"))
    document["start_trade_date"] = "2025-06-01"
    (home / DECLARATION_FILE).write_text(json.dumps(document), encoding="utf-8")
    clear_guard_cache()
    with pytest.raises(ConfigurationError) as caught:
        load_declaration(store, home=home)
    assert "disagree" in str(caught.value)


# ------------------------------------------------------------------------------- widening only


def test_a_declaration_can_only_be_widened(store: Path, home: Path) -> None:
    _declare(store, home)
    # an earlier start is a widening
    widened = _declare(store, home, start=dt.date(2024, 6, 1))
    assert widened.start_trade_date == dt.date(2024, 6, 1)
    # a later start is a narrowing and is refused
    with pytest.raises(ConfigurationError) as caught:
        _declare(store, home, start=dt.date(2025, 6, 1))
    assert "LOCK LESS" in str(caught.value)
    # dropping a root is a narrowing
    with pytest.raises(ConfigurationError) as caught:
        _declare(store, home, start=dt.date(2024, 6, 1), universe=("ES",))
    assert "un-protect" in str(caught.value)
    # narrowing the family lock to a single root is refused
    with pytest.raises(ConfigurationError):
        declare_vault(
            store_root=store,
            home=home,
            universe=["ES"],
            start_trade_date=dt.date(2024, 1, 1),
            scope="root",
            audit_ref="sneaky",
        )
    # an end date is a narrowing (the vault is open-ended)
    with pytest.raises(ConfigurationError) as caught:
        declare_vault(
            store_root=store,
            home=home,
            universe=list(ROOTS),
            start_trade_date=dt.date(2024, 6, 1),
            audit_ref="closed",
            end_trade_date=dt.date(2025, 12, 31),
        )
    assert "open-ended" in str(caught.value)


def test_a_root_scope_vault_needs_exactly_one_root(store: Path, home: Path) -> None:
    with pytest.raises(ConfigurationError) as caught:
        declare_vault(
            store_root=store,
            home=home,
            universe=["ES", "NQ"],
            start_trade_date=START,
            scope="root",
            audit_ref="two roots",
        )
    assert "exactly one root" in str(caught.value)
    declaration = _declare(store, home, universe=("ES",), scope="root")
    assert declaration.scope == "root"
    assert load_declaration(store, home=home) == declaration


# ------------------------------------------------------------------------------- the family


def test_another_root_of_the_family_does_not_bypass_the_vault(store: Path, home: Path) -> None:
    _declare(store, home)
    _bars("nq_bars", store, [VAULT_START_NS])
    clear_guard_cache()
    with pytest.raises(VaultLockedError):
        _store(store, home).read(DatasetId("nq_bars"), TimestampNs(VAULT_START_NS)).collect()


def test_a_new_trial_family_name_is_not_a_door(store: Path, home: Path) -> None:
    """The lock is by dataset ROOT, not by family name: nothing in the guard reads a family."""
    _declare(store, home)
    assert _store(store, home).guard is not None
    guard = _store(store, home).guard
    assert guard is not None
    for name in ("es_bars", "ES_BARS", "es_1m_cont_v3", "es_1m_raw"):
        assert guard.protects(name), name
    assert not guard.protects("equities_daily_v1")


def test_protected_datasets_are_found_by_id_and_by_manifest(store: Path, home: Path) -> None:
    document_root = store / "export_v1"
    document_root.mkdir()
    _bars("export_v1", store, [VAULT_START_NS])
    manifest = json.loads((document_root / "manifest.json").read_text(encoding="utf-8"))
    manifest["source"] = "continuous:v3;root=ES;synthetic"
    (document_root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    declaration = _declare(store, home)
    found = protected_datasets(store, declaration)
    assert "es_bars" in found
    assert "export_v1" in found
    assert "px" not in found


# ------------------------------------------------------------------------------- the session


def test_a_session_admits_its_own_datasets_and_clips_at_the_window_end(
    store: Path, home: Path
) -> None:
    _declare(store, home)
    data = _store(store, home)
    session = VaultSession(
        vr_id="VR-0000000000000000",
        datasets=frozenset({"es_bars"}),
        window_end_ns=VAULT_START_NS,
    )
    scope = open_vault_session(session)
    try:
        frame = data.read(DatasetId("es_bars"), TimestampNs(VAULT_START_NS)).collect()
        # the session admits the registered dataset up to the registered window end
        assert frame["event_time"].to_list() == [VAULT_START_NS - 60]
        assert _access_log(home)[-1]["outcome"] == "allowed_evaluation"
        assert _access_log(home)[-1]["vr_id"] == "VR-0000000000000000"
        # a dataset the registration does not name is still refused
        _bars("nq_bars", store, [VAULT_START_NS])
        with pytest.raises(VaultLockedError):
            data.read(DatasetId("nq_bars"), TimestampNs(VAULT_START_NS)).collect()
        assert _access_log(home)[-1]["outcome"] == "refused_session_scope"
        # and reading past the registered window end is refused, even inside the session
        with pytest.raises(VaultLockedError) as caught:
            data.read(DatasetId("es_bars"), TimestampNs(2**63 - 1)).collect()
        assert "cannot read past the window" in str(caught.value)
    finally:
        close_vault_session(scope)
    # outside the session the same read is refused again
    with pytest.raises(VaultLockedError):
        data.read(DatasetId("es_bars"), TimestampNs(VAULT_START_NS)).collect()


def test_a_whole_file_inside_a_session_is_admitted(store: Path, home: Path) -> None:
    _declare(store, home)
    data = _store(store, home)
    scope = open_vault_session(
        VaultSession(
            vr_id="VR-0000000000000000",
            datasets=frozenset({"es_bars"}),
            window_end_ns=VAULT_START_NS,
        )
    )
    try:
        assert data.data_path(DatasetId("es_bars")).is_file()
    finally:
        close_vault_session(scope)


# ------------------------------------------------------------------------------- the window check


def test_a_run_window_that_reaches_the_vault_is_refused_before_any_read(
    store: Path, home: Path
) -> None:
    _declare(store, home)
    clear_guard_cache()
    with pytest.raises(VaultLockedError) as caught:
        refuse_protected_window(
            root="ES",
            start=dt.date(2025, 1, 2),
            end=dt.date(2025, 1, 3),
            store_root=store,
            home=home,
            what="the futures run 'demo'",
        )
    assert "the futures run 'demo'" in str(caught.value)
    # a window that ends the day before the vault is fine
    refuse_protected_window(
        root="ES",
        start=dt.date(2024, 1, 2),
        end=dt.date(2024, 12, 31),
        store_root=store,
        home=home,
        what="the futures run 'demo'",
    )
    # and an unrelated root has nothing to do with the ES family vault
    refuse_protected_window(
        root="CL",
        start=dt.date(2025, 1, 2),
        end=dt.date(2025, 1, 3),
        store_root=store,
        home=home,
        what="a crude oil run",
    )
    assert _access_log(home)[-1]["outcome"] == "refused_window"


# ------------------------------------------------------------------------------- the home


def test_the_vault_home_resolves_like_the_product_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``crucible.product`` sits above ``crucible.data`` in the layering rule, so the guard
    resolves the home itself; the two must agree (ADR-0068 order: env, settings, default)."""
    from crucible.product.home import HOME_ENV, resolve_home

    settings = tmp_path / "settings.json"
    monkeypatch.setenv("CRUCIBLE_SETTINGS", str(settings))
    monkeypatch.delenv(HOME_ENV, raising=False)
    assert home_root() == resolve_home(None).root
    configured = tmp_path / "from-settings"
    settings.write_text(json.dumps({"home": str(configured)}), encoding="utf-8")
    assert home_root() == resolve_home(None).root == configured.resolve()
    from_env = tmp_path / "from-env"
    monkeypatch.setenv(HOME_ENV, str(from_env))
    assert home_root() == resolve_home(None).root == from_env.resolve()


# ------------------------------------------------------------------------------- the log


def _access_log(home: Path) -> list[dict[str, object]]:
    """Every access-log row of ``home``, oldest first (an empty home has no log)."""
    path = home / "vault.duckdb"
    if not path.is_file():
        return []
    with duckdb.connect(str(path)) as connection:
        try:
            rows = connection.execute(
                "SELECT seq, ts, caller, purpose, dataset, as_of, outcome, vr_id, detail "
                "FROM access_log ORDER BY seq"
            ).fetchall()
        except duckdb.CatalogException:
            return []
    return [
        {
            "seq": int(row[0]),
            "ts": str(row[1]),
            "caller": str(row[2]),
            "purpose": str(row[3]),
            "dataset": str(row[4]),
            "as_of": None if row[5] is None else int(row[5]),
            "outcome": str(row[6]),
            "vr_id": None if row[7] is None else str(row[7]),
            "detail": str(row[8]),
        }
        for row in rows
    ]


def test_every_attempt_is_logged_both_ways(store: Path, home: Path) -> None:
    _declare(store, home)
    data = _store(store, home)
    data.read(DatasetId("es_bars"), TimestampNs(VAULT_START_NS - 1)).collect()
    with pytest.raises(VaultLockedError):
        data.read(DatasetId("es_bars"), TimestampNs(VAULT_START_NS)).collect()
    with pytest.raises(VaultLockedError):
        data.data_path(DatasetId("es_bars"))
    data.data_path(DatasetId("es_bars"), purpose="metadata")
    outcomes = [row["outcome"] for row in _access_log(home)]
    assert outcomes == ["allowed", "refused", "refused", "allowed_metadata"]
    assert [row["seq"] for row in _access_log(home)] == [1, 2, 3, 4]
    # the log has no UPDATE and no DELETE: the rows only accumulate
    guard = data.guard
    assert isinstance(guard, VaultGuard)
    with pytest.raises(VaultLockedError):
        guard.check_read(DatasetId("es_bars"), TimestampNs(VAULT_START_NS), caller="unit test")
    assert _access_log(home)[-1]["caller"] == "unit test"
