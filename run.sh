#!/bin/bash
# Starts Edge Notes using the environment created by setup.sh.
cd "$(dirname "${BASH_SOURCE[0]}")"
if [[ ! -x .venv/bin/python ]]; then
  echo "Run ./setup.sh first." >&2
  exit 1
fi
exec .venv/bin/python edge_notes.py "$@"
