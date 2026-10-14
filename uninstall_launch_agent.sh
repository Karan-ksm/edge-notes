#!/bin/bash
# Stops Edge Notes and removes its LaunchAgent.
set -uo pipefail

LABEL="com.karan.edgenotes"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"

launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
rm -f "$PLIST"
echo "Removed $LABEL"
