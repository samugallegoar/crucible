"""``crucible prop confirm <file>``: the owner's interactive verification step (ADR-0107 s2).

Verification is a HUMAN step and never an agent's. Like ``crucible vault set-admin`` (ADR-0105),
the command refuses when standard input is not a TTY: a sidecar written from a pipe, a script or
an environment variable could only come from the agent that the protocol is meant to exclude.

The command prints every rule with its evidence, quotation, URL, conflicts and assumptions, then
asks the owner to type the first 12 hexadecimal characters of the content hash. Only then does it
write ``<file>.verification.yaml``. It is never exposed over MCP.
"""

from __future__ import annotations

import sys
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import TextIO

from crucible.core.errors import ConfigurationError
from crucible.prop.ruleset import (
    PropRuleset,
    load_ruleset,
    sidecar_path,
    write_verification_sidecar,
)


def _attribution_line(source: object) -> str:
    url = getattr(source, "url", None) or f"provided by {getattr(source, 'provided_by', None)}"
    quote = getattr(source, "quote", "")
    return f"    source: {url}\n    quote:  {quote}"


def manifest_lines(ruleset: PropRuleset) -> list[str]:
    """Every rule, its evidence and source, then conflicts and assumptions (ADR-0107 section 2)."""
    lines = [
        f"ruleset {ruleset.ruleset_id} v{ruleset.version} ({ruleset.firm} / {ruleset.program})",
        f"content hash: {ruleset.ruleset_sha256}",
        "",
    ]
    for phase in ruleset.phases:
        lines.append(f"phase {phase.phase_id} ({phase.kind})")
        for group, rules in (
            ("rule", phase.rules),
            ("pass condition", phase.pass_conditions),
            ("fee", phase.fees),
        ):
            for rule in rules:
                lines.append(f"  {group} {rule.rule_id}: {rule.kind} [{rule.evidence}]")
                lines.append(f"    {rule.description or ''}".rstrip())
                lines.append(_attribution_line(rule.source))
                assumption = getattr(rule, "assumption", None)
                if assumption is not None:
                    lines.append(f"    assumption {assumption.name}: {assumption.rationale}")
    for entry in ruleset.not_modeled:
        lines.append(f"  not_modeled {entry.rule} ({entry.materiality}): {entry.description}")
        lines.append(_attribution_line(entry.source))
    for conflict in ruleset.conflicts:
        lines.append(
            f"  conflict {conflict.conflict_id} on {conflict.rule_id}.{conflict.field}: "
            f"selected {conflict.selected_value!r}"
        )
        for index, alternative in enumerate(conflict.alternatives):
            lines.append(f"    alternative {index}: {alternative.value!r}")
            lines.append(_attribution_line(alternative.source))
        lines.append(f"    rationale: {conflict.rationale}")
    return lines


def _read_line(prompt: str) -> str:
    return input(prompt)


def confirm_ruleset(
    path: str | Path,
    *,
    stdin: TextIO | None = None,
    stdout: TextIO | None = None,
    reader: Callable[[str], str] | None = None,
    confirmed_by: str | None = None,
    confirmation_note: str = "owner confirmed every rule in an interactive session",
) -> Path:
    """Print the ruleset and, after the owner types the hash prefix, write the sidecar."""
    stream = sys.stdin if stdin is None else stdin
    out = sys.stdout if stdout is None else stdout
    if not getattr(stream, "isatty", lambda: False)():
        msg = (
            "`crucible prop confirm` needs an interactive TTY: verification is the OWNER's step "
            "and must not run from a pipe, a script or an agent (ADR-0107 section 2, like "
            "`crucible vault set-admin`)"
        )
        raise ConfigurationError(msg)
    ruleset_path = Path(path)
    ruleset = load_ruleset(ruleset_path)
    if ruleset.verified:
        raise ConfigurationError(
            f"ruleset {ruleset.ruleset_id} v{ruleset.version} is already verified by "
            f"{ruleset.verification.confirmed_by}; a change is a new version"
        )
    for line in manifest_lines(ruleset):
        out.write(line + "\n")
    prefix = ruleset.ruleset_sha256[:12]
    ask = reader or _read_line
    typed = ask(f"Type the first 12 hex characters of the content hash ({prefix}) to confirm: ")
    if typed.strip().lower() != prefix:
        msg = (
            f"the typed value does not match {prefix}: nothing was verified, no sidecar was written"
        )
        raise ConfigurationError(msg)
    owner = confirmed_by or _owner(stdin)
    return write_verification_sidecar(
        ruleset_path,
        ruleset,
        confirmed_by=owner,
        confirmation_note=confirmation_note,
    )


def _owner(stdin: TextIO | None) -> str:
    import getpass
    import os

    del stdin
    try:
        return getpass.getuser()
    except (OSError, KeyError):  # pragma: no cover - a platform without a user name
        return os.environ.get("USER", "owner")


def sidecar_for(path: str | Path) -> Path:
    return sidecar_path(path)


def iter_rules(ruleset: PropRuleset) -> Iterable[object]:
    for phase in ruleset.phases:
        yield from phase.rules
        yield from phase.pass_conditions
        yield from phase.fees
