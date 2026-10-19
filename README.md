# Crucible

**Backtest a trading idea by describing it. Get an honest answer.**

Tell your AI agent - Claude, Codex, Cursor, Gemini - a strategy in plain words. Crucible tests it
on historical prices against simply holding, puts an approximate 95% range on the Sharpe ratio,
counts how many variants you tried, and says in plain language when the result is too weak to mean
anything. You
never write code.

> *"Backtest buying SPY when the 10-day average crosses above the 30-day and selling when it
> crosses below. Long only, 2015 to 2025, $100,000."*

```text
SMA 10/30 crossover turned $100,000 into $225,789 (+125.8%, 7.7% a year) on SPY; buying and
holding would have made $399,682 (+299.7%, 13.5% a year).

Verdict: Not conclusive: it made money in this one backtest and earned less than buy-and-hold; the
evidence is too thin to tell skill from luck.

  Metric                                Strategy             Buy and hold
  Final value                           $225,789             $399,682
  Total return                          +125.8%              +299.7%
  Return per year                       7.7%                 13.5%
  Volatility (per year)                 10.9%                17.8%
  Worst fall from a peak                -17.8%               -33.7%
  Sharpe ratio (95% range)              0.74 (0.10 to 1.34)  0.80 (0.28 to 1.44)
  Completed trades                      39                   -
  Winning trades (before costs)         48.7%                -
  Average bars held                     47.3                 -
  Time in the market                    67.3%                100.0%
  Variants tried (trial count)          1                    -
  Chance the Sharpe is real (deflated)  99%                  -
  Shuffled-returns p-value              0.228                -
  Realism level                         BASIC_FRICTION       -
  - Only 39 completed trades. One instrument is one history. Per unit of risk it did not improve
    on buy-and-hold.
```

That is the product: not "your strategy is great", but what the numbers do and do not show.

## Get started

**1. Install** (needs [uv](https://docs.astral.sh/uv/); it brings its own Python)

```bash
uv tool install git+https://github.com/samugallegoar/crucible
```

**2. Connect your agent** - add this server to its MCP settings:

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

Claude Code: `claude mcp add crucible -- uvx --from git+https://github.com/samugallegoar/crucible crucible-mcp`.
Cursor, VS Code, Codex and Gemini CLI: [install and connect](docs/guide/install-and-connect.md).

**3. Ask.** Paste one of these:

- *Backtest "buy when RSI(14) is below 30, sell when it is above 55, stop at 8%" on QQQ and AAPL,
  2012 to 2024, with conservative costs.*
- *Does a 200-day moving-average trend filter on SPY beat holding it? Be honest about whether the
  result means anything.*
- *Try the same rule on 2005 to 2014 and tell me if it still holds.*
- *Show me my earlier backtests.*

No agent? `crucible backtest --entry "sma(10) crosses_above sma(30)" --exit "sma(10) crosses_below sma(30)" --symbols SPY --start 2015-01-01 --end 2025-12-30`.

## What you get back

- **Strategy next to buy-and-hold**, same instruments, period and costs: return, worst fall,
  Sharpe ratio, number of trades.
- **An approximate 95% range on the Sharpe ratio** (a block bootstrap; the return and drawdown
  figures are point estimates without one), and the **trial count**: how many variants you have
  tried on these symbols. Try enough and one looks great by luck; Crucible counts the ones it ran
  and deflates. It cannot count variants you tried elsewhere.
- **A verdict in words**: *no edge detected*, *not conclusive*, or *some evidence*. It never says a
  strategy "works", and it names the reasons (few trades, one instrument, a short period, ...).
- **A report** you open in a browser: equity curve against buy-and-hold, drawdowns, every trade,
  what to try next. Same strategy, data and settings always give the same report.

How to read it: [reading a report](docs/guide/reading-a-report.md). A full worked example:
[an example session](docs/guide/example-session.md) and [its report](docs/guide/example-report.html) (download and open).

## What it can test

Rules written as a few lines of data, no code: moving-average crossovers (SMA, EMA), RSI and
momentum thresholds, channel breakouts, Bollinger bands, long only or long/short, all-in or a fixed
fraction of capital, stop-loss, take-profit and maximum holding time, on one or many instruments
(US equities and ETFs, indices, crypto; daily bars from Yahoo Finance or Tiingo, and intraday
bars of 5, 15 or 30 minutes or 1 hour from Yahoo Finance, which keeps about 60 days of the shorter
ones and about two years of hourly bars).
[Strategy spec reference](docs/guide/strategy-spec.md).

Why the answers are trustworthy rather than flattering: a rule only ever sees bars that had
closed by the simulated moment (point-in-time *access*, enforced in code; the stored prices are not
a versioned record of what was known on each date), the engine refuses suspicious states instead of
warning, results are deterministic, and a Sharpe ratio is never reported without its interval,
trial count and realism level. What it cannot give you: the prices are today's dividend-and-split
adjusted series (not the quotes traded on the day), fills are simulated from daily or intraday bars (no order
book, no market impact), and the statistics are honest about luck only for the variants Crucible
saw. The engineering behind that is in
the [contributor hub](docs/contributing/README.md).

## What Crucible does not do

No options, no live trading or broker connection, no investment advice, no prediction. A backtest is
a story about the past. The limits are listed plainly in
[what Crucible does not do](docs/guide/what-crucible-does-not-do.md).

## More

| | |
|---|---|
| [Install and connect](docs/guide/install-and-connect.md) | Claude Desktop/Code, Cursor, VS Code, Codex, Gemini |
| [Strategy spec](docs/guide/strategy-spec.md) | the rule language and plain-language translations |
| [Reading a report](docs/guide/reading-a-report.md) | what each number means and how far to trust it |
| [FAQ](docs/guide/faq.md), [Troubleshooting](docs/guide/troubleshooting.md) | |
| [Agent guide](AGENT_GUIDE.md) | what an agent does when you hand it a strategy |
| [Contributing](CONTRIBUTING.md), [AGENTS.md](AGENTS.md), [docs index](docs/README.md) | the engine, ADRs, module pages |

## License

MIT; see [`LICENSE`](LICENSE).
