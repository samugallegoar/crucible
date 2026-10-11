"""The readable report: one self-contained HTML page, no scripts, no external assets (ADR-0068).

Reads the same document the JSON result is made of, so the page and the JSON cannot disagree. The
charts are inline SVG built here (no plotting library, no fonts or scripts fetched), numbers are
formatted with fixed precision, and nothing depends on the clock: the same document renders to
the same bytes.
"""

from __future__ import annotations

import html
from dataclasses import dataclass

_W, _H = 860, 300
_PAD_L, _PAD_R, _PAD_T, _PAD_B = 64, 16, 14, 28


@dataclass(frozen=True, slots=True)
class Series:
    label: str
    css: str  # "strategy" | "benchmark"
    values: list[float]


def _fmt_axis(value: float, kind: str) -> str:
    if kind == "pct":
        return f"{value:.0f}%"
    return f"${value:,.0f}"


def line_chart(dates: list[str], series: list[Series], *, kind: str, title: str) -> str:
    """An inline SVG with every series on shared axes; ``dates`` are ISO strings."""
    n = len(dates)
    if n < 2:
        return f"<p><em>{html.escape(title)}: not enough data to draw.</em></p>"
    flat = [v for s in series for v in s.values]
    lo, hi = min(flat), max(flat)
    if hi == lo:
        hi = lo + 1.0
    span = hi - lo
    lo -= span * 0.05
    hi += span * 0.05
    plot_w = _W - _PAD_L - _PAD_R
    plot_h = _H - _PAD_T - _PAD_B

    def x(i: int) -> float:
        return _PAD_L + plot_w * i / (n - 1)

    def y(v: float) -> float:
        return _PAD_T + plot_h * (1.0 - (v - lo) / (hi - lo))

    parts = [
        f'<svg viewBox="0 0 {_W} {_H}" role="img" aria-label="{html.escape(title)}" '
        'xmlns="http://www.w3.org/2000/svg">'
    ]
    for k in range(5):
        value = lo + (hi - lo) * k / 4
        yy = y(value)
        parts.append(
            f'<line class="grid" x1="{_PAD_L}" x2="{_W - _PAD_R}" y1="{yy:.1f}" y2="{yy:.1f}"/>'
            f'<text class="tick" x="{_PAD_L - 6}" y="{yy + 4:.1f}" text-anchor="end">'
            f"{_fmt_axis(value, kind)}</text>"
        )
    years: list[tuple[int, str]] = []
    last_year = ""
    for i, d in enumerate(dates):
        if d[:4] != last_year:
            last_year = d[:4]
            years.append((i, last_year))
    step = max(1, len(years) // 8)
    for i, year in years[::step]:
        parts.append(
            f'<text class="tick" x="{x(i):.1f}" y="{_H - 8}" text-anchor="middle">{year}</text>'
        )
    for s in series:
        points = " ".join(f"{x(i):.1f},{y(v):.1f}" for i, v in enumerate(s.values))
        parts.append(f'<polyline class="line {s.css}" points="{points}" fill="none"/>')
    parts.append("</svg>")
    legend = "".join(f'<span class="key {s.css}">{html.escape(s.label)}</span>' for s in series)
    body = "".join(parts)
    return (
        f"<figure><figcaption>{html.escape(title)}</figcaption>{body}"
        f'<div class="legend">{legend}</div></figure>'
    )


def downsample(
    values: list[float], dates: list[str], limit: int = 400
) -> tuple[list[str], list[float]]:
    if len(values) <= limit:
        return dates, values
    step = -(-len(values) // limit)
    idx = list(range(0, len(values), step))
    if idx[-1] != len(values) - 1:
        idx.append(len(values) - 1)
    return [dates[i] for i in idx], [values[i] for i in idx]


_CSS = """
:root{--bg:#ffffff;--fg:#1c2330;--muted:#5b6575;--line:#d9dee7;--card:#f6f8fb;
--strategy:#1f5fd6;--benchmark:#8a6d00;--warn:#8a4b00;--warnbg:#fff4e0;--ok:#14663a;--okbg:#e6f5ec;
--bad:#8c1d1d;--badbg:#fdeaea;--mid:#33415c;--midbg:#eef1f6}
@media (prefers-color-scheme:dark){:root{--bg:#10141c;--fg:#e4e8ef;--muted:#9aa5b6;--line:#2a3140;
--card:#171c27;--strategy:#6ea2ff;--benchmark:#e0b84a;--warn:#ffcc80;--warnbg:#3a2b12;--ok:#7fd9a4;
--okbg:#12301f;--bad:#ff9d9d;--badbg:#3a1717;--mid:#b9c3d6;--midbg:#1c2331}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);
font:16px/1.55 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
main{max-width:900px;margin:0 auto;padding:24px 16px 64px}
h1{font-size:1.5rem;margin:.2em 0}h2{font-size:1.15rem;margin:1.8em 0 .5em;
border-bottom:1px solid var(--line);padding-bottom:.25em}
.lead{font-size:1.1rem}.muted{color:var(--muted)}
.verdict{border-radius:8px;padding:12px 16px;margin:16px 0;border:1px solid var(--line)}
.verdict.not_conclusive{background:var(--warnbg);color:var(--warn)}
.verdict.some_evidence{background:var(--okbg);color:var(--ok)}
.verdict.no_edge_detected{background:var(--badbg);color:var(--bad)}
.verdict strong{display:block;font-size:1.05rem;margin-bottom:.2em}
table{border-collapse:collapse;width:100%;margin:.6em 0;font-variant-numeric:tabular-nums}
th,td{text-align:left;padding:6px 10px;border-bottom:1px solid var(--line)}
th{font-weight:600;color:var(--muted)}td.num,th.num{text-align:right}
.scroll{overflow-x:auto}ul{padding-left:1.2em}li{margin:.3em 0}
figure{margin:1em 0}figcaption{font-weight:600;margin-bottom:.3em}svg{width:100%;height:auto}
.grid{stroke:var(--line);stroke-width:1}.tick{fill:var(--muted);font-size:11px}
.line{stroke-width:2}.line.strategy{stroke:var(--strategy)}
.line.benchmark{stroke:var(--benchmark);stroke-dasharray:6 4}
.legend{display:flex;gap:18px;flex-wrap:wrap;font-size:.9rem}
.key::before{content:"";display:inline-block;width:22px;height:0;border-top:3px solid;
margin-right:6px;vertical-align:middle}
.key.strategy::before{border-color:var(--strategy)}
.key.benchmark::before{border-color:var(--benchmark);border-top-style:dashed}
.flag{background:var(--card);border-left:4px solid var(--warn);padding:8px 12px;margin:8px 0;
border-radius:0 6px 6px 0}
footer{margin-top:2.5em;font-size:.85rem;color:var(--muted)}code{font-size:.9em}
"""


def _esc(value: object) -> str:
    return html.escape(str(value))


def _table(headers: list[str], rows: list[list[str]], numeric_from: int = 1) -> str:
    head = "".join(
        f'<th class="num">{_esc(h)}</th>' if i >= numeric_from else f"<th>{_esc(h)}</th>"
        for i, h in enumerate(headers)
    )
    body = "".join(
        "<tr>"
        + "".join(
            f'<td class="num">{_esc(c)}</td>' if i >= numeric_from else f"<td>{_esc(c)}</td>"
            for i, c in enumerate(row)
        )
        + "</tr>"
        for row in rows
    )
    return f'<div class="scroll"><table><tr>{head}</tr>{body}</table></div>'


def _interval(low: object, high: object) -> str:
    if low is None or high is None:
        return "-"
    return f"{float(str(low)):.2f} to {float(str(high)):.2f}"


def render_html(doc: dict[str, object], charts: dict[str, object]) -> str:
    """The report page for ``doc`` (the result document) and its chart series."""
    summary = doc["summary"]
    assert isinstance(summary, dict)
    results = doc["results"]
    assert isinstance(results, dict)
    strat = results["strategy"]
    bench = results["benchmark"]
    assert isinstance(strat, dict)
    assert isinstance(bench, dict)
    request = doc["request"]
    assert isinstance(request, dict)
    validation = doc["validation"]
    assert isinstance(validation, dict)
    provenance = doc["provenance"]
    assert isinstance(provenance, dict)

    dates = [str(d) for d in charts["dates"]]  # type: ignore[attr-defined]
    eq_dates, eq_strategy = downsample([float(v) for v in charts["strategy"]], dates)  # type: ignore[attr-defined]
    _, eq_bench = downsample([float(v) for v in charts["benchmark"]], dates)  # type: ignore[attr-defined]
    dd_dates, dd_strategy = downsample([float(v) for v in charts["strategy_drawdown"]], dates)  # type: ignore[attr-defined]
    _, dd_bench = downsample([float(v) for v in charts["benchmark_drawdown"]], dates)  # type: ignore[attr-defined]
    label = _esc(request.get("strategy_name") or "Strategy")

    equity_chart = line_chart(
        eq_dates,
        [
            Series(f"{request.get('strategy_name') or 'Strategy'}", "strategy", eq_strategy),
            Series("Buy and hold", "benchmark", eq_bench),
        ],
        kind="usd",
        title="Value of the account over time",
    )
    drawdown_chart = line_chart(
        dd_dates,
        [
            Series(f"{request.get('strategy_name') or 'Strategy'}", "strategy", dd_strategy),
            Series("Buy and hold", "benchmark", dd_bench),
        ],
        kind="pct",
        title="How far the account was below its previous peak",
    )

    def sharpe_cell(side: dict[str, object]) -> str:
        interval = _interval(side["sharpe_low"], side["sharpe_high"])
        return f"{float(str(side['sharpe'])):.2f} ({interval})"

    def metric_row(name: str, key: str, fmt: str) -> list[str]:
        return [name, fmt.format(strat[key]), fmt.format(bench[key])]

    rows = [
        [
            "Final value",
            f"${float(strat['final_equity']):,.0f}",
            f"${float(bench['final_equity']):,.0f}",
        ],
        metric_row("Total return", "total_return_pct", "{:+.1f}%"),
        metric_row("Return per year", "cagr_pct", "{:.1f}%"),
        metric_row("Volatility (per year)", "volatility_pct", "{:.1f}%"),
        metric_row("Worst fall from a peak", "max_drawdown_pct", "{:.1f}%"),
        [
            "Sharpe ratio (95% range)",
            sharpe_cell(strat),
            sharpe_cell(bench),
        ],
        ["Completed trades", str(strat["n_trades"]), "1 (held throughout)"],
    ]

    flags = summary["flags"]
    assert isinstance(flags, list)
    flag_html = (
        "".join(f'<div class="flag">{_esc(f["text"])}</div>' for f in flags)
        or "<p>No warnings were raised.</p>"
    )

    def bullets(items: object) -> str:
        assert isinstance(items, list)
        return "<ul>" + "".join(f"<li>{_esc(t)}</li>" for t in items) + "</ul>"

    trades = doc["trades"]
    assert isinstance(trades, list)
    shown = trades[:200]
    trade_rows = [
        [
            str(t["symbol"]),
            str(t["side"]),
            str(t["entry_date"]),
            str(t["exit_date"]),
            f"{int(t['bars_held'])}",
            f"{float(t['price_change_pct']):+.1f}%",
            f"${float(t['gross_pnl']):+,.0f}",
        ]
        for t in shown
    ]
    trade_note = (
        f'<p class="muted">Showing the first {len(shown)} of {len(trades)} trades.</p>'
        if len(trades) > len(shown)
        else ""
    )
    trades_table = (
        _table(
            ["Symbol", "Side", "Entered", "Exited", "Bars held", "Price change", "Gross P&L"],
            trade_rows,
            numeric_from=4,
        )
        + trade_note
        if trade_rows
        else "<p>The strategy completed no trades in this period.</p>"
    )

    explained = doc["strategy_explained"]
    verdict_level = _esc(summary["verdict_level"])
    null = validation.get("null_test")
    null_html = ""
    if isinstance(null, dict):
        null_html = (
            f"<p>Random re-ordering test: {null['iterations']} shuffles of the same daily returns; "
            f"the strategy's Sharpe was matched or beaten in {null.get('exceedances', '?')} of "
            f"them (Monte Carlo p-value {float(null['p_value']):.3f}).</p>"
        )

    subtitle = (
        f"{', '.join(request['symbols'])} - {request['start']} to {request['end']} - "
        f"starting capital ${float(request['capital']):,.0f}"
    )
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{label} - Crucible backtest</title><style>{_CSS}</style></head><body><main>
<h1>{label}</h1>
<p class="muted">{_esc(subtitle)}</p>
<p class="lead">{_esc(summary["headline"])}</p>
<div class="verdict {verdict_level}"><strong>Verdict</strong>{_esc(summary["verdict"])}</div>

<h2>Strategy vs buy and hold</h2>
{_table(["", "Strategy", "Buy and hold"], rows)}
{bullets(summary["versus_benchmark"])}
{equity_chart}
{drawdown_chart}

<h2>What the strategy did</h2>
{bullets(summary["what_happened"])}

<h2>How much to trust this</h2>
{bullets(summary["how_much_to_trust"])}
{null_html}
{flag_html}

<h2>What to try next</h2>
{bullets(summary["next_steps"])}

<h2>The rules, in words</h2>
{bullets(explained)}

<h2>Trades</h2>
{trades_table}

<footer>
<p>{_esc(summary["disclaimer"])}</p>
<p>Experiment <code>{_esc(provenance["experiment_id"])}</code> &middot; realism level
{_esc(provenance["realism_level"])} &middot; engine {_esc(provenance["engine"])} &middot;
costs {_esc(provenance["costs"])} &middot; data <code>{_esc(provenance["dataset"])}</code>
({_esc(provenance["data_hash"][:12])}) from {_esc(provenance["provider"])},
{_esc(provenance["price_basis"])} prices &middot; seed {_esc(provenance["seed"])}.
The same strategy, data and settings always give this same report.</p>
</footer>
</main></body></html>
"""
