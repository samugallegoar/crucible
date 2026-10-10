# Install Crucible and connect your agent

Three steps: install, connect, ask. You need [uv](https://docs.astral.sh/uv/) (it brings its own
Python) and an AI client that can use local MCP servers.

## 1. Install

Pick one. Both give you the `crucible` command and the `crucible-mcp` server.

```bash
# a permanent install (recommended)
uv tool install git+https://github.com/samugallegoar/crucible

# or run it on demand, nothing installed (what the connection snippets below do)
uvx --from git+https://github.com/samugallegoar/crucible crucible --version
```

From a clone of the repository: `uv tool install .` (or `uvx --from /path/to/crucible ...`).
`pipx install git+https://github.com/samugallegoar/crucible` works the same way. Check it:

```bash
crucible --version
crucible config show        # where your data and results will be kept
```

If your shell prints a `VIRTUAL_ENV ... does not match` warning on every `uv run`, an old virtual
environment is still exported in your profile. Remove it for the session (`deactivate`, or
`Remove-Item Env:VIRTUAL_ENV` in PowerShell) or delete the variable from your profile. The installed
`crucible` and `crucible-mcp` commands are not affected, and the MCP server strips it from its own
child processes.

## 2. Connect your agent

The server speaks MCP over standard input/output, so the client must be able to start a local
program. In every snippet, `uvx` downloads and runs Crucible the first time and reuses it afterwards.

**Claude Desktop** - open Settings > Developer > Edit config, add to `claude_desktop_config.json`,
then restart the app:

```json
{
  "mcpServers": {
    "crucible": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/samugallegoar/crucible", "crucible-mcp"]
    }
  }
}
```

**Claude Code**:

```bash
claude mcp add crucible -- uvx --from git+https://github.com/samugallegoar/crucible crucible-mcp
```

**Cursor** - `~/.cursor/mcp.json` (all projects) or `.cursor/mcp.json` (one project), the same JSON as
Claude Desktop above.

**VS Code (Copilot agent mode)** - `.vscode/mcp.json`:

```json
{
  "servers": {
    "crucible": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/samugallegoar/crucible", "crucible-mcp"]
    }
  }
}
```

**Codex CLI** - `~/.codex/config.toml`:

```toml
[mcp_servers.crucible]
command = "uvx"
args = ["--from", "git+https://github.com/samugallegoar/crucible", "crucible-mcp"]
```

**Gemini CLI** - `~/.gemini/settings.json`, same `mcpServers` object as Claude Desktop.

**ChatGPT (apps)** and other clients that accept only a *remote* MCP URL cannot start a local
server; Crucible has no hosted endpoint (see [what it does not do](what-crucible-does-not-do.md)).
Use a client from the list above, or paste the CLI commands into any agent that has a terminal.
Client menus and file locations change; if one of these moved, the pattern is always "a server
named `crucible` that runs `uvx --from <repo> crucible-mcp`".

Where results go: your **home folder** (`crucible config show`). Move it once with
`crucible config set-home D:\Backtests` or set `CRUCIBLE_HOME` in the `env` block of the server entry.

## 3. Ask

Give your agent the idea in plain words. It already knows how to use Crucible (the server hands
it [`AGENT_GUIDE.md`](../../AGENT_GUIDE.md)), but you can paste one of these:

> Backtest buying SPY when the 10-day average crosses above the 30-day average and selling when it
> crosses below. Long only, 2015 to 2025, $100,000. Compare it with just holding SPY and tell me
> honestly whether the result means anything.

> Test "buy when RSI(14) is below 30, sell when it is above 55, stop out at 8%" on QQQ and AAPL from
> 2012 to 2024. Use conservative costs.

> What happens to that SPY strategy if costs are worse? And does it hold in 2005 to 2014?

> Show me my earlier backtests.

You get back the numbers next to buy-and-hold, a plain-language verdict that says when the
evidence is weak, and a report file you can open in a browser. How to read it:
[reading a report](reading-a-report.md). A full worked example: [an example session](example-session.md).

## Without an agent

```bash
crucible backtest --entry "sma(10) crosses_above sma(30)" --exit "sma(10) crosses_below sma(30)" \
    --symbols SPY --start 2015-01-01 --end 2025-12-30 --capital 100000
crucible results
```

The first run downloads prices (internet needed once); the same request later runs offline and gives
byte-identical files.
