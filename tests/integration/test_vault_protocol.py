"""The holdout vault protocol, end to end (C6c, ADR-0105): register, a HUMAN authorizes, and ONE
evaluation per registration.

Every path here is a throwaway: a synthetic ES store whose trade dates are INSIDE the vault
(2025-01-06 and 2025-01-07, built here, never read from a real dataset), a throwaway home for
``vault.duckdb`` and the admin token, and a throwaway artifacts root. The admin token is created by
the test for its own home and is never printed.

What is enforced (the acceptance list of ADR-0105 decisions 4-7):

- an evaluation without an authorization is refused and logged;
- a wrong admin token is refused and logged, and ``CRUCIBLE_VAULT_TOKEN`` is the non-interactive
  way to supply the right one;
- a config EDITED after registration is refused, because its hash is no longer the registered one;
- the first evaluation seals its artifact under ``VAULT/<VR-...>/``, increments the persistent open
  counter, and moves the status to ``evaluated``; a second evaluation is refused and the counter
  stays where it is;
- a crash inside the evaluation still consumes it;
- a run, batch or walk-forward whose window reaches the vault is refused before any read;
- nothing about the protected period is readable before the evaluation (status and log carry no
  metric);
- the MCP server exposes status/register/log only: no authorize, no evaluate, no set-admin;
- ``set_admin`` refuses a non-TTY, and the token never appears in a file or a log.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import json
from pathlib import Path

import polars as pl
import pytest
import yaml

from crucible.core.errors import ConfigurationError, ExperimentError, VaultLockedError
from crucible.core.types import DatasetId
from crucible.data.calendars import chicago_wall_to_utc_ns
from crucible.data.contracts import (
    BAR_SCHEMA,
    BAR_SORT_KEYS,
    CONTINUOUS_BAR_SCHEMA,
    CONTINUOUS_BAR_SORT_KEYS,
    ROLL_SCHEMA,
    ROLL_SORT_KEYS,
)
from crucible.data.store import build_dataset
from crucible.data.vault import DECLARATION_FILE, VAULT_DB_FILE, clear_guard_cache
from crucible.experiments.artifact_id import verify_artifact
from crucible.experiments.futures_batch import run_futures_batch
from crucible.experiments.futures_compare import _pool_ids, load_member
from crucible.experiments.futures_run import run_futures
from crucible.experiments.futures_trials import futures_effective_trials
from crucible.experiments.futures_walkforward import run_futures_walkforward
from crucible.experiments.vault import (
    VAULT_ARTIFACTS_DIR,
    VaultRegistry,
    registry_for,
    set_admin,
    write_admin_secret,
)

ESH, ESM = "ESH2025", "ESM2025"
FACTOR = {ESH: 1.01, ESM: 1.0}
PRICE_COLUMNS = ("open", "high", "low", "close")
DAY1, DAY2 = "2025-01-06", "2025-01-07"
CLOSES = {
    DAY1: [6000.00, 6001.00, 6002.00, 6003.00, 6004.00],
    DAY2: [6003.75, 6003.00, 6002.25, 6001.50, 6000.75],
}
WALLS = ["09:01", "09:02", "09:03", "09:04", "09:05"]
FAMILY = "es-vault-acceptance"
TOKEN = "throwaway-vault-admin-token-4f2a9c"
"""A token this test generates for its OWN throwaway home. It is never logged or printed."""


def utc(wall: str) -> int:
    """UTC ns of a naive America/Chicago wall clock."""
    return chicago_wall_to_utc_ns([dt.datetime.fromisoformat(wall)])[0]


def _ohlc(close: float) -> tuple[float, float, float, float]:
    return (close - 0.25, close + 0.50, close - 0.50, close)


def _continuous() -> pl.DataFrame:
    rows: list[tuple[int, str, tuple[float, float, float, float]]] = []
    for day, contract in ((DAY1, ESH), (DAY2, ESM)):
        for wall, close in zip(WALLS, CLOSES[day], strict=True):
            rows.append((utc(f"{day} {wall}"), contract, _ohlc(close)))
    return pl.DataFrame(
        {
            "symbol": ["ES"] * len(rows),
            "event_time": [t for t, _, _ in rows],
            "available_at": [t + 1 for t, _, _ in rows],
            "open": [p[0] for _, _, p in rows],
            "high": [p[1] for _, _, p in rows],
            "low": [p[2] for _, _, p in rows],
            "close": [p[3] for _, _, p in rows],
            "volume": [100.0] * len(rows),
            "contract": [contract for _, contract, _ in rows],
        },
        schema=CONTINUOUS_BAR_SCHEMA,
    )


def _ratio(execution: pl.DataFrame) -> pl.DataFrame:
    factors = pl.Series([FACTOR[contract] for contract in execution["contract"]])
    return execution.with_columns([(pl.col(name) * factors).alias(name) for name in PRICE_COLUMNS])


def _raw() -> pl.DataFrame:
    rows: list[tuple[int, str, tuple[float, float, float, float]]] = []
    for wall, close in zip(WALLS, CLOSES[DAY1], strict=True):
        rows.append((utc(f"{DAY1} {wall}"), ESH, _ohlc(close)))
    rows.append((utc(f"{DAY2} 09:01"), ESH, _ohlc(6004.50)))
    for wall, close in zip(WALLS, CLOSES[DAY2], strict=True):
        rows.append((utc(f"{DAY2} {wall}"), ESM, _ohlc(close)))
    return pl.DataFrame(
        {
            "symbol": [symbol for _, symbol, _ in rows],
            "event_time": [t for t, _, _ in rows],
            "available_at": [t + 1 for t, _, _ in rows],
            "open": [p[0] for _, _, p in rows],
            "high": [p[1] for _, _, p in rows],
            "low": [p[2] for _, _, p in rows],
            "close": [p[3] for _, _, p in rows],
            "volume": [100.0] * len(rows),
        },
        schema=BAR_SCHEMA,
    )


def build_store(root: Path) -> Path:
    """The four synthetic ES datasets, on trade dates INSIDE the vault (2025-01-06/07)."""
    root.mkdir(parents=True, exist_ok=True)
    execution = _continuous()
    decision = utc(f"{DAY1} 16:00")
    build_dataset(
        root,
        DatasetId("es_1m_cont_v3"),
        execution,
        schema=CONTINUOUS_BAR_SCHEMA,
        sort_keys=CONTINUOUS_BAR_SORT_KEYS,
        source="continuous:v3;price_basis=raw;adjustment=none;root=ES;synthetic",
    )
    build_dataset(
        root,
        DatasetId("es_1m_cont_ratio_v3"),
        _ratio(execution),
        schema=CONTINUOUS_BAR_SCHEMA,
        sort_keys=CONTINUOUS_BAR_SORT_KEYS,
        source="continuous:v3;price_basis=adjusted;adjustment=ratio;root=ES;synthetic",
    )
    build_dataset(
        root,
        DatasetId("es_1m_rolls_v3"),
        pl.DataFrame(
            {
                "symbol": ["ES"],
                "event_time": [decision],
                "available_at": [decision],
                "from_contract": [ESH],
                "to_contract": [ESM],
                "effective_trade_date": [DAY2],
                "reference_time": [decision],
                "from_price": [6003.25],
                "to_price": [6004.25],
                "ratio": [6004.25 / 6003.25],
                "gap_points": [1.0],
                "reason": ["volume"],
            },
            schema=ROLL_SCHEMA,
        ),
        schema=ROLL_SCHEMA,
        sort_keys=ROLL_SORT_KEYS,
        source="continuous:v3;rolls;root=ES;synthetic",
    )
    build_dataset(
        root,
        DatasetId("es_1m_raw"),
        _raw(),
        schema=BAR_SCHEMA,
        sort_keys=BAR_SORT_KEYS,
        source="import:databento;price_basis=raw;rows_read=11;synthetic",
    )
    return root


def config_mapping(**overrides: object) -> dict[str, object]:
    """A valid futures-run config for the synthetic store, with the window INSIDE the vault."""
    base: dict[str, object] = {
        "kind": "futures_run",
        "run": {"name": "es-vault-demo", "family": FAMILY},
        "root": "ES",
        "window": {"start": DAY1, "end": DAY2},
        "strategy": {
            "spec": {"entry": {"long": "close > sma(2)"}, "exit": {"long": "close < sma(2)"}}
        },
        "contracts": 1,
        "capital": "50000",
        "costs": {"commission": "2.00"},
        # the 2025 CME table has trade dates whose schedule no transcribed source covers
        "session": {"allow_unverified_sessions": True},
    }
    out = json.loads(json.dumps(base))
    for path, value in overrides.items():
        parts = path.split(".")
        node: object = out
        for part in parts[:-1]:
            assert isinstance(node, dict)
            node = node.setdefault(part, {})
        assert isinstance(node, dict)
        node[parts[-1]] = value
    return out


def config_file(directory: Path, **overrides: object) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "config.yaml"
    path.write_text(yaml.safe_dump(config_mapping(**overrides)), encoding="utf-8")
    return path


@pytest.fixture
def store(tmp_path: Path) -> Path:
    return build_store(tmp_path / "store")


@pytest.fixture
def home(tmp_path: Path) -> Path:
    return tmp_path / "home"


@pytest.fixture
def registry(store: Path, home: Path, tmp_path: Path) -> VaultRegistry:
    from crucible.data.vault import declare_vault

    declare_vault(
        store_root=store,
        home=home,
        universe=["ES", "NQ", "YM", "RTY", "NKD"],
        start_trade_date=dt.date(2025, 1, 1),
        audit_ref="the exposure audit of 2026-11-19 (ADR-0105)",
    )
    write_admin_secret(home, TOKEN)
    clear_guard_cache()
    return registry_for(store_root=store, home=home, artifacts_root=tmp_path / "artifacts")


def _register(registry: VaultRegistry, path: Path) -> str:
    return registry.register(path).vr_id


@pytest.fixture
def authorized(registry: VaultRegistry, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> str:
    monkeypatch.setenv("CRUCIBLE_VAULT_TOKEN", TOKEN)
    vr_id = _register(registry, config_file(tmp_path / "cfg"))
    registry.authorize(vr_id)
    return vr_id


# ------------------------------------------------------------------- registration and authorization


def test_registration_records_the_hashes_and_starts_pending(
    registry: VaultRegistry, store: Path, tmp_path: Path
) -> None:
    path = config_file(tmp_path / "cfg")
    registration = registry.register(path)
    assert registration.vr_id.startswith("VR-")
    assert len(registration.vr_id) == len("VR-") + 16
    assert registration.status == "pending"
    assert registration.authorized_at is None
    assert registration.evaluated_at is None
    assert registration.artifact_id is None
    assert set(registration.dataset_hashes) == {
        "es_1m_cont_v3",
        "es_1m_cont_ratio_v3",
        "es_1m_rolls_v3",
        "es_1m_raw",
    }
    assert registration.candidate_id is not None
    assert registration.candidate_id.startswith("CND-")
    assert (registration.window_start, registration.window_end) == (
        dt.date(2025, 1, 6),
        dt.date(2025, 1, 7),
    )
    assert registry.opens() == 0
    # the same config and window are ONE registration, not a second trial
    with pytest.raises(ConfigurationError):
        registry.register(path)


def test_a_window_outside_the_vault_is_refused(registry: VaultRegistry, tmp_path: Path) -> None:
    path = config_file(tmp_path / "before", window={"start": "2024-03-05", "end": DAY2})
    with pytest.raises(ConfigurationError) as caught:
        registry.register(path)
    assert "must lie INSIDE the vault" in str(caught.value)


def test_evaluating_without_authorization_is_refused_and_logged(
    registry: VaultRegistry, tmp_path: Path
) -> None:
    vr_id = _register(registry, config_file(tmp_path / "cfg"))
    with pytest.raises(VaultLockedError) as caught:
        registry.evaluate(vr_id)
    assert "needs an authorization first" in str(caught.value)
    assert registry.opens() == 0
    outcomes = [row["outcome"] for row in registry.access_log(50)]
    assert "refused_evaluate_unauthorized" in outcomes
    registration = registry.registration(vr_id)
    assert registration is not None
    assert registration.status == "pending"


def test_a_wrong_admin_token_is_refused_and_logged(
    registry: VaultRegistry, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    vr_id = _register(registry, config_file(tmp_path / "cfg"))
    monkeypatch.setenv("CRUCIBLE_VAULT_TOKEN", "not-the-token")
    with pytest.raises(VaultLockedError) as caught:
        registry.authorize(vr_id)
    assert "does not verify" in str(caught.value)
    outcomes = [row["outcome"] for row in registry.access_log(50)]
    assert "refused_authorize_token" in outcomes
    registration = registry.registration(vr_id)
    assert registration is not None
    assert registration.status == "pending"


def test_authorization_with_the_environment_token_succeeds(
    registry: VaultRegistry, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    vr_id = _register(registry, config_file(tmp_path / "cfg"))
    monkeypatch.setenv("CRUCIBLE_VAULT_TOKEN", TOKEN)
    authorized = registry.authorize(vr_id)
    assert authorized.status == "authorized"
    assert authorized.authorized_at is not None
    assert "allowed_authorize" in [row["outcome"] for row in registry.access_log(50)]


def test_authorization_without_a_token_and_without_a_tty_is_refused(
    registry: VaultRegistry, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("CRUCIBLE_VAULT_TOKEN", raising=False)
    vr_id = _register(registry, config_file(tmp_path / "cfg"))
    with pytest.raises(ConfigurationError) as caught:
        registry.authorize(vr_id)
    assert "not interactive" in str(caught.value)


def test_set_admin_refuses_a_non_interactive_call(home: Path) -> None:
    home.mkdir(parents=True, exist_ok=True)
    with pytest.raises(ConfigurationError) as caught:
        set_admin(home=home)
    assert "interactive TTY" in str(caught.value)
    assert not (home / "vault_admin").exists()


# ------------------------------------------------------------------------------------ evaluation


def test_the_evaluation_seals_its_artifact_and_consumes_the_registration(
    registry: VaultRegistry, authorized: str, tmp_path: Path
) -> None:
    document = registry.evaluate(authorized)
    assert document["status"] == "evaluated"
    assert document["opens"] == 1
    assert registry.opens() == 1
    run_dir = Path(str(document["run_dir"]))
    assert run_dir.parent == tmp_path / "artifacts" / VAULT_ARTIFACTS_DIR / authorized
    assert verify_artifact(run_dir) == document["artifact_id"]
    registration = registry.registration(authorized)
    assert registration is not None
    assert registration.status == "evaluated"
    assert registration.artifact_id == document["artifact_id"]
    # the store's copy of the declaration mirrors the database's state
    mirror = json.loads((tmp_path / "store" / DECLARATION_FILE).read_text(encoding="utf-8"))
    assert mirror["opens"] == 1
    assert mirror["last_log_hash"]

    # a SECOND evaluation is refused, logged, and the counter stays where it is
    with pytest.raises(VaultLockedError) as caught:
        registry.evaluate(authorized)
    assert "already evaluated" in str(caught.value)
    assert registry.opens() == 1
    assert "refused_evaluate_second" in [row["outcome"] for row in registry.access_log(50)]


def test_a_config_edited_after_registration_refuses_the_evaluation(
    registry: VaultRegistry, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("CRUCIBLE_VAULT_TOKEN", TOKEN)
    path = config_file(tmp_path / "cfg")
    vr_id = _register(registry, path)
    registry.authorize(vr_id)
    # a single edited value changes the config hash, so the registration no longer describes it
    path.write_text(yaml.safe_dump(config_mapping(**{"contracts": 2})), encoding="utf-8")
    with pytest.raises(VaultLockedError) as caught:
        registry.evaluate(vr_id)
    assert "changed after it was registered" in str(caught.value)
    assert registry.opens() == 0
    assert "refused_evaluate_config" in [row["outcome"] for row in registry.access_log(50)]


def test_a_crash_inside_the_evaluation_still_consumes_it(
    registry: VaultRegistry,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def boom(*_args: object, **_kwargs: object) -> None:
        msg = "simulated crash inside the evaluation"
        raise RuntimeError(msg)

    vr_id = _register(registry, config_file(tmp_path / "cfg-crash"))
    monkeypatch.setenv("CRUCIBLE_VAULT_TOKEN", TOKEN)
    registry.authorize(vr_id)
    monkeypatch.setattr("crucible.experiments.vault.run_futures", boom)
    with pytest.raises(RuntimeError):
        registry.evaluate(vr_id)
    assert registry.opens() == 1
    registration = registry.registration(vr_id)
    assert registration is not None
    assert registration.status == "evaluated"
    assert registration.artifact_id is None
    assert "evaluate_failed" in [row["outcome"] for row in registry.access_log(50)]
    monkeypatch.undo()
    with pytest.raises(VaultLockedError):
        registry.evaluate(vr_id)
    assert registry.opens() == 1


# ------------------------------------------------------- the vault is closed outside an evaluation


def test_a_run_a_batch_and_a_walk_forward_reaching_the_vault_are_refused(
    registry: VaultRegistry, tmp_path: Path
) -> None:
    from crucible.experiments.futures_config import load_futures_config

    path = config_file(tmp_path / "cfg")
    with pytest.raises(VaultLockedError) as caught:
        run_futures(
            load_futures_config(path),
            store_root=registry.store_root,
            artifacts_root=tmp_path / "artifacts",
        )
    assert "holdout vault" in str(caught.value)

    batch = tmp_path / "batch.yaml"
    batch.write_text(
        yaml.safe_dump(
            {
                "kind": "futures_batch",
                "base": "cfg/config.yaml",
                "candidates": [{"name": "a", "expression": "close > sma($n:int=2)"}],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(VaultLockedError):
        run_futures_batch(
            batch, store_root=registry.store_root, artifacts_root=tmp_path / "artifacts"
        )

    walkforward = tmp_path / "walkforward.yaml"
    walkforward.write_text(
        yaml.safe_dump(
            {
                "kind": "futures_walkforward",
                "base": "cfg/config.yaml",
                "candidates": [{"name": "a", "expression": "close > sma($n:int=2)"}],
                "train_trade_dates": 1,
                "test_trade_dates": 1,
                "scheme": "rolling",
                "constraints": {"max_intraday_drawdown_usd": "5000"},
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(VaultLockedError):
        run_futures_walkforward(
            walkforward, store_root=registry.store_root, artifacts_root=tmp_path / "artifacts"
        )


def test_the_vault_artifact_is_out_of_every_pool_unless_asked_for(
    registry: VaultRegistry, authorized: str, tmp_path: Path
) -> None:
    document = registry.evaluate(authorized)
    run_id = str(document["run_id"])
    artifacts = tmp_path / "artifacts"
    assert run_id not in _pool_ids(artifacts)
    assert run_id in _pool_ids(artifacts, include_vault=True)
    with pytest.raises(ConfigurationError):
        load_member(artifacts, run_id)
    member = load_member(artifacts, run_id, include_vault=True)
    assert member.verified
    # the family's trial registry still counts the evaluation, so it deflates the DSR...
    report = futures_effective_trials(FAMILY, artifacts_root=artifacts)
    assert report.counts["total_trials"] >= 1
    # ...while the vault's series stays out of the correlation pool
    assert run_id not in {candidate.run_id for candidate in report.candidates}
    with_vault = futures_effective_trials(FAMILY, artifacts_root=artifacts, include_vault=True)
    assert run_id in {candidate.run_id for candidate in with_vault.candidates}


def test_status_and_log_report_no_metric(
    registry: VaultRegistry, authorized: str, tmp_path: Path
) -> None:
    registry.evaluate(authorized)
    status = json.dumps(registry.status().document(), sort_keys=True)
    log = json.dumps([dict(row) for row in registry.access_log(500)], sort_keys=True)
    for forbidden in ("sharpe", "dsr", "psr", "net_pnl", "final_equity"):
        assert forbidden not in status.lower()
        assert forbidden not in log.lower()


def test_a_database_behind_the_store_mirror_is_refused(
    registry: VaultRegistry, authorized: str, tmp_path: Path
) -> None:
    registry.evaluate(authorized)
    (registry.home / VAULT_DB_FILE).unlink()
    with pytest.raises(ExperimentError) as caught:
        registry.verify()
    assert "vault database" in str(caught.value)


# ------------------------------------------------------------------------------------ the agents


def test_the_mcp_server_exposes_no_authorize_evaluate_or_set_admin() -> None:
    from mcp import Client

    from crucible.mcp_server.server import build_server

    async def names() -> set[str]:
        async with Client(build_server()) as client:
            return {tool.name for tool in (await client.list_tools()).tools}

    tools = asyncio.run(names())
    vault_tools = {name for name in tools if "vault" in name}
    expected = {
        "crucible_vault_status",
        "crucible_vault_register",
        "crucible_vault_log",
    }
    # status/register/log only (ADR-0105): no authorize, no evaluate, no set-admin
    assert vault_tools == expected


def test_the_admin_token_never_reaches_a_file_or_a_log(
    registry: VaultRegistry, authorized: str, tmp_path: Path
) -> None:
    registry.evaluate(authorized)
    seen = 0
    for root in (registry.home, registry.store_root, tmp_path / "artifacts"):
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            seen += 1
        raw = path.read_bytes()
        assert TOKEN.encode() not in raw, f"the admin token was written to {path}"
    assert seen > 0
