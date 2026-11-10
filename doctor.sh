#!/bin/bash
# Report what is working on this Mac, using the same Python the agent runs,
# which is the binary any permission has to be granted to.

set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON="$(cat "$DIR/.python" 2>/dev/null || command -v python3 || echo /usr/bin/python3)"
cd "$DIR"
if [ "$#" -eq 0 ]; then
  exec "$PYTHON" -m tracker doctor
fi
exec "$PYTHON" -m tracker "$@"
