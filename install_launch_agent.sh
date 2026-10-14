#!/bin/bash
# Installs a LaunchAgent so Edge Notes starts at login (and restarts if it exits).
set -euo pipefail

LABEL="com.karan.edgenotes"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP="$SCRIPT_DIR/edge_notes.py"
# Prefer the environment made by setup.sh; otherwise fall back to an installed Python 3.
if [[ -x "$SCRIPT_DIR/.venv/bin/python" ]]; then
  PYTHON="$SCRIPT_DIR/.venv/bin/python"
elif command -v python3.14 >/dev/null 2>&1; then
  PYTHON="$(python3.14 -c 'import sys; print(sys.executable)')"
else
  PYTHON="$(python3 -c 'import sys; print(sys.executable)')"
fi

if [[ ! -f "$APP" ]]; then
  echo "Cannot find $APP" >&2
  exit 1
fi

mkdir -p "$HOME/Library/LaunchAgents"
cat > "$PLIST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>$PYTHON</string>
    <string>$APP</string>
  </array>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
  <key>StandardErrorPath</key>
  <string>/tmp/edgenotes.err</string>
</dict>
</plist>
PLIST

# Replace any previously loaded copy, then load the new one.
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"
echo "Installed $PLIST"
echo "Python: $PYTHON"
echo "Errors go to /tmp/edgenotes.err"
