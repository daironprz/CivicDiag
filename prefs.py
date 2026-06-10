"""User preferences — stored as JSON in %APPDATA%\\CivicDiag."""

import json
import os

APP_DIR = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")),
                       "CivicDiag")
PREFS_PATH = os.path.join(APP_DIR, "prefs.json")

DEFAULTS = {
    "theme": "dark",              # dark | light
    "mode": "basic",              # basic | advanced
    "large_controls": False,      # bigger buttons for in-car laptop use
    "first_run_done": False,
    "save_folder": os.path.join(os.path.expanduser("~"),
                                "Documents", "CivicDiag"),
    "favorites": [],              # favorite live-data PIDs
    "live_pids": [],              # last selected live PIDs
    "last_port": "",
}


def load_prefs():
    prefs = dict(DEFAULTS)
    try:
        with open(PREFS_PATH, encoding="utf-8") as f:
            prefs.update(json.load(f))
    except (OSError, ValueError):
        pass
    return prefs


def save_prefs(prefs):
    try:
        os.makedirs(APP_DIR, exist_ok=True)
        with open(PREFS_PATH, "w", encoding="utf-8") as f:
            json.dump(prefs, f, indent=2)
    except OSError:
        pass


def ensure_save_folder(prefs):
    folder = prefs.get("save_folder") or DEFAULTS["save_folder"]
    try:
        os.makedirs(folder, exist_ok=True)
    except OSError:
        folder = os.path.expanduser("~")
    return folder
