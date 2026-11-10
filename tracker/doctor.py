"""Self-diagnosis.

The macOS probes cannot be tested from anywhere but your own Mac, so this is
how you find out what is actually working. Run it after install, and again
after granting a permission.

    python3 -m tracker doctor
"""

from __future__ import annotations

import json
import os
import platform
import shutil
import socket
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from . import config, db, macos

OK = "  ok  "
WARN = " warn "
FAIL = " fail "
INFO = " info "

LAUNCH_LABEL = "ai.leadprinter.timetracker"


def _line(state: str, title: str, detail: str = "") -> None:
    print(f"[{state}] {title}" + (f"\n         {detail}" if detail else ""))


def _port_open(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(1.0)
        return sock.connect_ex((host, port)) == 0


def _fetch_status(host: str, port: int) -> dict[str, Any] | None:
    from urllib.error import URLError
    from urllib.request import urlopen

    try:
        with urlopen(f"http://{host}:{port}/api/status", timeout=3) as response:
            return json.loads(response.read().decode("utf-8"))
    except (URLError, OSError, ValueError):
        return None


def _age(ts: float | None) -> str:
    if not ts:
        return "never"
    delta = max(0.0, time.time() - ts)
    if delta < 90:
        return f"{delta:.0f}s ago"
    if delta < 5400:
        return f"{delta / 60:.0f}m ago"
    return f"{delta / 3600:.1f}h ago"


def _human(seconds: float) -> str:
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}s"
    hours, rest = divmod(seconds, 3600)
    minutes = rest // 60
    return f"{hours}h {minutes:02d}m" if hours else f"{minutes}m"


def probe(seconds: int = 20) -> int:
    """Show what the probes see, once a second, while you switch apps.

    This answers the one question a static check cannot: does the frontmost-app
    probe actually *follow* your focus, or is it returning a stale value? A
    launchd agent runs outside your login session's usual context, and that is
    where this breaks when it breaks.
    """
    print()
    print("  Switch between apps while this runs — Chrome, Terminal, anything.")
    print("  Each line is one sample. The app column must change when you do.")
    print(f"  pyobjc installed: {macos.HAVE_PYOBJC}")
    print()
    print(
        f"  {'time':8} {'idle':>5}  {'osascript':20} {'lsappinfo':20} "
        f"{'pyobjc':20} title"
    )
    print(f"  {'-' * 8} {'-' * 5}  {'-' * 20} {'-' * 20} {'-' * 20} {'-' * 24}")

    seen: dict[str, int] = {}
    per_source: dict[str, set[str]] = {"osascript": set(), "lsappinfo": set(), "pyobjc": set()}
    denied = False
    sources_used: dict[str, int] = {}

    for _ in range(seconds):
        started = time.monotonic()
        p = macos.probe_all()
        took = time.monotonic() - started

        if not p["osascript_allowed"]:
            denied = True
        chosen = p["chosen"] or "(none)"
        seen[chosen] = seen.get(chosen, 0) + 1
        src = p["source"] or "(none)"
        sources_used[src] = sources_used.get(src, 0) + 1
        for key in per_source:
            if p.get(key):
                per_source[key].add(p[key])

        def cell(value: Any) -> str:
            return (str(value) if value else "-")[:20]

        slow = f"  [{took:.1f}s]" if took > 1.0 else ""
        print(
            f"  {datetime.now().strftime('%H:%M:%S')} {p['idle']:5.1f}  "
            f"{cell(p['osascript']):20} {cell(p['lsappinfo']):20} "
            f"{cell(p['pyobjc']):20} {(p['osascript_title'] or '')[:24]}{slow}"
        )
        time.sleep(max(0.0, 1.0 - took))

    print()
    for key, values in per_source.items():
        if not values:
            print(f"  {key:12} never answered")
        else:
            verdict = "STUCK" if len(values) == 1 else f"{len(values)} apps"
            print(f"  {key:12} {verdict:10} {', '.join(sorted(values))[:70]}")
    print()
    print(f"  source actually used: {', '.join(f'{k} x{v}' for k, v in sources_used.items())}")
    print(f"  apps recorded: {len(seen)} — {', '.join(sorted(seen))}")
    print()

    live = {k: v for k, v in per_source.items() if len(v) > 1}
    if len(seen) <= 1:
        if live:
            _line(
                FAIL,
                "the chosen source is stuck, but another one is working",
                f"{', '.join(live)} followed your focus. The tracker is using the\n"
                "         wrong source — send me this output and I will reorder it.",
            )
        else:
            _line(
                FAIL,
                "no source followed your focus",
                "If you did switch apps during that run, every minute of your day\n"
                "         would be credited to one app. Do not trust the dashboard\n"
                "         numbers until this passes.",
            )
        return 1

    _line(OK, "the probe follows your focus", f"{len(seen)} different apps seen")
    if denied:
        _line(WARN, "window titles are not permitted", "app-level tracking still works")
    return 0


def run() -> int:
    cfg = config.load()
    problems = 0

    print("=" * 66)
    print(" Local time tracker — diagnostic")
    print("=" * 66)

    # -- host ----------------------------------------------------------
    print("\nHOST")
    _line(INFO, f"{platform.system()} {platform.mac_ver()[0] or platform.release()} ({platform.machine()})")
    _line(INFO, f"python {sys.version.split()[0]}", sys.executable)

    if platform.system() != "Darwin":
        _line(FAIL, "not macOS", "the watcher probes are macOS-only")
        problems += 1

    # -- probe layer ---------------------------------------------------
    print("\nPROBES")
    if macos.HAVE_PYOBJC:
        _line(OK, "pyobjc available", "app and idle probes run in-process")
    else:
        _line(
            INFO,
            "pyobjc not installed (optional)",
            "falling back to lsappinfo + ioreg, which spawn a few short-lived\n"
            "         processes per sample. To use the lighter path:\n"
            f"         {sys.executable} -m pip install pyobjc-framework-Cocoa pyobjc-framework-Quartz",
        )

    for name, path in (("lsappinfo", macos.LSAPPINFO), ("ioreg", macos.IOREG), ("osascript", macos.OSASCRIPT)):
        if Path(path).exists() or shutil.which(name):
            _line(OK, f"{name} present")
        else:
            _line(FAIL, f"{name} missing at {path}")
            problems += 1

    app, bundle = macos.front_app()
    if app:
        _line(OK, "frontmost app detected", f"{app}  ({bundle or 'no bundle id'})")
    else:
        _line(FAIL, "cannot detect the frontmost app", "app-level tracking will not work")
        problems += 1

    idle = macos.idle_seconds()
    _line(OK, "idle detection working", f"last input {idle:.1f}s ago")
    if idle == 0.0:
        _line(
            WARN,
            "idle reads exactly 0.0",
            "that is normal if you just typed; rerun after a few idle seconds",
        )

    title_app, title, allowed = macos.window_title()
    if allowed and title:
        _line(OK, "window titles working", f"{title_app}: {title!r}")
    elif allowed:
        _line(
            WARN,
            "window titles permitted but empty",
            "the frontmost app has no window right now, which is fine",
        )
    else:
        _line(
            WARN,
            "window titles blocked (Accessibility not granted)",
            "App-level tracking still works. To capture which document, repo or\n"
            "         window you were in, open\n"
            "           System Settings -> Privacy & Security -> Accessibility\n"
            "         press +, then Cmd-Shift-G and paste this exact path:\n"
            f"           {sys.executable}\n"
            "         Then restart the tracker. Chrome tabs do not need this —\n"
            "         they come from the extension.",
        )
        if macos.title_error():
            _line(INFO, "osascript said", macos.title_error()[:300])

    _line(INFO, f"screen locked: {macos.is_locked(app, bundle)}")

    # -- storage -------------------------------------------------------
    print("\nSTORAGE")
    if cfg.db_path.exists():
        store = db.Store(cfg.db_path)
        stats = store.stats()
        _line(
            OK,
            f"database at {cfg.db_path}",
            f"{stats['db_bytes'] / 1_048_576:.1f} MB · "
            f"{stats['desktop_events']} desktop · {stats['browser_events']} browser · "
            f"{stats['rules']} rules",
        )
        _line(INFO, f"last desktop event: {_age(stats['last_desktop_event'])}")
        _line(INFO, f"last browser event: {_age(stats['last_browser_event'])}")
        if stats["desktop_events"] == 0:
            _line(WARN, "no desktop events recorded yet", "is the tracker running?")
    else:
        _line(WARN, "no database yet", f"expected at {cfg.db_path}")

    # -- service -------------------------------------------------------
    print("\nSERVICE")
    uid = os.getuid()
    result = subprocess.run(
        ["launchctl", "print", f"gui/{uid}/{LAUNCH_LABEL}"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode == 0:
        state = "unknown"
        for raw in result.stdout.splitlines():
            if "state =" in raw:
                state = raw.split("=", 1)[1].strip()
                break
        _line(OK, f"launch agent loaded ({state})", LAUNCH_LABEL)
    else:
        _line(
            WARN,
            "launch agent not loaded",
            f"run ./install.sh to start it at login",
        )

    if _port_open(cfg.host, cfg.port):
        status = _fetch_status(cfg.host, cfg.port)
        if status:
            watcher = status.get("watcher") or {}
            browser = status.get("browser") or {}
            _line(
                OK,
                f"server answering on http://{cfg.host}:{cfg.port}",
                f"today: {_human(status.get('today_seconds') or 0)} · "
                f"ticks: {watcher.get('ticks')} · errors: {watcher.get('errors')}",
            )
            current = watcher.get("current")
            if current:
                _line(
                    INFO,
                    f"currently tracking: {current.get('app')} "
                    f"({_human(current.get('seconds') or 0)})",
                )
            if browser.get("connected"):
                _line(
                    OK,
                    "Chrome extension connected",
                    f"{browser.get('heartbeats')} heartbeats · "
                    f"last {browser.get('last_heartbeat_age_seconds')}s ago",
                )
            else:
                _line(
                    WARN,
                    "Chrome extension not reporting",
                    "load ./extension as an unpacked extension at chrome://extensions\n"
                    "         (Developer mode on -> Load unpacked). Without it you still\n"
                    "         get Chrome time, just not per-tab detail.",
                )
            if watcher.get("last_error"):
                _line(WARN, "last watcher error", str(watcher["last_error"]))
        else:
            _line(
                FAIL,
                f"something is on port {cfg.port} but it is not this tracker",
                "change \"port\" in config.json, or stop the other process",
            )
            problems += 1
    else:
        _line(
            WARN,
            f"nothing listening on {cfg.host}:{cfg.port}",
            "the tracker is not running; ./install.sh starts it",
        )

    print("\n" + "=" * 66)
    if problems:
        print(f" {problems} blocking problem(s). Everything marked 'warn' is optional.")
    else:
        print(" No blocking problems. 'warn' items are optional capabilities.")
    print("=" * 66)
    return 1 if problems else 0
