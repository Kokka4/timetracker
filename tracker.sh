#!/bin/bash
# The command-line side of the tracker, so none of it has to be typed as
#
#     $(cat .python) -m tracker resume
#
# which expands to nothing at all when .python is missing or you are standing
# in the wrong directory, and leaves zsh reporting `command not found: -m`.
# That names the one part of the line that was never the problem.
#
#   ./tracker.sh resume
#   ./tracker.sh pause 30
#   ./tracker.sh status
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"

PYTHON="$(cat "$DIR/.python" 2>/dev/null || true)"
if [ -z "$PYTHON" ] || [ ! -x "$PYTHON" ]; then
  PYTHON="$(command -v python3 2>/dev/null || true)"
fi

if [ -z "$PYTHON" ]; then
  cat >&2 <<EOF
This Mac has no Python that the tracker can use, and no record of one.

  Install it (78 MB, about two minutes, no Xcode needed):
    curl -fsSL -o ~/Downloads/python.pkg \\
      https://www.python.org/ftp/python/3.15.2/python-3.15.2-macos11.pkg
    sudo installer -pkg ~/Downloads/python.pkg -target /

  Then re-run the installer:
    cd "$DIR" && ./install.sh
EOF
  exit 1
fi

if [ ! -f "$DIR/.python" ]; then
  echo "  note: .python is missing, so this is using $PYTHON." >&2
  echo "        Run ./install.sh to record the right one." >&2
fi

cd "$DIR"
exec "$PYTHON" -m tracker "$@"
