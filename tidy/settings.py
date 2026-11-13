"""Settings and the app's own folder (%LOCALAPPDATA%\\Tidy). Logs rotate, so the folder never grows."""
import json
import logging
import logging.handlers
import os
import sys

DEFAULTS = {
    "theme": "system",              # system, light, dark
    "window_mode": "windowed",
    "close_to_tray": False,
    "esc_to_tray": False,
    "esc_ask": True,
    "temp_hours": 24,               # temp files younger than this are left alone
    "installer_days": 30,           # downloaded installers older than this are suggested
    "large_mb": 100,                # the Large files page shows files at least this big
    "drives": [],                   # drives ticked for the scan; empty = every fixed drive
    "delete_mode": "recycle",       # recycle or permanent: the choice last used in Review
    "auto_update": True,            # look for a new version on GitHub a few seconds after starting
    "update_pending": "",           # the version an update was started for (to say if it didn't finish)
}


def data_dir():
    base = os.environ.get("TIDY_DATA") or os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"),
                                                       "Tidy")
    os.makedirs(base, exist_ok=True)
    return base


class Settings:
    def __init__(self, path=None):
        self.path = path or os.path.join(data_dir(), "settings.json")
        self.values = dict(DEFAULTS)
        try:
            with open(self.path, encoding="utf-8") as f:
                saved = json.load(f)
            if isinstance(saved, dict):
                self.values.update(saved)
        except (OSError, ValueError):
            pass

    def get(self, key, default=None):
        return self.values.get(key, DEFAULTS.get(key, default))

    def set(self, key, value):
        if self.values.get(key) == value:
            return
        self.values[key] = value
        tmp = self.path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.values, f, indent=1)
            os.replace(tmp, self.path)
        except OSError:
            logging.getLogger("tidy").warning("could not save settings", exc_info=True)


def log_dir():
    path = os.path.join(data_dir(), "logs")
    os.makedirs(path, exist_ok=True)
    return path


def setup_logging():
    """tidy.log keeps every deletion (what, how, what was skipped), 1 MB x 3 at most."""
    handler = logging.handlers.RotatingFileHandler(os.path.join(log_dir(), "tidy.log"), maxBytes=1024 * 1024,
                                                   backupCount=2, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger("tidy")
    root.setLevel(logging.INFO)
    root.addHandler(handler)

    def crash(kind, value, tb):
        root.critical("crash", exc_info=(kind, value, tb))
        sys.__excepthook__(kind, value, tb)
    sys.excepthook = crash
    return root
