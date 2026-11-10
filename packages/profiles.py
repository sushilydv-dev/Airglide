"""Keyboard shortcuts for each presentation app.

`None` means the app has no shortcut for that action (the action is skipped).
"""
import sys

IS_MAC = sys.platform == "darwin"
MOD = "command" if IS_MAC else "ctrl"

_COMMON = {
    "next": ("right",),
    "prev": ("left",),
    "first": ("home",),
    "last": ("end",),
    "exit": ("esc",),
}

PROFILES = {
    "powerpoint_win": {
        "label": "PowerPoint (Windows)",
        "open_file": True,
        "goto": True,   # typing a slide number + Enter jumps to it
        "keys": {**_COMMON, "start": ("f5",), "blank": ("b",),
                 "laser": ("ctrl", "l"), "pen": ("ctrl", "p"), "arrow": ("ctrl", "a"),
                 "zoom_in": ("+",), "zoom_out": ("-",)},
    },
    "powerpoint_mac": {
        "label": "PowerPoint (Mac)",
        "open_file": True,
        "goto": True,   # typing a slide number + Enter jumps to it
        "keys": {**_COMMON, "start": ("command", "shift", "enter"), "blank": ("b",),
                 "laser": None, "pen": ("command", "p"), "arrow": ("command", "a"),
                 "zoom_in": None, "zoom_out": None},
    },
    "keynote": {
        "label": "Keynote (Mac)",
        "open_file": True,
        "goto": True,   # typing a slide number + Enter jumps to it
        "keys": {**_COMMON, "start": ("option", "command", "p"), "blank": ("b",),
                 "laser": None, "pen": None, "arrow": None, "zoom_in": None, "zoom_out": None},
    },
    "google_slides": {
        "label": "Google Slides (browser)",
        "open_file": False,   # you open the deck in your browser yourself
        "goto": True,   # typing a slide number + Enter jumps to it
        "keys": {**_COMMON, "start": ("command" if IS_MAC else "ctrl", "enter"), "blank": ("b",),
                 "laser": ("l",), "pen": None, "arrow": ("l",), "zoom_in": None, "zoom_out": None},
    },
    "impress": {
        "label": "LibreOffice Impress",
        "open_file": True,
        "goto": True,   # typing a slide number + Enter jumps to it
        "keys": {**_COMMON, "start": ("f5",), "blank": ("b",),
                 "laser": None, "pen": None, "arrow": None, "zoom_in": None, "zoom_out": None},
    },
    "pdf": {
        "label": "PDF viewer",
        "open_file": True,
        "goto": False,  # PDF viewers have no jump-to-page shortcut in slideshow mode
        # Preview's slideshow on a Mac; full screen (F11) elsewhere. Page keys work in
        # Preview, Acrobat and browser PDF viewers alike.
        "keys": {"start": ("command", "shift", "f") if IS_MAC else ("f11",),
                 "next": ("pagedown",), "prev": ("pageup",),
                 "first": ("home",), "last": ("end",), "exit": ("esc",),
                 "blank": None, "laser": None, "pen": None, "arrow": None,
                 "zoom_in": (MOD, "="), "zoom_out": (MOD, "-")},
    },
    "document": {
        "label": "Word / Pages document",
        "open_file": True,
        "goto": False,
        "document": True,   # page through a document instead of slides
        "keys": {"start": None,
                 "next": ("pagedown",), "prev": ("pageup",),
                 "first": ("command", "up") if IS_MAC else ("ctrl", "home"),
                 "last": ("command", "down") if IS_MAC else ("ctrl", "end"),
                 "exit": None, "blank": None, "laser": None, "pen": None, "arrow": None,
                 "zoom_in": (MOD, "="), "zoom_out": (MOD, "-")},
    },
}


def resolve(profile_id, file_path=None):
    """Pick the profile: the user's choice, or a sensible default for the file."""
    path = (file_path or "").lower()
    # Documents and PDFs always use their own profile: slide shortcuts make no sense there.
    if path.endswith((".docx", ".doc")):
        return "document"
    if path.endswith(".pdf"):
        return "pdf"
    if path.startswith("https://docs.google.com/presentation/"):
        return "google_slides"
    if profile_id in PROFILES:
        return profile_id
    if sys.platform == "win32":
        return "powerpoint_win"
    if IS_MAC:
        return "powerpoint_mac"
    return "impress"


def pointer_modes(profile_id):
    """Pointer modes this app supports, in cycle order (always ends with 'off')."""
    keys = PROFILES[profile_id]["keys"]
    modes = [m for m in ("laser", "pen") if keys.get(m)]
    return modes + ["off"]


def choices():
    """Profiles the user can pick for slide decks (documents/PDFs choose automatically)."""
    return [{"id": "auto", "label": "Automatic"}] + [
        {"id": k, "label": v["label"]} for k, v in PROFILES.items() if k not in ("document", "pdf")]
