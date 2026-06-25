#!/usr/bin/env bash
# Remove the NetTracker application-menu entry and icon (per-user).
# Leaves your usage data and settings untouched.
set -e
APPS_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
ICON_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/icons"

rm -f "$APPS_DIR/nettracker.desktop"
rm -f "$ICON_DIR/nettracker.png"
rm -f "${XDG_CONFIG_HOME:-$HOME/.config}/autostart/nettracker.desktop"

command -v update-desktop-database >/dev/null 2>&1 && \
    update-desktop-database "$APPS_DIR" >/dev/null 2>&1 || true

echo "Removed NetTracker menu entry and icon."
echo "Your data (~/.local/share/nettracker) and settings were kept."
