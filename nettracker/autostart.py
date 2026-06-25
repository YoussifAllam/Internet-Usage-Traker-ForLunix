"""Manage a freedesktop autostart entry so NetTracker launches on login."""

import os
import sys

APP_ID = "nettracker"


def _autostart_dir():
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(base, "autostart")


def _desktop_path():
    return os.path.join(_autostart_dir(), f"{APP_ID}.desktop")


def _project_root():
    # nettracker/autostart.py -> project root is two levels up
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _exec_command():
    """Best launch command: prefer run.sh, else the current interpreter."""
    run_sh = os.path.join(_project_root(), "run.sh")
    if os.access(run_sh, os.X_OK):
        return run_sh
    main_py = os.path.join(_project_root(), "main.py")
    return f"{sys.executable} {main_py}"


def is_enabled():
    return os.path.exists(_desktop_path())


def save_icon(icon, size=64):
    """Render the QIcon to a PNG in the data dir; return its path or ''."""
    base = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    path = os.path.join(base, APP_ID, "icon.png")
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        pix = icon.pixmap(size, size)
        if pix.save(path, "PNG"):
            return path
    except OSError:
        pass
    return ""


def enable(icon_path=""):
    try:
        os.makedirs(_autostart_dir(), exist_ok=True)
        icon_line = f"Icon={icon_path}\n" if icon_path else ""
        content = (
            "[Desktop Entry]\n"
            "Type=Application\n"
            "Name=NetTracker\n"
            "Comment=Track internet usage\n"
            f"Exec={_exec_command()}\n"
            f"{icon_line}"
            "Terminal=false\n"
            "Categories=Network;Utility;Monitor;\n"
            "X-GNOME-Autostart-enabled=true\n"
        )
        with open(_desktop_path(), "w") as fh:
            fh.write(content)
        return True
    except OSError:
        return False


def disable():
    try:
        os.remove(_desktop_path())
    except OSError:
        pass
