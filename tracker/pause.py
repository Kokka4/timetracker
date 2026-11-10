"""The off switch.

Pausing is a privacy control, not a bookkeeping one, and the two want opposite
things. While paused the watcher does not probe, the ingest endpoint refuses
heartbeats, and nothing at all is written: no events, no away rows, and no
marker saying that a pause happened.

That last part is a deliberate choice with a cost. Because there is no marker,
a paused stretch is indistinguishable from the Mac having been shut, and shows
up in the dashboard as unaccounted time inside the day's span rather than as
anything explained. The alternative, a `paused` away row, would keep the daily
totals reconciling at the price of a permanent record of exactly when you
wanted no record. This file takes the privacy side, so the live indicators in
the dashboard and on the toolbar icon are the only warning that a pause is
running. They matter more than they look.

The switch itself still has to persist. An indefinite pause that lifted
whenever launchd restarted the agent would be worse than no switch at all, so
the state lives in the `meta` table: two keys, and no row in any events table
touched. Expiry is evaluated on read rather than by a timer, so a pause that
ran out while the process was dead is already over by the time anything asks.
"""

from __future__ import annotations

import threading
import time
from typing import Any

KEY_UNTIL = "pause_until"
KEY_SINCE = "pause_since"
INDEFINITE = "forever"

MIN_MINUTES = 1
MAX_MINUTES = 24 * 60
PRESET_MINUTES = (30, 60, 120)


class Pause:
    """Owns the pause state. Shared between the watcher and the HTTP threads."""

    def __init__(self, store):
        self.store = store
        self._lock = threading.RLock()

    # -- reads -------------------------------------------------------------

    def state(self, now: float | None = None) -> dict[str, Any]:
        """The current state, with expiry already applied."""
        now = time.time() if now is None else now
        with self._lock:
            raw = self.store.get_meta(KEY_UNTIL)
            if not raw:
                return self._off()

            if raw == INDEFINITE:
                return self._on(None, self._since(), now)

            try:
                until = float(raw)
            except (TypeError, ValueError):
                # A value we cannot read is a bug, not an instruction. Treating
                # it as an indefinite pause would stop recording for good and
                # never tell anyone why, so this fails towards tracking and
                # says so in the log.
                print(
                    f"[pause] unreadable {KEY_UNTIL}={raw!r}; treating as not paused",
                    flush=True,
                )
                self._clear()
                return self._off()

            if until <= now:
                self._clear()
                return self._off()
            return self._on(until, self._since(), now)

    def is_paused(self, now: float | None = None) -> bool:
        return bool(self.state(now)["paused"])

    # -- writes ------------------------------------------------------------

    def pause(self, minutes: float | None, now: float | None = None) -> dict[str, Any]:
        """Start or extend a pause. `minutes=None` means until resumed."""
        now = time.time() if now is None else now
        with self._lock:
            # Changing the duration of a pause that is already running keeps
            # its original start. The watcher closes its open events at that
            # boundary, and moving the boundary forward would hand back a
            # sliver of the time the first pause was meant to cover.
            since = self._since() if self.store.get_meta(KEY_UNTIL) else None
            if since is None:
                since = now
            self.store.set_meta(KEY_SINCE, repr(float(since)))

            if minutes is None:
                self.store.set_meta(KEY_UNTIL, INDEFINITE)
            else:
                capped = max(MIN_MINUTES, min(MAX_MINUTES, float(minutes)))
                self.store.set_meta(KEY_UNTIL, repr(now + capped * 60.0))
            return self.state(now)

    def resume(self, now: float | None = None) -> dict[str, Any]:
        now = time.time() if now is None else now
        with self._lock:
            self._clear()
            return self._off()

    # -- internals ---------------------------------------------------------

    def _clear(self) -> None:
        self.store.delete_meta(KEY_UNTIL)
        self.store.delete_meta(KEY_SINCE)

    def _since(self) -> float | None:
        raw = self.store.get_meta(KEY_SINCE)
        try:
            return float(raw) if raw else None
        except (TypeError, ValueError):
            return None

    def _off(self) -> dict[str, Any]:
        return {
            "paused": False,
            "indefinite": False,
            "until": None,
            "since": None,
            "seconds_left": None,
            "presets_minutes": list(PRESET_MINUTES),
            "max_minutes": MAX_MINUTES,
        }

    def _on(
        self, until: float | None, since: float | None, now: float
    ) -> dict[str, Any]:
        return {
            "paused": True,
            "indefinite": until is None,
            "until": until,
            "since": since,
            "seconds_left": None if until is None else round(max(0.0, until - now), 1),
            "paused_for_seconds": None if since is None else round(now - since, 1),
            "presets_minutes": list(PRESET_MINUTES),
            "max_minutes": MAX_MINUTES,
        }


def parse_request(payload: dict[str, Any]) -> float | None:
    """Turn a POST body into a number of minutes, or None for indefinite.

    Raises ValueError with a message meant for the caller to see.
    """
    if payload.get("indefinite") or payload.get("minutes") in ("forever", INDEFINITE):
        return None
    raw = payload.get("minutes")
    if raw is None:
        raise ValueError("expected \"minutes\": <number> or \"indefinite\": true")
    try:
        minutes = float(raw)
    except (TypeError, ValueError):
        raise ValueError(f"minutes must be a number, got {raw!r}") from None
    if minutes != minutes or minutes in (float("inf"), float("-inf")):
        raise ValueError("minutes must be a finite number")
    if minutes < MIN_MINUTES or minutes > MAX_MINUTES:
        raise ValueError(
            f"minutes must be between {MIN_MINUTES} and {MAX_MINUTES}"
            " (use \"indefinite\": true for longer)"
        )
    return minutes
