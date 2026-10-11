# An example session: SMA 10/30 on SPY

A real transcript of what happens when you ask an agent to test the classic moving-average
crossover. The numbers come from running `crucible backtest` on SPY (adjusted prices from Yahoo
Finance, 2015-01-01 to 2025-12-30) from a clean home folder. Prices are re-adjusted by Yahoo for
every dividend, so a run on another day can differ by a few dollars; the trade count, the 17.8%
worst fall and the Sharpe range reproduce.

## You

> Backtest buying SPY when the 10-day moving average crosses above the 30-day and selling when it
> crosses below. No shorting, 2015 to 2025, $100,000.

## The agent checks the rule with you

The agent has no missing answers (instrument, period, capital, long-only, an exit rule), so it
uses the default costs and reads the rule back by calling `crucible_check_strategy`:

> This is what I will test, tell me if it is wrong:
> - Buy when the 10-bar simple moving average of the closing price crosses above the 30-bar one.
> - Sell when it crosses back below.
> - Long only, all of the capital, no leverage. Costs: 1 bp slippage + 0.5 bp commission per trade.

## The call (what the agent sends; you never write it)

```json
{
  "tool": "crucible_backtest",
  "arguments": {
    "symbols": "SPY", "start": "2015-01-01", "end": "2025-12-30", "capital": 100000,
    "name": "SMA 10/30 crossover",
    "spec": {
      "spec_version": 1, "direction": "long_only",
      "entry": {"long": "sma(10) crosses_above sma(30)"},
      "exit":  {"long": "sma(10) crosses_below sma(30)"}
    }
  }
}
```

Crucible downloads SPY once, checks the data (sorted, positive prices, bar consistency, session
coverage), runs the strategy, runs buy-and-hold, runs 100 shuffles, and writes the report. About six
seconds.

## What comes back (the parts the agent reads to you)

```text
SMA 10/30 crossover turned $100,000 into $227,474 (+127.5%, 7.8% a year) on SPY from 2015-01-02
to 2025-12-30; buying and holding SPY would have made $402,665 (+302.7%, 13.5% a year).

Verdict: Not conclusive: it made money in this one backtest and earned less than buy-and-hold; the
evidence is too thin to tell skill from luck (see the warnings). Treat it as an idea worth testing
further, not a basis for real money.

                      Strategy                    Buy and hold
  Final value         $227,474                    $402,665
  Return per year     7.8%                        13.5%
  Worst fall          -17.8%                      -33.7%
  Sharpe (95% range)  0.74 (0.11 to 1.36)         0.80 (0.29 to 1.45)
  Trades              39                          -

Warnings:
  - The 95% range for the Sharpe ratio is wide (0.11 to 1.36): the data cannot pin down how good
    the strategy is, only that the estimate is above zero.
  - Only 39 completed trades. A few dozen decisions are not enough to separate skill from luck (this
    report asks for 100 or more).
  - One instrument (SPY) is one history. A rule that fits it may be a coincidence of that
    particular path; it has not been tested anywhere else.
  - Per unit of risk, the strategy did not improve on simply buying and holding (Sharpe 0.74 vs 0.80).
```

Also in the document: trial count 1, deflated Sharpe 0.99, the shuffle test (matched or beat in none
of 100 tries), 49% of trades profitable before costs, invested 67% of the time, the 39 trades one
by one, and `report`: the absolute path of `summary.html`.

## What the agent tells you

> Honest summary: the rule made about 7.8% a year against 13.5% for just holding SPY, so it
> **trailed** buy-and-hold by a wide margin. What it did buy you is a milder worst fall, about -18%
> against -34% (it stepped aside in 2020 and 2022). That is real, but it is one instrument and 39
> trades, and the range for how good it is runs from barely above zero to quite good, so this is
> **not conclusive**. It passed the check that shuffling the days breaks it, which says the timing
> matters in this data, not that it will keep working. This is a historical simulation, not advice.
>
> Reasonable next steps: the same rule on 2005-2014 (which includes 2008), on other index funds, and
> with conservative costs. Want me to run those? Each variant I try counts as a trial and lowers the
> reliability of the next result, and I will tell you how many we have used.

## Follow-ups

> Does it hold with realistic fills?

The agent repeats the call with `realism_check: true` (about 30 seconds more). Crucible re-runs the
same rules on the event-driven engine with next-bar fills, a spread and 100 ms latency, and adds to
the report that it would have ended at $228,193 (7.8% a year, worst fall -17.0%): here the
optimistic timing did not flatter the result, which is worth knowing. It is not counted as a new
trial.

> Try 2005 to 2014.

A new window on the same symbols stays in the same trial family (`quick:spy`), so the trial count
goes up: trying another period is part of the same search, and the deflated Sharpe ratio accounts for
it. To treat a period as a separate, pre-registered test, pass an explicit `family`.

> Show me what I have run so far.

`crucible_results` (or `crucible results`) lists them, newest first, with report paths.
