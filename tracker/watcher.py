"""The desktop watcher: the only thing in this system that claims time.

One open event at a time. Each tick either extends it or closes it and opens
the next. Three things get special handling, and they are the three that make
the difference between numbers you trust and numbers you don't:

* **Idle.** macOS reports how long ago the last input was, so when the user
  crosses the idle threshold we know they actually stopped `idle` seconds ago,
  not now. The already-recorded activity in that window is removed.
* **Lock.** A locked screen or running screensaver is away time, not app time.
* **Suspension.** Sleep, lid close and hibernation produce no events at all.
  A monotonic clock jump larger than a few ticks means the machine was not
  running, and that stretch is recorded as a gap rather than credited to
  whatever happened to be frontmost when it went down.

A fourth state, **paused**, is not handled here so much as refused: while the
off switch is on this loop does not probe at all and writes nothing, not even
the fact of the pause. See `pause.py`.
"""

from __future__ import annotations

import threading
import time
from typing import Any

from . import macos


class Watcher(threading.Thread):
    daemon = True

    def __init__(self, cfg, store, ingest=None, pause=None):
        super().__init__(name="watcher")
        self.cfg = cfg
        self.store = store
        self.ingest = ingest
        self.pause = pause

        # Not `_stop`: threading.Thread has a private _stop() method of its
        # own, and shadowing it with an attribute makes join() raise
        # "'Event' object is not callable" on every shutdown.
        self._halt = threading.Event()
        self._lock = threading.RLock()

        self.open_event: dict[str, Any] | None = None
        self.open_afk: dict[str, Any] | None = None

        self.last_mono: float | None = None
        self.last_wall: float | None = None
        # No away period may begin before this: the last moment we know the
        # machine was both running and being used.
        self.away_floor: float = 0.0
        # The boundary everything was closed at when the current pause began,
        # or None when not paused.
        self.paused_since: float | None = None

        self.ticks = 0
        self.errors = 0
        self.slow_ticks = 0
        self.last_app: str | None = None
        self.last_source: str | None = None
        self.last_error: str | None = None
        self.started_at = time.time()

    # -- thread ----------------------------------------------------------

    def run(self) -> None:
        while not self._halt.is_set():
            try:
                self.tick()
            except Exception as exc:  # never let one bad probe kill the loop
                self.errors += 1
                self.last_error = f"{type(exc).__name__}: {exc}"
            self._halt.wait(self.cfg.sample_interval)

    def stop(self) -> None:
        self._halt.set()

    def finalize(self) -> None:
        """Close whatever is open. Called on shutdown."""
        now = time.time()
        with self._lock:
            self._close_event(now)
            self._close_afk(now)
        if self.ingest:
            self.ingest.close_all(now)

    # -- one sample --------------------------------------------------------

    def tick(self) -> None:
        now = time.time()
        mono = time.monotonic()

        # Before anything else, and deliberately before the probes: a paused
        # tracker must not even ask macOS what you are doing.
        if self._handle_pause(now, mono):
            return

        # Probe BEFORE taking the lock. Every one of these shells out to macOS
        # and can block for seconds; holding the lock across them would stall
        # /api/status behind them and make a live tracker look dead.
        idle = macos.idle_seconds()
        # One combined probe. Asking two sources about "now" and trusting both
        # means they can disagree about the same instant; this way the app and
        # the title that goes with it come from the same answer.
        sample = macos.frontmost(want_title=self.cfg.capture_titles)
        app, bundle = sample["app"], sample["bundle_id"]
        locked = macos.is_locked(app, bundle)
        title = None
        if app and not locked and idle < self.cfg.idle_threshold:
            title = self._title_for(app, sample["title"])

        probe_seconds = time.monotonic() - mono
        if probe_seconds > self.cfg.sample_interval:
            self.slow_ticks += 1
            print(
                f"[watcher] slow probe: {probe_seconds:.1f}s "
                f"(app={app!r} idle={idle:.0f})",
                flush=True,
            )

        with self._lock:
            self._detect_suspension(now, mono)
            self.last_mono, self.last_wall = mono, now
            self.ticks += 1
            self.last_app = app
            self.last_source = sample["source"]

            if locked:
                self._go_away(now, idle, "locked")
            elif not app:
                self._go_away(now, idle, "unknown")
            elif idle >= self.cfg.idle_threshold:
                self._go_away(now, idle, "idle")
            else:
                # Active. The user's last input was `idle` seconds ago, so any
                # away period ended then at the latest.
                self._close_afk(now - idle)
                self._record_active(now, app, bundle, title)
                # The floor is the last moment of real input, not the last
                # tick: between the two, `idle` is already climbing and the
                # away period that follows must be back-dated to there.
                self.away_floor = max(self.away_floor, now - idle)

        if self.ingest:
            self.ingest.sweep(now)

    def _handle_pause(self, now: float, mono: float) -> bool:
        """Return True when this tick must record nothing whatsoever.

        The state is re-read from the database every tick rather than cached,
        which costs one primary-key lookup every five seconds and buys two
        things: a pause set from the dashboard or the extension takes effect
        without anything having to reach into this thread, and a pause that
        expired while the machine was asleep is already over by the time we
        look.
        """
        if self.pause is None:
            return False

        state = self.pause.state(now)

        if state["paused"]:
            with self._lock:
                if self.paused_since is None:
                    # Entering the pause. Close everything at the moment the
                    # pause actually began, not at this tick: the click landed
                    # up to one sample interval ago, and anything the previous
                    # tick recorded after it has to be given back. An event
                    # that started entirely inside the pause window collapses
                    # to zero duration here and is deleted outright.
                    boundary = state["since"] if state["since"] else now
                    boundary = min(boundary, now)
                    self._close_event(boundary)
                    self._close_afk(boundary)
                    if self.ingest:
                        self.ingest.close_all(boundary)
                    self.paused_since = boundary

                # Keep both clocks current even though nothing is recorded.
                # Suspension detection works by comparing the wall clock
                # against the monotonic one, so leaving these stale would make
                # the first tick after a long pause look exactly like waking
                # from sleep and write a `gap` row across the whole pause:
                # a permanent record of precisely the window we promised not
                # to record. The same applies if the Mac really does sleep
                # during a pause, which is why this runs on every paused tick
                # and not only on the first.
                self.last_mono, self.last_wall = mono, now
                self.ticks += 1
            return True

        if self.paused_since is not None:
            with self._lock:
                # Resuming. `idle` will be large, because nobody told macOS
                # about the pause, so without this floor the first away period
                # after a resume would back-date itself across the entire
                # paused stretch and reinstate it as `idle` time.
                self.away_floor = max(self.away_floor, now)
                self.last_mono, self.last_wall = mono, now
                self.paused_since = None
        return False

    def _detect_suspension(self, now: float, mono: float) -> None:
        """Account for the time this process was not running.

        `time.monotonic()` stops while the machine is suspended, on macOS and
        on Linux alike, whereas the wall clock does not. The difference between
        the two deltas is therefore the sleep duration itself — which is why
        this compares them against each other rather than either against the
        sample interval. Without this, closing the lid for an hour credits that
        hour to whatever happened to be frontmost.
        """
        if self.last_mono is None or self.last_wall is None:
            return

        wall_delta = now - self.last_wall
        mono_delta = mono - self.last_mono

        if wall_delta < -1.0:
            # The wall clock moved backwards (an NTP correction). Nothing can
            # be inferred about this interval, so just start fresh.
            self._close_event(self.last_wall)
            self._close_afk(self.last_wall)
            return

        asleep = wall_delta - mono_delta
        missed = mono_delta - self.cfg.sample_interval

        if asleep > max(5.0, self.cfg.sample_interval):
            down_at = self.last_wall + max(0.0, mono_delta)
        elif missed > self.cfg.sample_interval * 2 + 5:
            # The machine stayed awake but this process did not get to run, so
            # there is no evidence of anyone at the keyboard either.
            down_at = self.last_wall
        else:
            return

        self._close_event(down_at)
        self._close_afk(down_at)
        if self.ingest:
            self.ingest.close_all(down_at)
        self.store.add_afk(down_at, now, "gap")
        # The machine only came back just now, so no away period that follows
        # may claim to have started before this moment.
        self.away_floor = max(self.away_floor, now)

    def _go_away(self, now: float, idle: float, kind: str) -> None:
        """Stop the clock, back-dated to the moment input actually stopped.

        All three ways of becoming away share this. `idle` is how long ago the
        last keystroke or mouse move was, so it is also how far back the
        recorded activity needs rolling up — otherwise every break leaves
        behind up to `idle_threshold` seconds of phantom work.
        """
        cut = now - max(0.0, idle)

        # `idle` keeps growing for as long as nobody touches the machine, so
        # after a night it reaches back hours. Every power-nap wake closes and
        # reopens the away period, and without this floor each new row would
        # be back-dated over the whole night again — eighty overlapping rows
        # covering the same hours, and an away total larger than the day.
        cut = max(cut, self.away_floor)

        self._close_event(cut)
        if idle > self.cfg.sample_interval * 2:
            self.store.trim_after(cut)
        if self.ingest:
            self.ingest.close_all(cut)
        self._mark_afk(now, kind, start_hint=cut)

    def _record_active(
        self, now: float, app: str, bundle: str | None, title: str | None
    ) -> None:
        key = (app, bundle or "", title or "")

        if self.open_event is not None and self.open_event["key"] == key:
            self.store.touch_desktop_event(self.open_event["id"], now)
            return

        self._close_event(now)
        event_id = self.store.open_desktop_event(now, app, bundle, title)
        self.open_event = {
            "id": event_id,
            "start": now,
            "key": key,
            "app": app,
            "bundle_id": bundle,
            "title": title,
        }

    def _title_for(self, app: str, raw: str | None) -> str | None:
        if not self.cfg.capture_titles or not raw:
            return None
        if self.cfg.app_excluded(app):
            return None
        return self.cfg.redact_title(raw)

    # -- open event bookkeeping -------------------------------------------

    def _close_event(self, end_ts: float) -> None:
        if self.open_event is None:
            return
        start = self.open_event["start"]
        end_ts = max(end_ts, start)
        if end_ts - start < self.cfg.min_event:
            self.store.delete_desktop_event(self.open_event["id"])
        else:
            self.store.touch_desktop_event(self.open_event["id"], end_ts)
        self.open_event = None

    def _mark_afk(self, now: float, kind: str, start_hint: float | None = None) -> None:
        current = self.open_afk
        if current is not None and current["kind"] == kind:
            self.store.touch_afk(current["id"], now)
            return
        self._close_afk(now)
        start = start_hint if start_hint is not None else now
        start = min(start, now)
        afk_id = self.store.open_afk(start, kind)
        self.store.touch_afk(afk_id, now)
        self.open_afk = {"id": afk_id, "start": start, "kind": kind}

    def _close_afk(self, end_ts: float) -> None:
        if self.open_afk is None:
            return
        start = self.open_afk["start"]
        end_ts = max(end_ts, start)
        if end_ts - start < 1.0:
            self.store.delete_afk(self.open_afk["id"])
        else:
            self.store.touch_afk(self.open_afk["id"], end_ts)
        self.open_afk = None

    # -- status -------------------------------------------------------------

    def status(self) -> dict[str, Any]:
        with self._lock:
            event = None
            if self.open_event:
                event = {
                    "app": self.open_event["app"],
                    "title": self.open_event["title"],
                    "seconds": round(time.time() - self.open_event["start"], 1),
                }
            away = None
            if self.open_afk:
                away = {
                    "kind": self.open_afk["kind"],
                    "seconds": round(time.time() - self.open_afk["start"], 1),
                }
            return {
                "running": self.is_alive(),
                # Worth having here as well as at the top level: a watcher
                # whose tick count climbs while nothing gets recorded is
                # otherwise indistinguishable from a broken probe.
                "paused": self.paused_since is not None,
                "uptime_seconds": round(time.time() - self.started_at, 1),
                "ticks": self.ticks,
                "errors": self.errors,
                "slow_ticks": self.slow_ticks,
                "last_app": self.last_app,
                "probe_source": self.last_source,
                "last_error": self.last_error,
                "sample_interval": self.cfg.sample_interval,
                "idle_threshold": self.cfg.idle_threshold,
                "titles_allowed": macos.titles_allowed(),
                "title_error": macos.title_error(),
                "pyobjc": macos.HAVE_PYOBJC,
                "current": event,
                "away": away,
            }
