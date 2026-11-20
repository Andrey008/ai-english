#!/bin/sh
# Start the ai-english menu-bar app at login (and now). Undo with:
#   launchctl bootout gui/$(id -u)/com.aienglish.menubar && rm ~/Library/LaunchAgents/com.aienglish.menubar.plist
set -eu
SERVER_DIR=$(cd "$(dirname "$0")/.." && pwd)
LABEL=com.aienglish.menubar
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
cd "$SERVER_DIR" && uv sync -q
mkdir -p "$SERVER_DIR/logs" "$HOME/Library/LaunchAgents"
cat > "$PLIST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>$SERVER_DIR/.venv/bin/python</string>
    <string>$SERVER_DIR/scripts/menubar.py</string>
  </array>
  <key>WorkingDirectory</key><string>$SERVER_DIR</string>
  <key>EnvironmentVariables</key>
  <dict><key>PATH</key><string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string></dict>
  <key>RunAtLoad</key><true/>
  <key>ProcessType</key><string>Interactive</string>
  <key>StandardOutPath</key><string>$SERVER_DIR/logs/menubar.log</string>
  <key>StandardErrorPath</key><string>$SERVER_DIR/logs/menubar.log</string>
</dict>
</plist>
PLIST
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"
echo "Installed: look for ⚪ in the menu bar. Log: $SERVER_DIR/logs/menubar.log"
