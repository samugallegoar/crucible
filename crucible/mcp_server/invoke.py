"""Runs a CLI command and returns its ``--json`` document (ADR-0066).

The MCP tools are thin: each builds the argv of an existing command and runs ``crucible <argv>``,
so a tool and the command cannot disagree (same validation, same refusals, same numbers). Each call
is a **fresh interpreter**: a long-lived server that imported strategy code in process would keep
serving the old module after the agent edited it (``sys.modules`` caches it, and nothing in a run's
manifest hashes the code), which would silently break reruns. A child process also keeps the CLI's
stdout out of the MCP protocol stream, needs no lock, and cannot be left half-run in the server.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence


class ToolRefusal(Exception):
    """The command refused or failed; the message is the CLI's own, actionable one."""


def invoke(argv: Sequence[str], *, timeout: float | None = None) -> dict[str, object]:
    """Runs ``python -m crucible.cli.main <argv>`` and returns the JSON object it printed.

    Raises ``ToolRefusal`` with the command's message when it exits non-zero (a refusal prints
    ``{"error": {"type", "message"}}`` under ``--json``; an argument error prints usage on stderr),
    when it prints no single JSON document, or when it exceeds ``timeout`` seconds.
    """
    try:
        done = subprocess.run(
            [sys.executable, "-m", "crucible.cli.main", *argv],
            stdin=subprocess.DEVNULL,  # the child must never read the MCP protocol stream
            capture_output=True,
            text=True,
            encoding="utf-8",
            env={**os.environ, "PYTHONUTF8": "1"},
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        msg = f"crucible {argv[0]} did not finish within {timeout} seconds and was stopped"
        raise ToolRefusal(msg) from None
    payload: object = None
    try:
        payload = json.loads(done.stdout) if done.stdout.strip() else None
    except ValueError:
        payload = None
    if done.returncode != 0:
        raise ToolRefusal(_message(payload, done.stderr, done.stdout, done.returncode))
    if not isinstance(payload, dict):
        msg = f"crucible {argv[0]} printed no JSON document (stdout: {done.stdout[:200]!r})"
        raise ToolRefusal(msg)
    return payload


def _message(payload: object, stderr: str, stdout: str, code: int) -> str:
    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict) and "message" in error:
            return f"{error.get('type', 'error')}: {error['message']}"
    text = (stderr.strip() or stdout.strip() or f"exit code {code}").splitlines()
    # argparse prints the usage first and the actionable "error:" line last: keep the tail
    return "\n".join(text[-6:])[-2000:]
