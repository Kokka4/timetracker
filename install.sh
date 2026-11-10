#!/bin/bash
# Install the tracker as a login agent and start it.
# Safe to re-run: it replaces the agent definition and restarts cleanly.

set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LABEL="ai.leadprinter.timetracker"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
UID_NUM="$(id -u)"

bold()  { printf "\033[1m%s\033[0m\n" "$*"; }
ok()    { printf "  \033[32m✓\033[0m %s\n" "$*"; }
warn()  { printf "  \033[33m!\033[0m %s\n" "$*"; }
die()   { printf "  \033[31m✗\033[0m %s\n" "$*" >&2; exit 1; }

bold "Local time tracker — install"
echo

[ "$(uname -s)" = "Darwin" ] || die "This installs a macOS launch agent; you are on $(uname -s)."

# -- 1. find a usable Python ------------------------------------------------
# Homebrew's Python is preferred over /usr/bin/python3: the system one is a
# stub that depends on the Command Line Tools, and macOS privacy permissions
# are granted per binary, so a stable path matters later.

# Look everywhere a Python could plausibly already be, before telling anyone
# to download one. Plenty of Macs have an interpreter that is not on PATH.
PYTHON=""
CANDIDATES="
/Library/Frameworks/Python.framework/Versions/3.*/bin/python3
/opt/homebrew/bin/python3
/usr/local/bin/python3
$HOME/.homebrew/bin/python3
$HOME/.pyenv/versions/*/bin/python3
/opt/anaconda3/bin/python3
$HOME/anaconda3/bin/python3
$HOME/miniconda3/bin/python3
$HOME/miniforge3/bin/python3
$(command -v python3 2>/dev/null || true)
/usr/bin/python3
/Library/Developer/CommandLineTools/usr/bin/python3
/Applications/Xcode.app/Contents/Developer/usr/bin/python3
"

for pattern in $CANDIDATES; do
  for candidate in $pattern; do   # unquoted: expands the globs above
    [ -n "$candidate" ] && [ -x "$candidate" ] || continue
    if "$candidate" -c 'import sys,sqlite3,http.server; assert sys.version_info>=(3,9)' >/dev/null 2>&1; then
      PYTHON="$candidate"
      break 2
    fi
  done
done

if [ -z "$PYTHON" ]; then
  printf "  \033[31m✗\033[0m No usable Python 3.9+ on this Mac.\n\n" >&2
  cat >&2 <<'NOPYTHON'
  macOS ships a python3 stub that does nothing until a real interpreter is
  installed. Two ways to fix it — the first is far smaller.

  OPTION A — Python on its own (about 78 MB, two minutes)      <- recommended

      Download and run the macOS installer from python.org:
      https://www.python.org/downloads/macos/

      Click through it, then run ./install.sh again. This installs only
      Python, not a developer toolchain.

      From this Terminal, if you prefer:

        curl -fsSL -o ~/Downloads/python.pkg \
          https://www.python.org/ftp/python/3.15.2/python-3.15.2-macos11.pkg
        sudo installer -pkg ~/Downloads/python.pkg -target /

  OPTION B — Apple's Command Line Tools (over 1 GB, 10+ minutes)

      Only worth it if this Mac will also be used for development.

        xcode-select --install

  Either one works. Re-run ./install.sh when it finishes; nothing is lost.

NOPYTHON
  exit 1
fi

# The agent and any permission you grant must refer to the same real binary.
PYTHON_REAL="$("$PYTHON" -c 'import sys; print(sys.executable)')"
printf "%s" "$PYTHON_REAL" > "$DIR/.python"
ok "python $("$PYTHON_REAL" -c 'import sys;print(".".join(map(str,sys.version_info[:3])))') at $PYTHON_REAL"

# -- 2. optional fast path --------------------------------------------------

# Nothing is installed here on purpose. The tracker runs on the standard
# library alone, so an install never needs pip, a virtualenv, or network
# access — which is what makes it a one-command job on someone else's Mac.
if "$PYTHON_REAL" -c 'import AppKit, Quartz' >/dev/null 2>&1; then
  ok "pyobjc present (used only for idle detection)"
else
  ok "no third-party packages needed"
fi

# -- 3. directories and port ------------------------------------------------

mkdir -p "$DIR/data" "$DIR/logs" "$HOME/Library/LaunchAgents"
chmod 700 "$DIR/data"
chmod +x "$DIR/agent.sh" 2>/dev/null || true

# Snapshot the history before touching anything. Installing should never be
# able to cost you data, and once it has, "be more careful" is not a fix.
if [ -f "$DIR/data/tracker.db" ]; then
  mkdir -p "$DIR/data/backups"
  STAMP="$(date +%Y%m%d-%H%M%S)"
  if "$PYTHON_REAL" - "$DIR/data/tracker.db" "$DIR/data/backups/tracker-$STAMP.db" <<'PYBACKUP' 2>/dev/null
import sqlite3, sys
# The online backup API, not a file copy: in WAL mode the newest writes live
# in the -wal file and a plain cp silently loses them.
source = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
target = sqlite3.connect(sys.argv[2])
source.backup(target)
target.close()
source.close()
PYBACKUP
  then
    ok "history backed up to data/backups/tracker-$STAMP.db ($(du -h "$DIR/data/backups/tracker-$STAMP.db" | cut -f1))"
    # Keep the five most recent, discard the rest.
    ls -1t "$DIR/data/backups"/tracker-*.db 2>/dev/null | tail -n +6 | while IFS= read -r old; do
      rm -f "$old"
    done
  else
    warn "could not back up the existing database — continuing without a snapshot"
  fi
fi

# macOS protects Desktop, Documents and Downloads. Your Terminal can read them
# because you approved it once; a launchd agent cannot, and is denied with no
# prompt at all. Say so before it turns into a confusing crash loop.
case "$DIR/" in
  "$HOME/Desktop/"*|"$HOME/Documents/"*|"$HOME/Downloads/"*)
    warn "this project lives under a folder macOS protects ($DIR)"
    warn "a background agent may be refused access with no prompt"
    warn "if it fails to start, move it:  mv \"$DIR\" ~/timetracker && cd ~/timetracker && ./install.sh"
    ;;
esac

PORT="$("$PYTHON_REAL" - "$DIR/config.json" <<'PY' 2>/dev/null || echo 8734
import json, sys
try:
    print(json.load(open(sys.argv[1])).get("port", 8734))
except Exception:
    print(8734)
PY
)"
ok "dashboard port $PORT"

if lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
  if launchctl print "gui/$UID_NUM/$LABEL" >/dev/null 2>&1; then
    warn "port $PORT is in use by the running tracker — it will be restarted"
  else
    die "port $PORT is already in use by something else. Change \"port\" in config.json."
  fi
fi

# -- 4. the launch agent ----------------------------------------------------

cat > "$PLIST" <<PLISTEOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>$DIR/agent.sh</string>
  </array>
  <key>WorkingDirectory</key><string>$DIR</string>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>ThrottleInterval</key><integer>10</integer>
  <key>ProcessType</key><string>Background</string>
  <key>LowPriorityIO</key><true/>
  <key>Nice</key><integer>5</integer>
  <key>StandardOutPath</key><string>$DIR/logs/tracker.out.log</string>
  <key>StandardErrorPath</key><string>$DIR/logs/tracker.err.log</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PYTHONUNBUFFERED</key><string>1</string>
    <key>PYTHONPATH</key><string>$DIR</string>
    <key>PATH</key><string>/usr/bin:/bin:/usr/sbin:/sbin</string>
  </dict>
</dict>
</plist>
PLISTEOF

plutil -lint "$PLIST" >/dev/null || die "generated plist is malformed: $PLIST"
ok "launch agent written to $PLIST"

launchctl bootout "gui/$UID_NUM/$LABEL" >/dev/null 2>&1 || true
sleep 1

# Start from empty logs, so anything below is from this run and not the last.
: > "$DIR/logs/tracker.err.log" 2>/dev/null || true
: > "$DIR/logs/tracker.out.log" 2>/dev/null || true

if launchctl bootstrap "gui/$UID_NUM" "$PLIST" >/dev/null 2>&1; then
  launchctl enable "gui/$UID_NUM/$LABEL" >/dev/null 2>&1 || true
  launchctl kickstart -k "gui/$UID_NUM/$LABEL" >/dev/null 2>&1 || true
else
  # Older macOS, or a stale registration.
  launchctl unload "$PLIST" >/dev/null 2>&1 || true
  launchctl load -w "$PLIST" >/dev/null 2>&1 || die "launchctl could not load the agent"
fi
ok "agent loaded — it will start automatically at every login"

# -- 5. wait for it to answer ----------------------------------------------

printf "  waiting for the server"
UP=0
for _ in $(seq 1 30); do
  if curl -fsS --max-time 2 "http://127.0.0.1:$PORT/api/status" >/dev/null 2>&1; then UP=1; break; fi
  printf "."
  sleep 0.5
done
printf "\n"

if [ "$UP" = "1" ]; then
  ok "dashboard live at http://127.0.0.1:$PORT"
else
  printf "  \033[31m✗\033[0m the server did not answer within 15 seconds\n\n"
  echo "  --- logs/tracker.out.log ---"
  tail -n 20 "$DIR/logs/tracker.out.log" 2>/dev/null | sed 's/^/  /' || true
  echo "  --- logs/tracker.err.log ---"
  tail -n 20 "$DIR/logs/tracker.err.log" 2>/dev/null | sed 's/^/  /' || true
  echo
  echo "  The agent prints the reason above. The usual one is macOS refusing a"
  echo "  background agent access to a protected folder, which is fixed by"
  echo "  moving the project out of Desktop/Documents/Downloads:"
  echo
  echo "      mv \"$DIR\" ~/timetracker && cd ~/timetracker && ./install.sh"
  echo
  exit 1
fi

echo
bold "Checking what this Mac allows"
echo
cd "$DIR" && "$PYTHON_REAL" -m tracker doctor || true

echo
bold "Two things left, both optional"
echo
echo "  1. Window titles (which document, repo or window — not needed for Chrome tabs)"
echo "       System Settings → Privacy & Security → Accessibility → +"
echo "       press ⌘⇧G and paste:  $PYTHON_REAL"
echo "       then:  launchctl kickstart -k gui/$UID_NUM/$LABEL"
echo
echo "  2. Chrome tab detail"
echo "       chrome://extensions → Developer mode on → Load unpacked"
echo "       choose:  $DIR/extension"
echo
echo "  Dashboard:  http://127.0.0.1:$PORT"
echo "  Diagnose:   ./doctor.sh"
echo "  Remove:     ./uninstall.sh"
echo
