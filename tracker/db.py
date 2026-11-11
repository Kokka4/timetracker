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
    match_any    TEXT,
    match_mode   TEXT NOT NULL DEFAULT 'regex',
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

-- Categories and clients exist in their own right, not as a side effect of
-- the rules that happen to mention them. That is what lets you create one
-- before anything uses it, rename one without editing every rule, and give
-- one a colour that survives having no time against it today.
--
-- Rules still store the *name*, so classification stays a pure read-time
-- function of the rules table and a rename is a single UPDATE away from
-- re-labelling the whole history.
CREATE TABLE IF NOT EXISTS categories (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT NOT NULL,
    color      TEXT,
    sort_order INTEGER NOT NULL DEFAULT 100,
    source     TEXT NOT NULL DEFAULT 'user',
    created_ts REAL NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_categories_name
    ON categories(name COLLATE NOCASE);

CREATE TABLE IF NOT EXISTS clients (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT NOT NULL,
    color      TEXT,
    archived   INTEGER NOT NULL DEFAULT 0,
    created_ts REAL NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_clients_name
    ON clients(name COLLATE NOCASE);

-- A label put directly on a stretch of time, rather than on a pattern.
--
-- A rule says "anything matching this is Hanval". An assignment says "that
-- hour was Hanval" and claims nothing about anything else. Both exist
-- because they answer different questions: the first is how you stop doing
-- the work twice, the second is how you record the afternoon that does not
-- resemble any other afternoon. Assignments are read after rules and win,
-- field by field, so assigning a client to a block keeps whatever category
-- the rules worked out.
CREATE TABLE IF NOT EXISTS assignments (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    start_ts   REAL NOT NULL,
    end_ts     REAL NOT NULL,
    client     TEXT,
    project    TEXT,
    category   TEXT,
    source     TEXT NOT NULL DEFAULT 'user',
    created_ts REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_assign_start ON assignments(start_ts);
CREATE INDEX IF NOT EXISTS idx_assign_end   ON assignments(end_ts);
"""


# The categorical palette. Slots rather than hex, because the dashboard
# defines each one twice, for light and for dark, and a stored hex would be
# unreadable in one of them. Storage owns the vocabulary because storage is
# what has to keep two categories from claiming the same colour.
PALETTE = ("s1", "s2", "s3", "s4", "s5", "s6", "s7", "s8")


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
            self._add_missing_columns()

    def _add_missing_columns(self) -> None:
        """Columns added after the first release.

        `CREATE TABLE IF NOT EXISTS` does nothing to a table that already
        exists, so a column added later has to be bolted on separately or an
        upgraded install quietly runs the old shape.
        """
        conn = self.conn()
        have = {row["name"] for row in conn.execute("PRAGMA table_info(rules)")}
        if "source" not in have:
            # Where a rule came from: 'user' for anything you wrote,
            # 'starter' for the defaults, 'pack:<id>' for a pack. Removing a
            # pack takes back exactly its own rows and nothing else.
            conn.execute(
                "ALTER TABLE rules ADD COLUMN source TEXT NOT NULL DEFAULT 'user'"
            )
        if "match_any" not in have:
            # One pattern checked against the app, the window title, the
            # domain and the address, matching if ANY of them matches. The
            # four columns above AND together, which is right for "this app,
            # with this title" and useless for "anything mentioning Hanval".
            conn.execute("ALTER TABLE rules ADD COLUMN match_any TEXT")
        if "match_mode" not in have:
            # 'text' means the pattern is a phrase and is escaped before it
            # is compiled; 'regex' means it is a pattern and is not. Stored
            # rather than guessed, because guessing is how `C++` becomes an
            # invalid rule that fails silently.
            conn.execute(
                "ALTER TABLE rules ADD COLUMN match_mode TEXT NOT NULL DEFAULT 'regex'"
            )

    def backup_to(self, target: Path) -> Path:
        """A real snapshot, taken through SQLite rather than by copying bytes.

        In WAL mode the newest writes live in the -wal file, so `cp` of the
        database alone silently loses them.
        """
        target = Path(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        with self._write_lock:
            destination = sqlite3.connect(str(target))
            try:
                self.conn().backup(destination)
            finally:
                destination.close()
        return target

    # Deleting time is the one thing here that cannot be undone, so it is the
    # one thing that always leaves a way back.
    #
    # The snapshot worth having is the state before you *started* correcting
    # the day, not the state before the last of six clicks. So a burst shares
    # one: a new snapshot is taken only when the most recent is older than
    # `settle_seconds`. Five are kept, which is five sessions of corrections
    # rather than the last five clicks of one.
    def backup_before_delete(
        self, settle_seconds: float = 600.0, keep: int = 5
    ) -> Path | None:
        folder = self.path.parent / "backups"
        folder.mkdir(parents=True, exist_ok=True)
        existing = sorted(
            folder.glob("before-delete-*.db"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        if existing:
            age = time.time() - existing[0].stat().st_mtime
            if age < settle_seconds:
                return existing[0]

        # Seconds are not fine enough on their own: two corrections inside
        # the same second would write the same filename, and the second would
        # overwrite the only copy of the state the first was protecting.
        stamp = time.strftime("%Y%m%d-%H%M%S")
        candidate = folder / f"before-delete-{stamp}.db"
        suffix = 1
        while candidate.exists():
            candidate = folder / f"before-delete-{stamp}-{suffix}.db"
            suffix += 1
        target = self.backup_to(candidate)
        for old in existing[keep - 1:]:
            try:
                old.unlink()
            except OSError:
                pass
        return target

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

    # Patterns the rule could match on. A rule with none of them is not a
    # permissive rule, it is a dead one: `compile_rules` drops it, so it
    # classifies nothing and sits in the list looking like a rule that simply
    # has not been reached yet. Eleven of those turned up in a real database.
    MATCH_FIELDS = ("match_app", "match_title", "match_domain", "match_url",
                    "match_any")

    def add_rule(self, rule: dict[str, Any]) -> int:
        # Checked here rather than only at the HTTP layer, because an
        # invariant enforced by every caller separately is one that a new
        # caller will forget, and the failure is silent by construction.
        if not any(rule.get(field) for field in self.MATCH_FIELDS):
            raise ValueError("a rule with no pattern would match nothing")
        cur = self._write(
            "INSERT INTO rules"
            " (priority, match_app, match_title, match_domain, match_url,"
            "  match_any, match_mode, client, project, category, enabled,"
            "  created_ts, source)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                int(rule.get("priority") or 100),
                rule.get("match_app") or None,
                rule.get("match_title") or None,
                rule.get("match_domain") or None,
                rule.get("match_url") or None,
                rule.get("match_any") or None,
                "text" if str(rule.get("match_mode") or "regex") == "text" else "regex",
                rule.get("client") or None,
                rule.get("project") or None,
                rule.get("category") or None,
                1 if rule.get("enabled", True) else 0,
                time.time(),
                str(rule.get("source") or "user"),
            ),
        )
        return int(cur.lastrowid)

    def dead_rules(self) -> list[dict[str, Any]]:
        """Rules that can never match, because they carry no pattern."""
        where = " AND ".join(f"({f} IS NULL OR {f} = '')" for f in self.MATCH_FIELDS)
        return [
            _row_to_dict(row)
            for row in self.conn().execute(
                f"SELECT * FROM rules WHERE {where} ORDER BY id"
            ).fetchall()
        ]

    def delete_dead_rules(self) -> int:
        where = " AND ".join(f"({f} IS NULL OR {f} = '')" for f in self.MATCH_FIELDS)
        with self._write_lock:
            cur = self._write(f"DELETE FROM rules WHERE {where}")
            return cur.rowcount or 0

    def delete_rules_by_source(self, source: str) -> int:
        cur = self._write("DELETE FROM rules WHERE source = ?", (source,))
        return cur.rowcount or 0

    def rule_sources(self) -> dict[str, int]:
        rows = self.conn().execute(
            "SELECT source, COUNT(*) AS n FROM rules GROUP BY source"
        ).fetchall()
        return {r["source"]: int(r["n"]) for r in rows}

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

    # -- categories and clients ------------------------------------------
    # Rules store names rather than ids, so a rename has to carry the rules
    # with it. Both halves happen under the one write lock: a rename that
    # updated the registry but not the rules would leave the history pointing
    # at a category that no longer exists, which is worse than not renaming.

    def categories(self) -> list[dict[str, Any]]:
        """Every category, with how many rules currently assign it.

        The count is what makes the destructive actions honest: "Delete" next
        to a name you labelled forty things with should say so before you
        press it, not after.
        """
        rows = self.conn().execute(
            "SELECT c.*,"
            " (SELECT COUNT(*) FROM rules r"
            "  WHERE r.category = c.name COLLATE NOCASE) AS rule_count"
            " FROM categories c"
            " ORDER BY c.sort_order ASC, c.name COLLATE NOCASE ASC"
        ).fetchall()
        return [_row_to_dict(r) for r in rows]

    def category_named(self, name: str) -> dict[str, Any] | None:
        row = self.conn().execute(
            "SELECT * FROM categories WHERE name = ? COLLATE NOCASE", (name,)
        ).fetchone()
        return _row_to_dict(row) if row else None

    def free_color(self, preferred: str | None = None) -> str:
        """A palette slot nothing else is using, preferring the one asked for.

        Catalogue colours are written independently — the starter set does not
        know which packs will be turned on later — so two of them can easily
        name the same slot. Resolving it here rather than in the chart keeps
        the swatch in Settings honest: what you see next to a category really
        is the colour it draws in.

        Past eight categories some sharing is unavoidable, so the least-used
        slot wins and the chart's top-N cutoff keeps that out of sight.
        """
        counts = {slot: 0 for slot in PALETTE}
        for row in self.conn().execute("SELECT color FROM categories"):
            if row["color"] in counts:
                counts[row["color"]] += 1
        if preferred in counts and counts[preferred] == 0:
            return preferred
        return min(PALETTE, key=lambda slot: (counts[slot], PALETTE.index(slot)))

    def add_category(
        self,
        name: str,
        color: str | None = None,
        sort_order: int = 100,
        source: str = "user",
    ) -> int:
        """Create a category, or return the existing one of that name."""
        name = str(name).strip()
        if not name:
            raise ValueError("a category needs a name")
        with self._write_lock:
            existing = self.category_named(name)
            if existing:
                return int(existing["id"])
            # Only automatic assignment avoids collisions. A colour picked by
            # hand in Settings goes through update_category and is honoured
            # exactly, even if it duplicates another.
            color = self.free_color(color)
            cur = self._write(
                "INSERT INTO categories (name, color, sort_order, source, created_ts)"
                " VALUES (?, ?, ?, ?, ?)",
                (name, color, int(sort_order), source, time.time()),
            )
            return int(cur.lastrowid)

    def update_category(
        self,
        category_id: int,
        name: str | None = None,
        color: str | None = None,
        sort_order: int | None = None,
    ) -> dict[str, Any] | None:
        with self._write_lock:
            row = self.conn().execute(
                "SELECT * FROM categories WHERE id = ?", (category_id,)
            ).fetchone()
            if not row:
                return None
            old_name = row["name"]

            if name is not None:
                name = str(name).strip()
                if not name:
                    raise ValueError("a category needs a name")
                clash = self.category_named(name)
                if clash and int(clash["id"]) != int(category_id):
                    raise ValueError(f"there is already a category called {name!r}")
                self._write(
                    "UPDATE categories SET name = ? WHERE id = ?", (name, category_id)
                )
                if name != old_name:
                    # Classification is computed from the rules at read time,
                    # so this one statement re-labels the whole history.
                    self._write(
                        "UPDATE rules SET category = ? WHERE category = ? COLLATE NOCASE",
                        (name, old_name),
                    )
            if color is not None:
                self._write(
                    "UPDATE categories SET color = ? WHERE id = ?", (color, category_id)
                )
            if sort_order is not None:
                self._write(
                    "UPDATE categories SET sort_order = ? WHERE id = ?",
                    (int(sort_order), category_id),
                )
            return _row_to_dict(
                self.conn().execute(
                    "SELECT * FROM categories WHERE id = ?", (category_id,)
                ).fetchone()
            )

    # -- assignments -----------------------------------------------------

    def assignments(self, start_ts: float, end_ts: float) -> list[dict[str, Any]]:
        """Every assignment overlapping the window, earliest first."""
        return [
            _row_to_dict(row)
            for row in self.conn().execute(
                "SELECT * FROM assignments"
                " WHERE start_ts < ? AND end_ts > ?"
                " ORDER BY start_ts, id",
                (end_ts, start_ts),
            ).fetchall()
        ]

    def add_assignment(
        self,
        start_ts: float,
        end_ts: float,
        client: str | None = None,
        project: str | None = None,
        category: str | None = None,
        source: str = "user",
    ) -> int:
        """Label a stretch of time directly.

        Replaces whatever it covers rather than stacking on top: assigning
        the same block twice is a correction, not a second opinion, and two
        rows claiming the same minute would make the winner depend on insert
        order.
        """
        if end_ts <= start_ts:
            raise ValueError("an assignment must end after it starts")
        with self._write_lock:
            conn = self.conn()
            with conn:
                conn.execute(
                    "DELETE FROM assignments WHERE start_ts >= ? AND end_ts <= ?",
                    (start_ts, end_ts),
                )
                # Trim the ones that merely overlap, so no minute is claimed
                # twice and no earlier assignment is silently discarded.
                conn.execute(
                    "UPDATE assignments SET end_ts = ?"
                    " WHERE start_ts < ? AND end_ts > ? AND end_ts <= ?",
                    (start_ts, start_ts, start_ts, end_ts),
                )
                conn.execute(
                    "UPDATE assignments SET start_ts = ?"
                    " WHERE start_ts >= ? AND start_ts < ? AND end_ts > ?",
                    (end_ts, start_ts, end_ts, end_ts),
                )
                cur = conn.execute(
                    "INSERT INTO assignments"
                    " (start_ts, end_ts, client, project, category, source, created_ts)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        start_ts, end_ts,
                        client or None, project or None, category or None,
                        source, time.time(),
                    ),
                )
                return int(cur.lastrowid)

    def clear_assignments(self, start_ts: float, end_ts: float) -> int:
        """Put a stretch of time back to whatever the rules make of it."""
        with self._write_lock:
            cur = self._write(
                "DELETE FROM assignments WHERE start_ts < ? AND end_ts > ?",
                (end_ts, start_ts),
            )
            return cur.rowcount or 0

    def _release(self, field: str, name: str) -> dict[str, Any]:
        """Take a name off every rule that assigns it.

        Mislabelling in bulk is one click in the review panel and used to be
        unrecoverable without hunting through the rules list, so this is the
        undo. A rule that existed only to set this name has nothing left to
        say and goes; a rule that also sets the other field keeps it, with
        the released half cleared.

        Nothing recorded is touched. Classification is computed when you
        look, so the history simply stops claiming this name.

        Assignments carry the same names as rules and have to be released
        too. Clearing the rules alone would leave every block somebody
        assigned by hand still saying "Me", which is exactly the state this
        is meant to undo.
        """
        if field not in ("client", "category"):
            raise ValueError(f"cannot release {field!r}")
        with self._write_lock:
            cleared = self._write(
                f"UPDATE rules SET {field} = NULL WHERE {field} = ? COLLATE NOCASE",
                (name,),
            )
            emptied = self._write(
                "DELETE FROM rules WHERE client IS NULL AND project IS NULL"
                " AND category IS NULL"
            )
            unassigned = self._write(
                f"UPDATE assignments SET {field} = NULL"
                f" WHERE {field} = ? COLLATE NOCASE",
                (name,),
            )
            self._write(
                "DELETE FROM assignments WHERE client IS NULL AND project IS NULL"
                " AND category IS NULL"
            )
            return {
                "name": name,
                "rules_cleared": cleared.rowcount or 0,
                "rules_removed": emptied.rowcount or 0,
                "blocks_cleared": unassigned.rowcount or 0,
            }

    def unassign_category(self, category_id: int) -> dict[str, Any]:
        """Clear a category off everything, but keep the category itself."""
        row = self.conn().execute(
            "SELECT * FROM categories WHERE id = ?", (category_id,)
        ).fetchone()
        if not row:
            return {"ok": False}
        return {"ok": True, "kept": True, **self._release("category", row["name"])}

    def unassign_client(self, client_id: int) -> dict[str, Any]:
        row = self.conn().execute(
            "SELECT * FROM clients WHERE id = ?", (client_id,)
        ).fetchone()
        if not row:
            return {"ok": False}
        return {"ok": True, "kept": True, **self._release("client", row["name"])}

    def delete_category(self, category_id: int) -> dict[str, Any]:
        with self._write_lock:
            row = self.conn().execute(
                "SELECT * FROM categories WHERE id = ?", (category_id,)
            ).fetchone()
            if not row:
                return {"deleted": False}
            released = self._release("category", row["name"])
            self._write("DELETE FROM categories WHERE id = ?", (category_id,))
            return {"deleted": True, **released}

    def clients(self, include_archived: bool = True) -> list[dict[str, Any]]:
        sql = (
            "SELECT c.*,"
            " (SELECT COUNT(*) FROM rules r"
            "  WHERE r.client = c.name COLLATE NOCASE) AS rule_count"
            " FROM clients c"
        )
        if not include_archived:
            sql += " WHERE c.archived = 0"
        sql += " ORDER BY c.name COLLATE NOCASE ASC"
        return [_row_to_dict(r) for r in self.conn().execute(sql).fetchall()]

    def client_named(self, name: str) -> dict[str, Any] | None:
        row = self.conn().execute(
            "SELECT * FROM clients WHERE name = ? COLLATE NOCASE", (name,)
        ).fetchone()
        return _row_to_dict(row) if row else None

    def add_client(self, name: str, color: str | None = None) -> int:
        name = str(name).strip()
        if not name:
            raise ValueError("a client needs a name")
        with self._write_lock:
            existing = self.client_named(name)
            if existing:
                return int(existing["id"])
            cur = self._write(
                "INSERT INTO clients (name, color, archived, created_ts)"
                " VALUES (?, ?, 0, ?)",
                (name, color, time.time()),
            )
            return int(cur.lastrowid)

    def update_client(
        self,
        client_id: int,
        name: str | None = None,
        color: str | None = None,
        archived: bool | None = None,
    ) -> dict[str, Any] | None:
        with self._write_lock:
            row = self.conn().execute(
                "SELECT * FROM clients WHERE id = ?", (client_id,)
            ).fetchone()
            if not row:
                return None
            old_name = row["name"]

            if name is not None:
                name = str(name).strip()
                if not name:
                    raise ValueError("a client needs a name")
                clash = self.client_named(name)
                if clash and int(clash["id"]) != int(client_id):
                    # Renaming onto an existing name is a merge, and merging
                    # is the one thing here that cannot be undone by renaming
                    # back, so it is refused rather than guessed at.
                    raise ValueError(f"there is already a client called {name!r}")
                self._write(
                    "UPDATE clients SET name = ? WHERE id = ?", (name, client_id)
                )
                if name != old_name:
                    self._write(
                        "UPDATE rules SET client = ? WHERE client = ? COLLATE NOCASE",
                        (name, old_name),
                    )
            if color is not None:
                self._write(
                    "UPDATE clients SET color = ? WHERE id = ?", (color, client_id)
                )
            if archived is not None:
                self._write(
                    "UPDATE clients SET archived = ? WHERE id = ?",
                    (1 if archived else 0, client_id),
                )
            return _row_to_dict(
                self.conn().execute(
                    "SELECT * FROM clients WHERE id = ?", (client_id,)
                ).fetchone()
            )

    def delete_client(self, client_id: int) -> dict[str, Any]:
        with self._write_lock:
            row = self.conn().execute(
                "SELECT * FROM clients WHERE id = ?", (client_id,)
            ).fetchone()
            if not row:
                return {"deleted": False}
            released = self._release("client", row["name"])
            self._write("DELETE FROM clients WHERE id = ?", (client_id,))
            return {"deleted": True, **released}

    def categories_in_use(self) -> set[str]:
        rows = self.conn().execute(
            "SELECT DISTINCT category FROM rules WHERE category IS NOT NULL"
        ).fetchall()
        return {str(r["category"]).casefold() for r in rows}

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

    def delete_meta(self, key: str) -> None:
        self._write("DELETE FROM meta WHERE key = ?", (key,))

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

    # -- removing a stretch of time --------------------------------------

    # An event is an interval [start_ts, end_ts]. Against a deletion window
    # [a, b] there are five arrangements, and only the first leaves it alone:
    #
    #   outside    |--e--|                     a=====b
    #   inside               a===|--e--|===b           drop it
    #   head            |--e--|=====b                  clip the end back to a
    #   tail                 a=====|--e--|             clip the start up to b
    #   spanning   |--e-------a=====b-------|          keep both ends, drop
    #                                                  the middle: one event
    #                                                  becomes two
    #
    # Spanning is the case that is easy to miss and impossible to notice
    # afterwards, because the arithmetic still adds up — the day simply keeps
    # time you asked it to remove.
    #
    # Interaction counts cannot be placed in time: all the row records is how
    # many happened across the whole event. Every trim apportions them by the
    # share of the event that survives, which is the same thing analytics
    # already does when it splits a tab across a block. It conserves the total
    # and never invents activity.

    _COUNTERS = ("keys", "clicks", "scrolls", "media")

    def _scale(self, table: str, kept: str) -> str:
        """SET clauses that shrink the interaction counters along with the row.

        `kept` is an SQL expression for the surviving duration.
        """
        if table != "browser_events":
            return ""
        return "".join(
            f", {c} = CAST({c} * ({kept}) / duration AS INTEGER)"
            for c in self._COUNTERS
        )

    def removable_seconds(self, start_ts: float, end_ts: float) -> float:
        """How much recorded time lies inside the window, before touching it."""
        if end_ts <= start_ts:
            return 0.0
        total = 0.0
        conn = self.conn()
        for table in ("desktop_events", "browser_events"):
            row = conn.execute(
                f"SELECT COALESCE(SUM(MIN(end_ts, ?) - MAX(start_ts, ?)), 0) AS s"
                f" FROM {table} WHERE start_ts < ? AND end_ts > ?",
                (end_ts, start_ts, end_ts, start_ts),
            ).fetchone()
            total += float(row["s"] or 0.0)
        return total

    def delete_range(self, start_ts: float, end_ts: float) -> dict[str, Any]:
        """Remove every recorded second between `start_ts` and `end_ts`.

        Events are trimmed rather than dropped wholesale, so deleting an hour
        out of the middle of an afternoon costs exactly that hour. Nothing
        outside the window moves.
        """
        if end_ts <= start_ts:
            return {"seconds": 0.0, "deleted": 0, "clipped": 0, "split": 0}

        seconds = self.removable_seconds(start_ts, end_ts)
        deleted = clipped = split = 0
        a, b = start_ts, end_ts

        with self._write_lock:
            conn = self.conn()
            with conn:  # one transaction: a half-applied delete is not a state
                # Assignments are labels on time. When the time goes, so do
                # they: an assignment left over a window with nothing in it
                # would reattach itself to whatever was recorded there next.
                conn.execute(
                    "DELETE FROM assignments WHERE start_ts >= ? AND end_ts <= ?",
                    (a, b),
                )
                conn.execute(
                    "UPDATE assignments SET end_ts = ?"
                    " WHERE start_ts < ? AND end_ts > ? AND end_ts <= ?",
                    (a, a, a, b),
                )
                conn.execute(
                    "UPDATE assignments SET start_ts = ?"
                    " WHERE start_ts >= ? AND start_ts < ? AND end_ts > ?",
                    (b, a, b, b),
                )

                for table in ("desktop_events", "browser_events", "afk"):
                    if table == "desktop_events":
                        cols = "app, bundle_id, title"
                        extra = ""
                    elif table == "browser_events":
                        cols = "browser, domain, url, title, tab_id"
                        extra = "".join(
                            f", CAST({c} * (end_ts - ?) / duration AS INTEGER)"
                            for c in self._COUNTERS
                        )
                        cols += ", keys, clicks, scrolls, media"
                    else:
                        cols = "kind"
                        extra = ""

                    # The far half of a spanning event, created before
                    # anything is clipped — afterwards there is nothing left
                    # to split.
                    insert_cols = cols.split(", ")
                    select_cols = [c for c in insert_cols if c not in self._COUNTERS]
                    cur = conn.execute(
                        f"INSERT INTO {table}"
                        f" (start_ts, end_ts, duration, {', '.join(insert_cols)})"
                        f" SELECT ?, end_ts, end_ts - ?, {', '.join(select_cols)}{extra}"
                        f" FROM {table}"
                        f" WHERE start_ts < ? AND end_ts > ? AND duration > 0",
                        (b, b) + (b,) * (len(self._COUNTERS) if extra else 0) + (a, b),
                    )
                    split += cur.rowcount or 0

                    # Heads: began before the window, ran into it. Keep the
                    # part before.
                    cur = conn.execute(
                        f"UPDATE {table}"
                        f" SET end_ts = ?, duration = ? - start_ts"
                        f"{self._scale(table, '? - start_ts')}"
                        f" WHERE start_ts < ? AND end_ts > ? AND duration > 0",
                        (a, a) + ((a,) * len(self._COUNTERS) if table == "browser_events" else ())
                        + (a, a),
                    )
                    clipped += cur.rowcount or 0

                    # Tails: still running when the window ended. Keep the
                    # part after. The halves inserted above already start at
                    # b, so they do not match.
                    cur = conn.execute(
                        f"UPDATE {table}"
                        f" SET start_ts = ?, duration = end_ts - ?"
                        f"{self._scale(table, 'end_ts - ?')}"
                        f" WHERE start_ts >= ? AND start_ts < ? AND end_ts > ? AND duration > 0",
                        (b, b) + ((b,) * len(self._COUNTERS) if table == "browser_events" else ())
                        + (a, b, b),
                    )
                    clipped += cur.rowcount or 0

                    # Whatever still lies inside the window was entirely
                    # inside it.
                    cur = conn.execute(
                        f"DELETE FROM {table} WHERE start_ts >= ? AND end_ts <= ?",
                        (a, b),
                    )
                    deleted += cur.rowcount or 0

        # A spanning event is trimmed at its head as well as split, so it
        # lands in both tallies. Reporting it twice would make the numbers
        # add up to more events than the window ever held.
        return {
            "seconds": seconds,
            "deleted": deleted,
            "clipped": max(0, clipped - split),
            "split": split,
        }
