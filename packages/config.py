"""Paths and secret configuration (API key, model).

Secrets are read from (highest priority first):
  1. Environment variables (GEMINI_API_KEY, GEMINI_MODEL)
  2. config.json (git-ignored; copy config.example.json, or enter the key in the app)
  3. The defaults below

Everything else the user can change lives in settings.py.
"""
import json
import os
import ssl
import sys
import threading

APP_NAME = "Airglide"
FROZEN = getattr(sys, "frozen", False)  # True inside a PyInstaller build

SOURCE_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
RESOURCE_DIR = getattr(sys, "_MEIPASS", SOURCE_ROOT) if FROZEN else SOURCE_ROOT


def _user_data_dir():
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or os.path.expanduser("~\\AppData\\Roaming")
        return os.path.join(base, APP_NAME)
    if sys.platform == "darwin":
        return os.path.expanduser(f"~/Library/Application Support/{APP_NAME}")
    return os.path.join(os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share"), "airglide")


# Running from source keeps data next to the code; an installed app uses the
# per-user app data folder (the app bundle itself is read-only).
DATA_DIR = os.environ.get("AIRGLIDE_DATA_DIR") or (
    _user_data_dir() if FROZEN else os.path.join(SOURCE_ROOT, "data"))
VIEWS_DIR = os.path.join(RESOURCE_DIR, "views")
ASSETS_DIR = os.path.join(RESOURCE_DIR, "Assets")
BUNDLED_MODELS_DIR = os.path.join(RESOURCE_DIR, "models")
CONFIG_PATH = os.path.join(DATA_DIR if (FROZEN or os.environ.get("AIRGLIDE_DATA_DIR")) else SOURCE_ROOT,
                           "config.json")

DEFAULTS = {
    "gemini_api_key": "",
    "gemini_model": "gemini-flash-latest",
    "phone_cam_url": "",  # legacy location; now lives in settings
}

ENV_VARS = {
    "gemini_api_key": "GEMINI_API_KEY",
    "gemini_model": "GEMINI_MODEL",
}

_lock = threading.Lock()


def _read_file():
    if not os.path.exists(CONFIG_PATH):
        return {}
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            data = json.load(f)
        return {k: v for k, v in data.items() if k in DEFAULTS}
    except (OSError, ValueError) as e:
        print(f"[config] Could not read {CONFIG_PATH}: {e}")
        return {}


def load_config():
    config = dict(DEFAULTS)
    config.update(_read_file())
    for key, env in ENV_VARS.items():
        if os.environ.get(env):
            config[key] = os.environ[env]
    return config


CONFIG = load_config()


def save_config(updates):
    """Persist secret settings (e.g. an API key typed into the app)."""
    with _lock:
        data = _read_file()
        data.update({k: v for k, v in updates.items() if k in DEFAULTS})
        os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
        tmp = CONFIG_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, CONFIG_PATH)
        CONFIG.clear()
        CONFIG.update(load_config())


def key_source():
    """Where the API key comes from: 'env', 'file' or None."""
    if os.environ.get("GEMINI_API_KEY"):
        return "env"
    return "file" if _read_file().get("gemini_api_key") else None


def ssl_context():
    """HTTPS context using certifi's CA bundle (python.org builds on macOS
    ship without root certificates)."""
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()
