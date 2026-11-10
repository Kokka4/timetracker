"""Entry point.

    python3 -m tracker            run the watcher and the dashboard server
    python3 -m tracker doctor     check what is working on this machine
    python3 -m tracker probe      watch the probes live while you switch apps
    python3 -m tracker status     print the running tracker's status as JSON
    python3 -m tracker stats      print database counts
    python3 -m tracker purge 180  delete everything older than 180 days
"""

from __future__ import annotations

import json
import signal
import sys
import threading
import time
from datetime import datetime

from . import config, db
from . import rules as rules_mod
from .ingest import BrowserIngest
from .server import Context, serve
from .watcher import Watcher


def _stamp() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def log(message: str) -> None:
    print(f"{_stamp()} {message}", flush=True)


def run() -> int:
    cfg = config.load()
    cfg.log_dir.mkdir(parents=True, exist_ok=True)

    store = db.Store(cfg.db_path)
    seeded = store.seed_rules(rules_mod.SEED_RULES)

    ingest = BrowserIngest(cfg, store)
    watcher = Watcher(cfg, store, ingest)
    ctx = Context(cfg, store, watcher, ingest)

    try:
        httpd = serve(ctx)
    except OSError as exc:
        log(f"FATAL cannot bind {cfg.host}:{cfg.port} — {exc}")
        log("       another process is using the port, or a previous copy is")
        log("       still running. Change \"port\" in config.json, or stop it.")
        return 1

    log(f"tracker {cfg.root.name} starting")
    log(f"  database  {cfg.db_path}")
    log(f"  dashboard http://{cfg.host}:{cfg.port}")
    log(f"  sampling  every {cfg.sample_interval}s, idle after {cfg.idle_threshold}s")
    log(f"  titles    {'on' if cfg.capture_titles else 'off'}")
    if seeded:
        log(f"  seeded    {seeded} starter rules")

    watcher.start()

    stopping = threading.Event()

    def shutdown(signum: int, _frame: object) -> None:
        if stopping.is_set():
            return
        stopping.set()
        log(f"signal {signum}: shutting down")

    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            signal.signal(sig, shutdown)
        except (ValueError, OSError):
            pass

    thread = threading.Thread(target=httpd.serve_forever, name="http", daemon=True)
    thread.start()

    try:
        while not stopping.wait(1.0):
            if not watcher.is_alive():
                log("watcher thread died; restarting it")
                watcher = Watcher(cfg, store, ingest)
                ctx.watcher = watcher
                watcher.start()
    except KeyboardInterrupt:
        pass

    watcher.stop()
    watcher.join(timeout=5.0)
    watcher.finalize()
    ingest.close_all()
    httpd.shutdown()
    httpd.server_close()
    store.close()
    log("stopped cleanly")
    return 0


def status() -> int:
    from urllib.error import URLError
    from urllib.request import urlopen

    cfg = config.load()
    try:
        with urlopen(f"http://{cfg.host}:{cfg.port}/api/status", timeout=5) as response:
            print(json.dumps(json.loads(response.read().decode("utf-8")), indent=2))
        return 0
    except (URLError, OSError, ValueError) as exc:
        print(f"not reachable on {cfg.host}:{cfg.port} — {exc}")
        return 1


def stats() -> int:
    cfg = config.load()
    store = db.Store(cfg.db_path)
    print(json.dumps(store.stats(), indent=2, default=str))
    return 0


def purge(argv: list[str]) -> int:
    if not argv:
        print("usage: python3 -m tracker purge <days>")
        return 2
    try:
        days = int(argv[0])
    except ValueError:
        print("days must be a whole number")
        return 2
    cfg = config.load()
    store = db.Store(cfg.db_path)
    cutoff = time.time() - days * 86400
    removed = store.purge_before(cutoff)
    store.conn().execute("VACUUM")
    print(f"removed {removed} rows older than {days} days")
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    command = argv[0] if argv else "run"

    if command in ("run", "serve"):
        return run()
    if command == "doctor":
        from . import doctor

        return doctor.run()
    if command == "probe":
        from . import doctor

        seconds = 20
        if len(argv) > 1:
            try:
                seconds = max(5, min(120, int(argv[1])))
            except ValueError:
                pass
        return doctor.probe(seconds)
    if command == "status":
        return status()
    if command == "stats":
        return stats()
    if command == "purge":
        return purge(argv[1:])
    if command in ("-h", "--help", "help"):
        print(__doc__)
        return 0

    print(f"unknown command: {command}")
    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
