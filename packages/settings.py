"""User settings, stored as JSON in the data folder.

Every value has a default and (for numbers) an allowed range, so a bad or
hand-edited settings file can never break the app.
"""
import copy
import json
import os
import sys
import threading

from packages.config import CONFIG, DATA_DIR

ACTIONS = {
    "next": "Next slide",
    "prev": "Previous slide",
    "first": "First slide",
    "last": "Last slide",
    "pointer_cycle": "Laser / pen / off",
    "volume_up": "Volume up",
    "volume_down": "Volume down",
    "blank": "Black screen",
    "exit": "Exit slideshow",
    "pause": "Pause / resume",
    "none": "Do nothing",
}

DEFAULT_GESTURE_MAP = {
    "fist": "prev",
    "shaka": "next",
    "four": "first",
    "pinky": "last",
    "palm": "pointer_cycle",
    "point": "volume_up",
    "peace": "volume_down",
    "rock": "exit",
    "L": "pause",
    "three": "blank",
    "thumb": "none",
}

DEFAULTS = {
    "onboarded": False,
    # gestures
    "gesture_map": DEFAULT_GESTURE_MAP,
    "hold_frames": 4,
    "cooldown_s": 1.0,
    "detection_confidence": 0.7,
    "calibration": None,            # list of 5 thresholds, or None for defaults
    "two_hand_zoom": True,
    # virtual mouse
    "mouse_smoothing": 7,
    "mouse_margin": 0.15,
    "click_pinch": 0.3,
    # camera
    "camera_source": "0",           # camera index as text, or "phone"
    "phone_cam_url": "",
    # presenter
    "presenter_profile": "auto",
    "launcher_enabled": True,       # Airglide button floating in the screen corner
    "talk_minutes": 0,              # target talk length; 0 = use the estimate
    "speaking_pace": "normal",      # relaxed / normal / fast
    # app
    "hotkeys_enabled": True,
    "minimize_to_tray": sys.platform == "win32",
    "offline_mode": False,
    "assistant_engine": "local",    # local (on-device model) / gemini
    "local_model": "auto",          # auto = the built-in model (see packages/local_llm.py)
    "check_updates": True,
    "sounds": True,
    "theme": "light",               # light / dark / system
    "text_scale": 1.0,
    "high_contrast": False,
    # library
    "recent": [],
    "current": None,
}

RANGES = {
    "hold_frames": (1, 30),
    "cooldown_s": (0.0, 5.0),
    "detection_confidence": (0.3, 0.95),
    "mouse_smoothing": (1, 20),
    "mouse_margin": (0.0, 0.4),
    "click_pinch": (0.1, 0.8),
    "text_scale": (0.8, 1.6),
    "talk_minutes": (0, 240),
}

CHOICES = {
    "theme": ("light", "dark", "system"),
    "speaking_pace": ("relaxed", "normal", "fast"),
    "assistant_engine": ("local", "gemini"),
    "local_model": ("auto", "tiny"),
}


def _coerce(key, value):
    default = DEFAULTS[key]
    if isinstance(default, bool):
        return bool(value)
    if isinstance(default, (int, float)) and not isinstance(default, bool):
        value = type(default)(float(value)) if isinstance(default, int) else float(value)
        lo, hi = RANGES.get(key, (None, None))
        if lo is not None:
            value = min(max(value, lo), hi)
        return value
    if key == "gesture_map":
        merged = dict(DEFAULT_GESTURE_MAP)
        merged.update({p: a for p, a in dict(value).items() if p in DEFAULT_GESTURE_MAP and a in ACTIONS})
        return merged
    if key == "calibration":
        if value is None:
            return None
        values = [float(v) for v in value]
        if len(values) != 5:
            raise ValueError("calibration needs 5 values")
        return values
    if key == "recent":
        return [dict(e) for e in value]
    if key in CHOICES:
        if value not in CHOICES[key]:
            raise ValueError(f"{key} must be one of {CHOICES[key]}")
        return value
    if isinstance(default, str):
        return str(value)
    return value


class Settings:
    def __init__(self, path):
        self.path = path
        self._lock = threading.RLock()
        self._listeners = []
        self._data = copy.deepcopy(DEFAULTS)
        self._load()

    def _load(self):
        loaded = {}
        if os.path.exists(self.path):
            try:
                with open(self.path, encoding="utf-8") as f:
                    loaded = json.load(f)
            except (OSError, ValueError) as e:
                print(f"[settings] Ignoring unreadable {self.path}: {e}")
        for key, value in loaded.items():
            if key in DEFAULTS:
                try:
                    self._data[key] = _coerce(key, value)
                except (TypeError, ValueError):
                    pass
        # Migrate the phone camera URL from the old config.json location.
        if not self._data["phone_cam_url"] and CONFIG.get("phone_cam_url"):
            self._data["phone_cam_url"] = CONFIG["phone_cam_url"]

    def get(self, key):
        with self._lock:
            return copy.deepcopy(self._data[key])

    def all(self):
        with self._lock:
            return copy.deepcopy(self._data)

    def update(self, changes):
        """Validate and save. Unknown keys and invalid values are ignored.
        Returns the keys that actually changed."""
        changed = []
        with self._lock:
            for key, value in changes.items():
                if key not in DEFAULTS:
                    continue
                try:
                    value = _coerce(key, value)
                except (TypeError, ValueError):
                    continue
                if self._data[key] != value:
                    self._data[key] = value
                    changed.append(key)
            if changed:
                self._save()
        if changed:
            for fn in list(self._listeners):
                try:
                    fn(changed)
                except Exception as e:
                    print(f"[settings] listener error: {e}")
        return changed

    def reset(self, keys):
        self.update({k: copy.deepcopy(DEFAULTS[k]) for k in keys if k in DEFAULTS})

    def subscribe(self, fn):
        self._listeners.append(fn)

    def _save(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self._data, f, indent=2, ensure_ascii=False)
        os.replace(tmp, self.path)


settings = Settings(os.path.join(DATA_DIR, "settings.json"))
