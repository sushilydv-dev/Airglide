"""OS integration: permissions, global hotkeys, tray icon, update check and
single-instance lock. Every part is optional and fails soft."""
import ctypes
import json
import socket
import subprocess
import sys
import threading
import urllib.request
import webbrowser

from packages import __version__
from packages.config import ssl_context
from packages.logs import log

IS_MAC = sys.platform == "darwin"
IS_WIN = sys.platform == "win32"
GITHUB_REPO = "sushilydv-dev/Airglide"


# ---- permissions -----------------------------------------------------------
_AX_LIB = "/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices"
_CF_LIB = "/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation"
BUNDLE_ID = "com.airglide.app"


def accessibility_ok(prompt=False):
    """macOS needs Accessibility permission to send keys / move the mouse.

    Without it macOS silently drops every synthetic key press and mouse event,
    so gestures are recognised but nothing happens. With prompt=True macOS
    adds Airglide to the Accessibility list and shows its "allow" dialog."""
    if not IS_MAC:
        return True
    try:
        ax = ctypes.cdll.LoadLibrary(_AX_LIB)
        if not prompt:
            ax.AXIsProcessTrusted.restype = ctypes.c_bool
            return bool(ax.AXIsProcessTrusted())
        cf = ctypes.cdll.LoadLibrary(_CF_LIB)
        cf.CFDictionaryCreate.restype = ctypes.c_void_p
        cf.CFDictionaryCreate.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
                                          ctypes.c_long, ctypes.c_void_p, ctypes.c_void_p]
        cf.CFRelease.argtypes = [ctypes.c_void_p]
        ax.AXIsProcessTrustedWithOptions.restype = ctypes.c_bool
        ax.AXIsProcessTrustedWithOptions.argtypes = [ctypes.c_void_p]
        keys = (ctypes.c_void_p * 1)(ctypes.c_void_p.in_dll(ax, "kAXTrustedCheckOptionPrompt").value)
        values = (ctypes.c_void_p * 1)(ctypes.c_void_p.in_dll(cf, "kCFBooleanTrue").value)
        options = cf.CFDictionaryCreate(
            None, keys, values, 1,
            ctypes.addressof(ctypes.c_void_p.in_dll(cf, "kCFTypeDictionaryKeyCallBacks")),
            ctypes.addressof(ctypes.c_void_p.in_dll(cf, "kCFTypeDictionaryValueCallBacks")))
        try:
            return bool(ax.AXIsProcessTrustedWithOptions(options))
        finally:
            cf.CFRelease(options)
    except (OSError, ValueError, AttributeError) as e:
        log.warning("Accessibility check failed: %s", e)
        return True


def request_accessibility():
    """Ask for Accessibility permission. Returns True if already granted.

    An installed app is only ad-hoc signed, so a permission granted to an older
    build can linger in System Settings (switch shown on) without applying to
    this one. Clear Airglide's stale entry first so the prompt re-adds it."""
    if accessibility_ok():
        return True
    from packages.config import FROZEN
    if IS_MAC and FROZEN:
        try:
            subprocess.run(["tccutil", "reset", "Accessibility", BUNDLE_ID],
                           capture_output=True, timeout=5)
        except (OSError, subprocess.SubprocessError) as e:
            log.info("Could not reset Accessibility entry: %s", e)
    accessibility_ok(prompt=True)
    log.info("Accessibility permission requested")
    return False


def overlay_mode(on):
    """macOS: while presenting, run as a background ("accessory") app so the
    floating button, quick panel and presenter overlay can appear over a
    full-screen slideshow. macOS keeps a normal Dock app's windows out of other
    apps' full-screen Spaces. The Dock icon is hidden until presenting stops."""
    if not IS_MAC:
        return
    try:
        from AppKit import (NSApp, NSApplicationActivationPolicyAccessory,
                            NSApplicationActivationPolicyRegular)
        from PyObjCTools import AppHelper
        policy = NSApplicationActivationPolicyAccessory if on else NSApplicationActivationPolicyRegular
        AppHelper.callAfter(lambda: NSApp.setActivationPolicy_(policy))
    except Exception as e:
        log.debug("overlay mode: %s", e)


def camera_status():
    """'granted', 'denied', 'undetermined' or 'unknown'.

    On macOS this asks AVFoundation instead of opening the camera, because
    OpenCV cannot show the permission prompt from a background thread."""
    if IS_MAC:
        try:
            import AVFoundation as av
            status = av.AVCaptureDevice.authorizationStatusForMediaType_(av.AVMediaTypeVideo)
            return {0: "undetermined", 1: "denied", 2: "denied", 3: "granted"}.get(status, "unknown")
        except ImportError:
            return "unknown"
    return "granted" if camera_ok() else "denied"


def request_camera_access(on_done=None):
    """Show the macOS camera permission prompt (must run on the main thread)."""
    if not IS_MAC:
        return
    try:
        import AVFoundation as av
        from PyObjCTools import AppHelper
    except ImportError:
        return

    def handler(granted):
        log.info("Camera access %s", "granted" if granted else "denied")
        if on_done:
            on_done(bool(granted))

    AppHelper.callAfter(
        lambda: av.AVCaptureDevice.requestAccessForMediaType_completionHandler_(av.AVMediaTypeVideo, handler))


def camera_ok(index=0):
    from packages.camera import open_capture

    cap = open_capture(index)
    try:
        if not cap.isOpened():
            return False
        ok, _ = cap.read()
        return bool(ok)
    finally:
        cap.release()


def list_cameras(max_index=4):
    """Indices of cameras that open. Slow-ish, so only called from Settings."""
    from packages.camera import open_capture

    found = []
    for i in range(max_index):
        cap = open_capture(i)
        if cap.isOpened():
            found.append(i)
        cap.release()
    return found


SETTINGS_PAGES = {
    "camera": {"darwin": "x-apple.systempreferences:com.apple.preference.security?Privacy_Camera",
               "win32": "ms-settings:privacy-webcam"},
    "accessibility": {"darwin": "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility"},
}


def open_settings_page(kind):
    if kind == "accessibility" and IS_MAC and request_accessibility():
        return True
    url = SETTINGS_PAGES.get(kind, {}).get(sys.platform)
    if not url:
        return False
    if IS_MAC:
        subprocess.Popen(["open", url])
    else:
        import os
        os.startfile(url)  # noqa: S606
    return True


def open_url(url):
    if url.startswith(("https://", "http://")):
        webbrowser.open(url)


# ---- global hotkeys --------------------------------------------------------
HOTKEYS = {"p": "presenter", "m": "mouse", "h": "pause", "a": "show"}


def hotkey_label(letter):
    return f"⌃⌥{letter.upper()}" if IS_MAC else f"Ctrl+Alt+{letter.upper()}"


class Hotkeys:
    """Ctrl+Alt+<letter> anywhere in the OS (Control+Option on a Mac)."""

    def __init__(self, callbacks):
        self._callbacks = callbacks  # action name -> callable
        self._handle = None
        self.enabled = False

    def _fire(self, letter):
        action = HOTKEYS.get(letter)
        fn = self._callbacks.get(action)
        if fn:
            log.info("hotkey: %s", action)
            threading.Thread(target=fn, daemon=True).start()

    def start(self):
        if self._handle:
            return
        try:
            if IS_MAC:
                self._start_mac()
            else:
                self._start_pynput()
            self.enabled = True
        except Exception as e:
            log.warning("Global hotkeys unavailable: %s", e)

    def _start_pynput(self):
        from pynput import keyboard

        mapping = {f"<ctrl>+<alt>+{k}": (lambda k=k: self._fire(k)) for k in HOTKEYS}
        self._handle = keyboard.GlobalHotKeys(mapping)
        self._handle.daemon = True
        self._handle.start()

    def _start_mac(self):
        # pynput's keyboard listener crashes on recent macOS, so use AppKit's
        # event monitors on the main thread instead.
        from AppKit import (NSEvent, NSEventMaskKeyDown, NSEventModifierFlagControl,
                            NSEventModifierFlagOption)
        from PyObjCTools import AppHelper

        wanted = NSEventModifierFlagControl | NSEventModifierFlagOption

        def handle(event):
            if (event.modifierFlags() & wanted) == wanted:
                chars = (event.charactersIgnoringModifiers() or "").lower()
                if chars in HOTKEYS:
                    self._fire(chars)
                    return True
            return False

        def global_handler(event):
            handle(event)

        def local_handler(event):
            return None if handle(event) else event

        def install():
            self._handle = (
                NSEvent.addGlobalMonitorForEventsMatchingMask_handler_(NSEventMaskKeyDown, global_handler),
                NSEvent.addLocalMonitorForEventsMatchingMask_handler_(NSEventMaskKeyDown, local_handler),
            )

        AppHelper.callAfter(install)

    def stop(self):
        if not self._handle:
            return
        try:
            if IS_MAC:
                from AppKit import NSEvent
                for h in self._handle:
                    NSEvent.removeMonitor_(h)
            else:
                self._handle.stop()
        except Exception:
            pass
        self._handle = None
        self.enabled = False


# ---- tray icon (Windows) ---------------------------------------------------
class Tray:
    """System tray icon on Windows. (macOS shows Airglide in the Dock instead;
    a menu-bar icon can't share the main thread with the app window there.)"""

    def __init__(self, icon_path, actions):
        self._icon_path = icon_path
        self._actions = actions  # dict of callables: show, presenter, mouse, pause, quit
        self._icon = None

    @property
    def available(self):
        return self._icon is not None

    def start(self):
        if not IS_WIN:
            return
        try:
            import pystray
            from PIL import Image

            a = self._actions
            menu = pystray.Menu(
                pystray.MenuItem("Show Airglide", lambda: a["show"](), default=True),
                pystray.MenuItem("Presenter on/off", lambda: a["presenter"]()),
                pystray.MenuItem("Virtual mouse on/off", lambda: a["mouse"]()),
                pystray.MenuItem("Pause / resume gestures", lambda: a["pause"]()),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Quit", lambda: a["quit"]()),
            )
            self._icon = pystray.Icon("Airglide", Image.open(self._icon_path), "Airglide", menu)
            self._icon.run_detached()
        except Exception as e:
            log.warning("Tray icon unavailable: %s", e)
            self._icon = None

    def notify(self, message):
        if self._icon:
            try:
                self._icon.notify(message, "Airglide")
            except Exception:
                pass

    def stop(self):
        if self._icon:
            try:
                self._icon.stop()
            except Exception:
                pass
            self._icon = None


# ---- updates ---------------------------------------------------------------
def parse_version(text):
    parts = []
    for piece in str(text).lstrip("vV").split("."):
        digits = "".join(ch for ch in piece if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts + [0] * (3 - len(parts)))[:3]


def check_for_update(current=__version__):
    """Return {"version", "url"} if GitHub has a newer release, else None."""
    req = urllib.request.Request(
        f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest",
        headers={"Accept": "application/vnd.github+json", "User-Agent": "Airglide-updater"},
    )
    try:
        with urllib.request.urlopen(req, timeout=6, context=ssl_context()) as resp:
            data = json.load(resp)
    except Exception as e:  # no releases yet, offline, rate limited...
        log.info("Update check skipped: %s", e)
        return None
    tag = data.get("tag_name", "")
    if parse_version(tag) > parse_version(current):
        return {"version": tag.lstrip("vV"), "url": data.get("html_url") or
                f"https://github.com/{GITHUB_REPO}/releases/latest"}
    return None


# ---- single instance -------------------------------------------------------
class SingleInstance:
    """Only one Airglide at a time. A second launch asks the first to show itself."""

    PORT = 47613

    def __init__(self, on_show):
        self._on_show = on_show
        self._sock = None

    def acquire(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        if IS_WIN:
            sock.setsockopt(socket.SOL_SOCKET, getattr(socket, "SO_EXCLUSIVEADDRUSE", 0), 1)
        try:
            sock.bind(("127.0.0.1", self.PORT))
        except OSError:
            sock.close()
            self._signal_existing()
            return False
        sock.listen(2)
        self._sock = sock
        threading.Thread(target=self._serve, name="single-instance", daemon=True).start()
        return True

    def _signal_existing(self):
        try:
            with socket.create_connection(("127.0.0.1", self.PORT), timeout=1) as s:
                s.sendall(b"show")
        except OSError:
            pass

    def _serve(self):
        while self._sock:
            try:
                conn, _ = self._sock.accept()
            except OSError:
                return
            with conn:
                try:
                    if conn.recv(16) == b"show":
                        self._on_show()
                except OSError:
                    pass

    def release(self):
        if self._sock:
            s, self._sock = self._sock, None
            s.close()
