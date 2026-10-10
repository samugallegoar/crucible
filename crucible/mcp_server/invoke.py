"""Runs a CLI command and returns its ``--json`` document (ADR-0066).

The MCP tools are thin: each builds the argv of an existing command and runs ``crucible <argv>``,
so a tool and the command cannot disagree (same validation, same refusals, same numbers). Each call
is a **fresh interpreter**: a long-lived server that imported strategy code in process would keep
serving the old module after the agent edited it (``sys.modules`` caches it, and nothing in a run's
manifest hashes the code), which would silently break reruns. A child process also keeps the CLI's
stdout out of the MCP protocol stream, needs no lock, and cannot be left half-run in the server.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path


def _child_env() -> dict[str, str]:
    """The child's environment: UTF-8 I/O, and no inherited virtualenv (a stale ``VIRTUAL_ENV``
    makes uv-launched tools print a warning on every call)."""
    env = {**os.environ, "PYTHONUTF8": "1"}
    env.pop("VIRTUAL_ENV", None)
    return env


class ToolRefusal(Exception):
    """The command refused or failed; the message is the CLI's own, actionable one."""


def invoke(
    argv: Sequence[str], *, timeout: float | None = None, cwd: Path | None = None
) -> dict[str, object]:
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
            env=_child_env(),
            timeout=timeout,
            cwd=cwd,
            check=False,
        )
    except subprocess.TimeoutExpired:
        msg = f"crucible {argv[0]} did not finish within {timeout} seconds and was stopped"
        raise ToolRefusal(msg) from None
    return _document(argv, done.returncode, done.stdout, done.stderr)


async def ainvoke(
    argv: Sequence[str], *, timeout: float | None = None, cwd: Path | None = None
) -> dict[str, object]:
    """Like :func:`invoke`, but cancellable: when the awaiting task is cancelled (the client
    cancelled the call, or the server is shutting down) or ``timeout`` passes, the child process
    is killed instead of being left to run on."""
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "crucible.cli.main",
        *argv,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=_child_env(),
        cwd=cwd,
    )
    try:
        out, err = await asyncio.wait_for(process.communicate(), timeout=timeout)
    except TimeoutError:
        process.kill()
        await process.wait()
        msg = f"crucible {argv[0]} did not finish within {timeout} seconds and was stopped"
        raise ToolRefusal(msg) from None
    except BaseException:  # includes CancelledError: never leave the child running
        process.kill()
        await asyncio.shield(process.wait())
        raise
    return _document(
        argv,
        process.returncode if process.returncode is not None else -1,
        out.decode("utf-8", errors="replace"),
        err.decode("utf-8", errors="replace"),
    )


def _document(argv: Sequence[str], returncode: int, stdout: str, stderr: str) -> dict[str, object]:
    payload: object = None
    try:
        payload = json.loads(stdout) if stdout.strip() else None
    except ValueError:
        payload = None
    if returncode != 0:
        raise ToolRefusal(_message(payload, stderr, stdout, returncode))
    if not isinstance(payload, dict):
        msg = f"crucible {argv[0]} printed no JSON document (stdout: {stdout[:200]!r})"
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
