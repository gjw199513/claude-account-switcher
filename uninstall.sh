#!/bin/bash
set -euo pipefail
AGENT="$HOME/Library/LaunchAgents/local.claude.account-sync.plist"
APP="$HOME/Applications/Claude Account Switcher.app"
/bin/launchctl bootout "gui/$(id -u)/local.claude.account-sync" >/dev/null 2>&1 || true
rm -f "$AGENT"
if [ -d "$APP" ] && [ ! -L "$APP" ]; then
  rm -rf "$APP"
fi
printf '%s\n' 'Removed the app and background task. Claude profiles, session data, and backups were preserved.'
