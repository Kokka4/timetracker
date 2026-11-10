#!/bin/bash
# Pull the latest code and restart. Recorded data and rules are untouched.

set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

ok()   { printf "  \033[32m✓\033[0m %s\n" "$*"; }
warn() { printf "  \033[33m!\033[0m %s\n" "$*"; }

printf "\033[1mUpdating the time tracker\033[0m\n\n"

if [ -d .git ]; then
  BEFORE="$(git rev-parse --short HEAD)"
  if ! git diff --quiet 2>/dev/null; then
    warn "you have local edits; stashing them as 'timetracker-update'"
    git stash push -m "timetracker-update" --quiet || true
  fi
  git pull --ff-only --quiet
  AFTER="$(git rev-parse --short HEAD)"
  if [ "$BEFORE" = "$AFTER" ]; then
    ok "already on the latest version ($AFTER)"
  else
    ok "updated $BEFORE -> $AFTER"
    git log --oneline "$BEFORE..$AFTER" | head -10 | sed 's/^/      /'
  fi
elif [ -n "${TRACKER_REPO:-}" ] || grep -q 'REPO_URL="\${TRACKER_REPO:-https' bootstrap.sh 2>/dev/null; then
  # Installed without git (no Command Line Tools on this Mac). Pull a fresh
  # tarball instead; curl and tar are in the base macOS install.
  REPO_URL="${TRACKER_REPO:-$(sed -n 's/^REPO_URL="\${TRACKER_REPO:-\(.*\)}"$/\1/p' bootstrap.sh)}"
  SLUG="$(printf '%s' "$REPO_URL" | sed -E 's#^.*github\.com[:/]##; s#\.git$##')"
  case "$SLUG" in
    ""|*OWNER/REPO*) warn "no repository configured — update the files by hand, then re-run ./install.sh" ;;
    *)
      TARBALL="https://codeload.github.com/$SLUG/tar.gz/refs/heads/${TRACKER_BRANCH:-main}"
      if curl -fsSL "$TARBALL" | tar -xz -C . --strip-components=1 \
           --exclude='*/data' --exclude='*/logs' --exclude='*/config.json'; then
        ok "refreshed from $SLUG (data, logs and config untouched)"
      else
        warn "could not download $TARBALL — leaving the current version in place"
      fi
      ;;
  esac
else
  warn "not a git clone — replace the files by hand, then re-run ./install.sh"
fi

./install.sh
