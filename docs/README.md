# Documentation

## Using Crucible

For people who want to test a strategy, and for the agents that do it for them.

| Page | Read it to |
|---|---|
| [Install and connect your agent](guide/install-and-connect.md) | install Crucible and add it to Claude Desktop/Code, Cursor, VS Code, Codex or Gemini |
| [An example session](guide/example-session.md) | see a whole request, result and explanation (SMA 10/30 on SPY); the [report it produced](guide/example-report.html) (download and open) |
| [Strategy spec](guide/strategy-spec.md) | write or read a rule: conditions, indicators, sizing, stops, plain-language translations |
| [Reading a report](guide/reading-a-report.md) | understand each number, the verdict and the warnings |
| [FAQ](guide/faq.md) and [Troubleshooting](guide/troubleshooting.md) | fix a refusal or a Windows/environment problem |
| [What Crucible does not do](guide/what-crucible-does-not-do.md) | know the limits before you rely on it |
| [`AGENT_GUIDE.md`](../AGENT_GUIDE.md) | (agents) exactly what to do when a person hands you a strategy |

## Building on Crucible

For people extending the engine, and agents working on this repository. Start at the
[contributor hub](contributing/README.md); `AGENTS.md` at the repository root is the operating manual.

## Where the reference pages are

The architecture, conventions, schemas, ADRs and per-module pages are the engineering reference.
They keep their paths because the code, the tests and the append-only decision records cite them
(ADR-0069). The hub lists them by purpose.
