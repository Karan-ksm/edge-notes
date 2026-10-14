#!/bin/bash
# One-time setup: creates a private Python environment in .venv and installs what Edge Notes needs.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

if [[ "$(uname)" != "Darwin" ]]; then
  echo "Edge Notes only runs on macOS." >&2
  exit 1
fi

# Pick the newest Python 3 available (3.9 or later).
PYTHON=""
for candidate in python3.14 python3.13 python3.12 python3.11 python3.10 python3; do
  if command -v "$candidate" >/dev/null 2>&1 &&
     "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' 2>/dev/null; then
    PYTHON="$(command -v "$candidate")"
    break
  fi
done

if [[ -z "$PYTHON" ]]; then
  echo "Python 3.9+ was not found." >&2
  echo "Install it with:  xcode-select --install   (or: brew install python)" >&2
  exit 1
fi

echo "Using $("$PYTHON" --version) at $PYTHON"
"$PYTHON" -m venv .venv
.venv/bin/python -m pip install --quiet --upgrade pip
.venv/bin/python -m pip install --quiet -r requirements.txt
echo
echo "Setup complete. Start Edge Notes with:  ./run.sh"
