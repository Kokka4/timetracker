"""Loopback HTTP server: the dashboard, the read API, and the browser ingest.

Bound to 127.0.0.1 by default, so nothing on the network can reach it. The
ingest endpoint additionally rejects any request carrying an http(s) `Origin`,
which is what stops a random web page you happen to have open from posting
junk into your database; a browser extension's origin is `chrome-extension://`.
"""

from __future__ import annotations

import csv
import io
import json
import mimetypes
import re
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

from . import analytics, rules as rules_mod

MAX_BODY = 256 * 1024
EXTENSION_ORIGINS = (
    "chrome-extension://",
    "moz-extension://",
    "safari-web-extension://",
)
CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
}
RULE_ID_PATH = re.compile(r"^/api/rules/(\d+)$")
RULE_TOGGLE_PATH = re.compile(r"^/api/rules/(\d+)/toggle$")


class Context:
    def __init__(self, cfg, store, watcher=None, ingest=None):
        self.cfg = cfg
        self.store = store
        self.watcher = watcher
        self.ingest = ingest
        self.started_at = time.time()
        self.requests = 0


def _summary(ctx: Context, params: dict[str, list[str]]) -> dict[str, Any]:
    window = analytics.resolve_range(
        (params.get("range") or ["today"])[0],
        (params.get("from") or [None])[0],
        (params.get("to") or [None])[0],
    )
    blocks = analytics.build_blocks(
        ctx.store, ctx.cfg, window["start_ts"], window["end_ts"]
    )
    afk = ctx.store.afk_rows(window["start_ts"], window["end_ts"])
    return analytics.summarize(blocks, afk, window)


def make_handler(ctx: Context):
    class Handler(BaseHTTPRequestHandler):
        server_version = "LocalTimeTracker"
        sys_version = ""
        protocol_version = "HTTP/1.1"

        # -- plumbing ----------------------------------------------------

        def log_message(self, fmt: str, *args: Any) -> None:
            return  # the launchd log is for errors, not for every request

        def _send(
            self,
            status: int,
            body: bytes,
            content_type: str = "application/json; charset=utf-8",
            extra: dict[str, str] | None = None,
        ) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            for key, value in (extra or {}).items():
                self.send_header(key, value)
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def _json(self, payload: Any, status: int = 200) -> None:
            body = json.dumps(payload, default=str).encode("utf-8")
            self._send(status, body)

        def _error(self, status: int, message: str) -> None:
            self._json({"ok": False, "error": message}, status=status)

        def _body(self) -> dict[str, Any]:
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                return {}
            if length <= 0 or length > MAX_BODY:
                return {}
            raw = self.rfile.read(length)
            try:
                parsed = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, ValueError):
                return {}
            return parsed if isinstance(parsed, dict) else {}

        def _extension_origin(self) -> bool:
            origin = self.headers.get("Origin")
            if not origin:
                return True  # a direct POST, e.g. curl during setup
            return origin.startswith(EXTENSION_ORIGINS)

        def _cors(self) -> dict[str, str]:
            origin = self.headers.get("Origin")
            if origin and origin.startswith(EXTENSION_ORIGINS):
                return {
                    "Access-Control-Allow-Origin": origin,
                    "Access-Control-Allow-Headers": "Content-Type",
                    "Access-Control-Allow-Methods": "POST, OPTIONS",
                    "Access-Control-Max-Age": "86400",
                    "Vary": "Origin",
                }
            return {}

        # -- static ------------------------------------------------------

        def _static(self, path: str) -> None:
            name = path.lstrip("/") or "index.html"
            root = ctx.cfg.web_dir.resolve()
            target = (root / name).resolve()
            if root not in target.parents and target != root:
                return self._error(403, "outside the web directory")
            if not target.is_file():
                return self._error(404, f"no such file: {name}")
            suffix = target.suffix.casefold()
            content_type = CONTENT_TYPES.get(suffix) or (
                mimetypes.guess_type(target.name)[0] or "application/octet-stream"
            )
            self._send(200, target.read_bytes(), content_type)

        # -- GET ---------------------------------------------------------

        def do_GET(self) -> None:  # noqa: N802
            ctx.requests += 1
            parts = urlsplit(self.path)
            path = parts.path
            params = parse_qs(parts.query)

            try:
                if path in ("/", "/index.html"):
                    return self._static("index.html")
                if path == "/favicon.ico":
                    return self._send(204, b"", "image/x-icon")
                if not path.startswith("/api/"):
                    return self._static(path)

                if path == "/api/status":
                    return self._json(self._status())
                if path == "/api/summary":
                    return self._json(_summary(ctx, params))
                if path == "/api/rules":
                    return self._json({"ok": True, "rules": ctx.store.rules(False)})
                if path == "/api/labels":
                    return self._json(self._labels())
                if path == "/api/export.csv":
                    return self._export(params)
                return self._error(404, f"unknown endpoint: {path}")
            except BrokenPipeError:
                return
            except Exception as exc:  # a bad query should not take the server down
                return self._error(500, f"{type(exc).__name__}: {exc}")

        do_HEAD = do_GET

        def _status(self) -> dict[str, Any]:
            window = analytics.resolve_range("today")
            blocks = analytics.build_blocks(
                ctx.store, ctx.cfg, window["start_ts"], window["end_ts"]
            )
            today_total = sum(b["seconds"] for b in blocks)
            return {
                "ok": True,
                "version": "1.0.0",
                "server_uptime_seconds": round(time.time() - ctx.started_at, 1),
                "requests": ctx.requests,
                "today_seconds": round(today_total, 1),
                "watcher": ctx.watcher.status() if ctx.watcher else {"running": False},
                "browser": ctx.ingest.status() if ctx.ingest else {"connected": False},
                "database": ctx.store.stats(),
                "config": {
                    "port": ctx.cfg.port,
                    "sample_interval_seconds": ctx.cfg.sample_interval,
                    "idle_threshold_seconds": ctx.cfg.idle_threshold,
                    "capture_window_titles": ctx.cfg.capture_titles,
                },
            }

        def _labels(self) -> dict[str, Any]:
            clients: set[str] = set()
            categories: set[str] = set()
            projects: set[str] = set()
            for rule in ctx.store.rules(False):
                if rule.get("client"):
                    clients.add(rule["client"])
                if rule.get("category"):
                    categories.add(rule["category"])
                if rule.get("project"):
                    projects.add(rule["project"])
            return {
                "ok": True,
                "clients": sorted(clients),
                "categories": sorted(categories),
                "projects": sorted(projects),
            }

        def _export(self, params: dict[str, list[str]]) -> None:
            window = analytics.resolve_range(
                (params.get("range") or ["week"])[0],
                (params.get("from") or [None])[0],
                (params.get("to") or [None])[0],
            )
            blocks = analytics.build_blocks(
                ctx.store, ctx.cfg, window["start_ts"], window["end_ts"]
            )
            buffer = io.StringIO()
            writer = csv.writer(buffer)
            for row in analytics.csv_rows(blocks):
                writer.writerow(row)
            name = f"time-{window['start_date']}-to-{window['end_date']}.csv"
            self._send(
                200,
                buffer.getvalue().encode("utf-8"),
                "text/csv; charset=utf-8",
                {"Content-Disposition": f'attachment; filename="{name}"'},
            )

        # -- POST --------------------------------------------------------

        def do_OPTIONS(self) -> None:  # noqa: N802
            self._send(204, b"", "text/plain", self._cors())

        def do_POST(self) -> None:  # noqa: N802
            ctx.requests += 1
            path = urlsplit(self.path).path
            try:
                if path == "/api/ingest/chrome":
                    return self._ingest()
                if path == "/api/rules":
                    return self._create_rule()
                if path == "/api/label":
                    return self._label_block()
                match = RULE_TOGGLE_PATH.match(path)
                if match:
                    return self._toggle_rule(int(match.group(1)))
                return self._error(404, f"unknown endpoint: {path}")
            except BrokenPipeError:
                return
            except Exception as exc:
                return self._error(500, f"{type(exc).__name__}: {exc}")

        def _ingest(self) -> None:
            if not self._extension_origin():
                return self._error(403, "only a browser extension may post here")
            if ctx.ingest is None:
                return self._error(503, "ingest is not running")
            payload = self._body()
            if not payload:
                return self._error(400, "expected a JSON object")
            result = ctx.ingest.heartbeat(payload)
            body = json.dumps(result).encode("utf-8")
            self._send(200, body, "application/json; charset=utf-8", self._cors())

        def _create_rule(self) -> None:
            payload = self._body()
            if not any(
                payload.get(f"match_{field}") for field in rules_mod.FIELDS
            ):
                return self._error(400, "a rule needs at least one match_* pattern")
            if not (
                payload.get("client")
                or payload.get("project")
                or payload.get("category")
            ):
                return self._error(400, "a rule needs a client, project or category")
            probe = rules_mod.Rule({**payload, "id": 0})
            if probe.error:
                return self._error(400, f"bad pattern: {probe.error}")
            rule_id = ctx.store.add_rule(payload)
            self._json({"ok": True, "id": rule_id})

        def _label_block(self) -> None:
            payload = self._body()
            signature = payload.get("signature") or {}
            if not isinstance(signature, dict):
                return self._error(400, "signature must be an object")
            try:
                rule = rules_mod.rule_from_signature(
                    signature,
                    client=payload.get("client"),
                    project=payload.get("project"),
                    category=payload.get("category"),
                    scope=str(payload.get("scope") or "auto"),
                    priority=int(payload.get("priority") or 20),
                )
            except ValueError as exc:
                return self._error(400, str(exc))
            if not (rule["client"] or rule["project"] or rule["category"]):
                return self._error(400, "nothing to label it with")
            rule_id = ctx.store.add_rule(rule)
            self._json({"ok": True, "id": rule_id, "rule": rule})

        def _toggle_rule(self, rule_id: int) -> None:
            payload = self._body()
            ctx.store.set_rule_enabled(rule_id, bool(payload.get("enabled", True)))
            self._json({"ok": True, "id": rule_id})

        # -- DELETE ------------------------------------------------------

        def do_DELETE(self) -> None:  # noqa: N802
            ctx.requests += 1
            path = urlsplit(self.path).path
            match = RULE_ID_PATH.match(path)
            if not match:
                return self._error(404, f"unknown endpoint: {path}")
            ctx.store.delete_rule(int(match.group(1)))
            self._json({"ok": True})

    return Handler


def serve(ctx: Context) -> ThreadingHTTPServer:
    handler = make_handler(ctx)
    httpd = ThreadingHTTPServer((ctx.cfg.host, ctx.cfg.port), handler)
    httpd.daemon_threads = True
    return httpd
