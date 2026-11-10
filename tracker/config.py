"""Configuration loading and path resolution."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent

DEFAULTS: dict[str, Any] = {
    "host": "127.0.0.1",
    "port": 8734,
    "sample_interval_seconds": 5.0,
    "idle_threshold_seconds": 180,
    "min_event_seconds": 2.0,
    "capture_window_titles": True,
    "browser_heartbeat_timeout_seconds": 90,
    "strip_query_strings": True,
    "store_full_urls": True,
    "excluded_apps": [],
    "excluded_title_patterns": [],
    "excluded_domains": [],
    "work_hours": {"start": 8, "end": 19},
    "browsers": {
        "com.google.Chrome": "Chrome",
        "com.brave.Browser": "Brave",
        "com.microsoft.edgemac": "Edge",
        "company.thebrowser.Browser": "Arc",
        "com.apple.Safari": "Safari",
        "org.mozilla.firefox": "Firefox",
    },
}

# Fallback match on app name, for a browser whose bundle id we did not resolve.
BROWSER_NAME_HINTS = (
    "chrome",
    "brave",
    "edge",
    "arc",
    "safari",
    "firefox",
    "comet",
    "sigmaos",
    "vivaldi",
    "opera",
)


class Config:
    """Parsed configuration. Regex options are compiled once, here."""

    def __init__(self, data: dict[str, Any], root: Path = ROOT):
        merged = dict(DEFAULTS)
        for key, value in (data or {}).items():
            if key.startswith("_"):
                continue
            merged[key] = value

        self.root = root
        self.raw = merged

        self.host: str = str(merged["host"])
        self.port: int = int(merged["port"])
        self.sample_interval: float = max(1.0, float(merged["sample_interval_seconds"]))
        self.idle_threshold: float = max(30.0, float(merged["idle_threshold_seconds"]))
        self.min_event: float = max(0.0, float(merged["min_event_seconds"]))
        self.capture_titles: bool = bool(merged["capture_window_titles"])
        self.browser_timeout: float = max(
            15.0, float(merged["browser_heartbeat_timeout_seconds"])
        )
        self.strip_query: bool = bool(merged["strip_query_strings"])
        self.store_full_urls: bool = bool(merged["store_full_urls"])

        self.excluded_apps = {str(a).casefold() for a in merged["excluded_apps"]}
        self.excluded_domains = {
            str(d).casefold().lstrip(".") for d in merged["excluded_domains"]
        }
        self.title_filters = [
            re.compile(p) for p in merged["excluded_title_patterns"] if p
        ]

        self.browsers: dict[str, str] = {
            str(k): str(v) for k, v in (merged.get("browsers") or {}).items()
        }

        work = merged.get("work_hours") or {}
        self.work_start = int(work.get("start", 8))
        self.work_end = int(work.get("end", 19))

        self.db_path = root / "data" / "tracker.db"
        self.web_dir = root / "web"
        self.log_dir = root / "logs"

    # -- derived helpers -------------------------------------------------

    def browser_name(self, bundle_id: str | None, app: str | None) -> str | None:
        """Return a browser label when this app is a browser, else None."""
        if bundle_id and bundle_id in self.browsers:
            return self.browsers[bundle_id]
        if app:
            folded = app.casefold()
            for hint in BROWSER_NAME_HINTS:
                if hint in folded:
                    return app
        return None

    def app_excluded(self, app: str | None) -> bool:
        return bool(app) and app.casefold() in self.excluded_apps

    def domain_excluded(self, domain: str | None) -> bool:
        if not domain:
            return False
        folded = domain.casefold()
        for blocked in self.excluded_domains:
            if folded == blocked or folded.endswith("." + blocked):
                return True
        return False

    def redact_title(self, title: str | None) -> str | None:
        """Drop a window title that matches a privacy filter."""
        if not title:
            return None
        for pattern in self.title_filters:
            if pattern.search(title):
                return None
        return title


def load(root: Path = ROOT) -> Config:
    path = root / "config.json"
    data: dict[str, Any] = {}
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:  # keep running on a bad edit
            print(f"[config] could not read {path}: {exc}; using defaults")
            data = {}
    return Config(data, root=root)
