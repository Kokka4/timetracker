"""Joining the two streams, and rolling the result up.

The desktop stream owns the clock. The browser stream only labels it. So a
desktop interval during which Chrome was frontmost is cut into the pieces
covered by browser intervals, and whatever is left over stays as plain browser
time with no tab attached. Nothing is double counted, and the totals add up to
the desktop total whether or not the extension was running.
"""

from __future__ import annotations

import bisect
from datetime import date, datetime, timedelta
from typing import Any, Iterable

from . import rules as rules_mod

UNTRACKED_TAB = "(tab not tracked)"
NO_CLIENT = "(unlabelled)"
MAX_TIMELINE = 600
MIN_TIMELINE_SECONDS = 15.0


# -- time ranges ---------------------------------------------------------


def _midnight(day: date) -> float:
    return datetime(day.year, day.month, day.day).timestamp()


def _parse_day(text: str | None) -> date | None:
    if not text:
        return None
    try:
        return datetime.strptime(text.strip()[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def resolve_range(
    name: str = "today",
    frm: str | None = None,
    to: str | None = None,
    now: float | None = None,
) -> dict[str, Any]:
    """Turn a range name into concrete local-time boundaries."""
    now = now if now is not None else datetime.now().timestamp()
    today = datetime.fromtimestamp(now).date()
    name = (name or "today").strip().casefold()

    if name == "custom":
        start_day = _parse_day(frm) or today
        end_day = _parse_day(to) or start_day
    elif name == "today":
        start_day = end_day = today
    elif name == "yesterday":
        start_day = end_day = today - timedelta(days=1)
    elif name in ("week", "7d"):
        start_day, end_day = today - timedelta(days=6), today
    elif name in ("month", "30d"):
        start_day, end_day = today - timedelta(days=29), today
    elif name == "this_week":
        start_day, end_day = today - timedelta(days=today.weekday()), today
    elif name == "this_month":
        start_day, end_day = today.replace(day=1), today
    elif name in ("quarter", "90d"):
        start_day, end_day = today - timedelta(days=89), today
    else:
        start_day = end_day = today

    if end_day < start_day:
        start_day, end_day = end_day, start_day

    start_ts = _midnight(start_day)
    end_ts = min(_midnight(end_day + timedelta(days=1)), now)
    if end_ts <= start_ts:
        end_ts = start_ts

    days = (end_day - start_day).days + 1
    return {
        "name": name,
        "start_ts": start_ts,
        "end_ts": end_ts,
        "start_date": start_day.isoformat(),
        "end_date": end_day.isoformat(),
        "days": days,
        "granularity": "hour" if days == 1 else "day",
    }


def buckets(start_ts: float, end_ts: float, granularity: str) -> list[dict[str, Any]]:
    """Bucket edges in local time. Naive datetime arithmetic keeps DST honest."""
    out: list[dict[str, Any]] = []
    cursor = datetime.fromtimestamp(start_ts)
    if granularity == "hour":
        cursor = cursor.replace(minute=0, second=0, microsecond=0)
        step = timedelta(hours=1)
        fmt = "%H:%M"
    else:
        cursor = cursor.replace(hour=0, minute=0, second=0, microsecond=0)
        step = timedelta(days=1)
        fmt = "%Y-%m-%d"

    guard = 0
    while cursor.timestamp() < end_ts and guard < 2000:
        guard += 1
        nxt = cursor + step
        b_start = max(cursor.timestamp(), start_ts)
        b_end = min(nxt.timestamp(), end_ts)
        if b_end > b_start:
            out.append(
                {
                    "label": cursor.strftime(fmt),
                    "start": b_start,
                    "end": b_end,
                    "weekday": cursor.strftime("%a"),
                }
            )
        cursor = nxt
    return out


# -- the join ------------------------------------------------------------


def _browser_matches(event_browser: str | None, app_browser: str) -> bool:
    if not event_browser:
        return True
    a, b = event_browser.casefold(), app_browser.casefold()
    return a == b or a in b or b in a


def build_blocks(store, cfg, start_ts: float, end_ts: float) -> list[dict[str, Any]]:
    """Desktop intervals, cut by browser intervals, each one classified."""
    desktop = store.desktop_events(start_ts, end_ts)
    browser = store.browser_events(start_ts, end_ts)
    rule_list = rules_mod.compile_rules(store.rules())

    starts = [b["start_ts"] for b in browser]
    longest = max((b["end_ts"] - b["start_ts"] for b in browser), default=0.0)

    blocks: list[dict[str, Any]] = []

    for event in desktop:
        span_start = max(event["start_ts"], start_ts)
        span_end = min(event["end_ts"], end_ts)
        if span_end <= span_start:
            continue

        browser_label = cfg.browser_name(event["bundle_id"], event["app"])
        if not browser_label:
            blocks.append(_make_block(span_start, span_end, event, None, rule_list, None))
            continue

        # Candidates: any browser interval that can possibly overlap. Both
        # bounds are exact, so this is a filter, not an approximation.
        lo = bisect.bisect_left(starts, span_start - longest)
        hi = bisect.bisect_right(starts, span_end)

        def collect(strict: bool) -> list[tuple[float, float, dict[str, Any]]]:
            found = []
            for candidate in browser[lo:hi]:
                if strict and not _browser_matches(candidate["browser"], browser_label):
                    continue
                overlap_start = max(span_start, candidate["start_ts"])
                overlap_end = min(span_end, candidate["end_ts"])
                if overlap_end > overlap_start:
                    found.append((overlap_start, overlap_end, candidate))
            return found

        # Brave, Arc and several other Chromium browsers identify themselves as
        # "Chrome" from inside an extension, so the label is advisory. Prefer a
        # label match, but never throw away tab data just because the name
        # disagrees — only one browser can be frontmost at a given instant.
        segments = collect(strict=True) or collect(strict=False)
        segments.sort(key=lambda s: s[0])

        cursor = span_start
        for seg_start, seg_end, candidate in segments:
            if seg_start > cursor:
                blocks.append(
                    _make_block(cursor, seg_start, event, None, rule_list, browser_label)
                )
            piece_start = max(cursor, seg_start)
            if seg_end > piece_start:
                blocks.append(
                    _make_block(
                        piece_start, seg_end, event, candidate, rule_list, browser_label
                    )
                )
            cursor = max(cursor, seg_end)

        if cursor < span_end:
            blocks.append(
                _make_block(cursor, span_end, event, None, rule_list, browser_label)
            )

    blocks.sort(key=lambda b: b["start"])
    return blocks


def _make_block(
    start: float,
    end: float,
    event: dict[str, Any],
    tab: dict[str, Any] | None,
    rule_list: list[rules_mod.Rule],
    browser_label: str | None,
) -> dict[str, Any]:
    seconds = end - start
    domain = tab["domain"] if tab else None
    url = tab["url"] if tab else None
    title = (tab["title"] if tab and tab["title"] else event["title"]) or None

    signature = {
        "app": event["app"],
        "title": title,
        "domain": domain,
        "url": url,
    }
    label = rules_mod.classify(rule_list, signature)

    block = {
        "start": start,
        "end": end,
        "seconds": seconds,
        "app": event["app"],
        "bundle_id": event["bundle_id"],
        "title": title,
        "domain": domain,
        "url": url,
        "is_browser": bool(browser_label),
        "browser": browser_label,
        "untracked_tab": bool(browser_label) and tab is None,
        "client": label["client"],
        "project": label["project"],
        "category": label["category"],
        "rule_ids": label["rule_ids"],
        "keys": 0,
        "clicks": 0,
        "scrolls": 0,
        "media": 0,
    }

    if tab:
        full = max(1e-6, tab["end_ts"] - tab["start_ts"])
        share = min(1.0, seconds / full)
        block["keys"] = int(round((tab["keys"] or 0) * share))
        block["clicks"] = int(round((tab["clicks"] or 0) * share))
        block["scrolls"] = int(round((tab["scrolls"] or 0) * share))
        block["media"] = int(tab["media"] or 0)

    return block


# -- rollups -------------------------------------------------------------


def _top(
    counts: dict[str, float], total: float, limit: int = 12
) -> list[dict[str, Any]]:
    ordered = sorted(counts.items(), key=lambda kv: -kv[1])
    out = [
        {
            "key": key,
            "seconds": round(seconds, 1),
            "share": round(seconds / total, 4) if total else 0.0,
        }
        for key, seconds in ordered[:limit]
    ]
    rest = sum(seconds for _, seconds in ordered[limit:])
    if rest > 0:
        out.append(
            {
                "key": "Other",
                "seconds": round(rest, 1),
                "share": round(rest / total, 4) if total else 0.0,
            }
        )
    return out


def _display_label(block: dict[str, Any]) -> str:
    if block["domain"]:
        return block["domain"]
    if block["untracked_tab"]:
        return f"{block['app']} {UNTRACKED_TAB}"
    return block["app"]


def summarize(
    blocks: list[dict[str, Any]],
    afk_rows: list[dict[str, Any]],
    window: dict[str, Any],
    series_limit: int = 7,
    review_min_seconds: float = 60.0,
) -> dict[str, Any]:
    total = sum(b["seconds"] for b in blocks)

    # Away time is only meaningful between the first and last thing you did.
    # A locked Mac at 04:00 is not "away from the keyboard", it is night, and
    # counting it tells you nothing about your day. Bounding it this way also
    # makes the figures reconcile: active + away = first to last activity.
    # Per day, not across the whole range: taking one span from the first
    # block of the month to the last would swallow every night in between.
    days: dict[Any, list[float]] = {}
    for block in blocks:
        key = datetime.fromtimestamp(block["start"]).date()
        bounds = days.get(key)
        if bounds is None:
            days[key] = [block["start"], block["end"]]
        else:
            bounds[0] = min(bounds[0], block["start"])
            bounds[1] = max(bounds[1], block["end"])

    away = {kind: 0.0 for kind in AWAY_PRIORITY}
    away["total"] = 0.0
    span_seconds = 0.0
    for day_start, day_end in days.values():
        span_seconds += max(0.0, day_end - day_start)
        for kind, seconds in away_summary(afk_rows, day_start, day_end).items():
            away[kind] += seconds

    span_start = min((b[0] for b in days.values()), default=window["start_ts"])
    span_end = max((b[1] for b in days.values()), default=window["start_ts"])

    by_app: dict[str, float] = {}
    by_domain: dict[str, float] = {}
    by_client: dict[str, float] = {}
    by_category: dict[str, float] = {}
    by_project: dict[str, float] = {}
    interaction = {"keys": 0, "clicks": 0, "scrolls": 0}

    for block in blocks:
        seconds = block["seconds"]
        by_app[block["app"]] = by_app.get(block["app"], 0.0) + seconds
        by_category[block["category"]] = (
            by_category.get(block["category"], 0.0) + seconds
        )
        by_client[block["client"] or NO_CLIENT] = (
            by_client.get(block["client"] or NO_CLIENT, 0.0) + seconds
        )
        if block["project"]:
            by_project[block["project"]] = by_project.get(block["project"], 0.0) + seconds
        if block["domain"]:
            by_domain[block["domain"]] = by_domain.get(block["domain"], 0.0) + seconds
        elif block["untracked_tab"]:
            key = f"{block['app']} {UNTRACKED_TAB}"
            by_domain[key] = by_domain.get(key, 0.0) + seconds
        interaction["keys"] += block["keys"]
        interaction["clicks"] += block["clicks"]
        interaction["scrolls"] += block["scrolls"]

    bucket_list = buckets(window["start_ts"], window["end_ts"], window["granularity"])
    series_keys = [
        key
        for key, _ in sorted(by_category.items(), key=lambda kv: -kv[1])[:series_limit]
    ]
    if len(by_category) > len(series_keys):
        series_keys = series_keys + ["Other"]

    index = {key: i for i, key in enumerate(series_keys)}
    matrix = [[0.0 for _ in bucket_list] for _ in series_keys]

    # A block can straddle a bucket edge (midnight, or the top of the hour), so
    # each one is distributed across the buckets it actually covers. bisect
    # finds the first candidate bucket instead of rescanning them all.
    bucket_ends = [b["end"] for b in bucket_list]
    for block in blocks:
        row = index.get(block["category"], index.get("Other"))
        if row is None:
            continue
        first = bisect.bisect_right(bucket_ends, block["start"])
        for b_index in range(first, len(bucket_list)):
            bucket = bucket_list[b_index]
            if bucket["start"] >= block["end"]:
                break
            overlap = min(block["end"], bucket["end"]) - max(
                block["start"], bucket["start"]
            )
            if overlap > 0:
                matrix[row][b_index] += overlap

    client_work = sum(
        seconds for key, seconds in by_client.items() if key != NO_CLIENT
    )

    return {
        "window": window,
        "total_seconds": round(total, 1),
        "block_count": len(blocks),
        "client_seconds": round(client_work, 1),
        "client_share": round(client_work / total, 4) if total else 0.0,
        "away": {
            "idle": round(away["idle"], 1),
            "locked": round(away["locked"], 1),
            "gap": round(away["gap"], 1),
            "unknown": round(away["unknown"], 1),
            "total": round(away["total"], 1),
        },
        "span": {
            "seconds": round(span_seconds, 1),
            "start": span_start if blocks else None,
            "end": span_end if blocks else None,
            "unaccounted": round(max(0.0, span_seconds - total - away["total"]), 1),
        },
        "interaction": interaction,
        "by_app": _top(by_app, total),
        "by_domain": _top(by_domain, total),
        "by_client": _top(by_client, total),
        "by_category": _top(by_category, total, limit=20),
        "by_project": _top(by_project, total),
        "series": {
            "buckets": [
                {"label": b["label"], "weekday": b["weekday"]} for b in bucket_list
            ],
            "keys": series_keys,
            "data": [[round(v, 1) for v in row] for row in matrix],
        },
        "timeline": timeline(blocks),
        "unlabelled": unlabelled(blocks, min_seconds=review_min_seconds),
        "review_min_seconds": review_min_seconds,
    }


AWAY_PRIORITY = ("gap", "locked", "idle", "unknown")


def away_summary(
    rows: list[dict[str, Any]], lo: float, hi: float
) -> dict[str, float]:
    """Away time as a union of intervals, never a sum of their durations.

    Away rows overlap heavily and legitimately: a Mac that power-naps awake
    every quarter of an hour closes and reopens its away period each time, and
    each new row is back-dated to when input actually stopped. Adding those
    durations together reports more away time than the window physically
    contains — 246 hours in a 24-hour day, in the case that prompted this.

    A single instant can only be away for one reason, so overlaps are resolved
    by specificity rather than shared out: a machine that is asleep is also
    locked and also idle, and "asleep" is the most informative of the three.
    """
    events: list[tuple[float, int, str]] = []
    for row in rows:
        start = max(float(row["start_ts"]), lo)
        end = min(float(row["end_ts"]), hi)
        if end <= start:
            continue
        kind = row["kind"] if row["kind"] in AWAY_PRIORITY else "unknown"
        events.append((start, 1, kind))
        events.append((end, -1, kind))

    if not events:
        return {kind: 0.0 for kind in AWAY_PRIORITY} | {"total": 0.0}

    events.sort(key=lambda e: (e[0], -e[1]))
    totals = {kind: 0.0 for kind in AWAY_PRIORITY}
    open_counts = {kind: 0 for kind in AWAY_PRIORITY}
    previous = events[0][0]

    for moment, delta, kind in events:
        if moment > previous:
            live = [k for k in AWAY_PRIORITY if open_counts[k] > 0]
            if live:
                totals[live[0]] += moment - previous  # AWAY_PRIORITY order wins
            previous = moment
        open_counts[kind] += delta

    totals["total"] = sum(totals.values())
    return totals


def timeline(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Merge adjacent blocks that look the same, for the day strip."""
    merged: list[dict[str, Any]] = []
    for block in blocks:
        label = _display_label(block)
        key = (block["app"], label, block["category"], block["client"])
        if merged:
            last = merged[-1]
            if last["_key"] == key and block["start"] - last["end"] <= 60:
                last["end"] = block["end"]
                last["seconds"] = last["end"] - last["start"]
                continue
        merged.append(
            {
                "_key": key,
                "start": block["start"],
                "end": block["end"],
                "seconds": block["seconds"],
                "app": block["app"],
                "label": label,
                "title": block["title"],
                "category": block["category"],
                "client": block["client"],
            }
        )

    kept = [m for m in merged if m["seconds"] >= MIN_TIMELINE_SECONDS]
    if len(kept) > MAX_TIMELINE:
        kept.sort(key=lambda m: -m["seconds"])
        kept = kept[:MAX_TIMELINE]
        kept.sort(key=lambda m: m["start"])
    for item in kept:
        item.pop("_key", None)
        item["seconds"] = round(item["seconds"], 1)
    return kept


def unlabelled(
    blocks: list[dict[str, Any]],
    limit: int = 25,
    min_seconds: float = 60.0,
) -> list[dict[str, Any]]:
    """Blocks with no client, grouped so one click can label a whole group.

    Each group carries a `context` list: what was in front immediately before
    and after. A 12-minute block in an AI app means nothing alone; the same
    block surrounded by one client's campaign work almost always belongs to
    that client, and this is what lets you see that at a glance.

    Groups totalling less than `min_seconds` are left out. Every one of those
    rows costs a decision and returns almost no attributed time, and a queue
    of forty-second glances is one you stop opening. The time is still
    recorded and still counted in every total; it simply stops asking.

    `first_ts` and `last_ts` say when the group happened, because "which
    client was this" is a question you answer by remembering the afternoon,
    not by recognising a window title.
    """
    groups: dict[tuple[str, str], dict[str, Any]] = {}
    for position, block in enumerate(blocks):
        if block["client"]:
            continue
        key = (block["app"], block["domain"] or block["title"] or "")
        group = groups.get(key)
        if group is None:
            group = {
                "app": block["app"],
                "domain": block["domain"],
                "title": block["title"],
                "url": block["url"],
                "category": block["category"],
                "seconds": 0.0,
                "blocks": 0,
                "positions": [],
                "first_ts": block["start"],
                "last_ts": block["end"],
                "longest": 0.0,
                "days": set(),
            }
            groups[key] = group
        group["seconds"] += block["seconds"]
        group["blocks"] += 1
        group["first_ts"] = min(group["first_ts"], block["start"])
        group["last_ts"] = max(group["last_ts"], block["end"])
        group["longest"] = max(group["longest"], block["seconds"])
        group["days"].add(
            datetime.fromtimestamp(block["start"]).strftime("%Y-%m-%d")
        )
        if len(group["positions"]) < 40:
            group["positions"].append(position)

    worth_deciding = [g for g in groups.values() if g["seconds"] >= min_seconds]
    ordered = sorted(worth_deciding, key=lambda g: -g["seconds"])[:limit]

    for group in ordered:
        neighbours: dict[str, float] = {}
        for position in group["positions"]:
            for offset in (-2, -1, 1, 2):
                index = position + offset
                if 0 <= index < len(blocks):
                    other = blocks[index]
                    if other["client"]:
                        neighbours[other["client"]] = (
                            neighbours.get(other["client"], 0.0) + other["seconds"]
                        )
        group["context"] = [
            {"client": client, "seconds": round(seconds, 1)}
            for client, seconds in sorted(neighbours.items(), key=lambda kv: -kv[1])[:3]
        ]
        group["seconds"] = round(group["seconds"], 1)
        group["longest"] = round(group["longest"], 1)
        group["day_count"] = len(group["days"])
        group.pop("days", None)
        group.pop("positions", None)

    return ordered


def csv_rows(blocks: Iterable[dict[str, Any]]) -> Iterable[list[Any]]:
    yield [
        "start_local",
        "end_local",
        "seconds",
        "app",
        "domain",
        "title",
        "client",
        "project",
        "category",
        "keys",
        "clicks",
        "scrolls",
    ]
    for block in blocks:
        yield [
            datetime.fromtimestamp(block["start"]).isoformat(timespec="seconds"),
            datetime.fromtimestamp(block["end"]).isoformat(timespec="seconds"),
            round(block["seconds"], 1),
            block["app"],
            block["domain"] or "",
            block["title"] or "",
            block["client"] or "",
            block["project"] or "",
            block["category"],
            block["keys"],
            block["clicks"],
            block["scrolls"],
        ]
