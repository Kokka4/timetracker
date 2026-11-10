"""SQLite storage.

Event model
-----------
An event is an interval, not a sample. The watcher holds one open event at a
time, inserts it on open, extends its `end_ts` on every tick, and finalises it
when the thing being watched changes. That means the database is always within
one sample interval of the truth, and a crash costs at most one tick.

`desktop_events` is the source of truth for time. `browser_events` is an
enrichment stream: it never claims time of its own, it only labels the
intervals during which a browser was the frontmost app.
"""

from __future__ import annotations

import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Iterable, Sequence

SCHEMA = """
CREATE TABLE IF NOT EXISTS desktop_events (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    start_ts   REAL NOT NULL,
    end_ts     REAL NOT NULL,
    duration   REAL NOT NULL,
    app        TEXT NOT NULL,
    bundle_id  TEXT,
    title      TEXT
);
CREATE INDEX IF NOT EXISTS idx_desktop_start ON desktop_events(start_ts);
CREATE INDEX IF NOT EXISTS idx_desktop_end   ON desktop_events(end_ts);

CREATE TABLE IF NOT EXISTS browser_events (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    start_ts   REAL NOT NULL,
    end_ts     REAL NOT NULL,
    duration   REAL NOT NULL,
    browser    TEXT,
    domain     TEXT,
    url        TEXT,
    title      TEXT,
    tab_id     INTEGER,
    keys       INTEGER NOT NULL DEFAULT 0,
    clicks     INTEGER NOT NULL DEFAULT 0,
    scrolls    INTEGER NOT NULL DEFAULT 0,
    media      INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_browser_start ON browser_events(start_ts);
CREATE INDEX IF NOT EXISTS idx_browser_end   ON browser_events(end_ts);

CREATE TABLE IF NOT EXISTS afk (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    start_ts  REAL NOT NULL,
    end_ts    REAL NOT NULL,
    duration  REAL NOT NULL,
    kind      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_afk_start ON afk(start_ts);

CREATE TABLE IF NOT EXISTS rules (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    priority     INTEGER NOT NULL DEFAULT 100,
    match_app    TEXT,
    match_title  TEXT,
    match_domain TEXT,
    match_url    TEXT,
    client       TEXT,
    project      TEXT,
    category     TEXT,
    enabled      INTEGER NOT NULL DEFAULT 1,
    created_ts   REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {k: row[k] for k in row.keys()}


class Store:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        self._write_lock = threading.RLock()
        with self._write_lock:
            self.conn().executescript(SCHEMA)

    # -- connection ------------------------------------------------------

    def conn(self) -> sqlite3.Connection:
        """One connection per thread; WAL lets them overlap safely."""
        existing = getattr(self._local, "conn", None)
        if existing is not None:
            return existing
        conn = sqlite3.connect(
            str(self.path),
            timeout=30.0,
            isolation_level=None,  # autocommit
            check_same_thread=False,
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA busy_timeout=30000")
        self._local.conn = conn
        return conn

    def close(self) -> None:
        existing = getattr(self._local, "conn", None)
        if existing is not None:
            existing.close()
            self._local.conn = None

    def _write(self, sql: str, params: Sequence[Any] = ()) -> sqlite3.Cursor:
        with self._write_lock:
            return self.conn().execute(sql, params)

    # -- desktop events --------------------------------------------------

    def open_desktop_event(
        self, ts: float, app: str, bundle_id: str | None, title: str | None
    ) -> int:
        cur = self._write(
            "INSERT INTO desktop_events (start_ts, end_ts, duration, app, bundle_id, title)"
            " VALUES (?, ?, 0, ?, ?, ?)",
            (ts, ts, app, bundle_id, title),
        )
        return int(cur.lastrowid)

    def touch_desktop_event(self, event_id: int, end_ts: float) -> None:
        self._write(
            "UPDATE desktop_events SET end_ts = ?, duration = ? - start_ts"
            " WHERE id = ? AND ? > start_ts",
            (end_ts, end_ts, event_id, end_ts),
        )

    def delete_desktop_event(self, event_id: int) -> None:
        self._write("DELETE FROM desktop_events WHERE id = ?", (event_id,))

    # -- browser events --------------------------------------------------

    def open_browser_event(
        self,
        ts: float,
        browser: str | None,
        domain: str | None,
        url: str | None,
        title: str | None,
        tab_id: int | None,
    ) -> int:
        cur = self._write(
            "INSERT INTO browser_events"
            " (start_ts, end_ts, duration, browser, domain, url, title, tab_id)"
            " VALUES (?, ?, 0, ?, ?, ?, ?, ?)",
            (ts, ts, browser, domain, url, title, tab_id),
        )
        return int(cur.lastrowid)

    def touch_browser_event(
        self,
        event_id: int,
        end_ts: float,
        keys: int = 0,
        clicks: int = 0,
        scrolls: int = 0,
        media: int = 0,
    ) -> None:
        self._write(
            "UPDATE browser_events SET"
            "   end_ts = ?,"
            "   duration = ? - start_ts,"
            "   keys = keys + ?,"
            "   clicks = clicks + ?,"
            "   scrolls = scrolls + ?,"
            "   media = MAX(media, ?)"
            " WHERE id = ? AND ? > start_ts",
            (end_ts, end_ts, keys, clicks, scrolls, media, event_id, end_ts),
        )

    def delete_browser_event(self, event_id: int) -> None:
        self._write("DELETE FROM browser_events WHERE id = ?", (event_id,))

    # -- retroactive correction -----------------------------------------

    def trim_after(self, ts: float) -> int:
        """Remove recorded activity after `ts`.

        Called when idle detection reveals that input actually stopped `ts`
        seconds ago, so the last stretch of "activity" was nobody at the
        keyboard. Events that start after the cut are dropped; events that
        straddle it are clipped back to it.
        """
        removed = 0
        with self._write_lock:
            conn = self.conn()
            for table in ("desktop_events", "browser_events"):
                cur = conn.execute(
                    f"DELETE FROM {table} WHERE start_ts >= ?", (ts,)
                )
                removed += cur.rowcount or 0
                conn.execute(
                    f"UPDATE {table} SET end_ts = ?, duration = ? - start_ts"
                    f" WHERE end_ts > ? AND start_ts < ?",
                    (ts, ts, ts, ts),
                )
        return removed

    # -- away time -------------------------------------------------------

    def add_afk(self, start_ts: float, end_ts: float, kind: str) -> None:
        """Record a complete away interval that is already known in full."""
        if end_ts <= start_ts:
            return
        self._write(
            "INSERT INTO afk (start_ts, end_ts, duration, kind) VALUES (?, ?, ?, ?)",
            (start_ts, end_ts, end_ts - start_ts, kind),
        )

    def open_afk(self, ts: float, kind: str) -> int:
        """Open an away interval, extended on each tick like an event.

        Away time is written as it happens rather than when the user returns,
        so the dashboard is right about the current state even if the process
        is killed in the middle of a long break.
        """
        cur = self._write(
            "INSERT INTO afk (start_ts, end_ts, duration, kind) VALUES (?, ?, 0, ?)",
            (ts, ts, kind),
        )
        return int(cur.lastrowid)

    def touch_afk(self, afk_id: int, end_ts: float) -> None:
        self._write(
            "UPDATE afk SET end_ts = ?, duration = ? - start_ts"
            " WHERE id = ? AND ? > start_ts",
            (end_ts, end_ts, afk_id, end_ts),
        )

    def delete_afk(self, afk_id: int) -> None:
        self._write("DELETE FROM afk WHERE id = ?", (afk_id,))

    # -- reads -----------------------------------------------------------

    def desktop_events(self, start_ts: float, end_ts: float) -> list[dict[str, Any]]:
        rows = self.conn().execute(
            "SELECT * FROM desktop_events"
            " WHERE end_ts > ? AND start_ts < ? AND duration > 0"
            " ORDER BY start_ts",
            (start_ts, end_ts),
        ).fetchall()
        return [_row_to_dict(r) for r in rows]

    def browser_events(self, start_ts: float, end_ts: float) -> list[dict[str, Any]]:
        rows = self.conn().execute(
            "SELECT * FROM browser_events"
            " WHERE end_ts > ? AND start_ts < ? AND duration > 0"
            " ORDER BY start_ts",
            (start_ts, end_ts),
        ).fetchall()
        return [_row_to_dict(r) for r in rows]

    def afk_rows(self, start_ts: float, end_ts: float) -> list[dict[str, Any]]:
        """Raw away intervals. These can overlap, so the caller must union
        them rather than add their durations up."""
        rows = self.conn().execute(
            "SELECT * FROM afk WHERE end_ts > ? AND start_ts < ? ORDER BY start_ts",
            (start_ts, end_ts),
        ).fetchall()
        return [_row_to_dict(r) for r in rows]

    def afk_total(self, start_ts: float, end_ts: float) -> dict[str, float]:
        rows = self.conn().execute(
            "SELECT kind, SUM(MIN(end_ts, ?) - MAX(start_ts, ?)) AS secs"
            " FROM afk WHERE end_ts > ? AND start_ts < ?"
            " GROUP BY kind",
            (end_ts, start_ts, start_ts, end_ts),
        ).fetchall()
        return {r["kind"]: float(r["secs"] or 0.0) for r in rows}

    # -- rules -----------------------------------------------------------

    def rules(self, enabled_only: bool = True) -> list[dict[str, Any]]:
        sql = "SELECT * FROM rules"
        if enabled_only:
            sql += " WHERE enabled = 1"
        sql += " ORDER BY priority ASC, id ASC"
        return [_row_to_dict(r) for r in self.conn().execute(sql).fetchall()]

    def add_rule(self, rule: dict[str, Any]) -> int:
        cur = self._write(
            "INSERT INTO rules"
            " (priority, match_app, match_title, match_domain, match_url,"
            "  client, project, category, enabled, created_ts)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                int(rule.get("priority") or 100),
                rule.get("match_app") or None,
                rule.get("match_title") or None,
                rule.get("match_domain") or None,
                rule.get("match_url") or None,
                rule.get("client") or None,
                rule.get("project") or None,
                rule.get("category") or None,
                1 if rule.get("enabled", True) else 0,
                time.time(),
            ),
        )
        return int(cur.lastrowid)

    def delete_rule(self, rule_id: int) -> None:
        self._write("DELETE FROM rules WHERE id = ?", (rule_id,))

    def set_rule_enabled(self, rule_id: int, enabled: bool) -> None:
        self._write(
            "UPDATE rules SET enabled = ? WHERE id = ?",
            (1 if enabled else 0, rule_id),
        )

    def rule_count(self) -> int:
        return int(self.conn().execute("SELECT COUNT(*) FROM rules").fetchone()[0])

    def seed_rules(self, rules: Iterable[dict[str, Any]]) -> int:
        """Insert starter rules, once, on a database that has none."""
        if self.rule_count() > 0:
            return 0
        count = 0
        for rule in rules:
            self.add_rule(rule)
            count += 1
        return count

    # -- meta / stats ----------------------------------------------------

    def set_meta(self, key: str, value: str) -> None:
        self._write(
            "INSERT INTO meta (key, value) VALUES (?, ?)"
            " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )

    def get_meta(self, key: str, default: str | None = None) -> str | None:
        row = self.conn().execute(
            "SELECT value FROM meta WHERE key = ?", (key,)
        ).fetchone()
        return row["value"] if row else default

    def stats(self) -> dict[str, Any]:
        conn = self.conn()
        out: dict[str, Any] = {}
        for table in ("desktop_events", "browser_events", "afk", "rules"):
            out[table] = int(
                conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            )
        row = conn.execute(
            "SELECT MAX(end_ts) AS t FROM desktop_events"
        ).fetchone()
        out["last_desktop_event"] = float(row["t"]) if row and row["t"] else None
        row = conn.execute(
            "SELECT MAX(end_ts) AS t FROM browser_events"
        ).fetchone()
        out["last_browser_event"] = float(row["t"]) if row and row["t"] else None
        try:
            out["db_bytes"] = self.path.stat().st_size
        except OSError:
            out["db_bytes"] = 0
        return out

    def purge_before(self, ts: float) -> int:
        removed = 0
        with self._write_lock:
            conn = self.conn()
            for table in ("desktop_events", "browser_events", "afk"):
                cur = conn.execute(f"DELETE FROM {table} WHERE end_ts < ?", (ts,))
                removed += cur.rowcount or 0
        return removed
