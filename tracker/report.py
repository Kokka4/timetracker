"""A standalone report you can keep, send or print.

Three formats were asked for: CSV, HTML and PDF. Two are here, and the third
is the reason this module exists rather than a dependency.

Nothing in this project needs pip. That is what makes installing it on
somebody else's Mac one command and no toolchain, and it is the single
constraint that has shaped every other decision here. No PDF library ships
with macOS, so a real PDF writer would mean either vendoring one or asking
every install to grow a package manager. Browsers already contain an
excellent PDF writer, and a page built for print goes through it with Cmd+P,
Save as PDF, at better typographic quality than anything a few hundred lines
of stdlib would produce.

So this emits one self-contained HTML file: no network, no scripts, no
external stylesheet, nothing to resolve when it is opened in a year or
forwarded to somebody who does not have the tracker. It carries a print
stylesheet that drops the page to black on white and keeps tables off page
breaks.
"""

from __future__ import annotations

import html
from datetime import datetime
from typing import Any, Iterable

# Eight hues held to one chroma band, matching the dashboard's slots. Printed
# in hex rather than as tokens, because a report has to render correctly in a
# browser that never loaded the app's stylesheet.
SLOTS = (
    "#2f74c0", "#df7a40", "#1b9c86", "#c9971f",
    "#cf6f9b", "#5d9c3c", "#6a62c8", "#cc5a52",
)


def _dur(seconds: float | None) -> str:
    total = max(0, round(seconds or 0))
    if total < 60:
        return f"{total}s"
    hours, rest = divmod(total, 3600)
    minutes = round(rest / 60)
    if minutes == 60:
        hours, minutes = hours + 1, 0
    if hours and minutes:
        return f"{hours}h {minutes}m"
    if hours:
        return f"{hours}h"
    return f"{minutes}m"


def _pct(share: float | None) -> str:
    return f"{round((share or 0) * 100)}%"


def _e(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def _bar_table(
    title: str, rows: Iterable[dict[str, Any]], total: float, colours: dict[str, str]
) -> str:
    rows = list(rows)
    if not rows:
        return ""
    out = [f'<section class="block"><h2>{_e(title)}</h2>',
           '<table><thead><tr><th>Name</th><th class="n">Time</th>'
           '<th class="n">Share</th><th class="bar-head"></th></tr></thead><tbody>']
    biggest = max((row.get("seconds") or 0) for row in rows) or 1
    for row in rows:
        key = str(row.get("key", ""))
        seconds = row.get("seconds") or 0
        width = round(100 * seconds / biggest, 1)
        colour = colours.get(key, "#8aa0b8")
        out.append(
            "<tr>"
            f'<td class="k"><i style="background:{_e(colour)}"></i>{_e(key)}</td>'
            f'<td class="n">{_e(_dur(seconds))}</td>'
            f'<td class="n dim">{_e(_pct(seconds / total if total else 0))}</td>'
            f'<td class="bar"><span style="width:{width}%;background:{_e(colour)}"></span></td>'
            "</tr>"
        )
    out.append("</tbody></table></section>")
    return "".join(out)


def _day_table(series: dict[str, Any]) -> str:
    """Time per bucket, as a table rather than a chart.

    A bar chart in a printed report is decoration: the reader almost always
    wants to read a number off it, and a table lets them.

    `data` is one row per category and one column per bucket, so the total
    for a bucket is the column, not the row.
    """
    buckets = series.get("buckets") or []
    data = series.get("data") or []
    if not buckets or not data:
        return ""
    labels = [b.get("label", "") for b in buckets]
    totals = [sum(row[i] for row in data) for i in range(len(buckets))]
    if not any(totals):
        return ""
    biggest = max(totals) or 1
    rows = []
    for label, value in zip(labels, totals):
        width = round(100 * value / biggest, 1)
        rows.append(
            "<tr>"
            f"<td>{_e(label)}</td>"
            f'<td class="n">{_e(_dur(value))}</td>'
            f'<td class="bar"><span style="width:{width}%;background:#2f74c0"></span></td>'
            "</tr>"
        )
    return (
        '<section class="block"><h2>Across the period</h2>'
        "<table><thead><tr><th>When</th><th class=\"n\">Active</th>"
        '<th class="bar-head"></th></tr></thead><tbody>'
        + "".join(rows)
        + "</tbody></table></section>"
    )


STYLE = """
:root { --ink:#15212f; --dim:#5d7082; --line:#dde5ee; --rule:#eef3f8; }
* { box-sizing: border-box; }
body {
  margin: 0; padding: 40px 36px 64px;
  font: 14px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif;
  color: var(--ink); background: #fff;
  -webkit-font-smoothing: antialiased;
}
.sheet { max-width: 880px; margin: 0 auto; }
header { border-bottom: 2px solid var(--ink); padding-bottom: 14px; margin-bottom: 26px; }
h1 { margin: 0 0 4px; font-size: 23px; letter-spacing: -0.015em; }
.range { font-size: 13px; color: var(--dim); }
.made { margin-top: 2px; font-size: 11.5px; color: var(--dim); }

.tiles { display: grid; grid-template-columns: repeat(4, 1fr); gap: 1px;
         background: var(--line); border: 1px solid var(--line);
         border-radius: 8px; overflow: hidden; margin-bottom: 30px; }
.tile { background: #fff; padding: 13px 14px 15px; }
.tile .label { font-size: 11.5px; color: var(--dim); }
.tile .value { font-size: 23px; font-weight: 600; margin-top: 5px; letter-spacing: -0.015em; }
.tile .sub { font-size: 11.5px; color: var(--dim); margin-top: 3px; }

.block { margin-bottom: 28px; break-inside: avoid; }
h2 { font-size: 14px; margin: 0 0 9px; }
table { width: 100%; border-collapse: collapse; font-size: 12.5px; }
th { text-align: left; font-weight: 500; color: var(--dim); font-size: 11.5px;
     padding: 0 8px 6px 0; border-bottom: 1px solid var(--line); }
td { padding: 5px 8px 5px 0; border-bottom: 1px solid var(--rule); vertical-align: middle; }
tr:last-child td { border-bottom: 0; }
.n { text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }
.dim { color: var(--dim); }
.k { display: flex; align-items: center; gap: 7px; }
.k i { width: 9px; height: 9px; border-radius: 2px; flex: none; display: inline-block; }
.bar-head { width: 34%; }
.bar { width: 34%; }
.bar span { display: block; height: 7px; border-radius: 4px; min-width: 2px; }

footer { margin-top: 34px; padding-top: 14px; border-top: 1px solid var(--line);
         font-size: 11px; color: var(--dim); line-height: 1.6; }

/* Printing is the PDF path, so it is the layout that matters most. */
@page { margin: 16mm 14mm; }
@media print {
  body { padding: 0; font-size: 11.5pt; }
  .sheet { max-width: none; }
  .tiles { break-inside: avoid; }
  table { font-size: 10.5pt; }
  tr, .block { break-inside: avoid; }
  h2 { break-after: avoid; }
}
"""


def render(
    summary: dict[str, Any],
    window: dict[str, Any],
    colours: dict[str, str] | None = None,
    detail: list[dict[str, Any]] | None = None,
) -> str:
    colours = colours or {}
    total = summary.get("total_seconds") or 0
    days = max(1, window.get("days") or 1)
    away = summary.get("away") or {}
    span = summary.get("span") or {}

    top_client = next(
        (
            row for row in summary.get("by_client") or []
            if row.get("key") not in ("(unlabelled)", "Other")
        ),
        None,
    )

    tiles = [
        ("Active time", _dur(total),
         f"{_dur(total / days)} a day across {days} day{'s' if days != 1 else ''}"),
        ("Attributed to a client", _pct(summary.get("client_share")),
         f"{_dur(summary.get('client_seconds'))} of {_dur(total)}"),
        ("Biggest client", _e(top_client["key"]) if top_client else "—",
         f"{_dur(top_client['seconds'])}, {_pct(top_client['share'])} of tracked time"
         if top_client else "Nothing attributed yet"),
        ("Away during work hours", _dur(away.get("total")),
         f"of {_dur(span.get('seconds'))} first to last" if span.get("seconds")
         else "Nothing recorded"),
    ]

    parts = [
        "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">",
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        f"<title>Time report, {_e(window.get('start_date'))} to "
        f"{_e(window.get('end_date'))}</title>",
        f"<style>{STYLE}</style></head><body><div class=\"sheet\">",
        "<header><h1>Time report</h1>",
        f'<div class="range">{_e(window.get("start_date"))} to '
        f'{_e(window.get("end_date"))}, {days} day{"s" if days != 1 else ""}</div>',
        f'<div class="made">Generated {_e(datetime.now().strftime("%-d %B %Y at %H:%M"))} '
        "on this machine. Nothing in this file came from, or went to, anywhere else."
        "</div></header>",
        '<div class="tiles">',
    ]
    for label, value, sub in tiles:
        parts.append(
            f'<div class="tile"><div class="label">{_e(label)}</div>'
            f'<div class="value">{value}</div>'
            f'<div class="sub">{_e(sub)}</div></div>'
        )
    parts.append("</div>")

    parts.append(_day_table(summary.get("series") or {}))
    parts.append(_bar_table("By client", summary.get("by_client") or [], total, colours))
    parts.append(_bar_table("By category", summary.get("by_category") or [], total, colours))
    parts.append(_bar_table("By app", summary.get("by_app") or [], total, colours))
    parts.append(_bar_table("By site", summary.get("by_domain") or [], total, colours))

    if detail:
        rows = []
        for block in detail:
            rows.append(
                "<tr>"
                f'<td class="dim n">{_e(datetime.fromtimestamp(block["start"]).strftime("%d %b %H:%M"))}</td>'
                f'<td class="n">{_e(_dur(block["seconds"]))}</td>'
                f'<td>{_e(block.get("domain") or block.get("app"))}</td>'
                f'<td class="dim">{_e((block.get("title") or "")[:70])}</td>'
                f'<td>{_e(block.get("client") or "")}</td>'
                f'<td>{_e(block.get("category") or "")}</td>'
                "</tr>"
            )
        parts.append(
            '<section class="block"><h2>Every block</h2><table><thead><tr>'
            '<th class="n">When</th><th class="n">Time</th><th>What</th>'
            "<th>Detail</th><th>Client</th><th>Category</th>"
            "</tr></thead><tbody>" + "".join(rows) + "</tbody></table></section>"
        )

    parts.append(
        "<footer>Produced by a time tracker that runs entirely on this Mac. "
        "It has no account, no server and no way to report to anyone: every "
        "figure above was computed locally from a single file on this machine. "
        "Durations are time with an app in front of you, excluding anything "
        "idle, locked or asleep."
        "</footer></div></body></html>"
    )
    return "".join(parts)
