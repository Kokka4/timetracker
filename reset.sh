#!/bin/bash
# Delete all recorded history and start again from empty.
#
# Doing this by hand is fiddlier than it looks: launchd needs a moment to
# actually release a service after bootout, and bootstrapping too soon fails
# with "Input/output error". zsh also refuses an unmatched glob outright, so
# `rm -f data/tracker.db*` aborts the line rather than doing nothing. This
# handles both.
#
# Your rules are stored in the database, so they go too. Nothing else is
# touched: config.json, the code and the Chrome extension are left alone.

set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LABEL="ai.leadprinter.timetracker"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
UID_NUM="$(id -u)"

ok()   { printf "  \033[32m✓\033[0m %s\n" "$*"; }
warn() { printf "  \033[33m!\033[0m %s\n" "$*"; }

printf "\033[1mReset — this deletes every event and rule recorded so far\033[0m\n\n"

if [ -f "$DIR/data/tracker.db" ] && [ -t 0 ]; then
  SIZE="$(du -h "$DIR/data/tracker.db" | cut -f1)"
  read -r -p "  Delete $DIR/data/tracker.db ($SIZE)? [y/N] " reply
  [[ "${reply:-n}" =~ ^[Yy]$ ]] || { echo "  cancelled"; exit 0; }
fi

launchctl bootout "gui/$UID_NUM/$LABEL" >/dev/null 2>&1 || true

# Wait for launchd to really let go, rather than racing it.
for _ in $(seq 1 20); do
  launchctl print "gui/$UID_NUM/$LABEL" >/dev/null 2>&1 || break
  sleep 0.5
done
ok "tracker stopped"

# Named explicitly: a glob would abort under zsh when nothing matches.
rm -f "$DIR/data/tracker.db" "$DIR/data/tracker.db-wal" "$DIR/data/tracker.db-shm"
ok "history deleted"

if [ ! -f "$PLIST" ]; then
  warn "no launch agent found — run ./install.sh instead"
  exit 1
fi

if ! launchctl bootstrap "gui/$UID_NUM" "$PLIST" >/dev/null 2>&1; then
  launchctl load -w "$PLIST" >/dev/null 2>&1 || true
fi
launchctl kickstart -k "gui/$UID_NUM/$LABEL" >/dev/null 2>&1 || true

PORT="$(sed -n 's/.*"port"[[:space:]]*:[[:space:]]*\([0-9]*\).*/\1/p' "$DIR/config.json" | head -1)"
PORT="${PORT:-8734}"

printf "  waiting for the server"
for _ in $(seq 1 30); do
  if curl -fsS --max-time 2 "http://127.0.0.1:$PORT/api/status" >/dev/null 2>&1; then
    printf "\n"
    ok "running again on http://127.0.0.1:$PORT — recording from zero"
    exit 0
  fi
  printf "."
  sleep 0.5
done

printf "\n"
warn "the server did not come back up; check logs/tracker.err.log"
exit 1
