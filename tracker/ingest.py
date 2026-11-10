"""Browser heartbeat ingestion.

The extension never accumulates time. It posts "at this timestamp, this tab was
frontmost", and the coalescing into intervals happens here, where the process
is not killed every thirty seconds. If the extension's service worker dies, the
open browser interval is closed at the last heartbeat and the desktop watcher
keeps counting the time as plain browser time with no tab attached.
"""

from __future__ import annotations

import re
import threading
import time
from typing import Any
from urllib.parse import urlsplit, urlunsplit

# "(3) Inbox - ..." fragments an interval every time the unread count ticks.
_UNREAD_PREFIX = re.compile(r"^\(\d+\+?\)\s*")
_MAX_URL = 500
_MAX_TITLE = 400


def clean_title(raw: Any) -> str | None:
    text = _UNREAD_PREFIX.sub("", str(raw or "")).strip()
    return text[:_MAX_TITLE] or None


class BrowserIngest:
    def __init__(self, cfg, store):
        self.cfg = cfg
        self.store = store
        self._lock = threading.RLock()
        # browser label -> {id, start, key, last_ts}
        self.sessions: dict[str, dict[str, Any]] = {}
        self.heartbeats = 0
        self.rejected = 0
        self.last_heartbeat_at: float | None = None
        self.last_browser: str | None = None

    # -- url handling ----------------------------------------------------

    def normalize(self, raw: str) -> tuple[str | None, str | None]:
        """Return ``(domain, stored_url)``, or ``(None, None)`` to skip."""
        raw = (raw or "").strip()
        if not raw:
            return None, None

        parts = urlsplit(raw)
        scheme = (parts.scheme or "").casefold()

        if raw.casefold() in ("about:blank", "about:newtab"):
            return None, None

        if scheme not in ("http", "https"):
            # chrome://newtab, file://... Worth counting, not worth a path.
            if not scheme:
                return None, None
            label = f"{scheme}:{(parts.netloc or parts.path or '').strip('/')[:40]}"
            return label, label

        host = (parts.hostname or "").casefold()
        if not host:
            return None, None
        if host.startswith("www."):
            host = host[4:]

        # Keep a non-default port in the host. Two local tools on different
        # ports are two different things, and collapsing them would make
        # anything you run on localhost unattributable.
        try:
            port = parts.port
        except ValueError:
            port = None
        if port and port not in (80, 443):
            host = f"{host}:{port}"

        path = parts.path or "/"
        query = "" if self.cfg.strip_query else (parts.query or "")

        if self.cfg.store_full_urls:
            stored = urlunsplit((scheme, host, path, query, ""))
        else:
            segments = [s for s in path.split("/") if s][:2]
            stored = host + ("/" + "/".join(segments) if segments else "")

        return host, stored[:_MAX_URL]

    # -- heartbeat -------------------------------------------------------

    def heartbeat(self, payload: dict[str, Any]) -> dict[str, Any]:
        now = time.time()

        try:
            ts = float(payload.get("ts") or now)
        except (TypeError, ValueError):
            ts = now
        # A heartbeat older than ten minutes or from the future is a clock
        # problem, not information.
        if ts > now + 10 or ts < now - 600:
            ts = now

        browser = str(payload.get("browser") or "Chrome")[:40]
        activity = payload.get("activity") or {}

        def count(key: str) -> int:
            try:
                return max(0, min(100_000, int(activity.get(key) or 0)))
            except (TypeError, ValueError):
                return 0

        counters = (count("keys"), count("clicks"), count("scrolls"))
        media = 1 if activity.get("media") else 0

        with self._lock:
            self.heartbeats += 1
            self.last_heartbeat_at = now
            self.last_browser = browser

            tab = payload.get("tab") or {}
            if not payload.get("focused") or not tab or tab.get("incognito"):
                self._close(browser, ts)
                return {"ok": True, "state": "idle"}

            domain, url = self.normalize(str(tab.get("url") or ""))
            if not domain or self.cfg.domain_excluded(domain):
                self._close(browser, ts)
                self.rejected += 1
                return {"ok": True, "state": "skipped"}

            title = clean_title(tab.get("title"))
            if title is not None and self.cfg.redact_title(title) is None:
                title = None

            key = (url, title)
            session = self.sessions.get(browser)

            if (
                session
                and session["key"] == key
                and ts - session["last_ts"] <= self.cfg.browser_timeout
            ):
                self.store.touch_browser_event(
                    session["id"], ts, counters[0], counters[1], counters[2], media
                )
                session["last_ts"] = ts
                return {"ok": True, "state": "extended"}

            if session:
                # Close at the last heartbeat, not now: the gap between them is
                # time we have no evidence for.
                self._close(
                    browser,
                    min(ts, session["last_ts"] + self.cfg.browser_timeout),
                )

            try:
                tab_id = int(tab.get("id"))
            except (TypeError, ValueError):
                tab_id = None

            event_id = self.store.open_browser_event(
                ts, browser, domain, url, title, tab_id
            )
            self.sessions[browser] = {
                "id": event_id,
                "start": ts,
                "key": key,
                "last_ts": ts,
            }
            return {"ok": True, "state": "opened"}

    # -- lifecycle -------------------------------------------------------

    def _close(self, browser: str, end_ts: float) -> None:
        session = self.sessions.pop(browser, None)
        if not session:
            return
        end_ts = max(end_ts, session["start"])
        if end_ts - session["start"] < self.cfg.min_event:
            self.store.delete_browser_event(session["id"])
        else:
            self.store.touch_browser_event(session["id"], end_ts)

    def sweep(self, now: float | None = None) -> None:
        """Close any interval whose extension has stopped arriving."""
        now = now if now is not None else time.time()
        with self._lock:
            for browser, session in list(self.sessions.items()):
                if now - session["last_ts"] > self.cfg.browser_timeout:
                    self._close(browser, session["last_ts"])

    def close_all(self, end_ts: float | None = None) -> None:
        end_ts = end_ts if end_ts is not None else time.time()
        with self._lock:
            for browser in list(self.sessions):
                self._close(browser, end_ts)

    def status(self) -> dict[str, Any]:
        with self._lock:
            age = (
                round(time.time() - self.last_heartbeat_at, 1)
                if self.last_heartbeat_at
                else None
            )
            return {
                "connected": age is not None and age < 180,
                "heartbeats": self.heartbeats,
                "skipped": self.rejected,
                "last_heartbeat_age_seconds": age,
                "browser": self.last_browser,
                "open_sessions": len(self.sessions),
            }
