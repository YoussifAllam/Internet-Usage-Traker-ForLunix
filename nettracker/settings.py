"""Persistent settings stored as JSON under the user's config dir."""

import json
import os

DEFAULTS = {
    "interface": None,
    "rate_unit": "bytes",  # "bytes" or "bits"
    "cap_enabled": False,
    "cap_limit_gb": 100.0,
    "cap_billing_day": 1,  # 1..28
    "cap_notified": {},  # {"<cycle-key>": [80, 100]}
    "close_to_tray": True,
    "tray_hint_shown": False,
    "track_apps": True,       # accumulate per-app usage in the background
}


def _config_path():
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(base, "nettracker", "settings.json")


class Settings:
    def __init__(self):
        self.path = _config_path()
        self._data = dict(DEFAULTS)
        self.load()

    def load(self):
        try:
            with open(self.path) as fh:
                stored = json.load(fh)
            if isinstance(stored, dict):
                self._data.update(stored)
        except (OSError, json.JSONDecodeError):
            pass

    def save(self):
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            tmp = self.path + ".tmp"
            with open(tmp, "w") as fh:
                json.dump(self._data, fh, indent=2)
            os.replace(tmp, self.path)
        except OSError:
            pass

    def get(self, key, default=None):
        return self._data.get(key, DEFAULTS.get(key, default))

    def set(self, key, value, save=True):
        self._data[key] = value
        if save:
            self.save()
