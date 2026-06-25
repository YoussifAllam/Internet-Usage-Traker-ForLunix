#!/usr/bin/env bash
# Install NetTracker into the application menu (per-user, no root).
# Writes a .desktop launcher to ~/.local/share/applications and renders the
# icon. The app itself runs via run.sh (which resolves its own interpreter),
# so this script does NOT create a virtualenv.
set -e
cd "$(dirname "$0")"
ROOT="$(pwd)"

APPS_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
ICON_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/icons"
DESKTOP="$APPS_DIR/nettracker.desktop"
ICON="$ICON_DIR/nettracker.png"

mkdir -p "$APPS_DIR" "$ICON_DIR"

# Find a Python with PyQt5 for icon rendering (the same one run.sh uses, the
# project venv, $PYTHON, or python3). Icon generation is best-effort.
RUNSH_PY="$(grep -oE '/[^"'"'"' ]*/bin/python[0-9.]*' run.sh 2>/dev/null | head -1)"
ICON_OK=""
for c in "$PYTHON" "$ROOT/venv/bin/python" "$RUNSH_PY" python3; do
    [ -n "$c" ] && command -v "$c" >/dev/null 2>&1 || continue
    if QT_QPA_PLATFORM=offscreen "$c" - "$ICON" >/dev/null 2>&1 <<'PY'
import sys
from PyQt5.QtWidgets import QApplication
app = QApplication([])
from nettracker.widgets import make_icon
make_icon(128).pixmap(128, 128).save(sys.argv[1], "PNG")
PY
    then ICON_OK=1; echo "Icon rendered with: $c"; break; fi
done
[ -n "$ICON_OK" ] || { ICON=""; echo "(PyQt5 not found — using a generic icon)"; }

{
    echo "[Desktop Entry]"
    echo "Type=Application"
    echo "Name=NetTracker"
    echo "GenericName=Internet Usage Tracker"
    echo "Comment=Track internet usage: live speed, history, per-app usage, data caps"
    echo "Exec=$ROOT/run.sh"
    [ -n "$ICON" ] && echo "Icon=$ICON" || echo "Icon=network-workgroup"
    echo "Terminal=false"
    echo "Categories=Network;Monitor;Utility;"
    echo "Keywords=network;bandwidth;usage;data;vnstat;"
    echo "StartupNotify=true"
} > "$DESKTOP"
chmod +x "$ROOT/run.sh" 2>/dev/null || true

command -v update-desktop-database >/dev/null 2>&1 && \
    update-desktop-database "$APPS_DIR" >/dev/null 2>&1 || true

echo "Installed: $DESKTOP"
echo "NetTracker should now appear in your application menu."
