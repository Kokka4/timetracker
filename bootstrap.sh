#!/bin/bash
# One-command install on a Mac that has never seen this project.
#
#   curl -fsSL https://raw.githubusercontent.com/kokka4/timetracker/main/bootstrap.sh | bash
#
# Override the repository or branch at the call site if you need to:
#   TRACKER_REPO=https://github.com/you/fork.git bash bootstrap.sh
#
# Safe to re-run. On a machine that already has it, this updates instead of
# reinstalling, and never touches recorded data.

set -euo pipefail

REPO_URL="${TRACKER_REPO:-https://github.com/kokka4/timetracker.git}"
DEST="${TRACKER_DIR:-$HOME/timetracker}"

bold() { printf "\033[1m%s\033[0m\n" "$*"; }
ok()   { printf "  \033[32m✓\033[0m %s\n" "$*"; }
step() { printf "\n\033[1m%s\033[0m\n" "$*"; }
die()  { printf "  \033[31m✗\033[0m %s\n" "$*" >&2; exit 1; }


# -- Apple's command-line shims ---------------------------------------------
# /usr/bin/git, /usr/bin/python3, /usr/bin/clang and friends are stubs, not
# programs. On a Mac without the Command Line Tools they exist, pass -x, and
# satisfy `command -v` — and the moment one is RUN it pops Apple's installer
# dialog and starts a download of over a gigabyte. So never run one to find
# out whether it works.
#
# `xcode-select -p` is the safe question. It prints the active developer
# directory, or fails if there is none, and never offers to install anything.
have_clt() { xcode-select -p >/dev/null 2>&1; }

# True when the path is one of those stubs on a machine that has no real tools
# behind it. Anything outside /usr/bin (Homebrew, python.org, pyenv) is a real
# binary and is left alone.
is_apple_shim() {
  case "$1" in
    /usr/bin/*) have_clt && return 1 || return 0 ;;
    *) return 1 ;;
  esac
}

bold "Time tracker — setup"

# -- 1. the machine ---------------------------------------------------------

[ "$(uname -s)" = "Darwin" ] || die "This is macOS only (you are on $(uname -s))."
ok "macOS $(sw_vers -productVersion 2>/dev/null || echo '?') on $(uname -m)"
have_clt || ok "no developer tools here, and none will be installed"

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
#
# "Happens to be there" has to be asked carefully. /usr/bin/git exists on
# every Mac whether or not git does, so `command -v git` is not the question;
# have_git is.
have_git() {
  command -v git >/dev/null 2>&1 || return 1
  ! is_apple_shim "$(command -v git)"
}

case "$REPO_URL" in
  *OWNER/REPO*) die "Edit bootstrap.sh and set REPO_URL to your repository." ;;
esac

SLUG="$(printf '%s' "$REPO_URL" | sed -E 's#^.*github\.com[:/]##; s#\.git$##')"
BRANCH="${TRACKER_BRANCH:-main}"
TARBALL="https://codeload.github.com/$SLUG/tar.gz/refs/heads/$BRANCH"

# Remember whether a database was here BEFORE the fetch. Anything found
# afterwards that was not here before arrived with the download; anything that
# was already here is this machine's own history and must never be touched.
HAD_DB=0
[ -f "$DEST/data/tracker.db" ] && HAD_DB=1

step "Fetching the code"
if [ -d "$DEST/.git" ] && have_git; then
  git -C "$DEST" pull --ff-only --quiet && ok "updated the existing clone at $DEST"
elif [ -d "$DEST" ] && [ -n "$(ls -A "$DEST" 2>/dev/null)" ]; then
  # Already installed without git: refresh the code, keep data/ and logs/.
  curl -fsSL "$TARBALL" \
    | tar -xz -C "$DEST" --strip-components=1 \
        --exclude='*/data' --exclude='*/logs' --exclude='*/config.json' \
    || die "could not download $TARBALL"
  ok "refreshed $DEST (your data, logs and config kept)"
elif have_git; then
  git clone --depth 1 --quiet "$REPO_URL" "$DEST" && ok "cloned into $DEST"
else
  mkdir -p "$DEST"
  curl -fsSL "$TARBALL" | tar -xz -C "$DEST" --strip-components=1 \
    || die "could not download $TARBALL
      Check the repository is public and the branch is '$BRANCH'."
  ok "downloaded into $DEST (no git needed)"
fi

# A release should never carry anyone else's recorded activity — but this
# only ever applies to a database that ARRIVED with the download. An earlier
# version of this check ran unconditionally and destroyed the local history of
# every machine that re-ran the installer to update. Two guards now: it must
# be new, and it is renamed rather than deleted, so a mistake here is always
# recoverable.
if [ "$HAD_DB" = "0" ] && [ -f "$DEST/data/tracker.db" ]; then
  KEEP="$DEST/data/inherited-$(date +%Y%m%d-%H%M%S).db"
  printf "  \033[33m!\033[0m a database arrived with the download — that is somebody\n"
  printf "      else's history, so this install starts from zero.\n"
  mv "$DEST/data/tracker.db" "$KEEP" 2>/dev/null \
    && printf "      moved aside to %s\n" "$KEEP"
  rm -f "$DEST/data/tracker.db-wal" "$DEST/data/tracker.db-shm"
elif [ "$HAD_DB" = "1" ]; then
  ok "existing history kept ($(du -h "$DEST/data/tracker.db" 2>/dev/null | cut -f1))"
fi

# -- 3. install -------------------------------------------------------------
# install.sh owns Python detection, so there is one place that knows where a
# usable interpreter might hide and one error message when none exists.

step "Installing the background agent"
chmod +x "$DEST"/*.sh 2>/dev/null || true
cd "$DEST"
./install.sh
