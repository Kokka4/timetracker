#!/bin/bash
# One-command install on a Mac that has never seen this project.
#
#   curl -fsSL https://raw.githubusercontent.com/OWNER/REPO/main/bootstrap.sh | bash
#
# Set OWNER/REPO below once, or override at the call site:
#   TRACKER_REPO=https://github.com/you/timetracker.git bash bootstrap.sh
#
# Safe to re-run. On a machine that already has it, this updates instead of
# reinstalling, and never touches recorded data.

set -euo pipefail

REPO_URL="${TRACKER_REPO:-https://github.com/OWNER/REPO.git}"
DEST="${TRACKER_DIR:-$HOME/timetracker}"

bold() { printf "\033[1m%s\033[0m\n" "$*"; }
ok()   { printf "  \033[32m✓\033[0m %s\n" "$*"; }
step() { printf "\n\033[1m%s\033[0m\n" "$*"; }
die()  { printf "  \033[31m✗\033[0m %s\n" "$*" >&2; exit 1; }

bold "Time tracker — setup"

# -- 1. the machine ---------------------------------------------------------

[ "$(uname -s)" = "Darwin" ] || die "This is macOS only (you are on $(uname -s))."
ok "macOS $(sw_vers -productVersion 2>/dev/null || echo '?') on $(uname -m)"

case "$DEST/" in
  "$HOME/Desktop/"*|"$HOME/Documents/"*|"$HOME/Downloads/"*)
    die "Pick a folder outside Desktop/Documents/Downloads — macOS blocks background
      agents from reading those. The default ($HOME/timetracker) is fine."
    ;;
esac

# -- 2. get the code --------------------------------------------------------
# Deliberately does NOT require git. git only arrives with Apple's Command
# Line Tools, which is a multi-gigabyte download, and GitHub serves a plain
# tarball that curl and tar — both in the base macOS install — handle fine.
# git is used when it happens to be there, because it makes updates cheaper.

case "$REPO_URL" in
  *OWNER/REPO*) die "Edit bootstrap.sh and set REPO_URL to your repository." ;;
esac

SLUG="$(printf '%s' "$REPO_URL" | sed -E 's#^.*github\.com[:/]##; s#\.git$##')"
BRANCH="${TRACKER_BRANCH:-main}"
TARBALL="https://codeload.github.com/$SLUG/tar.gz/refs/heads/$BRANCH"

step "Fetching the code"
if [ -d "$DEST/.git" ] && command -v git >/dev/null 2>&1; then
  git -C "$DEST" pull --ff-only --quiet && ok "updated the existing clone at $DEST"
elif [ -d "$DEST" ] && [ -n "$(ls -A "$DEST" 2>/dev/null)" ]; then
  # Already installed without git: refresh the code, keep data/ and logs/.
  curl -fsSL "$TARBALL" \
    | tar -xz -C "$DEST" --strip-components=1 \
        --exclude='*/data' --exclude='*/logs' --exclude='*/config.json' \
    || die "could not download $TARBALL"
  ok "refreshed $DEST (your data, logs and config kept)"
elif command -v git >/dev/null 2>&1; then
  git clone --depth 1 --quiet "$REPO_URL" "$DEST" && ok "cloned into $DEST"
else
  mkdir -p "$DEST"
  curl -fsSL "$TARBALL" | tar -xz -C "$DEST" --strip-components=1 \
    || die "could not download $TARBALL
      Check the repository is public and the branch is '$BRANCH'."
  ok "downloaded into $DEST (no git needed)"
fi

# A release should never carry anyone else's recorded activity.
if [ -f "$DEST/data/tracker.db" ]; then
  printf "  \033[33m!\033[0m data/tracker.db came with the download — that is somebody\n"
  printf "      else's history. Removing it so you start from zero.\n"
  rm -f "$DEST/data/tracker.db" "$DEST/data/tracker.db-wal" "$DEST/data/tracker.db-shm"
fi

# -- 3. install -------------------------------------------------------------
# install.sh owns Python detection, so there is one place that knows where a
# usable interpreter might hide and one error message when none exists.

step "Installing the background agent"
chmod +x "$DEST"/*.sh 2>/dev/null || true
cd "$DEST"
./install.sh
