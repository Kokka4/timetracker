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

from . import analytics, pause as pause_mod, rules as rules_mod, taxonomy

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
CATEGORY_ID_PATH = re.compile(r"^/api/categories/(\d+)$")
CLIENT_ID_PATH = re.compile(r"^/api/clients/(\d+)$")
PACK_PATH = re.compile(r"^/api/packs/([a-z0-9_-]+)$")


class Context:
    def __init__(self, cfg, store, watcher=None, ingest=None, pause=None):
        self.cfg = cfg
        self.store = store
        self.watcher = watcher
        self.ingest = ingest
        self.pause = pause
        self.started_at = time.time()
        self.requests = 0

    def pause_state(self) -> dict[str, Any]:
        if self.pause is None:
            return {"paused": False, "available": False}
        return {**self.pause.state(), "available": True}


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

        def _json(
            self,
            payload: Any,
            status: int = 200,
            extra: dict[str, str] | None = None,
        ) -> None:
            body = json.dumps(payload, default=str).encode("utf-8")
            self._send(status, body, extra=extra)

        def _error(self, status: int, message: str) -> None:
            self._json({"ok": False, "error": message}, status=status)

        def _drain_body(self) -> None:
            """Take the request body off the socket, whoever ends up using it.

            This server speaks HTTP/1.1, so connections are reused. A handler
            that ignores its body leaves those bytes in the stream, and the
            next request on that connection is then parsed starting from them:
            the client gets a 501 for a method called `{}POST` and every
            subsequent request on the connection is lost. Draining centrally,
            before dispatch, is what makes that impossible to reintroduce by
            adding an endpoint that happens not to care about its input.
            """
            self._raw_body = b""
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                return
            if length <= 0:
                return
            if length <= MAX_BODY:
                self._raw_body = self.rfile.read(length)
                return
            # Too big to parse, but it still has to come off the wire.
            remaining = length
            while remaining > 0:
                chunk = self.rfile.read(min(65536, remaining))
                if not chunk:
                    break
                remaining -= len(chunk)

        def _body(self) -> dict[str, Any]:
            raw = getattr(self, "_raw_body", b"")
            if not raw:
                return {}
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

        def _control_origin(self) -> bool:
            """Who may work the off switch.

            Wider than `_extension_origin` because the dashboard is served
            from this same port and so posts with an `http://` origin, which
            the ingest rule exists to reject. Still narrow enough that a page
            you happen to have open cannot switch your tracker off behind your
            back.
            """
            origin = self.headers.get("Origin")
            if not origin:
                return True
            if origin.startswith(EXTENSION_ORIGINS):
                return True
            return origin in (
                f"http://{ctx.cfg.host}:{ctx.cfg.port}",
                f"http://127.0.0.1:{ctx.cfg.port}",
                f"http://localhost:{ctx.cfg.port}",
            )

        def _cors(self) -> dict[str, str]:
            origin = self.headers.get("Origin")
            if origin and origin.startswith(EXTENSION_ORIGINS):
                return {
                    "Access-Control-Allow-Origin": origin,
                    "Access-Control-Allow-Headers": "Content-Type",
                    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
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
                if path == "/api/pause":
                    # The extension polls this to keep its badge honest, so it
                    # needs the CORS headers that the read API otherwise has
                    # no use for.
                    return self._json(
                        {"ok": True, "pause": ctx.pause_state()}, extra=self._cors()
                    )
                if path == "/api/summary":
                    return self._json(_summary(ctx, params))
                if path == "/api/rules":
                    return self._json({"ok": True, "rules": ctx.store.rules(False)})
                if path == "/api/taxonomy":
                    return self._json(self._taxonomy())
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
                "pause": ctx.pause_state(),
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

        def _taxonomy(self) -> dict[str, Any]:
            return {
                "ok": True,
                "categories": ctx.store.categories(),
                "clients": ctx.store.clients(),
                "packs": taxonomy.pack_list(ctx.store),
                "palette": list(taxonomy.SLOTS),
                "in_use": sorted(ctx.store.categories_in_use()),
            }

        def _labels(self) -> dict[str, Any]:
            """The pickable names.

            Sourced from the registries rather than from whatever the rules
            happen to mention, which is what lets you create a category and
            then use it, instead of only the other way round. Names found only
            in rules are still included, so a database mid-upgrade never
            offers less than it did before.
            """
            categories = [c["name"] for c in ctx.store.categories()]
            clients = [c["name"] for c in ctx.store.clients() if not c["archived"]]
            seen_categories = {name.casefold() for name in categories}
            seen_clients = {name.casefold() for name in clients}
            projects: set[str] = set()

            for rule in ctx.store.rules(False):
                if rule.get("category") and rule["category"].casefold() not in seen_categories:
                    categories.append(rule["category"])
                    seen_categories.add(rule["category"].casefold())
                if rule.get("client") and rule["client"].casefold() not in seen_clients:
                    clients.append(rule["client"])
                    seen_clients.add(rule["client"].casefold())
                if rule.get("project"):
                    projects.add(rule["project"])

            return {
                "ok": True,
                "clients": sorted(clients, key=str.casefold),
                "categories": categories,
                "projects": sorted(projects),
                "colors": {
                    c["name"]: c["color"] for c in ctx.store.categories() if c["color"]
                },
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
            self._drain_body()
            try:
                if path == "/api/ingest/chrome":
                    return self._ingest()
                if path == "/api/pause":
                    return self._pause()
                if path == "/api/resume":
                    return self._resume()
                if path == "/api/rules":
                    return self._create_rule()
                if path == "/api/label":
                    return self._label_block()
                if path == "/api/categories":
                    return self._create_named("category")
                if path == "/api/clients":
                    return self._create_named("client")
                match = RULE_TOGGLE_PATH.match(path)
                if match:
                    return self._toggle_rule(int(match.group(1)))
                match = CATEGORY_ID_PATH.match(path)
                if match:
                    return self._update_named("category", int(match.group(1)))
                match = CLIENT_ID_PATH.match(path)
                if match:
                    return self._update_named("client", int(match.group(1)))
                match = PACK_PATH.match(path)
                if match:
                    return self._pack(match.group(1))
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

            # The gate that actually enforces the off switch for the browser
            # half. The extension stops sending of its own accord, but that
            # depends on it having noticed, and an extension that has not
            # noticed yet must not be able to write through.
            state = ctx.pause_state()
            if state.get("paused"):
                result = {"ok": True, "state": "paused", "pause": state}
            else:
                result = ctx.ingest.heartbeat(payload)
                result["pause"] = state

            body = json.dumps(result, default=str).encode("utf-8")
            self._send(200, body, "application/json; charset=utf-8", self._cors())

        def _pause(self) -> None:
            if not self._control_origin():
                return self._error(403, "not allowed to change the tracker state")
            if ctx.pause is None:
                return self._error(503, "the pause switch is not available")
            try:
                minutes = pause_mod.parse_request(self._body())
            except ValueError as exc:
                return self._error(400, str(exc))
            state = ctx.pause.pause(minutes)
            kind = "indefinitely" if minutes is None else f"for {minutes:g} min"
            print(f"[pause] tracking paused {kind}", flush=True)
            self._json({"ok": True, "pause": state}, extra=self._cors())

        def _resume(self) -> None:
            if not self._control_origin():
                return self._error(403, "not allowed to change the tracker state")
            if ctx.pause is None:
                return self._error(503, "the pause switch is not available")
            state = ctx.pause.resume()
            print("[pause] tracking resumed", flush=True)
            self._json({"ok": True, "pause": state}, extra=self._cors())

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

            # A name typed into the review panel becomes a managed record
            # right here. Without this, a category would exist only inside
            # the rule that mentions it and could not be recoloured, renamed
            # or reused, which is the whole thing this release is about.
            created: dict[str, str] = {}
            if rule.get("category") and not ctx.store.category_named(rule["category"]):
                ctx.store.add_category(
                    rule["category"], color=taxonomy.slot_for(rule["category"])
                )
                created["category"] = rule["category"]
            if rule.get("client") and not ctx.store.client_named(rule["client"]):
                ctx.store.add_client(rule["client"])
                created["client"] = rule["client"]

            self._json({"ok": True, "id": rule_id, "rule": rule, "created": created})

        def _toggle_rule(self, rule_id: int) -> None:
            payload = self._body()
            ctx.store.set_rule_enabled(rule_id, bool(payload.get("enabled", True)))
            self._json({"ok": True, "id": rule_id})

        # -- the taxonomy ------------------------------------------------
        # Categories and clients differ only in which columns they carry, so
        # they share these three handlers rather than six near-identical ones.

        def _create_named(self, kind: str) -> None:
            payload = self._body()
            name = str(payload.get("name") or "").strip()
            if not name:
                return self._error(400, f"a {kind} needs a name")
            if len(name) > 60:
                return self._error(400, "that name is too long (60 characters)")
            color = payload.get("color") or None
            if color and color not in taxonomy.SLOTS:
                return self._error(
                    400, f"colour must be one of {', '.join(taxonomy.SLOTS)}"
                )
            try:
                if kind == "category":
                    new_id = ctx.store.add_category(
                        name,
                        color=color or taxonomy.slot_for(name),
                        sort_order=int(payload.get("sort_order") or 500),
                    )
                else:
                    new_id = ctx.store.add_client(name, color=color)
            except ValueError as exc:
                return self._error(400, str(exc))
            self._json({"ok": True, "id": new_id, "name": name})

        def _update_named(self, kind: str, record_id: int) -> None:
            payload = self._body()
            if payload.get("delete"):
                result = (
                    ctx.store.delete_category(record_id)
                    if kind == "category"
                    else ctx.store.delete_client(record_id)
                )
                if not result.get("deleted"):
                    return self._error(404, f"no such {kind}: {record_id}")
                return self._json({"ok": True, **result})

            color = payload.get("color")
            if color and color not in taxonomy.SLOTS:
                return self._error(
                    400, f"colour must be one of {', '.join(taxonomy.SLOTS)}"
                )
            try:
                if kind == "category":
                    row = ctx.store.update_category(
                        record_id,
                        name=payload.get("name"),
                        color=color,
                        sort_order=payload.get("sort_order"),
                    )
                else:
                    row = ctx.store.update_client(
                        record_id,
                        name=payload.get("name"),
                        color=color,
                        archived=payload.get("archived"),
                    )
            except ValueError as exc:
                return self._error(409, str(exc))
            if row is None:
                return self._error(404, f"no such {kind}: {record_id}")
            self._json({"ok": True, kind: row})

        def _pack(self, pack_id: str) -> None:
            payload = self._body()
            wants = payload.get("apply")
            try:
                result = (
                    taxonomy.remove_pack(ctx.store, pack_id)
                    if wants is False
                    else taxonomy.apply_pack(ctx.store, pack_id)
                )
            except ValueError as exc:
                return self._error(404, str(exc))
            self._json({"ok": True, **result, "packs": taxonomy.pack_list(ctx.store)})

        # -- DELETE ------------------------------------------------------

        def do_DELETE(self) -> None:  # noqa: N802
            ctx.requests += 1
            path = urlsplit(self.path).path
            self._drain_body()
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
