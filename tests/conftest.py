"""Shared test configuration.

Hypothesis profiles: CI runs derandomized (AGENTS.md §7) so failures are
reproducible; local runs explore.
"""

from __future__ import annotations

import os
import socket
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest
from hypothesis import settings

# examples/ is an importable package rooted at the repo, used by integration
# and lookahead tests exactly the way `crucible run` loads it.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

settings.register_profile("ci", derandomize=True, max_examples=50)
settings.register_profile("local", max_examples=100)
settings.load_profile("ci" if os.environ.get("CI") else "local")


def pytest_addoption(parser: object) -> None:
    parser.addoption(  # type: ignore[attr-defined]
        "--regen-golden",
        action="store_true",
        default=False,
        help=(
            "Regenerate golden fixtures instead of comparing. Requires a "
            "justification in the commit message and a changelog/ADR entry "
            "(AGENTS.md §1.6). Never use it to make a red test green."
        ),
    )


def pytest_terminal_summary(
    terminalreporter: pytest.TerminalReporter, exitstatus: int, config: pytest.Config
) -> None:
    """Print the random seed at the end of the run too (ADR-0108).

    ``pytest-randomly`` reports it in the header, which ``-q`` hides — and ``-q`` is what CI and
    ``tools.check`` run. A random order without a printed, reproducible seed is a coin flip: the
    line below is what turns a failure into ``uv run pytest --randomly-seed=<seed>``."""
    seed = config.getoption("randomly_seed", None)
    if seed is None:
        return
    terminalreporter.write_sep("-", f"random order: reproduce with --randomly-seed={seed}")


def _slow_modules() -> frozenset[str]:
    """Test modules measured slow (``tests/slow_modules.txt``, ``python -m tools.slow_report``)."""
    path = Path(__file__).resolve().parent / "slow_modules.txt"
    if not path.is_file():
        return frozenset()
    return frozenset(
        line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    )


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Marks slow modules ``slow`` and skips benchmarks unless ``-m bench``.

    The ``slow`` marker only *selects*: a plain ``pytest`` still runs every test, and the fast
    tier is the opt-in ``-m "not slow"``. Benchmarks never gate correctness (AGENTS.md section 7).
    """
    slow = _slow_modules()
    root = Path(__file__).resolve().parent.parent
    for item in items:
        module = Path(str(item.path)).resolve()
        try:
            relative = module.relative_to(root).as_posix()
        except ValueError:
            continue
        if relative in slow:
            item.add_marker(pytest.mark.slow)
    if "bench" in (config.getoption("-m") or ""):
        return
    skip = pytest.mark.skip(reason="benchmark: run with -m bench")
    for item in items:
        if "bench" in item.keywords:
            item.add_marker(skip)


_REAL_CONNECT = socket.socket.connect
_REAL_CONNECT_EX = socket.socket.connect_ex


def _is_local(address: object) -> bool:
    host = address[0] if isinstance(address, tuple) and address else address
    return isinstance(host, str) and (host in {"localhost", "::1", ""} or host.startswith("127."))


@pytest.fixture(autouse=True)
def _no_real_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """No test may open a connection to a non-local address (ADR-0063): providers are tested
    with injected transports, never the network. Local sockets stay allowed."""

    def guarded_connect(self: socket.socket, address: object) -> None:
        if not _is_local(address):
            msg = f"a test tried to open a real network connection to {address!r}"
            raise RuntimeError(msg)
        _REAL_CONNECT(self, address)  # type: ignore[arg-type]

    def guarded_connect_ex(self: socket.socket, address: object) -> int:
        if not _is_local(address):
            msg = f"a test tried to open a real network connection to {address!r}"
            raise RuntimeError(msg)
        return _REAL_CONNECT_EX(self, address)  # type: ignore[arg-type]

    monkeypatch.setattr(socket.socket, "connect", guarded_connect)
    monkeypatch.setattr(socket.socket, "connect_ex", guarded_connect_ex)


@pytest.fixture(scope="session", autouse=True)
def _throwaway_crucible_home(tmp_path_factory: pytest.TempPathFactory) -> Iterator[None]:
    """Every test session gets its own Crucible home and settings file (ADR-0105).

    The futures holdout vault is declared in the real home AND in the real store, and the guard
    enforces it if either copy exists. A test that resolved the real home would therefore (a) read
    the vault's access log into a real file and (b) be refused on synthetic datasets named after a
    declared root (``es_1m_cont_v3`` in a ``tmp_path`` store). Pointing ``CRUCIBLE_HOME`` and
    ``CRUCIBLE_SETTINGS`` at a throwaway folder keeps the suite hermetic: no test writes to a
    person's home, and a declaration in it cannot change a result.
    """
    home = tmp_path_factory.mktemp("crucible-home")
    previous = {name: os.environ.get(name) for name in ("CRUCIBLE_HOME", "CRUCIBLE_SETTINGS")}
    os.environ["CRUCIBLE_HOME"] = str(home)
    os.environ["CRUCIBLE_SETTINGS"] = str(home / "settings.json")
    try:
        yield
    finally:
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
