# Troubleshooting

Every refusal says what is wrong and how to fix it; these are the common ones and some environment
problems.

| You see | Why | Fix |
|---|---|---|
| `end 2025-12-31 is not in the past` | a window that includes today's unfinished session would change tomorrow | use yesterday or earlier |
| `no stored data ... offline mode is on` | `--offline`/`offline: true` and this exact request was never fetched | run once without it, connected |
| `could not reach yfinance` / `rate limiting` | no connection, or Yahoo is throttling | wait a few minutes and repeat the same request; answers already fetched are cached |
| `returned no 1d rows for XYZ` / unknown ticker | wrong symbol for the provider | use the Yahoo symbol (`BRK-B`, `^GSPC`, `BTC-USD`) |
| `data-quality check 'ohlc_bounds' failed` | a bar whose high/low do not contain open/close by more than rounding noise | the data is bad; try another provider (`--provider tiingo`) or another window |
| `has no bars before 2017-05-01` in warnings | the symbol started trading after your start date | start later; the benchmark and strategy only cover where all symbols exist |
| `the window ... is too short for rules that need N bars` | indicators need history inside the window | lengthen the period or shorten the periods |
| `entry.long has no way out` | an entry without an exit would hold forever | add `exit`, a stop, or `max_holding_bars` |
| `both true for SPY at ts=...` | long and short entries overlap | make them mutually exclusive |
| `the MCP server needs the 'mcp' package` | an old or broken install | `uv tool install --reinstall git+https://github.com/samugallegoar/crucible` |

## Windows

- **`UnicodeEncodeError` printing a table**: fixed; `crucible` writes UTF-8 whatever the console code
  page. If a script of your own prints Crucible frames, run it with `PYTHONUTF8=1`.
- **`VIRTUAL_ENV=... does not match the project environment`**: a stale variable from another
  project. `Remove-Item Env:VIRTUAL_ENV` for the session or delete it from your profile.
- **`uvx` not found**: `uv` is not on the PATH; reopen the terminal after installing, or run
  `uv tool update-shell`.
- Do not edit repository files with `Set-Content`; it adds a BOM and corrupts text.

## The agent cannot find results

`crucible config show` prints the home folder. If you started the server from different places and
see different folders, set one: `crucible config set-home PATH` (or `CRUCIBLE_HOME` in the server's
`env`). Relative paths a tool receives are resolved against `CRUCIBLE_WORKDIR`, defaulting to the
server's working directory.

## A call takes too long or hangs

A first run downloads data and a realism check adds about 30 seconds. The server stops any call
after `CRUCIBLE_MCP_TIMEOUT` seconds (default 900) and kills the work; cancelling a call in the
client does the same. The shuffled-returns test runs 1,000 shuffles by default, which takes
about 30 seconds for ten years of daily bars (more with several symbols or a long intraday
window), and some MCP clients give up on a tool call sooner than that. For a quick look ask for
fewer shuffles (`null_iterations: 100`, about six seconds); raise the client's tool timeout if it
has one.

## It will not use my own data

The one-step flow fetches from a provider. For your own files, build a dataset with
[`docs/data/adding-a-dataset.md`](../data/adding-a-dataset.md) and use a config
(`crucible run-vectorized`); this is the contributor path.
