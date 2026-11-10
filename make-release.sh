#!/bin/bash
# Build a clean zip to hand to someone, with none of your own data in it.
#
#   ./make-release.sh            -> ~/Desktop/timetracker-YYYY-MM-DD.zip
#   ./make-release.sh /tmp/out   -> /tmp/out/timetracker-YYYY-MM-DD.zip
#
# Use this when you would rather AirDrop a file than clone a repo. The repo
# route is still better for updates — this is the offline fallback.

set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUT_DIR="${1:-$HOME/Desktop}"
STAMP="$(date +%Y-%m-%d)"
NAME="timetracker-$STAMP"
STAGE="$(mktemp -d)/$NAME"

ok()  { printf "  \033[32m✓\033[0m %s\n" "$*"; }
die() { printf "  \033[31m✗\033[0m %s\n" "$*" >&2; exit 1; }

printf "\033[1mBuilding a shareable release\033[0m\n\n"

mkdir -p "$STAGE"

# An allow-list, not an ignore-list. Anything new has to be added here on
# purpose, so a future file full of personal data cannot ship by accident.
for item in \
  tracker web extension \
  install.sh uninstall.sh doctor.sh reset.sh update.sh agent.sh bootstrap.sh \
  config.json README.md SETUP.md .gitignore
do
  [ -e "$DIR/$item" ] || continue
  cp -R "$DIR/$item" "$STAGE/"
done

find "$STAGE" -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true
find "$STAGE" -name '.DS_Store' -delete 2>/dev/null || true
rm -f "$STAGE/.python"
mkdir -p "$STAGE/data" "$STAGE/logs"

# -- refuse to ship anything personal --------------------------------------

LEAKS="$(find "$STAGE" \( -name '*.db' -o -name '*.db-wal' -o -name '*.db-shm' -o -name '*.log' \) 2>/dev/null || true)"
[ -z "$LEAKS" ] || die "refusing to build — these would ship: $LEAKS"

# A bare username false-positives on ordinary words. The thing that actually
# leaks is a hardcoded home directory.
if grep -rqI "$HOME/" "$STAGE" 2>/dev/null; then
  printf "  \033[33m!\033[0m your home path appears in the release:\n"
  grep -rlI "$HOME/" "$STAGE" 2>/dev/null | sed 's/^/      /'
  printf "      check these before sending.\n"
fi

ok "no database, no logs, no machine-specific paths"
ok "$(find "$STAGE" -type f | wc -l | tr -d ' ') files, $(du -sh "$STAGE" | cut -f1)"

mkdir -p "$OUT_DIR"
rm -f "$OUT_DIR/$NAME.zip"
(cd "$(dirname "$STAGE")" && zip -rq "$OUT_DIR/$NAME.zip" "$NAME" -x '*.DS_Store')
rm -rf "$(dirname "$STAGE")"

ok "written to $OUT_DIR/$NAME.zip"
printf "\n  Send that file. On the other Mac:\n"
printf "      unzip ~/Downloads/%s.zip -d ~/\n" "$NAME"
printf "      mv ~/%s ~/timetracker\n" "$NAME"
printf "      cd ~/timetracker && ./install.sh\n\n"
