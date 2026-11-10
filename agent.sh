#!/bin/bash
# Launched by launchd. Everything printed here lands in logs/tracker.out.log
# (or tracker.err.log), which is the only diagnostic channel a background agent
# has — there is no terminal and no permission prompt behind it.

DIR="$(cd "$(dirname "$0")" 2>/dev/null && pwd)"

if [ -z "$DIR" ] || ! cd "$DIR" 2>/dev/null; then
  echo "FATAL could not enter the project directory. macOS may be blocking it."
  sleep 60
  exit 78
fi

PYTHON="$(cat "$DIR/.python" 2>/dev/null)"
[ -x "$PYTHON" ] || PYTHON="$(command -v python3 2>/dev/null)"
[ -x "$PYTHON" ] || PYTHON=/usr/bin/python3

echo "$(date '+%Y-%m-%d %H:%M:%S') agent starting — dir=$DIR python=$PYTHON"

# Folders under ~/Desktop, ~/Documents and ~/Downloads are protected by macOS.
# A Terminal you have already approved can read them; a launchd agent cannot,
# and it is denied silently, with no prompt and no obvious error. Check for
# that explicitly rather than letting it surface as a confusing import failure.
if [ ! -r "$DIR/tracker/__init__.py" ]; then
  echo "FATAL cannot read $DIR/tracker"
  echo "      The files are there, but this background agent is not allowed to"
  echo "      read them. Folders under ~/Desktop, ~/Documents and ~/Downloads"
  echo "      are protected by macOS and an agent gets no permission prompt."
  echo ""
  echo "      Fix it either way:"
  echo "        a) move the project somewhere unprotected, then reinstall:"
  echo "             mv \"$DIR\" ~/timetracker && cd ~/timetracker && ./install.sh"
  echo "        b) or grant Full Disk Access to: $PYTHON"
  sleep 60
  exit 78
fi

# Do not depend on launchd honouring WorkingDirectory for module resolution.
export PYTHONPATH="$DIR${PYTHONPATH:+:$PYTHONPATH}"
export PYTHONUNBUFFERED=1

exec "$PYTHON" -m tracker
