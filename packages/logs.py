"""Logging to a rotating file plus the console, and the diagnostics report."""
import logging
import logging.handlers
import os
import platform
import sys
from importlib import metadata

from packages import __version__
from packages.config import DATA_DIR, FROZEN

LOG_DIR = os.path.join(DATA_DIR, "logs")
LOG_PATH = os.path.join(LOG_DIR, "airglide.log")

log = logging.getLogger("airglide")


def setup_logging():
    if log.handlers:
        return
    log.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)s [%(threadName)s] %(message)s")
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
    log.addHandler(console)
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            LOG_PATH, maxBytes=1_000_000, backupCount=3, encoding="utf-8")
        file_handler.setFormatter(fmt)
        log.addHandler(file_handler)
    except OSError as e:
        log.warning("File logging disabled: %s", e)


def diagnostics(extra=None):
    """Plain-text report for bug reports. Never includes the API key."""
    from packages.settings import settings

    lines = [
        f"Airglide {__version__} ({'installed app' if FROZEN else 'source'})",
        f"OS: {platform.platform()}",
        f"Python: {sys.version.split()[0]}",
    ]
    for pkg in ("mediapipe", "opencv-contrib-python", "opencv-python", "pywebview",
                "PyAutoGUI", "python-pptx", "pypdf", "pynput", "pystray"):
        try:
            lines.append(f"{pkg}: {metadata.version(pkg)}")
        except metadata.PackageNotFoundError:
            pass
    s = settings.all()
    s.pop("recent", None)
    lines.append(f"Settings: {s}")
    for k, v in (extra or {}).items():
        lines.append(f"{k}: {v}")
    lines.append("")
    lines.append("--- last log lines ---")
    try:
        with open(LOG_PATH, encoding="utf-8", errors="replace") as f:
            lines.extend(f.read().splitlines()[-150:])
    except OSError:
        lines.append("(no log file)")
    return "\n".join(lines)
