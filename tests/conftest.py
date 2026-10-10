"""Shared test configuration.

Hypothesis profiles: CI runs derandomized (AGENTS.md §7) so failures are
reproducible; local runs explore.
"""

from __future__ import annotations

import os
import socket
import sys
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


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Benchmarks run only with ``-m bench``; they never gate correctness (AGENTS.md section 7)."""
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
