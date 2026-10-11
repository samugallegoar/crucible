# FAQ

**Do I need to write code or YAML?**
No. You describe the strategy; your agent builds the spec and calls Crucible. If you want to see or
edit the spec it is a few lines ([strategy spec](strategy-spec.md)).

**Does it need an API key or an account?**
No. Prices come from Yahoo Finance through `yfinance` (free, unofficial). Tiingo is an optional,
official alternative with a free key (`TIINGO_API_KEY`).

**Is my data sent anywhere?**
Crucible runs on your machine. It only makes requests to the price provider, for the symbols and
dates you asked for. Results stay in your home folder (`crucible config show`).

**Why does it say "not conclusive" about a strategy that made money?**
Because one good backtest is weak evidence: few trades, one instrument, a short or lucky period or
many variants tried can all produce it by chance. The verdict names the specific reasons.
[Reading a report](reading-a-report.md) lists them.

**Why is a strategy "worse" than buy-and-hold and still interesting?**
Because return is not everything: a smaller worst fall, or a different kind of risk, can be worth a
lower return. The report shows both and does not pick for you.

**Can it tell me what to buy?**
No. It tests an idea you give it, against history. It is not investment advice.

**Can I test intraday strategies?**
Yes: pass `interval` (`1h`, `30m`, `15m` or `5m`; `--interval` on the command line). Rules count
bars of that interval, Sharpe and returns are annualized from the number of bars per session, and
trades are timestamped to the minute. Yahoo keeps about 60 days of 5-30 minute bars and about two
years of hourly bars, so intraday tests are short and the report will usually say "not
conclusive". Rules cannot use the time of day yet.

**How are the confidence intervals made?**
A circular block bootstrap of the bar returns (blocks of about the square root of the number
of days, 1,000 resamples, the 2.5th and 97.5th percentiles). In the one-step report only the
Sharpe ratio carries one; the return and drawdown are point estimates. The interval is
approximate: on synthetic data with a known Sharpe ratio it held the true value 94-95% of the
time with five years of data, but only about 91-93% with one year, and about 91% with heavy-tailed
returns even over five years (the blocks do handle autocorrelation; the measured numbers are in
ADR-0070). Treat it as the least uncertainty there is, not the most.

**What is the trial count and why does it matter?**
It is the number of different variants tried on the same symbols, over any period, in this
Crucible home (pass a `family` to group differently). Try enough and one looks great by luck.
Crucible counts them and reduces the deflated Sharpe accordingly. Renaming a strategy does not add a
trial; changing a number or the period does. A second count covers every backtest in your
Crucible home, other instruments included, and the strongest verdict needs to clear both. Variants
you tried outside Crucible are not counted, so the correction can only be too small, never too
large.

**What do the costs mean?**
`standard`: 1 basis point of slippage and 0.5 of commission on every trade (a liquid large ETF or
stock, small size, low-cost broker). `conservative`: 5 and 2. `none`: an upper bound no account
gets. A basis point is 0.01%.

**Does it handle dividends and splits?**
The one-step flow uses adjusted prices, which already include them, so returns are total
returns. It refuses raw prices, because without dividend events they would silently understate
returns; raw prices with corporate-action datasets are an event-driven-engine feature
([`docs/modules/data.md`](../modules/data.md)).

**Can I test crypto, futures, FX, options?**
Crypto works with Yahoo symbols such as `BTC-USD` and `--calendar 24/7` (the year is then 365 days).
Futures and FX exist in the engine through configs, not the one-step flow. Options are not
supported. See [what Crucible does not do](what-crucible-does-not-do.md).

**Can I trust a result tomorrow?**
Same rules, same data, same settings give the same numbers and the same files. The dataset hash is
in every report. Re-fetching later can change adjusted prices slightly, which changes the hash.

**Where are my files?**
`crucible config show` prints the home folder. Reports are in `experiments/EXP-.../summary.html`.
