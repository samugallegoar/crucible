"""The futures holdout vault's protocol: registration, human authorization, one evaluation (C6c).

``crucible.data.vault`` is the LOCK: it decides, on every read, whether the declared protected
period may be touched. This module is the PROTOCOL around it (ADR-0105 decisions 4-7), kept above
the data layer because it needs the futures config, the futures run and the artifact store:

- ``declare`` writes the declaration into the store root AND the Crucible home;
- ``register`` records ``VR-<16 hex>``: the COMPLETE config hash, the dataset content hashes, the
  candidate id, the evaluation window (which must lie inside the vault) and the requester. It reads
  no protected row (manifests only);
- ``authorize`` is a HUMAN step: it verifies the admin token (interactive TTY prompt, or
  ``CRUCIBLE_VAULT_TOKEN``) against a salted ``scrypt`` hash stored in ``<home>/vault_admin`` and
  moves the registration ``pending -> authorized``. Crucible never generates, prints or stores the
  token in clear;
- ``evaluate`` runs the registered config exactly once: it recomputes the config hash and the
  dataset hashes (a config or dataset changed after registration is refused and logged), increments
  the persistent open counter BEFORE reading anything (a crash consumes the evaluation), opens the
  data-layer :class:`~crucible.data.vault.VaultSession`, runs ``run_futures`` into
  ``<artifacts_root>/VAULT/<VR-...>/`` and seals the result, then moves the registration to
  ``evaluated``. A second evaluation of the same registration is refused and logged.

Persistence: ``<home>/vault.duckdb`` holds ``registrations``, ``counter`` and ``access_log``. The
code has NO UPDATE and NO DELETE except the two status transitions
(``pending -> authorized -> evaluated``) and the counter increment. ``<store>/vault.json`` mirrors
``{opens, last_log_hash}``; a database that is missing, behind that state, or whose log does not
contain the named row is refused.

Results stay hidden until the evaluation has run: ``status`` and ``log`` report statuses, counters
and access attempts, never a metric.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import getpass
import hashlib
import hmac
import json
import os
import secrets
import sys
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal

import duckdb
from pydantic import BaseModel, ConfigDict, Field

from crucible.core.errors import ConfigurationError, ExperimentError, VaultLockedError
from crucible.core.types import DatasetId
from crucible.data.cme_sessions import SessionCalendar
from crucible.data.continuous import calendar_for
from crucible.data.store import ParquetDataStore
from crucible.data.vault import (
    ADMIN_FILE,
    DECLARATION_FILE,
    VAULT_DB_FILE,
    VaultDeclaration,
    VaultSession,
    close_vault_session,
    current_vault_session,
    declare_vault,
    first_protected_session,
    home_root,
    load_declaration,
    open_vault_session,
)
from crucible.experiments.futures_config import (
    FuturesRunConfig,
    candidate_id,
    futures_config_hash,
    load_futures_config,
)
from crucible.experiments.futures_run import DATASET_ROLES, run_futures

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

REGISTRATION_PREFIX = "VR-"
"""``VR-`` + 16 hex digits (ADR-0105 decision 4)."""

VAULT_ARTIFACTS_DIR = "VAULT"
"""``<artifacts_root>/VAULT/<VR-...>/``: where a vault evaluation's sealed run lives, outside every
research pool (``compare`` and ``trials`` scan the top level only)."""

SCRYPT_N = 2**14
SCRYPT_R = 8
SCRYPT_P = 1
SCRYPT_DKLEN = 32
"""The ``hashlib.scrypt`` parameters (memory about 16 MiB: a token, not a password database)."""

TOKEN_ENV = "CRUCIBLE_VAULT_TOKEN"
"""The non-interactive way to hand the admin token to ``authorize`` (CI, a script). The token is
never logged, never echoed and never written anywhere by Crucible."""

REQUESTER_ENV = "CRUCIBLE_VAULT_REQUESTER"
"""Who asked for a registration; defaults to the OS user (audit only)."""

_SQL_SCHEMA = """
CREATE TABLE IF NOT EXISTS registrations (
    vr_id VARCHAR PRIMARY KEY,
    vault_id VARCHAR NOT NULL,
    config_hash VARCHAR NOT NULL,
    dataset_hashes VARCHAR NOT NULL,
    candidate_id VARCHAR,
    window_start DATE NOT NULL,
    window_end DATE NOT NULL,
    requester VARCHAR NOT NULL,
    status VARCHAR NOT NULL,
    registered_at VARCHAR NOT NULL,
    authorized_at VARCHAR,
    evaluated_at VARCHAR,
    artifact_id VARCHAR,
    config_path VARCHAR NOT NULL,
    store_root VARCHAR NOT NULL
);
CREATE TABLE IF NOT EXISTS counter (
    vault_id VARCHAR PRIMARY KEY,
    opens BIGINT NOT NULL
);
CREATE TABLE IF NOT EXISTS access_log (
    seq BIGINT PRIMARY KEY,
    ts VARCHAR NOT NULL,
    caller VARCHAR NOT NULL,
    purpose VARCHAR NOT NULL,
    dataset VARCHAR NOT NULL,
    as_of BIGINT,
    outcome VARCHAR NOT NULL,
    vr_id VARCHAR,
    detail VARCHAR NOT NULL,
    chain VARCHAR NOT NULL
)
"""
"""``config_path`` and ``store_root`` are recorded so ``evaluate --registration VR-...`` can reload
exactly the config that was registered (and refuse if it changed) without being told where it is."""

STATUSES = ("pending", "authorized", "evaluated")


def _now() -> str:
    return dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _requester() -> str:
    return os.environ.get(REQUESTER_ENV) or getpass.getuser()


# ---------------------------------------------------------------------------------------------
# a. the admin secret (a human's token; never generated, never printed)


@dataclass(frozen=True, slots=True)
class AdminSecret:
    """The salted ``scrypt`` hash of the admin token (never the token itself)."""

    salt: bytes
    digest: bytes

    def document(self) -> dict[str, object]:
        return {
            "algorithm": "scrypt",
            "n": SCRYPT_N,
            "r": SCRYPT_R,
            "p": SCRYPT_P,
            "dklen": SCRYPT_DKLEN,
            "salt": self.salt.hex(),
            "hash": self.digest.hex(),
        }

    @classmethod
    def from_document(cls, raw: dict[str, object]) -> AdminSecret:
        return cls(salt=bytes.fromhex(str(raw["salt"])), digest=bytes.fromhex(str(raw["hash"])))


def hash_token(token: str, *, salt: bytes | None = None) -> AdminSecret:
    """``scrypt`` hash of ``token`` with a fresh (or given) 16-byte salt."""
    used = salt if salt is not None else secrets.token_bytes(16)
    digest = hashlib.scrypt(
        token.encode("utf-8"),
        salt=used,
        n=SCRYPT_N,
        r=SCRYPT_R,
        p=SCRYPT_P,
        dklen=SCRYPT_DKLEN,
    )
    return AdminSecret(salt=used, digest=digest)


def admin_path(home: Path) -> Path:
    return Path(home) / ADMIN_FILE


def write_admin_secret(home: Path, token: str) -> Path:
    """Store the hash of ``token`` in ``<home>/vault_admin`` (0600 where the OS supports it).

    This is the primitive the interactive ``set_admin`` wraps; it exists so a test can plant a
    throwaway token in a THROWAWAY home. It never writes the token, only its salted hash, and it
    never reads one from anywhere.
    """
    if not token:
        msg = "the admin token cannot be empty: `crucible vault set-admin` reads one from the TTY"
        raise ConfigurationError(msg)
    path = admin_path(home)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(hash_token(token).document(), sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    # best effort: 0600 where the platform honours it (a no-op on Windows)
    with contextlib.suppress(OSError):
        path.chmod(0o600)
    return path


def set_admin(*, home: Path, stdin: object | None = None) -> Path:
    """Set the admin token from an INTERACTIVE TTY prompt (ADR-0105 decision 5).

    Refuses when standard input is not a TTY: a token that arrives from a pipe, a file or an
    environment variable could only come from the agent being locked out, which is exactly what the
    protocol forbids. The token is read with echo off, never echoed, never logged, and only its
    salted hash is stored.
    """
    stream = sys.stdin if stdin is None else stdin
    isatty = getattr(stream, "isatty", lambda: False)
    if not isatty():
        msg = (
            "`crucible vault set-admin` needs an interactive TTY: the admin token is a HUMAN's, "
            "and it must not be typed into a pipe, a file or an environment variable. Run it from "
            "a terminal yourself (ADR-0105 decision 5)"
        )
        raise ConfigurationError(msg)
    try:
        first = getpass.getpass("New vault admin token (input hidden): ")
        again = getpass.getpass("Repeat it: ")
    except (EOFError, KeyboardInterrupt) as exc:
        msg = f"no token read ({type(exc).__name__}): the admin token was not changed"
        raise ConfigurationError(msg) from exc
    if not first:
        msg = "the admin token cannot be empty: the admin token was not changed"
        raise ConfigurationError(msg)
    if first != again:
        msg = "the two tokens differ: the admin token was not changed"
        raise ConfigurationError(msg)
    return write_admin_secret(home, first)


def _read_admin(home: Path) -> AdminSecret:
    path = admin_path(home)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        msg = (
            f"no admin token is set for this home ({path}): a human runs `crucible vault "
            "set-admin` from a TTY first, then `crucible vault authorize --registration VR-...`"
        )
        raise ConfigurationError(msg) from exc
    except (OSError, ValueError) as exc:
        msg = f"the admin token hash {path} is unreadable ({exc}); a human runs set-admin again"
        raise ConfigurationError(msg) from exc
    if not isinstance(raw, dict):
        msg = f"the admin token hash {path} must hold a JSON object; a human runs set-admin again"
        raise ConfigurationError(msg)
    return AdminSecret.from_document(raw)


def verify_token(home: Path, token: str) -> bool:
    """``hmac.compare_digest`` of the token's ``scrypt`` hash against the stored one."""
    secret = _read_admin(home)
    candidate = hashlib.scrypt(
        token.encode("utf-8"),
        salt=secret.salt,
        n=SCRYPT_N,
        r=SCRYPT_R,
        p=SCRYPT_P,
        dklen=SCRYPT_DKLEN,
    )
    return hmac.compare_digest(candidate, secret.digest)


def _token_from_environment_or_tty(*, allow_prompt: bool = True) -> str:
    """The admin token: ``CRUCIBLE_VAULT_TOKEN``, else an interactive prompt, else refuse."""
    from_env = os.environ.get(TOKEN_ENV)
    if from_env:
        return from_env
    if allow_prompt and getattr(sys.stdin, "isatty", lambda: False)():
        try:
            return getpass.getpass("Vault admin token (input hidden): ")
        except (EOFError, KeyboardInterrupt) as exc:
            msg = (
                f"no token read ({type(exc).__name__}): authorization refused. Set "
                f"{TOKEN_ENV} for a non-interactive call, or run it from a terminal"
            )
            raise ConfigurationError(msg) from exc
    msg = (
        f"authorization needs the admin token: this call is not interactive and {TOKEN_ENV} is "
        "not set. A human sets the token with `crucible vault set-admin` (TTY only) and passes it "
        f"here from a terminal or through {TOKEN_ENV} (ADR-0105 decision 5)"
    )
    raise ConfigurationError(msg)


# ---------------------------------------------------------------------------------------------
# b. documents


class VaultDeclarationDocument(BaseModel):
    """The ``vault.json`` payload: the locked period of the declared family (ADR-0105)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    vault_id: str = Field(description="VLT-<16 hex>: the identity of the locked period.")
    universe: list[str] = Field(description="CME roots the vault covers (ES, NQ, YM, RTY, NKD).")
    start_trade_date: dt.date = Field(
        description="First protected Globex trade date; every later trade date is protected too."
    )
    end_trade_date: dt.date | None = Field(
        default=None, description="Always null: the vault is open-ended."
    )
    scope: Literal["family", "root"] = Field(
        description="family: the declared roots, not bypassable by another family. root: exactly "
        "one root, for single-instrument research."
    )
    declared_at: str = Field(description="When the declaration was written (audit only).")
    audit_ref: str = Field(description="The exposure audit that justifies the period.")
    protected_datasets: list[str] = Field(
        description="Datasets found protected at declaration time (the guard still matches by "
        "root on every call)."
    )


class VaultRegistrationDocument(BaseModel):
    """One ``VR-<16 hex>`` registration as ``crucible vault status --json`` reports it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    vr_id: str = Field(description="VR-<16 hex>.")
    vault_id: str = Field(description="The vault the registration is evaluated against.")
    config_hash: str = Field(description="SHA-256 of the registered config (its identity).")
    dataset_hashes: dict[str, str] = Field(
        description="Content hash of every dataset the config reads, at registration time."
    )
    candidate_id: str | None = Field(
        default=None, description="CND-<16 hex> candidate identity (ADR-0103)."
    )
    window_start: dt.date = Field(description="First trade date of the evaluation window.")
    window_end: dt.date = Field(description="Last trade date of the evaluation window.")
    requester: str = Field(description="Who registered it (audit).")
    status: Literal["pending", "authorized", "evaluated"] = Field(
        description="pending: registered. authorized: a human approved it. evaluated: the single "
        "evaluation has run (or crashed: it is consumed either way)."
    )
    registered_at: str = Field(description="When it was registered.")
    authorized_at: str | None = Field(default=None, description="When a human authorized it.")
    evaluated_at: str | None = Field(default=None, description="When the evaluation ran.")
    artifact_id: str | None = Field(
        default=None, description="ART-... of the sealed run, null before (and after a crash)."
    )


class VaultRegistrationSchema(BaseModel):
    """The registration's shape, for ``crucible schema --kind vault-registration``."""

    model_config = ConfigDict(extra="forbid")

    vr_id: str
    vault_id: str
    config_hash: str
    dataset_hashes: dict[str, str]
    candidate_id: str | None = None
    window_start: dt.date
    window_end: dt.date
    requester: str
    status: Literal["pending", "authorized", "evaluated"] = "pending"
    registered_at: str
    authorized_at: str | None = None
    evaluated_at: str | None = None
    artifact_id: str | None = None


def vault_declaration_json_schema() -> dict[str, object]:
    """The JSON Schema of ``vault.json`` (``crucible schema --kind vault-declaration``)."""
    return VaultDeclarationDocument.model_json_schema()


def vault_registration_json_schema() -> dict[str, object]:
    """The JSON Schema of a registration (``crucible schema --kind vault-registration``)."""
    return VaultRegistrationSchema.model_json_schema()


# ---------------------------------------------------------------------------------------------
# c. the registry


@dataclass(frozen=True, slots=True)
class Registration:
    """One row of ``registrations``."""

    vr_id: str
    vault_id: str
    config_hash: str
    dataset_hashes: dict[str, str]
    candidate_id: str | None
    window_start: dt.date
    window_end: dt.date
    requester: str
    status: str
    registered_at: str
    authorized_at: str | None
    evaluated_at: str | None
    artifact_id: str | None
    config_path: str
    store_root: str

    def document(self) -> dict[str, object]:
        return VaultRegistrationDocument(
            vr_id=self.vr_id,
            vault_id=self.vault_id,
            config_hash=self.config_hash,
            dataset_hashes=dict(self.dataset_hashes),
            candidate_id=self.candidate_id,
            window_start=self.window_start,
            window_end=self.window_end,
            requester=self.requester,
            status=self.status,
            registered_at=self.registered_at,
            authorized_at=self.authorized_at,
            evaluated_at=self.evaluated_at,
            artifact_id=self.artifact_id,
        ).model_dump(mode="json")


@dataclass(frozen=True, slots=True)
class VaultStatus:
    """What ``crucible vault status`` reports: ids, counters, statuses and the log. No metric."""

    vault_id: str
    universe: tuple[str, ...]
    start_trade_date: dt.date
    first_protected_trade_date: dt.date
    vault_start_ns: int
    opens: int
    registrations: tuple[Registration, ...]

    def document(self) -> dict[str, object]:
        return {
            "kind": "vault_status",
            "vault_id": self.vault_id,
            "universe": list(self.universe),
            "start_trade_date": self.start_trade_date.isoformat(),
            "first_protected_trade_date": self.first_protected_trade_date.isoformat(),
            "vault_start_ns": self.vault_start_ns,
            "opens": self.opens,
            "registrations": [entry.document() for entry in self.registrations],
            "note": (
                "Statuses, the open counter and the access log only: a vault result is readable "
                "from its sealed artifact after its single authorized evaluation, never from here"
            ),
        }


class VaultRegistry:
    """The home's vault database and the store's declaration, behind one object."""

    def __init__(self, *, store_root: Path, home: Path, artifacts_root: Path) -> None:
        self._store_root = Path(store_root)
        self._home = Path(home)
        self._artifacts_root = Path(artifacts_root)

    # -- paths and plumbing ---------------------------------------------------------------

    @property
    def store_root(self) -> Path:
        return self._store_root

    @property
    def home(self) -> Path:
        return self._home

    @property
    def artifacts_root(self) -> Path:
        return self._artifacts_root

    @property
    def db_path(self) -> Path:
        return self._home / VAULT_DB_FILE

    @property
    def vault_artifacts_root(self) -> Path:
        return self._artifacts_root / VAULT_ARTIFACTS_DIR

    @contextmanager
    def _connect(self) -> Iterator[duckdb.DuckDBPyConnection]:
        self._home.mkdir(parents=True, exist_ok=True)
        connection = duckdb.connect(str(self.db_path))
        try:
            connection.execute(_SQL_SCHEMA)
            yield connection
        finally:
            connection.close()

    def declaration(self) -> VaultDeclaration:
        declaration = load_declaration(self._store_root, home=self._home)
        if declaration is None:
            msg = (
                f"no futures holdout vault is declared for the store {self._store_root} or the "
                f"home {self._home}: run `crucible vault declare` first (ADR-0105)"
            )
            raise ConfigurationError(msg)
        return declaration

    # -- the declaration ------------------------------------------------------------------

    def declare(
        self,
        *,
        universe: Sequence[str],
        start_trade_date: dt.date,
        audit_ref: str,
        scope: Literal["family", "root"] = "family",
    ) -> VaultDeclaration:
        """Write the declaration in both places (widening only)."""
        declaration = declare_vault(
            store_root=self._store_root,
            home=self._home,
            universe=universe,
            start_trade_date=start_trade_date,
            scope=scope,
            audit_ref=audit_ref,
        )
        self._write_mirror(declaration, opens=self._opens())
        return declaration

    # -- the store mirror of the database's state -----------------------------------------

    def _store_document(self) -> dict[str, object]:
        path = self._store_root / DECLARATION_FILE
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            msg = (
                f"the store copy of the vault declaration {path} is missing: the vault is "
                "declared in the home only, so the store cannot mirror the database's state. "
                "Declare it again with `crucible vault declare --store DIR`"
            )
            raise ExperimentError(msg) from exc
        if not isinstance(raw, dict):
            msg = f"the vault declaration {path} must hold a JSON object"
            raise ExperimentError(msg)
        return raw

    def _write_mirror(self, declaration: VaultDeclaration, *, opens: int = 0) -> None:
        """Record the expected state of ``vault.duckdb`` in the STORE copy of ``vault.json``."""
        document = declaration.document()
        document["opens"] = opens
        document["last_log_hash"] = self._log_tip()
        path = self._store_root / DECLARATION_FILE
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(document, sort_keys=True, indent=2) + "\n", encoding="utf-8", newline="\n"
        )

    def _log_tip(self) -> str | None:
        if not self.db_path.is_file():
            return None
        with self._connect() as connection:
            row = connection.execute(
                "SELECT chain FROM access_log ORDER BY seq DESC LIMIT 1"
            ).fetchone()
        return None if row is None else str(row[0])

    def _opens(self) -> int:
        if not self.db_path.is_file():
            return 0
        with self._connect() as connection:
            row = connection.execute("SELECT COALESCE(MAX(opens), 0) FROM counter").fetchone()
        return int(row[0]) if row is not None else 0

    def verify(self) -> None:
        """Refuse a database that is missing or behind the state the store's copy records.

        The store's ``vault.json`` mirrors ``{opens, last_log_hash}``: a counter below it, a log
        that does not contain the row it names, or a missing ``vault.duckdb`` under a store that
        says one evaluation was consumed are all refusals — silently starting the counter again
        would hand the research path a second look at the vault.
        """
        mirror = self._store_document()
        expected_opens = int(str(mirror.get("opens", 0) or 0))
        tip = mirror.get("last_log_hash")
        if not self.db_path.is_file():
            if expected_opens or tip:
                mirror_path = self._store_root / DECLARATION_FILE
                msg = (
                    f"the vault database {self.db_path} is missing, but {mirror_path} "
                    f"records {expected_opens} open(s) and the log row {tip}: the registry was "
                    "deleted or moved. Restore it from its backup, or (deliberately) delete both "
                    "vault.json copies and declare the vault again"
                )
                raise ExperimentError(msg)
            return
        opens = self._opens()
        if opens < expected_opens:
            msg = (
                f"the vault database {self.db_path} is behind the store's declaration: the counter "
                f"says {opens} open(s), {self._store_root / DECLARATION_FILE} records "
                f"{expected_opens}. An evaluation would be re-opened, so this is refused"
            )
            raise ExperimentError(msg)
        if tip is not None:
            with self._connect() as connection:
                rows = connection.execute("SELECT chain FROM access_log").fetchall()
            if str(tip) not in {str(row[0]) for row in rows}:
                msg = (
                    f"the access log in {self.db_path} does not contain the row "
                    f"{self._store_root / DECLARATION_FILE} names ({tip}): the log was truncated "
                    "or replaced, so the audit trail is broken and this is refused"
                )
                raise ExperimentError(msg)

    # -- the human authorization ----------------------------------------------------------

    def authorize(self, vr_id: str, token: str | None = None) -> Registration:
        """Move ``pending -> authorized`` after verifying the admin token (a human's step)."""
        self.verify()
        registration = self.registration(vr_id)
        if registration is None:
            msg = f"no registration {vr_id!r} in {self.db_path}: `crucible vault status` lists them"
            raise ConfigurationError(msg)
        if registration.status == "evaluated":
            msg = (
                f"the registration {vr_id} was already evaluated at {registration.evaluated_at}: "
                "authorization cannot bring it back (one evaluation per registration)"
            )
            self._log(
                dataset="",
                as_of=None,
                outcome="refused_authorize_evaluated",
                purpose="authorize",
                caller="authorize",
                vr_id=vr_id,
                detail=msg,
            )
            raise VaultLockedError(msg)
        if registration.status == "authorized":
            msg = (
                f"the registration {vr_id} is already authorized ({registration.authorized_at}): "
                "run `crucible vault evaluate --registration "
                f"{vr_id}` (a registration gets one evaluation)"
            )
            self._log(
                dataset="",
                as_of=None,
                outcome="allowed_authorize_already",
                purpose="authorize",
                caller="authorize",
                vr_id=vr_id,
                detail=msg,
            )
            raise ConfigurationError(msg)
        supplied = token if token is not None else _token_from_environment_or_tty()
        if not verify_token(self._home, supplied):
            msg = (
                f"the admin token does not verify for the home {self._home}: authorization of "
                f"{vr_id} was REFUSED and logged. Ask the human who holds the token (it is set "
                "with `crucible vault set-admin`); Crucible never generates or prints it"
            )
            self._log(
                dataset="",
                as_of=None,
                outcome="refused_authorize_token",
                purpose="authorize",
                caller="authorize",
                vr_id=vr_id,
                detail=msg,
            )
            raise VaultLockedError(msg)
        self._transition(vr_id, "pending", "authorized", authorized_at=_now())
        self._log(
            dataset="",
            as_of=None,
            outcome="allowed_authorize",
            purpose="authorize",
            caller="authorize",
            vr_id=vr_id,
            detail="the admin token verified; the registration is authorized",
        )
        authorized = self.registration(vr_id)
        assert authorized is not None  # it was just transitioned
        return authorized

    # -- registration ---------------------------------------------------------------------

    def register(self, config_path: Path) -> Registration:
        """Record a registration for ``config_path`` (reads no protected row)."""
        self.verify()
        declaration = self.declaration()
        config = load_futures_config(config_path)
        self._refuse_outside_vault(config, declaration)
        store = ParquetDataStore(self._store_root, home=self._home)
        dataset_hashes: dict[str, str] = {}
        for role in DATASET_ROLES:
            name = getattr(config.datasets, role)
            dataset_hashes[name] = store.manifest(DatasetId(name)).content_hash
        config_hash = futures_config_hash(config)
        vr_id = _registration_id(
            vault_id=declaration.vault_id,
            config_hash=config_hash,
            window_start=config.window.start,
            window_end=config.window.end,
        )
        existing = self.registration(vr_id)
        if existing is not None:
            msg = (
                f"this config is already registered as {vr_id} (status {existing.status}): a "
                "registration is the identity of a config and its window, so it is not "
                "registered twice. Change the config (a new config hash) or use the existing "
                "registration"
            )
            raise ConfigurationError(msg)
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO registrations (vr_id, vault_id, config_hash, dataset_hashes, "
                "candidate_id, window_start, window_end, requester, status, registered_at, "
                "authorized_at, evaluated_at, artifact_id, config_path, store_root) VALUES "
                "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    vr_id,
                    declaration.vault_id,
                    config_hash,
                    json.dumps(dataset_hashes, sort_keys=True),
                    candidate_id(config),
                    config.window.start,
                    config.window.end,
                    _requester(),
                    "pending",
                    _now(),
                    None,
                    None,
                    None,
                    str(Path(config_path).resolve()),
                    str(self._store_root),
                ],
            )
        self._log(
            dataset="",
            as_of=None,
            outcome="allowed_register",
            purpose="registration",
            caller="register",
            vr_id=vr_id,
            detail=(
                f"registered config hash {config_hash[:16]}... for window "
                f"{config.window.start}..{config.window.end}"
            ),
        )
        registered = self.registration(vr_id)
        assert registered is not None
        return registered

    def _refuse_outside_vault(
        self, config: FuturesRunConfig, declaration: VaultDeclaration
    ) -> None:
        """The evaluation window must lie INSIDE the vault (ADR-0105 decision 4)."""
        if not declaration.covers_root(config.root):
            msg = (
                f"the config's root {config.root} is not in the vault's universe "
                f"{list(declaration.universe)}: a registration is evaluated against the declared "
                "locked period, so it must trade a declared root"
            )
            raise ConfigurationError(msg)
        start = declaration.start_trade_date
        if config.window.start < start:
            msg = (
                f"the config's window starts at {config.window.start}, before the vault's "
                f"{start}: an evaluation window must lie INSIDE the vault, so it can be "
                f"evaluated exactly once. Set window.start to {start} or later"
            )
            raise ConfigurationError(msg)
        end_limit = declaration.end_trade_date
        if end_limit is not None and config.window.end > end_limit:
            msg = (
                f"the config's window ends at {config.window.end}, after the vault's "
                f"{end_limit}: the window must lie inside the vault"
            )
            raise ConfigurationError(msg)

    # -- the evaluation -------------------------------------------------------------------

    def evaluate(self, vr_id: str) -> dict[str, object]:
        """Run the registered config exactly once (ADR-0105 decision 5).

        The order matters and is not negotiable: verify the database against the store's mirror,
        reload and re-hash the config, re-hash the datasets, increment the open counter, THEN open
        the data-layer session and run. A crash after the counter leaves the registration consumed.
        """
        self.verify()
        registration = self.registration(vr_id)
        if registration is None:
            msg = f"no registration {vr_id!r} in {self.db_path}: `crucible vault status` lists them"
            raise ConfigurationError(msg)
        if registration.status == "evaluated" or registration.evaluated_at is not None:
            msg = (
                f"the registration {vr_id} was already evaluated at {registration.evaluated_at}: "
                "one evaluation per registration, and the open counter is never decremented. "
                "Register the config again (a new VR-) if you need another look"
            )
            self._log(
                dataset="",
                as_of=None,
                outcome="refused_evaluate_second",
                purpose="evaluate",
                caller="evaluate",
                vr_id=vr_id,
                detail=msg,
            )
            raise VaultLockedError(msg)
        if registration.status != "authorized":
            msg = (
                f"the registration {vr_id} is {registration.status}: an evaluation needs an "
                "authorization first (`crucible vault authorize --registration "
                f"{vr_id}`, a HUMAN step with the admin token). Results are not readable before it"
            )
            self._log(
                dataset="",
                as_of=None,
                outcome="refused_evaluate_unauthorized",
                purpose="evaluate",
                caller="evaluate",
                vr_id=vr_id,
                detail=msg,
            )
            raise VaultLockedError(msg)
        config = load_futures_config(Path(registration.config_path))
        current_hash = futures_config_hash(config)
        if current_hash != registration.config_hash:
            msg = (
                f"the config {registration.config_path} hashes to {current_hash[:16]}..., the "
                f"registration {vr_id} recorded {registration.config_hash[:16]}...: the config "
                "changed after it was registered (or authorized), so this evaluation is refused "
                "and logged. Restore the registered config, or register the edited one (a new "
                "registration and a new authorization)"
            )
            self._log(
                dataset="",
                as_of=None,
                outcome="refused_evaluate_config",
                purpose="evaluate",
                caller="evaluate",
                vr_id=vr_id,
                detail=msg,
            )
            raise VaultLockedError(msg)
        changed = self._changed_datasets(registration)
        if changed:
            msg = (
                f"the dataset(s) {changed} changed content since {vr_id} was registered: the "
                "evaluation would read data the registration hashed. Rebuild is a new input, so "
                "this is refused and logged; register the config again against the rebuilt data"
            )
            self._log(
                dataset=",".join(changed),
                as_of=None,
                outcome="refused_evaluate_datasets",
                purpose="evaluate",
                caller="evaluate",
                vr_id=vr_id,
                detail=msg,
            )
            raise VaultLockedError(msg)

        # the counter goes up BEFORE any row is read: a crash consumes the evaluation
        opens = self._record_open(registration)
        self._log(
            dataset="",
            as_of=None,
            outcome="allowed_evaluate_start",
            purpose="evaluate",
            caller="evaluate",
            vr_id=vr_id,
            detail=f"open counter {opens}; the session admits the registered datasets only",
        )
        datasets = frozenset(registration.dataset_hashes)
        window_end_ns = _window_end_ns(config, registration)
        scope = open_vault_session(
            VaultSession(vr_id=vr_id, datasets=datasets, window_end_ns=window_end_ns)
        )
        try:
            result = run_futures(
                config,
                store_root=self._store_root,
                artifacts_root=self.vault_artifacts_root / vr_id,
                registry_root=self._artifacts_root,
            )
        except Exception as exc:  # the evaluation is consumed whatever went wrong
            message = f"the evaluation of {vr_id} failed ({type(exc).__name__}: {exc})"
            self._transition(vr_id, "authorized", "evaluated", evaluated_at=_now())
            self._log(
                dataset="",
                as_of=None,
                outcome="evaluate_failed",
                purpose="evaluate",
                caller="evaluate",
                vr_id=vr_id,
                detail=message,
            )
            raise
        finally:
            close_vault_session(scope)
        self._transition(
            vr_id, "authorized", "evaluated", evaluated_at=_now(), artifact_id=result.artifact_id
        )
        self._log(
            dataset="",
            as_of=None,
            outcome="allowed_evaluate_done",
            purpose="evaluate",
            caller="evaluate",
            vr_id=vr_id,
            detail=f"sealed {result.artifact_id} under {result.run_dir}",
        )
        return {
            "kind": "vault_evaluation",
            "vr_id": vr_id,
            "vault_id": registration.vault_id,
            "status": "evaluated",
            "opens": opens,
            "run_id": result.run_id,
            "artifact_id": result.artifact_id,
            "run_dir": str(result.run_dir),
            "window": {
                "start": registration.window_start.isoformat(),
                "end": registration.window_end.isoformat(),
            },
            "summary": result.summary,
            "note": (
                "One evaluation per registration. The artifact is sealed under "
                f"{self.vault_artifacts_root / vr_id}: it is excluded from the comparison and "
                "trials pools unless they are asked to include the vault"
            ),
        }

    def _changed_datasets(self, registration: Registration) -> list[str]:
        store = ParquetDataStore(self._store_root, home=self._home)
        changed: list[str] = []
        for name, recorded in sorted(registration.dataset_hashes.items()):
            try:
                actual = store.manifest(DatasetId(name)).content_hash
            except Exception:
                changed.append(name)
                continue
            if actual != recorded:
                changed.append(name)
        return changed

    def _record_open(self, registration: Registration) -> int:
        """Increment the persistent counter and mirror the new state into the store's copy."""
        with self._connect() as connection:
            row = connection.execute(
                "SELECT COALESCE(MAX(opens), 0) FROM counter WHERE vault_id = ?",
                [registration.vault_id],
            ).fetchone()
            opens = (int(row[0]) if row is not None else 0) + 1
            if row is None or int(row[0]) == 0:
                connection.execute(
                    "INSERT INTO counter (vault_id, opens) VALUES (?, ?)",
                    [registration.vault_id, opens],
                )
            else:
                connection.execute(
                    "UPDATE counter SET opens = ? WHERE vault_id = ?",
                    [opens, registration.vault_id],
                )
        declaration = load_declaration(self._store_root, home=self._home)
        if declaration is not None:
            self._write_mirror(declaration, opens=opens)
        return opens

    def _transition(self, vr_id: str, from_status: str, to_status: str, **fields: object) -> None:
        """The ONLY update in this module: a status transition and its timestamp/artifact."""
        allowed = {("pending", "authorized"), ("authorized", "evaluated")}
        if (from_status, to_status) not in allowed:
            msg = f"the vault status cannot go {from_status} -> {to_status} (ADR-0105 decision 6)"
            raise ExperimentError(msg)
        assignments = ", ".join(f"{name} = ?" for name in fields)
        sql = f"UPDATE registrations SET status = ?, {assignments} WHERE vr_id = ? AND status = ?"
        with self._connect() as connection:
            connection.execute(sql, [to_status, *fields.values(), vr_id, from_status])
            row = connection.execute(
                "SELECT status FROM registrations WHERE vr_id = ?", [vr_id]
            ).fetchone()
        if row is None or str(row[0]) != to_status:
            msg = (
                f"the registration {vr_id} could not move {from_status} -> {to_status}: its "
                "status is not the one the transition expects (a concurrent command changed it)"
            )
            raise ExperimentError(msg)

    # -- reading --------------------------------------------------------------------------

    def registration(self, vr_id: str) -> Registration | None:
        if not self.db_path.is_file():
            return None
        with self._connect() as connection:
            row = connection.execute(
                "SELECT vr_id, vault_id, config_hash, dataset_hashes, candidate_id, window_start, "
                "window_end, requester, status, registered_at, authorized_at, evaluated_at, "
                "artifact_id, config_path, store_root FROM registrations WHERE vr_id = ?",
                [vr_id],
            ).fetchone()
        return None if row is None else _registration(row)

    def registrations(self) -> tuple[Registration, ...]:
        if not self.db_path.is_file():
            return ()
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT vr_id, vault_id, config_hash, dataset_hashes, candidate_id, window_start, "
                "window_end, requester, status, registered_at, authorized_at, evaluated_at, "
                "artifact_id, config_path, store_root FROM registrations ORDER BY registered_at, "
                "vr_id"
            ).fetchall()
        return tuple(_registration(row) for row in rows)

    def opens(self) -> int:
        return self._opens()

    def status(self) -> VaultStatus:
        """The vault's ids, counters, registration statuses and nothing else (no metric)."""
        declaration = self.declaration()
        first_day, start_ns = first_protected_session(declaration)
        return VaultStatus(
            vault_id=declaration.vault_id,
            universe=declaration.universe,
            start_trade_date=declaration.start_trade_date,
            first_protected_trade_date=first_day,
            vault_start_ns=start_ns,
            opens=self._opens(),
            registrations=self.registrations(),
        )

    def access_log(self, limit: int = 200) -> tuple[dict[str, object], ...]:
        """The last ``limit`` access attempts, in order (allowed and refused alike)."""
        if limit < 1:
            msg = f"limit must be >= 1, got {limit}"
            raise ConfigurationError(msg)
        if not self.db_path.is_file():
            return ()
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT seq, ts, caller, purpose, dataset, as_of, outcome, vr_id, detail, chain "
                "FROM access_log ORDER BY seq DESC LIMIT ?",
                [limit],
            ).fetchall()
        return tuple(
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
                "chain": str(row[9]),
            }
            for row in reversed(rows)
        )

    def _log(
        self,
        *,
        dataset: str,
        as_of: int | None,
        outcome: str,
        purpose: str,
        caller: str,
        vr_id: str | None,
        detail: str,
    ) -> None:
        """Append to the same access log the data layer writes to (never a second log)."""
        from crucible.data.vault import AccessLogEntry, DuckDbAccessLog

        DuckDbAccessLog(self.db_path).append(
            AccessLogEntry(
                ts=_now(),
                caller=caller,
                purpose=purpose,
                dataset=dataset,
                as_of=as_of,
                outcome=outcome,
                vr_id=vr_id,
                detail=detail,
            )
        )


def _registration(row: Sequence[object]) -> Registration:
    raw = json.loads(str(row[3]))
    return Registration(
        vr_id=str(row[0]),
        vault_id=str(row[1]),
        config_hash=str(row[2]),
        dataset_hashes={str(k): str(v) for k, v in raw.items()},
        candidate_id=None if row[4] is None else str(row[4]),
        window_start=_date(row[5]),
        window_end=_date(row[6]),
        requester=str(row[7]),
        status=str(row[8]),
        registered_at=str(row[9]),
        authorized_at=None if row[10] is None else str(row[10]),
        evaluated_at=None if row[11] is None else str(row[11]),
        artifact_id=None if row[12] is None else str(row[12]),
        config_path=str(row[13]),
        store_root=str(row[14]),
    )


def _date(value: object) -> dt.date:
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    return dt.date.fromisoformat(str(value))


def _registration_id(
    *, vault_id: str, config_hash: str, window_start: dt.date, window_end: dt.date
) -> str:
    """``VR-`` + 16 hex digits of the registered identity (vault, config, window)."""
    basis = "|".join(
        [vault_id, config_hash, window_start.isoformat(), window_end.isoformat(), "v1"]
    )
    digest = hashlib.sha256(basis.encode("utf-8")).hexdigest()
    return REGISTRATION_PREFIX + digest[:16]


def _window_end_ns(config: FuturesRunConfig, registration: Registration) -> int:
    """The instant the evaluation session stops admitting reads: the close of the window's last
    trade date (the last bar a run of that window can read)."""
    calendar: SessionCalendar = calendar_for(config.root)
    session = calendar.session(registration.window_end)
    return int(session.close_ns)


def registry_for(
    *, store_root: Path | None = None, home: Path | None = None, artifacts_root: Path | None = None
) -> VaultRegistry:
    """The registry of the effective store, home and artifacts root (CLI and library default)."""
    resolved_home = Path(home) if home is not None else home_root()
    if resolved_home is None:  # pragma: no cover - home_root always resolves on a real platform
        msg = "the vault needs a Crucible home: pass --home or set CRUCIBLE_HOME"
        raise ConfigurationError(msg)
    resolved_store = Path(store_root) if store_root is not None else resolved_home / "data"
    resolved_artifacts = (
        Path(artifacts_root) if artifacts_root is not None else resolved_home / "experiments"
    )
    return VaultRegistry(
        store_root=resolved_store, home=resolved_home, artifacts_root=resolved_artifacts
    )


__all__ = [
    "REGISTRATION_PREFIX",
    "STATUSES",
    "TOKEN_ENV",
    "VAULT_ARTIFACTS_DIR",
    "Registration",
    "VaultRegistry",
    "VaultStatus",
    "current_vault_session",
    "hash_token",
    "registry_for",
    "set_admin",
    "vault_declaration_json_schema",
    "vault_registration_json_schema",
    "verify_token",
    "write_admin_secret",
]
