"""The futures holdout vault: a declared, data-layer-enforced locked period (C6c, ADR-0105).

The owner's decision (ADR-0105) is that a protected range of Globex trade dates applies to the
whole declared futures family and is enforced **where the data is read**, not only in a command:

- a *declaration* (``vault.json``) says which roots are locked, from which trade date, under which
  audit; it is written in the store root **and** in the Crucible home, and the guard enforces it if
  **either** copy exists, so copying the store or switching home does not lift it;
- :class:`VaultGuard` is consulted by :meth:`crucible.data.store.ParquetDataStore.read` (a read
  whose ``as_of`` reaches the vault start) and by ``.data_path`` (whole-file access). The one
  exception is an active :class:`VaultSession`, which only the authorized evaluation path sets
  (``crucible.experiments.vault.evaluate``), and even then only for the registered datasets up to
  the registered window end;
- integrity and catalog tooling may still look at whole files in ``purpose="metadata"`` mode: the
  access is allowed and logged, and a metadata READ is clipped below the vault start, so counts,
  hashes and date bounds are available and no protected row is;
- every attempt, allowed or refused, is appended to the access log (``<home>/vault.duckdb``).

Timing: the vault start is the scheduled OPEN of the first protected Globex trade date, computed
from the CME session table of each declared root (the earliest of them), never from observed bars;
so ``as_of`` comparisons are exact and deterministic. Pessimism: a dataset belongs to a protected
root when its id starts with ``<root>_`` or its manifest names the root, and an unknown situation
refuses.

Units: instants are UTC int64 nanoseconds; trade dates are ``datetime.date`` (Globex trade date).
"""

from __future__ import annotations

import contextvars
import dataclasses
import datetime as dt
import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal, Protocol

import duckdb

from crucible.core.errors import ConfigurationError, VaultLockedError
from crucible.data.cme_sessions import SessionCalendar

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from crucible.core.types import DatasetId, TimestampNs

DECLARATION_FILE = "vault.json"
"""The declaration's file name, in the store root and in the Crucible home (ADR-0105 decision 2)."""

VAULT_DB_FILE = "vault.duckdb"
"""The home's append-only registry, counter and access log (ADR-0105 decision 6)."""

ADMIN_FILE = "vault_admin"
"""The home's salted admin-token hash (never the token; ADR-0105 decision 5)."""

VAULT_ID_PREFIX = "VLT-"
VAULT_ID_HEX = 16
"""``VLT-`` + 16 hex digits: 64 bits of the declaration's SHA-256, like every other id here."""

VAULT_START_MAX_SEARCH_DAYS = 400
"""How far past ``start_trade_date`` to look for a root's first trade date (a holiday run)."""

PURPOSES = ("strategy", "metadata", "integrity", "authorize", "registration", "evaluate")
"""What an access is for. ``metadata`` is the only one that may look at a whole protected file."""

Scope = Literal["family", "root"]


# ---------------------------------------------------------------------------------------------
# a. the declaration


def _utc_now() -> str:
    """The declaration's ``declared_at``: an I/O boundary, so wall-clock is allowed here and only
    here. It is recorded for audit and is NOT part of the vault id."""
    return dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass(frozen=True, slots=True)
class VaultDeclaration:
    """The locked period of a declared futures family (ADR-0105 decision 2).

    ``universe`` is the set of CME roots the vault covers; ``scope`` is ``family`` (any of those
    roots, and another family does not bypass it) or ``root`` (exactly one root, for explicitly
    single-instrument research). ``end_trade_date`` is ``None``: the vault is open-ended, so a
    trade date that has not been ingested yet is protected too. ``protected_datasets`` is the
    audit record of what the guard found at declaration time; the guard still matches by root on
    every call, so a dataset added later is covered without a re-declaration.
    """

    vault_id: str
    universe: tuple[str, ...]
    start_trade_date: dt.date
    end_trade_date: dt.date | None
    scope: Scope
    declared_at: str
    audit_ref: str
    protected_datasets: tuple[str, ...]

    def document(self) -> dict[str, object]:
        """The JSON-ready declaration (the ``vault.json`` payload)."""
        return {
            "vault_id": self.vault_id,
            "universe": list(self.universe),
            "start_trade_date": self.start_trade_date.isoformat(),
            "end_trade_date": (
                None if self.end_trade_date is None else self.end_trade_date.isoformat()
            ),
            "scope": self.scope,
            "declared_at": self.declared_at,
            "audit_ref": self.audit_ref,
            "protected_datasets": list(self.protected_datasets),
        }

    def identity(self) -> dict[str, object]:
        """What the vault IS (the locked period), without the audit and the timestamp: the two
        copies of ``vault.json`` must agree on this, and the vault id hashes it."""
        return {
            "universe": list(self.universe),
            "start_trade_date": self.start_trade_date.isoformat(),
            "end_trade_date": (
                None if self.end_trade_date is None else self.end_trade_date.isoformat()
            ),
            "scope": self.scope,
        }

    @classmethod
    def from_document(cls, raw: Mapping[str, object], *, where: str) -> VaultDeclaration:
        """Parse a ``vault.json`` payload, refusing anything ambiguous (an unknown scope, a
        ``root`` scope with several roots, an end date, a missing field)."""
        try:
            universe = tuple(sorted({str(r).strip().upper() for r in _as_list(raw["universe"])}))
            start = dt.date.fromisoformat(str(raw["start_trade_date"]))
            end_raw = raw.get("end_trade_date")
            end = None if end_raw in (None, "") else dt.date.fromisoformat(str(end_raw))
            scope = str(raw.get("scope", "family"))
            if scope not in ("family", "root"):
                msg = (
                    f"{where}: scope {scope!r} is not a vault scope; use 'family' (the declared "
                    "roots) or 'root' (exactly one root)"
                )
                raise ConfigurationError(msg)
            if scope == "root" and len(universe) != 1:
                msg = (
                    f"{where}: a scope 'root' vault covers exactly one root, got {list(universe)}; "
                    "declare the family scope for several roots"
                )
                raise ConfigurationError(msg)
            return cls(
                vault_id=str(raw["vault_id"]),
                universe=universe,
                start_trade_date=start,
                end_trade_date=end,
                scope=scope,  # type: ignore[arg-type]
                declared_at=str(raw.get("declared_at", "")),
                audit_ref=str(raw.get("audit_ref", "")),
                protected_datasets=tuple(
                    sorted({str(d) for d in _as_list(raw.get("protected_datasets", []))})
                ),
            )
        except KeyError as exc:
            msg = f"{where}: the vault declaration is missing {exc.args[0]!r}"
            raise ConfigurationError(msg) from exc
        except ValueError as exc:
            msg = f"{where}: the vault declaration is not valid: {exc}"
            raise ConfigurationError(msg) from exc

    def covers_root(self, root: str) -> bool:
        """Whether ``root`` is one of the declared roots (case-insensitive)."""
        return root.strip().upper() in self.universe

    def protects_dataset(self, dataset: str) -> bool:
        """Whether ``dataset`` belongs to a protected root: its id starts with ``<root>_`` or the
        declaration recorded it (ADR-0105 decision 2; conservative on purpose)."""
        name = str(dataset).strip().lower()
        if name in {d.lower() for d in self.protected_datasets}:
            return True
        return any(name.startswith(f"{root.lower()}_") for root in self.universe)


def _as_list(value: object) -> Sequence[object]:
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    if isinstance(value, list | tuple):
        return list(value)
    msg = f"expected a list, got {type(value).__name__}"
    raise ConfigurationError(msg)


def home_root() -> Path | None:
    """The Crucible home the vault guard reads and logs to, without creating anything.

    Same resolution order as ``crucible.product.home.resolve_home`` (ADR-0068): the
    ``CRUCIBLE_HOME`` environment variable, the ``home`` entry of the settings file, then the
    platform default. It is duplicated here because ``crucible.product`` sits ABOVE
    ``crucible.data`` in the layering rule (docs/ARCHITECTURE.md) and the guard must be reachable
    from a plain library call; ``tests/unit/test_vault_guard.py`` pins the two to agree.
    """
    override = os.environ.get("CRUCIBLE_HOME")
    if override:
        return Path(override).expanduser().resolve()
    settings = _settings_path()
    try:
        raw = json.loads(settings.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raw = None
    if isinstance(raw, dict) and raw.get("home"):
        return Path(str(raw["home"])).expanduser().resolve()
    return _default_home()


def _settings_path() -> Path:
    override = os.environ.get("CRUCIBLE_SETTINGS")
    if override:
        return Path(override).expanduser().resolve()
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / "crucible" / "settings.json"


def _default_home() -> Path:
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
        return (base / "Crucible").resolve()
    base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    return (base / "crucible").resolve()


def _read_document(path: Path) -> dict[str, object] | None:
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except OSError as exc:
        msg = f"the vault declaration {path} is unreadable ({exc}); fix or delete it"
        raise ConfigurationError(msg) from exc
    try:
        raw = json.loads(text)
    except ValueError as exc:
        msg = f"the vault declaration {path} is not valid JSON ({exc}); fix or delete it"
        raise ConfigurationError(msg) from exc
    if not isinstance(raw, dict):
        msg = f"the vault declaration {path} must hold a JSON object"
        raise ConfigurationError(msg)
    return raw


class _Missing:
    """The "caller said nothing" default of ``home`` (``None`` means "there is no home")."""


_MISSING = _Missing()


def _resolve_home(home: object) -> Path | None:
    """``_MISSING`` -> the resolved Crucible home; ``None`` -> no home; a path -> that path."""
    if isinstance(home, _Missing):
        return home_root()
    if home is None:
        return None
    return Path(str(home)).expanduser().resolve()


def load_declaration(
    store_root: Path | None, *, home: object = _MISSING
) -> VaultDeclaration | None:
    """The declaration the guard enforces for ``store_root``, or ``None`` when there is none.

    Enforced if EITHER copy exists (ADR-0105 decision 2): a copy in the store root does not lift a
    home declaration and a home declaration does not lift a store one. When both exist they must
    agree on the locked period, or the situation is refused rather than guessed.
    """
    resolved_home = _resolve_home(home)
    copies: list[tuple[str, dict[str, object]]] = []
    if store_root is not None:
        raw = _read_document(store_root / DECLARATION_FILE)
        if raw is not None:
            copies.append((str(store_root / DECLARATION_FILE), raw))
    if resolved_home is not None:
        raw = _read_document(resolved_home / DECLARATION_FILE)
        if raw is not None:
            copies.append((str(resolved_home / DECLARATION_FILE), raw))
    if not copies:
        return None
    declarations = [VaultDeclaration.from_document(raw, where=where) for where, raw in copies]
    first = declarations[0]
    for other in declarations[1:]:
        if other.identity() != first.identity():
            msg = (
                f"the two vault declarations disagree ({copies[0][0]} says "
                f"{json.dumps(first.identity(), sort_keys=True)}, {copies[1][0]} says "
                f"{json.dumps(other.identity(), sort_keys=True)}). One of them was edited or "
                "replaced: restore the declared one, or delete both and declare the vault again "
                "with `crucible vault declare`"
            )
            raise ConfigurationError(msg)
    return first


def write_declaration(store_root: Path, home: Path, declaration: VaultDeclaration) -> None:
    """Write the declaration into BOTH the store root and the home (identical bytes)."""
    payload = json.dumps(declaration.document(), sort_keys=True, indent=2) + "\n"
    store_root.mkdir(parents=True, exist_ok=True)
    home.mkdir(parents=True, exist_ok=True)
    for path in (store_root / DECLARATION_FILE, home / DECLARATION_FILE):
        path.write_text(payload, encoding="utf-8", newline="\n")


def vault_id_for(identity: Mapping[str, object]) -> str:
    """``VLT-`` + 16 hex digits of the SHA-256 of the locked period (deterministic)."""
    text = json.dumps(
        {key: identity[key] for key in sorted(identity)}, sort_keys=True, separators=(",", ":")
    )
    return VAULT_ID_PREFIX + hashlib.sha256(text.encode("utf-8")).hexdigest()[:VAULT_ID_HEX]


def first_protected_session(declaration: VaultDeclaration) -> tuple[dt.date, int]:
    """The first protected Globex trade date and the instant its session opens (UTC ns).

    The earliest across the declared roots, so the family vault is protected from the moment ANY
    of its roots can trade the period. Refuses (never guesses) a root without a session calendar
    or a first trade date beyond the search window.
    """
    from crucible.data.continuous import calendar_for  # local: data.store imports this module

    earliest: tuple[dt.date, int] | None = None
    for root in declaration.universe:
        try:
            calendar: SessionCalendar = calendar_for(root)
        except ConfigurationError as exc:
            msg = (
                f"the vault's root {root} has no CME session calendar ({exc}): the vault start "
                "cannot be computed. Declare only roots Crucible can schedule"
            )
            raise ConfigurationError(msg) from exc
        day, open_ns = _first_trade_date_open(calendar, declaration.start_trade_date)
        if earliest is None or (day, open_ns) < earliest:
            earliest = (day, open_ns)
    if earliest is None:
        msg = "a vault declaration needs at least one root in its universe"
        raise ConfigurationError(msg)
    return earliest


def _first_trade_date_open(calendar: SessionCalendar, start: dt.date) -> tuple[dt.date, int]:
    day = start
    for _ in range(VAULT_START_MAX_SEARCH_DAYS):
        if day > calendar.last:
            break
        if day >= calendar.first and calendar.is_trade_date(day):
            return day, int(calendar.session(day).open_ns)
        day += dt.timedelta(days=1)
    msg = (
        f"no {calendar.root} Globex trade date on or after {start} within "
        f"{VAULT_START_MAX_SEARCH_DAYS} days (calendar coverage [{calendar.first}, "
        f"{calendar.last}]): the vault start cannot be computed"
    )
    raise ConfigurationError(msg)


def vault_start_ns(declaration: VaultDeclaration) -> int:
    """The instant the vault locks: the open of the first protected session (UTC ns)."""
    return first_protected_session(declaration)[1]


def declared(declaration: VaultDeclaration) -> dict[str, object]:
    """The declaration as a JSON-ready dict plus its computed start (for documents)."""
    day, open_ns = first_protected_session(declaration)
    return {
        **declaration.document(),
        "first_protected_trade_date": day.isoformat(),
        "vault_start_ns": open_ns,
    }


def declare_vault(
    *,
    store_root: Path,
    home: Path,
    universe: Sequence[str],
    start_trade_date: dt.date,
    scope: Scope = "family",
    audit_ref: str,
    end_trade_date: dt.date | None = None,
    declared_at: str | None = None,
) -> VaultDeclaration:
    """Declare the vault in the store root AND the home.

    A declaration can only be WIDENED: an existing one is refused if the new one starts later,
    drops a root, narrows ``root`` scope back from ``family``, or gives an end date (the vault is
    open-ended). Re-declaring the same locked period keeps its ``vault_id`` and rewrites the audit
    reference.
    """
    roots = tuple(sorted({str(root).strip().upper() for root in universe}))
    if not roots:
        msg = "a vault declaration needs at least one root (e.g. --universe ES,NQ,YM,RTY,NKD)"
        raise ConfigurationError(msg)
    if scope == "root" and len(roots) != 1:
        msg = (
            f"scope 'root' covers exactly one root, got {list(roots)}: use scope 'family' for "
            "several roots, or declare the single root you research"
        )
        raise ConfigurationError(msg)
    if end_trade_date is not None:
        msg = (
            f"end_trade_date {end_trade_date} cannot be set: the vault is open-ended (every "
            "trade date from the start, including data not yet ingested, is protected). "
            "ADR-0105 decision 1"
        )
        raise ConfigurationError(msg)
    from crucible.data.continuous import calendar_for  # local: data.store imports this module

    for root in roots:
        try:
            calendar_for(root)
        except ConfigurationError as exc:
            msg = f"root {root} cannot be vaulted: {exc}"
            raise ConfigurationError(msg) from exc
    identity = {
        "universe": list(roots),
        "start_trade_date": start_trade_date.isoformat(),
        "end_trade_date": None,
        "scope": scope,
    }
    candidate = VaultDeclaration(
        vault_id=vault_id_for(identity),
        universe=roots,
        start_trade_date=start_trade_date,
        end_trade_date=None,
        scope=scope,
        declared_at=declared_at or _utc_now(),
        audit_ref=audit_ref,
        protected_datasets=_protected_datasets(store_root, roots),
    )
    existing = load_declaration(store_root, home=home)
    if existing is not None:
        _refuse_narrowing(existing, candidate)
        candidate = dataclasses.replace(candidate, protected_datasets=existing.protected_datasets)
    write_declaration(store_root, home, candidate)
    return candidate


def _refuse_narrowing(existing: VaultDeclaration, new: VaultDeclaration) -> None:
    if new.start_trade_date > existing.start_trade_date:
        msg = (
            f"the vault already starts at {existing.start_trade_date}; declaring "
            f"{new.start_trade_date} would LOCK LESS data. A declaration can only be widened "
            "(an earlier-or-equal start); delete both vault.json copies deliberately if the "
            "period itself is wrong"
        )
        raise ConfigurationError(msg)
    dropped = sorted(set(existing.universe) - set(new.universe))
    if dropped:
        msg = (
            f"the vault already covers {list(existing.universe)}; dropping {dropped} would "
            "un-protect those roots. A declaration can only be widened (a superset universe)"
        )
        raise ConfigurationError(msg)
    if existing.scope == "family" and new.scope == "root":
        msg = (
            "the vault is declared family-wide: narrowing it to scope 'root' would let a "
            "single-instrument declaration lift the family lock (ADR-0105 decision 2)"
        )
        raise ConfigurationError(msg)


def _root_tokens(source: str) -> set[str]:
    """The roots a manifest ``source`` names (``root=es``, ``roots=es,nq``)."""
    out: set[str] = set()
    for part in source.split(";"):
        key, _, value = part.partition("=")
        if key.strip() in ("root", "roots"):
            out |= {token.strip().upper() for token in value.split(",") if token.strip()}
    return out


def _protected_datasets(store_root: Path, roots: Sequence[str]) -> tuple[str, ...]:
    """Every dataset in the store whose id starts with ``<root>_`` or whose manifest names a
    declared root (metadata only: directory names and ``manifest.json``, never rows)."""
    if not store_root.is_dir():
        return ()
    found: set[str] = set()
    lowered = tuple(root.lower() for root in roots)
    for directory in sorted(store_root.iterdir()):
        manifest = directory / "manifest.json"
        if not manifest.is_file():
            continue
        name = directory.name.lower()
        if any(name.startswith(f"{root}_") for root in lowered):
            found.add(directory.name)
            continue
        try:
            raw = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(raw, dict):
            continue
        if _root_tokens(str(raw.get("source", ""))) & set(roots):
            found.add(directory.name)
    return tuple(sorted(found))


def protected_datasets(store_root: Path, declaration: VaultDeclaration) -> tuple[str, ...]:
    """The datasets of ``store_root`` the declaration protects, right now."""
    return _protected_datasets(store_root, declaration.universe)


# ---------------------------------------------------------------------------------------------
# b. the evaluation session (set only by the authorized evaluation path)


@dataclass(frozen=True, slots=True)
class VaultSession:
    """One authorized evaluation: which registration, which datasets, up to which instant.

    ``datasets`` holds the dataset ids the registration names; a read of any OTHER protected
    dataset is still refused inside a session. ``window_end_ns`` is the close of the last trade
    date of the registered window: a read past it is refused even inside the session, so an
    evaluation cannot walk beyond what was registered and authorized.
    """

    vr_id: str
    datasets: frozenset[str]
    window_end_ns: int


_SESSION: contextvars.ContextVar[VaultSession | None] = contextvars.ContextVar(
    "crucible_vault_session", default=None
)


def current_vault_session() -> VaultSession | None:
    """The active evaluation session, or ``None`` outside one."""
    return _SESSION.get()


@dataclasses.dataclass(frozen=True, slots=True)
class _SessionScope:
    previous: contextvars.Token[VaultSession | None]


def open_vault_session(session: VaultSession) -> _SessionScope:
    """Enter an evaluation session and return the token to close it. Only
    ``crucible.experiments.vault.evaluate`` calls this, after the registration was authorized and
    the open counter incremented (ADR-0105 decision 5)."""
    return _SessionScope(previous=_SESSION.set(session))


def close_vault_session(scope: _SessionScope) -> None:
    """Leave the session, restoring whatever was active before it."""
    _SESSION.reset(scope.previous)


# ---------------------------------------------------------------------------------------------
# c. the access log


@dataclass(frozen=True, slots=True)
class AccessLogEntry:
    """One access attempt: allowed (``outcome`` starts with ``allowed``) or refused."""

    ts: str
    caller: str
    purpose: str
    dataset: str
    as_of: int | None
    outcome: str
    vr_id: str | None
    detail: str

    def document(self) -> dict[str, object]:
        return {
            "ts": self.ts,
            "caller": self.caller,
            "purpose": self.purpose,
            "dataset": self.dataset,
            "as_of": self.as_of,
            "outcome": self.outcome,
            "vr_id": self.vr_id,
            "detail": self.detail,
        }

    def digest(self, previous: str) -> str:
        """The chain hash of this row (``sha256(previous + canonical(row))``)."""
        payload = {**self.document(), "previous": previous}
        text = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(text.encode("utf-8")).hexdigest()


class AccessLog(Protocol):
    """Where the guard appends an access attempt (implemented in the home's ``vault.duckdb``)."""

    def append(self, entry: AccessLogEntry) -> str:
        """Append and return the new chain hash."""
        ...


_ACCESS_LOG_SCHEMA = """
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


class DuckDbAccessLog:
    """The append-only access log in ``<home>/vault.duckdb`` (ADR-0105 decisions 3 and 6).

    Only INSERTs: the log has no UPDATE and no DELETE anywhere in the code, and every row carries
    the chain hash of the row before it, so a removed or rewritten row breaks the chain a
    verification would recompute.
    """

    def __init__(self, path: Path) -> None:
        self._path = path

    @property
    def path(self) -> Path:
        return self._path

    def append(self, entry: AccessLogEntry) -> str:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with duckdb.connect(str(self._path)) as connection:
            connection.execute(_ACCESS_LOG_SCHEMA)
            seq, previous = connection.execute(
                "SELECT COALESCE(MAX(seq), 0), COALESCE("
                "  (SELECT chain FROM access_log ORDER BY seq DESC LIMIT 1), '')"
                " FROM access_log"
            ).fetchone() or (0, "")
            chain = entry.digest(str(previous or ""))
            connection.execute(
                "INSERT INTO access_log (seq, ts, caller, purpose, dataset, as_of, outcome, "
                "vr_id, detail, chain) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    int(seq) + 1,
                    entry.ts,
                    entry.caller,
                    entry.purpose,
                    entry.dataset,
                    entry.as_of,
                    entry.outcome,
                    entry.vr_id,
                    entry.detail,
                    chain,
                ],
            )
        return chain


class MemoryAccessLog:
    """An in-process access log (tests and ``--dry-run``-style inspection; never the default)."""

    def __init__(self) -> None:
        self.entries: list[AccessLogEntry] = []

    def append(self, entry: AccessLogEntry) -> str:
        self.entries.append(entry)
        return ""


def _utc_stamp() -> str:
    return dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


# ---------------------------------------------------------------------------------------------
# d. the guard


@dataclass(frozen=True, slots=True)
class VaultGuard:
    """The data-layer lock (ADR-0105 decision 3).

    ``guard.check_read(dataset, as_of)`` returns the instant a scan must not exceed (``None`` when
    the read needs no clipping) or raises :class:`VaultLockedError`. ``guard.check_path(dataset)``
    refuses whole-file access unless the purpose is ``metadata`` or a session is active. Every
    attempt on a dataset of a protected root is appended to the log, allowed or refused; a read of
    an unrelated dataset is neither logged nor touched.
    """

    declaration: VaultDeclaration
    start_ns: int
    log: AccessLog | None = None
    store_root: str | None = None

    @classmethod
    def load(
        cls,
        store_root: Path | None = None,
        *,
        home: object = _MISSING,
        log: AccessLog | None = None,
    ) -> VaultGuard | None:
        """The guard for ``store_root``/``home``, or ``None`` when no declaration exists."""
        declaration = load_declaration(store_root, home=home)
        if declaration is None:
            return None
        resolved_home = _resolve_home(home)
        sink = log
        if sink is None and resolved_home is not None:
            sink = DuckDbAccessLog(Path(resolved_home) / VAULT_DB_FILE)
        return cls(
            declaration=declaration,
            start_ns=vault_start_ns(declaration),
            log=sink,
            store_root=None if store_root is None else str(store_root),
        )

    # -- queries ------------------------------------------------------------------------

    def protects(self, dataset: str) -> bool:
        return self.declaration.protects_dataset(dataset)

    def _log(
        self,
        *,
        dataset: str,
        as_of: int | None,
        outcome: str,
        purpose: str,
        caller: str | None,
        detail: str = "",
    ) -> str | None:
        if self.log is None:
            return None
        session = current_vault_session()
        entry = AccessLogEntry(
            ts=_utc_stamp(),
            caller=caller or "library",
            purpose=purpose,
            dataset=str(dataset),
            as_of=None if as_of is None else int(as_of),
            outcome=outcome,
            vr_id=None if session is None else session.vr_id,
            detail=detail,
        )
        return self.log.append(entry)

    def _loaded_session(self, dataset: str, as_of: int | None) -> VaultSession | None:
        """A session that covers this read, or ``None`` (a session that does not cover it is
        refused: a registration admits its own datasets, nothing else)."""
        session = current_vault_session()
        if session is None:
            return None
        name = str(dataset)
        if name not in session.datasets:
            msg = (
                f"the active vault evaluation {session.vr_id} registered "
                f"{sorted(session.datasets)}, not {name!r}: an evaluation reads only the "
                "datasets its registration names (ADR-0105 decision 5)"
            )
            raise VaultLockedError(msg)
        if as_of is not None and int(as_of) > session.window_end_ns:
            msg = (
                f"the active vault evaluation {session.vr_id} is registered up to the close of "
                f"{_iso_ns(session.window_end_ns)}, but this read asks for {_iso_ns(int(as_of))}: "
                "an evaluation cannot read past the window that was registered and authorized"
            )
            raise VaultLockedError(msg)
        return session

    # -- the two doors ------------------------------------------------------------------

    def check_read(
        self,
        dataset: DatasetId | str,
        as_of: TimestampNs | int,
        *,
        purpose: str = "strategy",
        caller: str | None = None,
    ) -> int | None:
        """Admit (returning a clip, or ``None``) or refuse a point-in-time read.

        The clip is the largest ``available_at`` the caller may see, when the declaration narrows
        the requested ``as_of`` (inside a session, or in ``metadata`` mode).
        """
        if not self.protects(dataset):
            return None
        start = self.start_ns
        value = int(as_of)
        try:
            session = self._loaded_session(dataset, value)
        except VaultLockedError as exc:
            self._log(
                dataset=dataset,
                as_of=value,
                outcome="refused_session_scope",
                purpose=purpose,
                caller=caller,
                detail=str(exc),
            )
            raise
        if session is not None:
            self._log(
                dataset=dataset,
                as_of=value,
                outcome="allowed_evaluation",
                purpose=purpose,
                caller=caller,
                detail=f"window end {_iso_ns(session.window_end_ns)}",
            )
            return session.window_end_ns
        if purpose == "metadata":
            self._log(
                dataset=dataset,
                as_of=value,
                outcome="allowed_metadata",
                purpose=purpose,
                caller=caller,
                detail=f"clipped below the vault start {_iso_ns(start)}",
            )
            return min(value, start - 1)
        if value < start:
            self._log(
                dataset=dataset,
                as_of=value,
                outcome="allowed",
                purpose=purpose,
                caller=caller,
                detail="before the vault start",
            )
            return None
        message = self._refusal(
            dataset,
            f"a read with as_of {_iso_ns(value)} reaches the vault start "
            f"{_iso_ns(start)} ({self.declaration.start_trade_date})",
        )
        self._log(
            dataset=dataset,
            as_of=value,
            outcome="refused",
            purpose=purpose,
            caller=caller,
            detail=message,
        )
        raise VaultLockedError(message).at(
            dataset=str(dataset), as_of=value, vault_id=self.declaration.vault_id
        )

    def check_path(
        self, dataset: DatasetId | str, *, purpose: str = "rows", caller: str | None = None
    ) -> None:
        """Admit or refuse a whole-file access to ``dataset``.

        ``purpose="metadata"`` is the only non-session allowance: catalog and integrity tooling may
        look at the file, and the call is logged. Any other purpose outside a session is refused,
        because a whole file cannot be cut to a date.
        """
        if not self.protects(dataset):
            return
        try:
            session = self._loaded_session(dataset, None)
        except VaultLockedError as exc:
            self._log(
                dataset=dataset,
                as_of=None,
                outcome="refused_session_scope",
                purpose=purpose,
                caller=caller,
                detail=str(exc),
            )
            raise
        if session is not None:
            self._log(
                dataset=dataset,
                as_of=None,
                outcome="allowed_evaluation",
                purpose=purpose,
                caller=caller,
                detail=f"whole file of evaluation {session.vr_id}",
            )
            return
        if purpose == "metadata":
            self._log(
                dataset=dataset,
                as_of=None,
                outcome="allowed_metadata",
                purpose=purpose,
                caller=caller,
                detail="whole file for counts, hashes and date bounds only",
            )
            return
        message = self._refusal(
            dataset,
            "a whole-file access (data_path) cannot be cut to a date, so it is refused outside "
            "an authorized evaluation",
        )
        self._log(
            dataset=dataset,
            as_of=None,
            outcome="refused",
            purpose=purpose,
            caller=caller,
            detail=message,
        )
        raise VaultLockedError(message).at(dataset=str(dataset), vault_id=self.declaration.vault_id)

    def _refusal(self, dataset: DatasetId | str, what: str) -> str:
        declaration = self.declaration
        return (
            f"the futures holdout vault {declaration.vault_id} protects "
            f"{', '.join(declaration.universe)} from trade date "
            f"{declaration.start_trade_date} (open-ended): {what}. Data of the protected period "
            "is readable only through its authorized evaluation. Register a config with "
            "`crucible vault register --config FILE`, have a human authorize it with "
            "`crucible vault authorize --registration VR-...`, then run "
            "`crucible vault evaluate --registration VR-...` (ADR-0105). "
            f"Dataset: {dataset}"
        )


def _iso_ns(ns: int) -> str:
    return dt.datetime.fromtimestamp(int(ns) / 1e9, tz=dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def default_guard(store_root: Path | None, *, home: object = _MISSING) -> VaultGuard | None:
    """The guard a store should use, cached by the declaration files' ``(mtime, size)``.

    Cheap enough to call on every store construction: with no declaration the two ``stat`` calls
    are the whole cost, and a declaration written while the process runs is picked up.
    """
    resolved_home = _resolve_home(home)
    key = (
        None if store_root is None else str(store_root),
        None if resolved_home is None else str(resolved_home),
    )
    stamp = (
        _stamp(None if store_root is None else store_root / DECLARATION_FILE),
        _stamp(None if resolved_home is None else Path(resolved_home) / DECLARATION_FILE),
    )
    cached = _GUARD_CACHE.get(key)
    if cached is not None and cached[0] == stamp:
        return cached[1]
    guard = VaultGuard.load(store_root, home=resolved_home)
    _GUARD_CACHE[key] = (stamp, guard)
    return guard


def _stamp(path: Path | None) -> tuple[int, int] | None:
    if path is None:
        return None
    try:
        stat = path.stat()
    except OSError:
        return None
    return (stat.st_mtime_ns, stat.st_size)


_GUARD_CACHE: dict[tuple[str | None, str | None], tuple[object, VaultGuard | None]] = {}
"""``(store root, home) -> (declaration stamp, guard)``. Not part of the public surface."""


def clear_guard_cache() -> None:
    """Forget the cached guards (a test that rewrites a declaration calls this)."""
    _GUARD_CACHE.clear()


# ---------------------------------------------------------------------------------------------
# e. the explicit, config-level check (a clear message before a single row is read)


def refuse_protected_window(
    *,
    root: str,
    start: dt.date,
    end: dt.date,
    store_root: Path,
    home: object = _MISSING,
    what: str,
    purpose: str = "strategy",
) -> None:
    """Refuse a futures run/batch/walk-forward whose window reaches a declared vault.

    The data-layer guard already refuses the READ (that is the enforcement, ADR-0105 decision 3);
    this check exists so the refusal arrives before any work, with the window named. ``purpose``
    ``"evaluate"`` is the authorized path and therefore allowed (the session enforces the window
    end on every read).
    """
    if purpose in ("evaluate", "metadata") or current_vault_session() is not None:
        return  # an authorized evaluation IS the permission (its session bounds every read)
    guard = default_guard(store_root, home=home)
    if guard is None or not guard.declaration.covers_root(root):
        return
    declaration = guard.declaration
    if end < declaration.start_trade_date:
        return
    msg = (
        f"{what} covers Globex trade dates {start}..{end}, and the futures holdout vault "
        f"{declaration.vault_id} protects {', '.join(declaration.universe)} from trade date "
        f"{declaration.start_trade_date} (open-ended). Narrow the window to end before "
        f"{declaration.start_trade_date} (strategy work keeps everything up to "
        "2024-12-31), or register and have a human authorize a single evaluation: "
        "`crucible vault register --config FILE` -> `crucible vault authorize --registration "
        "VR-...` -> `crucible vault evaluate --registration VR-...` (ADR-0105)"
    )
    guard._log(
        dataset=f"{root}_*",
        as_of=None,
        outcome="refused_window",
        purpose=purpose,
        caller=what,
        detail=msg,
    )
    raise VaultLockedError(msg).at(
        root=root.upper(), window_end=end.isoformat(), vault_id=declaration.vault_id
    )
