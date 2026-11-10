#!/bin/bash
# Stop the tracker and remove the launch agent. Your data is left alone.

set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LABEL="ai.leadprinter.timetracker"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
UID_NUM="$(id -u)"

printf "\033[1mLocal time tracker — uninstall\033[0m\n\n"

launchctl bootout "gui/$UID_NUM/$LABEL" >/dev/null 2>&1 \
  || launchctl unload "$PLIST" >/dev/null 2>&1 \
  || true
printf "  ✓ agent stopped\n"

if [ -f "$PLIST" ]; then
  rm -f "$PLIST"
  printf "  ✓ removed %s\n" "$PLIST"
fi

if [ -f "$DIR/data/tracker.db" ]; then
  SIZE="$(du -h "$DIR/data/tracker.db" | cut -f1)"
  printf "\n  Your history is still here: %s (%s)\n" "$DIR/data/tracker.db" "$SIZE"
  printf "  Delete it yourself if you want it gone.\n"
fi

printf "\n  The Chrome extension, if you loaded it, is removed at chrome://extensions.\n"
printf "  Accessibility permission, if you granted it, is revoked in\n"
printf "  System Settings → Privacy & Security → Accessibility.\n\n"
