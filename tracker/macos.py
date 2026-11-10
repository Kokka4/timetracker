"""macOS probes: frontmost app, window title, idle time, lock state.

**Source order matters, and it is not the obvious one.**

There are three ways to ask what application is frontmost, and they are not
equally trustworthy from a background process:

1. ``osascript`` / System Events asks the window server what is frontmost *now*.
   Always current. Costs a subprocess (~100ms) and needs Accessibility. It
   returns the window title in the same call, so when it works it answers the
   whole question at once.
2. ``lsappinfo front`` asks Launch Services. Current, no permission needed, but
   no window title.
3. ``NSWorkspace.frontmostApplication()`` via pyobjc is the fastest — and the
   one that silently lies. It answers from a cache that is refreshed by
   workspace notifications, and those are only delivered when a Cocoa run loop
   is pumping. A plain script has no run loop, so it can return the app that
   was frontmost when the process started, forever. The failure mode is not a
   crash or an error: it is a whole day of work credited to one application.
   It is therefore tried last, and only when nothing better answers.

Idle time is unaffected by any of this — ``CGEventSourceSecondsSinceLastEventType``
and ``ioreg`` both read live state — so the fast path is kept for it.
"""

from __future__ import annotations

import re
import subprocess
import time
from typing import Any

OSASCRIPT = "/usr/bin/osascript"
LSAPPINFO = "/usr/bin/lsappinfo"
IOREG = "/usr/sbin/ioreg"

LOCK_APPS = {"loginwindow", "screensaverengine", "screen saver", "lock screen"}
LOCK_BUNDLES = {
    "com.apple.loginwindow",
    "com.apple.ScreenSaver.Engine",
    "com.apple.screensaver",
}

_DENIED_MARKERS = (
    "not allowed assistive access",
    "not authorized to send apple events",
    "-1743",
    "-25211",
    "-1719",
)

# -- optional pyobjc -----------------------------------------------------

_NSWorkspace = None
_Quartz = None
try:  # pragma: no cover - depends on the host
    from AppKit import NSWorkspace as _NSWorkspace  # type: ignore
    import Quartz as _Quartz  # type: ignore
except Exception:
    _NSWorkspace = None
    _Quartz = None

HAVE_PYOBJC = _NSWorkspace is not None and _Quartz is not None

SEPARATOR = "\x1f"

_SCRIPT_WITH_TITLE = (
    'tell application "System Events"\n'
    "  set frontProc to first application process whose frontmost is true\n"
    "  set procName to name of frontProc\n"
    '  set bid to ""\n'
    "  try\n"
    "    set bid to bundle identifier of frontProc\n"
    "  end try\n"
    '  set winName to ""\n'
    "  try\n"
    "    set winName to name of front window of frontProc\n"
    "  end try\n"
    "end tell\n"
    f'return procName & "{SEPARATOR}" & bid & "{SEPARATOR}" & winName\n'
)

_SCRIPT_NO_TITLE = (
    'tell application "System Events"\n'
    "  set frontProc to first application process whose frontmost is true\n"
    "  set procName to name of frontProc\n"
    '  set bid to ""\n'
    "  try\n"
    "    set bid to bundle identifier of frontProc\n"
    "  end try\n"
    "end tell\n"
    f'return procName & "{SEPARATOR}" & bid\n'
)


def _run(args: list[str], timeout: float = 5.0) -> tuple[int, str, str]:
    try:
        proc = subprocess.run(
            args, capture_output=True, text=True, timeout=timeout, check=False
        )
        return proc.returncode, proc.stdout or "", proc.stderr or ""
    except (OSError, subprocess.SubprocessError) as exc:
        return 127, "", str(exc)


# -- source 1: osascript -------------------------------------------------

_title_state: dict[str, Any] = {"allowed": None, "checked_at": 0.0, "error": ""}
_RECHECK_SECONDS = 60.0


def _frontmost_osascript(want_title: bool = True) -> dict[str, Any]:
    """Ask the window server. Returns app, bundle_id, title and `allowed`."""
    blank = {"app": None, "bundle_id": None, "title": None, "allowed": False}

    now = time.monotonic()
    if (
        _title_state["allowed"] is False
        and now - _title_state["checked_at"] < _RECHECK_SECONDS
    ):
        return blank

    script = _SCRIPT_WITH_TITLE if want_title else _SCRIPT_NO_TITLE
    code, out, err = _run([OSASCRIPT, "-e", script], timeout=8.0)
    _title_state["checked_at"] = now

    if code != 0:
        blob = (err or "").casefold()
        if any(marker in blob for marker in _DENIED_MARKERS):
            _title_state["allowed"] = False
            _title_state["error"] = err.strip()
            return blank
        _title_state["error"] = err.strip()
        return dict(blank, allowed=_title_state["allowed"] is not False)

    _title_state["allowed"] = True
    _title_state["error"] = ""

    parts = out.rstrip("\n").split(SEPARATOR)
    app = (parts[0].strip() if parts else "") or None
    bundle = (parts[1].strip() if len(parts) > 1 else "") or None
    title = (parts[2].strip() if len(parts) > 2 else "") or None
    return {"app": app, "bundle_id": bundle, "title": title, "allowed": True}


# -- source 2: lsappinfo -------------------------------------------------

_KV = re.compile(r'"([A-Za-z]+)"\s*=\s*"([^"]*)"')


def _front_app_lsappinfo() -> tuple[str | None, str | None]:
    code, out, _ = _run([LSAPPINFO, "front"])
    if code != 0 or not out.strip():
        return None, None
    asn = out.strip().strip('"').strip()
    if not asn:
        return None, None

    code, out, _ = _run([LSAPPINFO, "info", "-only", "name", "-only", "bundleid", asn])
    fields = dict(_KV.findall(out)) if code == 0 else {}
    name = fields.get("LSDisplayName")
    bundle = fields.get("CFBundleIdentifier")

    if not name:
        code, out, _ = _run([LSAPPINFO, "info", "-only", "name", asn])
        if code == 0:
            name = dict(_KV.findall(out)).get("LSDisplayName")
    if not bundle:
        code, out, _ = _run([LSAPPINFO, "info", "-only", "bundleid", asn])
        if code == 0:
            bundle = dict(_KV.findall(out)).get("CFBundleIdentifier")

    return (name or None, bundle or None)


# -- source 3: pyobjc (last; see the module docstring) -------------------


def _front_app_pyobjc() -> tuple[str | None, str | None]:
    try:
        app = _NSWorkspace.sharedWorkspace().frontmostApplication()
        if app is None:
            return None, None
        name = app.localizedName()
        bundle = app.bundleIdentifier()
        return (str(name) if name else None, str(bundle) if bundle else None)
    except Exception:
        return None, None


# -- the combined probe --------------------------------------------------


def frontmost(want_title: bool = True) -> dict[str, Any]:
    """The frontmost app, bundle id and window title, from the best source.

    One call per sample: when Accessibility is granted this is a single
    subprocess that answers everything, which is both cheaper and more
    consistent than asking two sources and hoping they agree about the same
    instant.
    """
    result = _frontmost_osascript(want_title=want_title)
    if result["app"]:
        return {
            "app": result["app"],
            "bundle_id": result["bundle_id"],
            "title": result["title"] if want_title else None,
            "source": "osascript",
        }

    app, bundle = _front_app_lsappinfo()
    if app:
        return {"app": app, "bundle_id": bundle, "title": None, "source": "lsappinfo"}

    # Deliberately NOT falling back to pyobjc here, even though it would
    # answer. A source that returns a stale value without erroring is worse
    # than no source at all: "unknown" is recorded honestly as away time,
    # whereas a stale answer silently credits a whole day to one app and looks
    # entirely plausible while doing it. Measured on a real machine, pyobjc sat
    # on one app for 15 consecutive samples while both other sources tracked
    # the user through three. It stays in probe_all() as a diagnostic only.
    return {"app": None, "bundle_id": None, "title": None, "source": None}


def front_app() -> tuple[str | None, str | None]:
    """Backwards-compatible wrapper."""
    result = frontmost(want_title=False)
    return result["app"], result["bundle_id"]


def window_title() -> tuple[str | None, str | None, bool]:
    """``(app, title, allowed)`` — kept for diagnostics."""
    result = _frontmost_osascript(want_title=True)
    return result["app"], result["title"], bool(result["allowed"])


def titles_allowed() -> bool | None:
    return _title_state["allowed"]


def title_error() -> str:
    return str(_title_state["error"] or "")


# -- idle ----------------------------------------------------------------


def _idle_pyobjc() -> float | None:
    try:
        seconds = _Quartz.CGEventSourceSecondsSinceLastEventType(
            _Quartz.kCGEventSourceStateHIDSystemState,
            _Quartz.kCGAnyInputEventType,
        )
        value = float(seconds)
        if value >= 0:
            return value
    except Exception:
        pass
    return None


_IDLE_RE = re.compile(r'"HIDIdleTime"\s*=\s*(\d+)')


def _idle_ioreg() -> float | None:
    code, out, _ = _run([IOREG, "-c", "IOHIDSystem", "-d", "1", "-r"], timeout=6.0)
    if code != 0:
        return None
    match = _IDLE_RE.search(out)
    if not match:
        return None
    return int(match.group(1)) / 1_000_000_000.0


def idle_seconds() -> float:
    """Seconds since the last keyboard or mouse input. Live in both paths."""
    if HAVE_PYOBJC:
        value = _idle_pyobjc()
        if value is not None:
            return value
    value = _idle_ioreg()
    return value if value is not None else 0.0


# -- lock ----------------------------------------------------------------


def _locked_pyobjc() -> bool | None:
    try:
        info = _Quartz.CGSessionCopyCurrentDictionary()
        if info is None:
            return None
        return bool(info.get("CGSSessionScreenIsLocked", False))
    except Exception:
        return None


def is_locked(app: str | None = None, bundle_id: str | None = None) -> bool:
    if HAVE_PYOBJC:
        value = _locked_pyobjc()
        if value is not None:
            return value
    if bundle_id and bundle_id in LOCK_BUNDLES:
        return True
    if app and app.casefold() in LOCK_APPS:
        return True
    return False


# -- diagnostics ---------------------------------------------------------


def probe_all() -> dict[str, Any]:
    """Every source, side by side. The only way to see them disagree."""
    script = _frontmost_osascript(want_title=True)
    ls_app, ls_bundle = _front_app_lsappinfo()
    ns_app, ns_bundle = _front_app_pyobjc() if HAVE_PYOBJC else (None, None)
    chosen = frontmost(want_title=True)
    return {
        "osascript": script["app"],
        "osascript_title": script["title"],
        "osascript_allowed": script["allowed"],
        "lsappinfo": ls_app,
        "pyobjc": ns_app,
        "chosen": chosen["app"],
        "source": chosen["source"],
        "bundle_id": chosen["bundle_id"],
        "idle": idle_seconds(),
        "locked": is_locked(chosen["app"], chosen["bundle_id"]),
    }


def capabilities() -> dict[str, Any]:
    result = frontmost(want_title=True)
    return {
        "pyobjc": HAVE_PYOBJC,
        "front_app": result["app"],
        "bundle_id": result["bundle_id"],
        "front_app_source": result["source"],
        "idle_seconds": round(idle_seconds(), 1),
        "idle_source": "pyobjc" if HAVE_PYOBJC else "ioreg",
        "titles_allowed": titles_allowed(),
        "window_title": result["title"],
        "title_error": title_error(),
        "locked": is_locked(result["app"], result["bundle_id"]),
    }
