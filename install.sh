#!/bin/bash
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
SUPPORT="$HOME/Library/Application Support/Local Claude Accounts"
APP="$HOME/Applications/Claude Account Switcher.app"
STAGED="$HOME/Applications/.Claude Account Switcher.build.$$"
AGENT="$HOME/Library/LaunchAgents/local.claude.account-sync.plist"
/usr/bin/python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' || { printf '%s\n' 'Python 3.9+ is required at /usr/bin/python3.' >&2; exit 1; }
command -v swiftc >/dev/null || { printf '%s\n' 'Xcode Command Line Tools are required: xcode-select --install' >&2; exit 1; }
mkdir -p "$SUPPORT" "$HOME/Applications" "$(dirname "$AGENT")" "$STAGED/Contents/MacOS" "$STAGED/Contents/Resources"
chmod 700 "$SUPPORT"
trap 'rm -rf "$STAGED"' EXIT
swiftc -O "$HERE/App.swift" -o "$STAGED/Contents/MacOS/LocalClaudeAccounts"
cp "$HERE/assets/AppIcon.icns" "$STAGED/Contents/Resources/AppIcon.icns"
cp "$HERE/assets/translations.json" "$STAGED/Contents/Resources/translations.json"
cat > "$STAGED/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>CFBundleName</key><string>Claude Account Switcher</string>
<key>CFBundleDisplayName</key><string>Claude Account Switcher</string>
<key>CFBundleIdentifier</key><string>local.claude.account-switcher</string>
<key>CFBundleVersion</key><string>4</string>
<key>CFBundleShortVersionString</key><string>0.4.0</string>
<key>CFBundlePackageType</key><string>APPL</string>
<key>CFBundleExecutable</key><string>LocalClaudeAccounts</string>
<key>CFBundleIconFile</key><string>AppIcon.icns</string>
<key>LSMinimumSystemVersion</key><string>12.0</string>
<key>NSHighResolutionCapable</key><true/>
</dict></plist>
PLIST
/usr/bin/codesign --force --sign - "$STAGED" >/dev/null
install -m 700 "$HERE/manager.py" "$SUPPORT/manager.py.new"
mv -f "$SUPPORT/manager.py.new" "$SUPPORT/manager.py"
if [ -e "$APP" ]; then
  mkdir -p "$SUPPORT/app-backups"
  mv "$APP" "$SUPPORT/app-backups/Claude Account Switcher.$(date +%Y%m%d-%H%M%S).app"
fi
mv "$STAGED" "$APP"
/usr/bin/python3 - "$AGENT" "$SUPPORT/manager.py" <<'PY'
import plistlib, sys
from pathlib import Path
path, script = sys.argv[1:]
p = {'Label': 'local.claude.account-sync', 'ProgramArguments': ['/usr/bin/python3', script, 'background'],
     'RunAtLoad': True, 'StartInterval': 20, 'StandardOutPath': '/dev/null',
     'StandardErrorPath': str(Path(script).parent / 'background-error.log')}
with open(path + '.new', 'wb') as f:
    plistlib.dump(p, f)
Path(path + '.new').replace(path)
PY
chmod 600 "$AGENT"
/bin/launchctl bootout "gui/$(id -u)/local.claude.account-sync" >/dev/null 2>&1 || true
/bin/launchctl bootstrap "gui/$(id -u)" "$AGENT"
printf 'Installed: %s\n' "$APP"
