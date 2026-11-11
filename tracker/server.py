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

from . import analytics, pause as pause_mod, report as report_mod, rules as rules_mod, taxonomy

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
        (params.get("range") or [None])[0],
        (params.get("from") or [None])[0],
        (params.get("to") or [None])[0],
    )
    blocks = analytics.build_blocks(
        ctx.store, ctx.cfg, window["start_ts"], window["end_ts"]
    )
    afk = ctx.store.afk_rows(window["start_ts"], window["end_ts"])
    return analytics.summarize(
        blocks, afk, window, review_min_seconds=ctx.cfg.review_min
    )


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
            if origin in (
                f"http://{ctx.cfg.host}:{ctx.cfg.port}",
                f"http://127.0.0.1:{ctx.cfg.port}",
                f"http://localhost:{ctx.cfg.port}",
            ):
                return True
            # Anything under `.localhost` is reserved by RFC 6761 and resolved
            # to the loopback address by the browser itself, with no hosts
            # file and no DNS. That makes `http://time.localhost:8734` a nicer
            # bookmark than an IP address, and it can only ever reach the
            # machine it was typed on, so it is as safe as 127.0.0.1 is.
            try:
                parts = urlsplit(origin)
            except ValueError:
                return False
            return (
                parts.scheme == "http"
                and (parts.hostname or "").endswith(".localhost")
                and parts.port == ctx.cfg.port
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
                    return self._json({
                        "ok": True,
                        "rules": ctx.store.rules(False),
                        # Rules carrying no pattern match nothing and look
                        # exactly like rules nothing has reached yet.
                        "dead": len(ctx.store.dead_rules()),
                    })
                if path == "/api/taxonomy":
                    return self._json(self._taxonomy())
                if path == "/api/labels":
                    return self._json(self._labels())
                if path == "/api/removable":
                    return self._removable(params)
                if path == "/api/blocks":
                    return self._blocks(params)
                if path == "/api/rule-preview":
                    return self._rule_preview(params)
                if path == "/api/export.csv":
                    return self._export(params)
                if path == "/api/report.html":
                    return self._report(params)
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
                # Kept on the machine, not in the browser: the greeting is
                # about this install, so it should not reappear because you
                # opened a different browser, and should appear exactly once
                # on a colleague's Mac after you set it up for them.
                "first_run": ctx.store.get_meta("welcomed") is None,
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
                (params.get("range") or [None])[0],
                (params.get("from") or [None])[0],
                (params.get("to") or [None])[0],
                default="week",
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

        def _report(self, params: dict[str, list[str]]) -> None:
            """One self-contained HTML file: the PDF path runs through the
            browser's own print engine, which is already excellent and
            already installed."""
            window = analytics.resolve_range(
                (params.get("range") or [None])[0],
                (params.get("from") or [None])[0],
                (params.get("to") or [None])[0],
                default="week",
            )
            blocks = analytics.build_blocks(
                ctx.store, ctx.cfg, window["start_ts"], window["end_ts"]
            )
            summary = analytics.summarize(
                blocks,
                ctx.store.afk_rows(window["start_ts"], window["end_ts"]),
                window,
                review_min_seconds=ctx.cfg.review_min,
            )
            # The dashboard's own colours, so a printed report and the screen
            # it came from do not disagree about which client is which.
            colours: dict[str, str] = {}
            for row in ctx.store.categories() + ctx.store.clients():
                slot = row.get("color")
                if slot and slot.startswith("s") and slot[1:].isdigit():
                    index = int(slot[1:]) - 1
                    if 0 <= index < len(report_mod.SLOTS):
                        colours[row["name"]] = report_mod.SLOTS[index]

            detail = None
            if (params.get("detail") or ["0"])[0] in ("1", "true", "yes"):
                detail = [b for b in blocks if b["seconds"] >= 60][:2000]

            page = report_mod.render(summary, window, colours, detail)
            name = f"time-report-{window['start_date']}-to-{window['end_date']}.html"
            disposition = "attachment" if (
                params.get("download") or ["0"])[0] in ("1", "true", "yes") else "inline"
            self._send(
                200,
                page.encode("utf-8"),
                "text/html; charset=utf-8",
                {"Content-Disposition": f'{disposition}; filename="{name}"'},
            )

        # -- POST --------------------------------------------------------

        def do_OPTIONS(self) -> None:  # noqa: N802
            self._send(204, b"", "text/plain", self._cors())

        def do_POST(self) -> None:  # noqa: N802
            ctx.requests += 1
            path = urlsplit(self.path).path
            self._drain_body()

            # Every write, not just the ones that felt dangerous.
            #
            # A page you have open cannot READ anything here: no CORS header
            # is granted to an http(s) origin, so the browser refuses to hand
            # it the response. Writing is a different matter. A cross-origin
            # POST carrying `text/plain` is a "simple request" and skips the
            # preflight entirely, and this server parses the body as JSON
            # whatever the content type claims. Without this check, any site
            # could quietly create rules or delete your categories while you
            # read it. It could not learn a thing, but it could make a mess.
            if not self._control_origin():
                return self._error(403, "not allowed to change the tracker")
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
                if path == "/api/welcome":
                    ctx.store.set_meta("welcomed", str(int(time.time())))
                    return self._json({"ok": True})
                if path == "/api/delete":
                    return self._delete_time()
                if path == "/api/rules/dead":
                    removed = ctx.store.delete_dead_rules()
                    return self._json({"ok": True, "removed": removed})
                if path == "/api/assign":
                    return self._assign()
                if path == "/api/unassign":
                    return self._assign(clearing=True)
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
                payload.get(f"match_{field}")
                for field in rules_mod.FIELDS + (rules_mod.ANY_FIELD,)
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

        def _rule_preview(self, params: dict[str, list[str]]) -> None:
            """What a rule would claim, before it exists.

            A rule rewrites the whole history the instant it is saved,
            because classification is computed when you look. That is the
            best thing about this design and the most alarming: a keyword
            that is one letter too short quietly reassigns a month. So the
            form shows the answer first, measured against what is actually
            recorded, with real examples rather than a count on its own.
            """
            one = lambda k, d=None: (params.get(k) or [d])[0]  # noqa: E731
            draft = {
                "id": 0,
                "priority": 20,
                "match_mode": one("mode", "text"),
                "client": one("client"),
                "category": one("category"),
            }
            for field in rules_mod.FIELDS + (rules_mod.ANY_FIELD,):
                value = one(f"match_{field}")
                if value:
                    draft[f"match_{field}"] = value

            probe = rules_mod.Rule(draft)
            if probe.error:
                return self._json({"ok": False, "error": probe.error})
            if not probe.patterns and probe.anywhere is None:
                return self._json({"ok": True, "seconds": 0, "blocks": 0,
                                   "examples": [], "empty": True})

            window = analytics.resolve_range(one("range", "month"))
            blocks = analytics.build_blocks(
                ctx.store, ctx.cfg, window["start_ts"], window["end_ts"]
            )

            seconds = 0.0
            hit = 0
            taken: dict[str, float] = {}
            examples: list[dict[str, Any]] = []
            for block in blocks:
                signature = {
                    "app": block["app"], "title": block["title"],
                    "domain": block["domain"], "url": block["url"],
                }
                if not probe.matches(signature):
                    continue
                hit += 1
                seconds += block["seconds"]
                # What it would take from somebody else. A keyword that
                # claims time already attributed is the mistake worth seeing.
                if block["client"] and block["client"] != draft.get("client"):
                    taken[block["client"]] = taken.get(block["client"], 0.0) + block["seconds"]
                if len(examples) < 6:
                    examples.append({
                        "when": block["start"],
                        "seconds": block["seconds"],
                        "what": block["domain"] or block["app"],
                        "title": block["title"],
                        "client": block["client"],
                        "category": block["category"],
                    })

            total = sum(b["seconds"] for b in blocks) or 1.0
            return self._json({
                "ok": True,
                "range": window["name"],
                "seconds": seconds,
                "blocks": hit,
                "share": seconds / total,
                "examples": examples,
                "taken_from": [
                    {"client": k, "seconds": v}
                    for k, v in sorted(taken.items(), key=lambda kv: -kv[1])[:4]
                ],
            })

        # -- assigning a stretch of time ---------------------------------

        def _assign(self, clearing: bool = False) -> None:
            payload = self._body()
            window = self._delete_window(payload.get("start"), payload.get("end"))
            if window is None:
                return
            start, end = window

            if clearing:
                removed = ctx.store.clear_assignments(start, end)
                return self._json({"ok": True, "cleared": removed})

            client = (payload.get("client") or "").strip() or None
            category = (payload.get("category") or "").strip() or None
            if not client and not category:
                return self._error(400, "nothing to assign it to")

            # A name typed here becomes a managed record, exactly as it does
            # when it is typed into the review panel. Otherwise a client
            # could exist only inside an assignment and never be renameable.
            created: dict[str, str] = {}
            if category and not ctx.store.category_named(category):
                ctx.store.add_category(category, color=taxonomy.slot_for(category))
                created["category"] = category
            if client and not ctx.store.client_named(client):
                ctx.store.add_client(client)
                created["client"] = client

            assignment_id = ctx.store.add_assignment(
                start, end, client=client, category=category
            )
            return self._json({
                "ok": True,
                "id": assignment_id,
                "start": start,
                "end": end,
                "client": client,
                "category": category,
                "created": created,
            })

        def _blocks(self, params: dict[str, list[str]]) -> None:
            """Every block in a window, for the day page.

            The strip draws one rectangle per block and a real day has
            hundreds, most of them a pixel wide. This is the same data as a
            list, which is the only form in which it can be read or acted
            on.
            """
            window = analytics.resolve_range(
                (params.get("range") or [None])[0],
                (params.get("from") or [None])[0],
                (params.get("to") or [None])[0],
            )
            blocks = analytics.build_blocks(
                ctx.store, ctx.cfg, window["start_ts"], window["end_ts"]
            )
            try:
                floor = float((params.get("min") or ["0"])[0])
            except ValueError:
                floor = 0.0
            kept = [b for b in blocks if b["seconds"] >= floor]
            return self._json({
                "ok": True,
                "window": window,
                "total": len(blocks),
                "shown": len(kept),
                "blocks": [
                    {
                        k: b[k] for k in (
                            "start", "end", "seconds", "app", "title", "domain",
                            "url", "client", "category", "project", "is_browser",
                            "assigned", "assignment_id",
                        )
                    }
                    for b in kept
                ],
            })

        # -- removing time -----------------------------------------------

        def _delete_window(self, start_raw, end_raw) -> tuple[float, float] | None:
            """Sanity-check a window, or send the error and return None.

            Takes the two raw values rather than a container, because a query
            string hands them over as one-element lists and a JSON body hands
            them over bare, and a helper that tries to tell those apart by
            inspecting the container is a helper that silently picks wrong.
            """
            try:
                start = float(start_raw)
                end = float(end_raw)
            except (TypeError, ValueError):
                self._error(400, "start and end must be unix timestamps")
                return None
            if not (start < end):
                self._error(400, "the window must end after it starts")
                return None
            # A window reaching into the future would delete time that has
            # not happened, and would race the watcher for the block it is
            # recording right now.
            end = min(end, time.time())
            if not (start < end):
                self._error(400, "that window is entirely in the future")
                return None
            return start, end

        def _removable(self, params: dict[str, list[str]]) -> None:
            """What a delete would take, described the way the page describes
            everything else, so the preview and the dashboard agree."""
            window = self._delete_window(
                (params.get("start") or [None])[0],
                (params.get("end") or [None])[0],
            )
            if window is None:
                return
            start, end = window
            blocks = analytics.build_blocks(ctx.store, ctx.cfg, start, end)
            groups: dict[str, float] = {}
            for block in blocks:
                label = analytics._display_label(block)
                groups[label] = groups.get(label, 0.0) + block["seconds"]
            top = sorted(groups.items(), key=lambda kv: -kv[1])[:8]
            # Summed from the blocks, not from the rows. A browser event sits
            # inside the desktop event for the browser that was frontmost, so
            # adding the two tables counts that stretch twice and the preview
            # would promise to remove twice the time the day shows.
            return self._json({
                "ok": True,
                "start": start,
                "end": end,
                "seconds": sum(b["seconds"] for b in blocks),
                "blocks": len(blocks),
                "top": [{"label": k, "seconds": v} for k, v in top],
            })

        def _delete_time(self) -> None:
            payload = self._body()
            window = self._delete_window(payload.get("start"), payload.get("end"))
            if window is None:
                return
            start, end = window

            # Settle the recording before editing it. The open block is a row
            # in the database, so trimming it and leaving the watcher holding
            # its id would see the next tick push it straight back.
            if ctx.watcher is not None:
                end = min(end, ctx.watcher.flush())
            elif ctx.ingest is not None:
                ctx.ingest.close_all()
            if not (start < end):
                return self._error(400, "nothing in that window to remove")

            # Measured the same way the preview measured it, so the figure
            # reported back matches the one that was agreed to.
            blocks = analytics.build_blocks(ctx.store, ctx.cfg, start, end)
            shown = sum(b["seconds"] for b in blocks)
            backup = ctx.store.backup_before_delete()
            result = ctx.store.delete_range(start, end)
            result["seconds"] = shown
            print(
                f"[delete] removed {result['seconds'] / 60:.1f} min"
                f" between {start:.0f} and {end:.0f}"
                f" ({result['deleted']} dropped, {result['clipped']} trimmed,"
                f" {result['split']} split)",
                flush=True,
            )
            return self._json({
                "ok": True,
                **result,
                "start": start,
                "end": end,
                "backup": str(backup) if backup else None,
            })

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

            if payload.get("unassign"):
                # The undo for a bulk mislabel: the name survives, every rule
                # that was assigning it lets go.
                result = (
                    ctx.store.unassign_category(record_id)
                    if kind == "category"
                    else ctx.store.unassign_client(record_id)
                )
                if not result.get("ok"):
                    return self._error(404, f"no such {kind}: {record_id}")
                print(
                    f"[taxonomy] {kind} {result['name']!r} cleared from "
                    f"{result['rules_cleared']} rules",
                    flush=True,
                )
                return self._json({"ok": True, **result})

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
            if not self._control_origin():
                return self._error(403, "not allowed to change the tracker")
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
