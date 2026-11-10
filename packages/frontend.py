"""Airglide app: the main window (a single-page app in views/app.html), the
floating corner button + quick panel shown while presenting (views/launcher.html,
views/panel.html) and the Python API they call.

Python pushes changes to the page with `App.emit(kind, payload)`, which calls
`ag.emit(kind, payload)` in JavaScript:
  toast    a notification         changed  state changed, re-fetch it
  frame    camera preview frame   chunk    streamed chatbot text
"""
import base64
import collections
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

if sys.platform == "darwin":
    # We request camera permission ourselves on the main thread (see
    # system.request_camera_access); OpenCV's own attempt fails off-thread.
    os.environ.setdefault("OPENCV_AVFOUNDATION_SKIP_AUTH", "1")

import cv2  # noqa: E402
import webview  # noqa: E402

from packages import __version__, system  # noqa: E402
from packages.camera import camera  # noqa: E402
from packages.chatbot import QUICK_PROMPTS, ChatSession  # noqa: E402
from packages.config import ASSETS_DIR, CONFIG, DATA_DIR, VIEWS_DIR, key_source, save_config  # noqa: E402
from packages.gesture import Presenter  # noqa: E402
from packages.handlogic import POSE_LABELS, POSE_NAMES, compute_calibration  # noqa: E402
from packages.library import Library, is_document, timeline  # noqa: E402
from packages.local_llm import MODELS, Downloader, active_model_id, local_model, runtime_available  # noqa: E402
from packages.logs import LOG_DIR, diagnostics, log, setup_logging  # noqa: E402
from packages.profiles import PROFILES, resolve as resolve_profile  # noqa: E402
from packages.profiles import choices as profile_choices  # noqa: E402
from packages.settings import ACTIONS, DEFAULTS, settings  # noqa: E402
from packages.virtual_mouse import VirtualMouse  # noqa: E402
from packages.vision import draw_overlay, vision  # noqa: E402

ICON_PATH = os.path.join(ASSETS_DIR, "icon.png")
LAUNCHER_SIZE = 52
PANEL_SIZE = (340, 610)
ERROR_WORDS = ("error", "denied", "unavailable", "could not", "couldn't", "no camera", "not found")


def view_url(filename):
    return Path(VIEWS_DIR, filename).resolve().as_uri()  # correct file:// URL on every OS


def play(name):
    if not settings.get("sounds"):
        return
    path = os.path.join(ASSETS_DIR, f"{name}.wav")
    try:
        if sys.platform == "win32":
            import winsound
            winsound.PlaySound(path, winsound.SND_FILENAME | winsound.SND_ASYNC)
        elif sys.platform == "darwin":
            subprocess.Popen(["afplay", path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            subprocess.Popen(["aplay", "-q", path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception as e:
        log.debug("sound: %s", e)


def js(window, code):
    if window is None:
        return
    try:
        window.evaluate_js(code)
    except Exception as e:
        log.debug("evaluate_js failed: %s", e)


def _excerpt(text, limit=160):
    text = text.split("Notes: ", 1)[0]
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    body = " · ".join(lines[1:]) if len(lines) > 1 else ""
    return body[:limit] + ("…" if len(body) > limit else "")


# ---- camera preview streamed into the main window -----------------------------
class Preview:
    def __init__(self, app, size=(640, 480), fps=15):
        self._app = app
        self._size = size
        self._fps = fps
        self._stop = threading.Event()
        self._thread = None
        self.users = set()  # "main" window and/or the quick "panel"

    @property
    def running(self):
        return self._thread is not None and self._thread.is_alive()

    def start(self, user="main"):
        self.users.add(user)
        if self.running and not self._stop.is_set():
            return
        if self.running:  # stopping: let it finish, then start a fresh loop
            self._thread.join(timeout=2)
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="preview", daemon=True)
        self._thread.start()

    def stop(self, user=None):
        """Stop showing frames to `user`; the camera stops when nobody needs it (None = everyone)."""
        if user is None:
            self.users.clear()
        else:
            self.users.discard(user)
        if not self.users:
            self._stop.set()

    def _loop(self):
        vision.acquire("preview")
        frame_id, last_error = None, None
        gesture_map, map_t = settings.get("gesture_map"), 0
        try:
            while not self._stop.is_set():
                frame = vision.read(frame_id)
                if frame is None:
                    err = vision.status_error()
                    if err and err != last_error:
                        self._app.emit_frame({"error": err}, self.users)
                        last_error = err
                    continue
                last_error = None
                frame_id = frame.id
                if time.time() - map_t > 1:
                    gesture_map, map_t = settings.get("gesture_map"), time.time()
                overlay = vision.overlay()
                pose = frame.primary.pose if frame.primary else None
                action = gesture_map.get(pose, "none") if pose else "none"
                if not overlay and pose and action != "none":
                    overlay = {"label": f"-> {ACTIONS[action]}"}  # gesture tester
                if pose:
                    self._app.gesture_seen = True
                img = cv2.resize(draw_overlay(frame, overlay), self._size)
                ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 72])
                if ok:
                    self._app.emit_frame({
                        "img": base64.b64encode(buf).decode("ascii"),
                        "pose": pose,
                        "pose_label": POSE_LABELS.get(pose, ""),
                        "action": ACTIONS.get(action) if action != "none" else "",
                        "hands": len(frame.hands),
                    }, self.users)
                self._stop.wait(1 / self._fps)
        finally:
            vision.release("preview")


# ---- app controller ------------------------------------------------------------
class App:
    def __init__(self):
        self.library = Library(settings)
        self.presenter = Presenter(notify=self.notify, on_update=self._on_presenter)
        self.mouse = VirtualMouse(notify=self.notify)
        self.window = None
        self.launcher = None   # floating logo button in the screen corner
        self._launcher_pos = (None, None)
        self.panel = None      # quick panel it opens
        self.update_info = None
        self.gesture_seen = False
        self.activity = collections.deque(maxlen=40)
        self._calibration = {"palm": [], "fist": []}
        self._chat = None
        self._chat_for = object()
        self._camera_check = None   # result of the last explicit camera test (non-macOS)
        self.downloader = Downloader(on_progress=lambda st: self.emit(
            "model", {k: st.get(k) for k in ("state", "progress", "done", "total", "error")}))
        self.preview = Preview(self)
        self.hotkeys = system.Hotkeys({
            "presenter": self.toggle_presenter,
            "mouse": self.toggle_mouse,
            "pause": self.toggle_pause,
            "show": self.show_main,
        })
        self.tray = system.Tray(ICON_PATH, {
            "show": self.show_main, "presenter": self.toggle_presenter,
            "mouse": self.toggle_mouse, "pause": self.toggle_pause, "quit": self.quit,
        })
        settings.subscribe(self._on_settings)

    # -- messaging --
    def emit(self, kind, payload=None):
        code = f"window.ag && ag.emit({json.dumps(kind)}, {json.dumps(payload)})"
        js(self.window, code)
        if kind in ("changed", "presenter", "toast"):
            js(self.panel, code)
            js(self.launcher, f"window.setActive && setActive({json.dumps(self.feature_active())})")

    def emit_frame(self, payload, users):
        code = f"window.ag && ag.emit('frame', {json.dumps(payload)})"
        if "main" in users:
            js(self.window, code)
        if "panel" in users:
            js(self.panel, code)

    def feature_active(self):
        if self.presenter.running:
            return "paused" if self.presenter.paused else "on"
        if self.mouse.running:
            return "paused" if self.mouse.paused else "on"
        return "off"

    def notify(self, message, level=None):
        if level is None:
            low = message.lower()
            level = "error" if any(w in low for w in ERROR_WORDS) else "info"
        log.info("status: %s", message)
        item = {"t": time.time(), "message": message, "level": level}
        self.activity.appendleft(item)
        self.emit("toast", item)
        self.emit("changed")

    def _on_settings(self, changed):
        if "launcher_enabled" in changed:
            if settings.get("launcher_enabled") and self.presenter.running:
                self.open_launcher()
            elif not settings.get("launcher_enabled"):
                self.close_launcher()
        if "hotkeys_enabled" in changed:
            (self.hotkeys.start if settings.get("hotkeys_enabled") else self.hotkeys.stop)()
        appearance = {"theme", "text_scale", "high_contrast"}
        if appearance & set(changed):
            js(self.panel, f"window.applyAppearance && applyAppearance({json.dumps(self.appearance())})")
        self.emit("changed")

    def appearance(self):
        return {k: settings.get(k) for k in ("theme", "text_scale", "high_contrast")}

    # -- state --
    def plan(self, slides=None):
        slides = self.library.slides() if slides is None else slides
        return timeline(slides, settings.get("talk_minutes"), settings.get("speaking_pace"))

    def checks(self):
        cam = system.camera_status() if system.IS_MAC else (
            "granted" if camera.running else self._camera_check or "unknown")
        items = [
            {"id": "camera", "label": "Camera access", "ok": cam == "granted",
             "detail": {"granted": "Camera is ready", "denied": "Blocked: allow it in system settings",
                        "undetermined": "Waiting for your permission",
                        "unknown": "Not checked yet"}.get(cam, cam),
             "action": "camera"},
        ]
        if system.IS_MAC:
            acc = system.accessibility_ok()
            items.append({"id": "accessibility", "label": "Accessibility permission", "ok": acc,
                          "detail": "Airglide can press keys for you" if acc
                          else "Needed to control slides and the mouse", "action": "accessibility"})
        cur = self.library.current()
        items += [
            {"id": "presentation", "label": "Presentation loaded", "ok": bool(cur),
             "detail": f"{cur['name']} · {cur['slides']} {self._unit(cur)}" if cur
             else "Add a deck, PDF, Word document or Google Slides link",
             "action": "add"},
            {"id": "calibration", "label": "Hand calibrated", "ok": bool(settings.get("calibration")),
             "detail": "Tuned to your hand" if settings.get("calibration") else "Optional: 10 seconds",
             "action": "calibrate"},
            {"id": "gesture", "label": "Test a gesture", "ok": self.gesture_seen,
             "detail": "Your hand was recognised" if self.gesture_seen else "Show your hand to the camera",
             "action": "gestures"},
        ]
        a = self.assistant_info()
        items.append({"id": "assistant", "label": "AI assistant", "ok": a["ready"], "optional": True,
                      "detail": a["detail"], "action": "assistant"})
        return items

    @staticmethod
    def _unit(entry):
        kind = entry.get("kind")
        return "sections" if is_document(kind) else "pages" if kind == "pdf" else "slides"

    def assistant_info(self):
        """Chatbot status for the UI. Deliberately doesn't name the model."""
        dl = self.downloader.status(active_model_id(settings.get("local_model")))
        installed = dl["state"] == "ready"
        ready = installed and runtime_available()
        detail = ("Ready to answer questions" if ready
                  else "Adding the chatbot…" if dl["state"] == "downloading" else "Add the chatbot")
        engine = "local"
        return {"engine": engine, "ready": ready, "installed": installed, "detail": detail,
                "download": {k: dl.get(k) for k in ("state", "progress", "done", "total", "error")},
                "runtime": runtime_available()}

    def state(self):
        cur = self.library.current()
        slides = self.library.slides() if cur else []
        plan = self.plan(slides)
        profile_id = resolve_profile(settings.get("presenter_profile"), self.library.current_path())
        p = self.presenter.state()
        return {
            "version": __version__,
            "platform": sys.platform,
            "onboarded": settings.get("onboarded"),
            "presentation": {**cur, "unit": self._unit(cur)} if cur else None,
            "recent": [{**e, "unit": self._unit(e)} for e in self.library.recent()],
            "slides": [{**step, "excerpt": _excerpt(s.get("text", ""))} for step, s in zip(plan, slides)],
            "plan_total": sum(x["duration"] for x in plan),
            "talk_minutes": settings.get("talk_minutes"),
            "presenter": {**p, "running": self.presenter.running},
            "mouse": {"running": self.mouse.running, "paused": self.mouse.paused},
            "preview": self.preview.running and "main" in self.preview.users,
            "profile": {"id": profile_id, "label": PROFILES[profile_id]["label"],
                        "goto": PROFILES[profile_id].get("goto", False),
                        "document": PROFILES[profile_id].get("document", False)},
            "checks": self.checks(),
            "hotkeys": [{"keys": system.hotkey_label(k), "action": a} for k, a in system.HOTKEYS.items()]
                       if self.hotkeys.enabled else [],
            "update": self.update_info,
            "appearance": self.appearance(),
            "has_key": bool(CONFIG.get("gemini_api_key")),
            "offline": settings.get("offline_mode"),
            "assistant": self.assistant_info(),
            "activity": list(self.activity)[:20],
        }

    def _on_presenter(self, state):
        if not state.get("running"):
            self.close_launcher()
            system.overlay_mode(False)
        self.emit("presenter", state)

    # -- features --
    def add_presentation(self):
        result = self.window.create_file_dialog(
            webview.FileDialog.OPEN,
            file_types=("Presentations and documents (*.pptx;*.pdf;*.docx;*.doc)",
                        "PowerPoint (*.pptx)", "PDF (*.pdf)", "Word (*.docx;*.doc)"),
        )
        if not result:
            return {"ok": False}
        path = result[0] if isinstance(result, (list, tuple)) else result
        try:
            entry = self.library.add(path)
        except Exception as e:
            log.exception("Could not add presentation")
            self.notify(f"Could not load that file: {e}", "error")
            return {"ok": False, "message": str(e)}
        unit = "sections" if is_document(entry["kind"]) else "pages" if entry["kind"] == "pdf" else "slides"
        self.notify(f"{entry['name']} is ready · {entry['slides']} {unit}", "success")
        return {"ok": True, "entry": entry}

    def add_link(self, url):
        try:
            entry = self.library.add_link(url)
        except ValueError as e:
            return {"ok": False, "message": str(e)}
        except Exception as e:
            log.exception("Could not add Google Slides link")
            return {"ok": False, "message": f"Couldn't add that link: {e}"}
        if entry["has_text"]:
            self.notify(f"{entry['name']} is ready · {entry['slides']} slides", "success")
        else:
            self.notify("Google Slides deck added. Share it as \"Anyone with the link\" so the timeline "
                        "and assistant can read its slides; presenting works either way.", "info")
        return {"ok": True, "entry": entry}

    def toggle_presenter(self):
        if self.presenter.running:
            self.presenter.stop()
            self.close_launcher()
            system.overlay_mode(False)
            self.emit("changed")
            return False
        path = self.library.current_path()
        if not path:
            self.notify("Add a presentation first", "error")
            return False
        if not self._can_control():
            return False
        if self.mouse.running:
            self.mouse.stop()
        slides = self.library.slides()
        self.presenter.start(path, slides, self.plan(slides))
        system.overlay_mode(True)
        if settings.get("launcher_enabled"):
            self.open_launcher()
        play("button_click")
        self.emit("changed")
        return True

    def _can_control(self):
        """macOS drops synthetic key presses and mouse events from apps without
        Accessibility permission, so gestures would be seen but do nothing."""
        if system.request_accessibility():
            return True
        self.notify("Allow Airglide under System Settings → Privacy & Security → Accessibility, "
                    "then quit and reopen Airglide. Gestures can't press keys or move the mouse until then.",
                    "error")
        self.emit("changed")
        return False

    def toggle_mouse(self):
        if self.mouse.running:
            self.mouse.stop()
            self.emit("changed")
            return False
        if not self._can_control():
            return False
        if self.presenter.running:
            self.presenter.stop()
        self.mouse.start()
        play("button_click")
        self.emit("changed")
        return True

    def toggle_pause(self):
        if self.presenter.running:
            result = self.presenter.toggle_pause()
        elif self.mouse.running:
            result = self.mouse.toggle_pause()
        else:
            self.notify("Nothing to pause: start presenting or the virtual mouse first")
            return False
        self.emit("changed")
        return result

    def chat(self):
        """Chat session for the current presentation (rebuilt when it changes)."""
        cur = self.library.current()
        key = cur["id"] if cur else None
        if self._chat is None or key != self._chat_for:
            self._chat = ChatSession(cur["name"] if cur else None, self.library.slides(),
                                     current_slide=self.presenter.current_slide,
                                     unit=self._unit(cur) if cur else "slides",
                                     downloader=self.downloader)
            self._chat_for = key
        return self._chat

    # -- calibration --
    def calibrate_sample(self, kind, seconds=2.0):
        """Collect extension ratios of the nearest hand for `seconds`."""
        if kind not in self._calibration:
            return {"ok": False, "message": "Unknown pose"}
        samples, frame_id = [], None
        vision.acquire("calibration")
        try:
            end = time.time() + seconds
            while time.time() < end:
                frame = vision.read(frame_id, timeout=0.5)
                if frame is None:
                    continue
                frame_id = frame.id
                if frame.primary:
                    samples.append(frame.primary.ratios)
        finally:
            vision.release("calibration")
        self._calibration[kind] = samples
        return {"ok": len(samples) >= 5, "count": len(samples),
                "message": "" if len(samples) >= 5 else "Couldn't see your hand. Try again"}

    def calibrate_finish(self):
        thresholds, problems = compute_calibration(self._calibration["palm"], self._calibration["fist"])
        if self._calibration["palm"] and self._calibration["fist"]:
            settings.update({"calibration": thresholds})
        self._calibration = {"palm": [], "fist": []}
        return {"ok": True, "thresholds": thresholds, "problems": problems}

    # -- windows --
    def show_main(self):
        if self.window:
            try:
                self.window.show()
                self.window.restore()
            except Exception:
                pass

    # -- corner button + quick panel --
    def open_launcher(self):
        if self.launcher:
            return
        try:
            screen = webview.screens[0]
            x, y = screen.width - LAUNCHER_SIZE - 16, 40
        except Exception:
            x, y = None, None
        self._launcher_pos = (x, y)
        self.launcher = webview.create_window(
            "Airglide button", url=view_url("launcher.html"), js_api=LauncherApi(self),
            width=LAUNCHER_SIZE, height=LAUNCHER_SIZE, x=x, y=y, frameless=True, on_top=True,
            resizable=False, focus=False, transparent=True, shadow=False, background_color="#FFFFFF")
        self.launcher.events.shown += lambda: _float_everywhere(self.launcher)
        self.launcher.events.closed += lambda: setattr(self, "launcher", None)

    def _launcher_xy(self):
        """Top-left of the corner button. Read from the native window (the user
        may have dragged it); pywebview's own lookup can block forever."""
        fallback = self._launcher_pos
        native = getattr(self.launcher, "native", None) if self.launcher else None
        if not system.IS_MAC or native is None:
            return fallback
        try:
            from AppKit import NSScreen
            frame = native.frame()
            screen = NSScreen.screens()[0].frame()  # the menu-bar screen: AppKit's y origin
            return (int(frame.origin.x),
                    int(screen.size.height - frame.origin.y - frame.size.height))
        except Exception as e:
            log.debug("launcher position: %s", e)
            return fallback

    def close_launcher(self):
        self.close_panel()
        w, self.launcher = self.launcher, None
        if w:
            try:
                w.destroy()
            except Exception:
                pass

    def toggle_panel(self):
        if self.panel:
            self.close_panel()
            return False
        x = y = None
        try:
            screen = webview.screens[0]
            lx, ly = self._launcher_xy()
            # Open below the button, on whichever side keeps it on screen.
            x = lx + LAUNCHER_SIZE - PANEL_SIZE[0] if lx + LAUNCHER_SIZE / 2 > screen.width / 2 else lx
            y = ly + LAUNCHER_SIZE + 8
            if y + PANEL_SIZE[1] > screen.height:
                y = max(ly - PANEL_SIZE[1] - 8, 0)
            x = min(max(x, 8), screen.width - PANEL_SIZE[0] - 8)
        except Exception:
            pass
        self.panel = webview.create_window(
            "Airglide", url=view_url("panel.html"), js_api=PanelApi(self),
            width=PANEL_SIZE[0], height=PANEL_SIZE[1], x=x, y=y, frameless=True, on_top=True,
            resizable=False, focus=False, background_color="#FFFFFF")
        self.panel.events.shown += lambda: _float_everywhere(self.panel)

        def on_closed():
            self.panel = None
            self.preview.stop("panel")

        self.panel.events.closed += on_closed
        self.emit("changed")
        return True

    def close_panel(self):
        panel, self.panel = self.panel, None
        self.preview.stop("panel")
        if panel:
            try:
                panel.destroy()
            except Exception:
                pass

    def return_focus(self):
        """Clicking the button or panel makes Airglide the active app, so the
        slideshow would stop receiving the keys gestures press. Hand focus back."""
        if system.IS_MAC and (self.presenter.running or self.mouse.running):
            try:
                from AppKit import NSApp
                from PyObjCTools import AppHelper
                AppHelper.callAfter(lambda: NSApp.deactivate())
            except Exception as e:
                log.debug("return focus: %s", e)

    def panel_state(self):
        cur = self.library.current()
        gesture_map = settings.get("gesture_map")
        return {
            "active": self.feature_active(),
            "presenter": {"running": self.presenter.running, "paused": self.presenter.paused,
                          "mode": self.presenter.mode,
                          "slide": self.presenter.slide, "total": self.presenter.total},
            "mouse": {"running": self.mouse.running, "paused": self.mouse.paused},
            "presentation": cur["name"] if cur else None,
            "camera": self.preview.running and "panel" in self.preview.users,
            "gestures": [{"pose": p, "label": POSE_LABELS[p], "action": ACTIONS[a]}
                         for p, a in gesture_map.items() if a != "none" and p in POSE_LABELS],
            "two_hand_zoom": settings.get("two_hand_zoom"),
            "hotkeys": [{"keys": system.hotkey_label(k), "action": a} for k, a in system.HOTKEYS.items()]
                       if self.hotkeys.enabled else [],
        }

    # -- lifecycle --
    def on_started(self):
        if system.camera_status() == "undetermined":
            system.request_camera_access(
                lambda ok: self.notify("Camera ready" if ok else "Camera access denied: allow it in System Settings",
                                       "success" if ok else "error"))
        if settings.get("hotkeys_enabled"):
            self.hotkeys.start()
        self.tray.start()
        play("startup_sound")
        if settings.get("check_updates") and not settings.get("offline_mode"):
            threading.Thread(target=self._check_updates, daemon=True).start()

    def _check_updates(self):
        self.update_info = system.check_for_update()
        if self.update_info:
            self.notify(f"Airglide {self.update_info['version']} is available", "success")

    def on_closing(self):
        """Closing the window hides it to the tray when that's enabled (Windows)."""
        if self.tray.available and settings.get("minimize_to_tray"):
            self.window.hide()
            self.tray.notify("Airglide is still running in the tray")
            return False
        return True

    def shutdown(self):
        self.downloader.cancel()
        local_model.unload()
        self.preview.stop()
        self.presenter.stop()
        self.mouse.stop()
        vision.shutdown()
        self.hotkeys.stop()
        self.tray.stop()

    def quit(self):
        self.shutdown()
        self.close_launcher()
        w, self.window = self.window, None
        if w:
            try:
                w.destroy()
            except Exception:
                pass


# ---- API for the main window (method names are what JavaScript calls) ----------
class Api:
    def __init__(self, app):
        self._app = app

    # state
    def get_state(self):
        return self._app.state()

    def get_settings(self):
        s = settings.all()
        s.pop("recent", None)
        return {
            "settings": s,
            "defaults": {k: v for k, v in DEFAULTS.items() if k not in ("recent", "current")},
            "actions": ACTIONS,
            "poses": [{"id": p, "label": POSE_LABELS[p], "name": POSE_NAMES[p]} for p in POSE_LABELS],
            "profiles": profile_choices(),
            "has_key": bool(CONFIG.get("gemini_api_key")),
            "key_source": key_source(),
            "model": CONFIG.get("gemini_model"),
            "tray_supported": sys.platform == "win32",
            "platform": sys.platform,
            "version": __version__,
            "update": self._app.update_info,
            "data_dir": DATA_DIR,
            "assistant_size": MODELS[active_model_id(settings.get("local_model"))]["size"],
            "runtime": runtime_available(),
        }

    def save(self, changes):
        return {"ok": True, "changed": settings.update(changes or {})}

    def reset(self, keys):
        settings.reset(keys)
        return self.get_settings()

    # library
    def add_presentation(self):
        return self._app.add_presentation()

    def add_link(self, url):
        return self._app.add_link(url)

    def select_presentation(self, entry_id):
        try:
            self._app.library.select(entry_id)
            return {"ok": True}
        except ValueError as e:
            return {"ok": False, "message": str(e)}

    def remove_presentation(self, entry_id):
        self._app.library.remove(entry_id)
        return {"ok": True}

    # features
    def toggle_presenter(self):
        return self._app.toggle_presenter()

    def toggle_mouse(self):
        return self._app.toggle_mouse()

    def toggle_pause(self):
        return self._app.toggle_pause()

    def goto_slide(self, number):
        return self._app.presenter.goto_slide(number)

    def start_preview(self):
        self._app.preview.start("main")
        return True

    def stop_preview(self):
        self._app.preview.stop("main")
        return True

    # calibration
    def calibrate_sample(self, kind):
        return self._app.calibrate_sample(kind)

    def calibrate_finish(self):
        return self._app.calibrate_finish()

    # assistant
    def chat_status(self):
        return self._app.chat().status()

    def chat_send(self, text, msg_id=""):
        text = (text or "").strip()
        if not text:
            return {"ok": False, "error": "Type a question first."}
        return self._app.chat().send(text, lambda c: self._app.emit("chunk", {"id": msg_id, "text": c}))

    def chat_quick(self, kind, msg_id=""):
        prompt = QUICK_PROMPTS.get(kind)
        if not prompt:
            return {"ok": False, "error": "Unknown prompt"}
        return {"prompt": prompt, **self.chat_send(prompt, msg_id)}

    def chat_about_slide(self, number, msg_id=""):
        prompt = f"Explain slide {int(number)} and give me two talking points for it."
        return {"prompt": prompt, **self.chat_send(prompt, msg_id)}

    def chat_clear(self):
        self._app.chat().clear()
        return True

    # on-device chatbot
    def assistant_status(self):
        return self._app.assistant_info()

    def install_assistant(self):
        """Download the built-in chatbot model (resumes if it was interrupted)."""
        if not runtime_available():
            return {"ok": False, "message": "The chatbot engine isn't installed. Run pip install -r requirements.txt."}
        if settings.get("offline_mode"):
            return {"ok": False, "message": "Offline mode is on. Turn it off to add the chatbot."}
        self._app.downloader.start(active_model_id(settings.get("local_model")))
        self._app.emit("changed")
        return {"ok": True}

    def cancel_install(self):
        self._app.downloader.cancel()
        return True

    def remove_assistant(self):
        self._app.downloader.cancel()
        local_model.unload()
        for model_id in MODELS:
            Downloader.delete(model_id)
        self._app.emit("changed")
        return {"ok": True}

    # setup
    def set_api_key(self, key):
        save_config({"gemini_api_key": (key or "").strip()})
        self._app.emit("changed")
        return {"ok": True, "has_key": bool(CONFIG.get("gemini_api_key")), "source": key_source()}

    def set_model(self, model):
        save_config({"gemini_model": (model or "").strip() or "gemini-flash-latest"})
        return {"ok": True, "model": CONFIG.get("gemini_model")}

    def check_camera(self):
        """Explicit camera test (opens the camera briefly unless it's already in use)."""
        if system.IS_MAC:
            status = system.camera_status()
            if status == "undetermined":
                system.request_camera_access(lambda ok: self._app.emit("changed"))
        else:
            status = "granted" if camera.running or system.camera_ok() else "denied"
            self._app._camera_check = status
        self._app.emit("changed")
        return status

    def open_permission(self, kind):
        return system.open_settings_page(kind)

    def finish_onboarding(self):
        settings.update({"onboarded": True})
        self._app.notify("You're all set. Add a presentation to begin.", "success")
        return True

    def list_cameras(self):
        if camera.running:
            return {"ok": False, "message": "Turn off the camera preview and features first", "cameras": []}
        return {"ok": True, "cameras": system.list_cameras()}

    # misc
    def diagnostics(self):
        return diagnostics({"Update": self._app.update_info,
                            "Camera error": vision.status_error(),
                            "Hotkeys active": self._app.hotkeys.enabled})

    def open_log_folder(self):
        os.makedirs(LOG_DIR, exist_ok=True)
        if sys.platform == "win32":
            os.startfile(LOG_DIR)  # noqa: S606
        else:
            subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", LOG_DIR])

    def check_updates(self):
        self._app.update_info = system.check_for_update()
        return {"update": self._app.update_info, "version": __version__}

    def open_url(self, url):
        system.open_url(url)

    def clear_activity(self):
        self._app.activity.clear()
        return True


class LauncherApi:
    def __init__(self, app):
        self._app = app

    def appearance(self):
        return self._app.appearance()

    def active(self):
        return self._app.feature_active()

    def toggle_panel(self):
        opened = self._app.toggle_panel()
        if not opened:
            self._app.return_focus()
        return opened


class PanelApi:
    def __init__(self, app):
        self._app = app

    def appearance(self):
        return self._app.appearance()

    def get_state(self):
        return self._app.panel_state()

    def _done(self, result):
        self._app.return_focus()
        return result

    def toggle_presenter(self):
        return self._done(self._app.toggle_presenter())

    def toggle_mouse(self):
        return self._done(self._app.toggle_mouse())

    def toggle_pause(self):
        return self._done(self._app.toggle_pause())

    def set_camera(self, on):
        (self._app.preview.start if on else self._app.preview.stop)("panel")
        return self._done(bool(on))

    def show_main(self):
        self._app.close_panel()
        self._app.show_main()

    def close(self):
        self._app.close_panel()
        self._app.return_focus()


def _float_everywhere(window):
    """macOS: keep a floating window visible on every Space, including over a
    full-screen slideshow."""
    if not system.IS_MAC or window is None:
        return
    try:
        from AppKit import (NSWindowCollectionBehaviorCanJoinAllSpaces,
                            NSWindowCollectionBehaviorFullScreenAuxiliary)
        from PyObjCTools import AppHelper

        def apply():
            native = getattr(window, "native", None)
            if native is not None:
                native.setCollectionBehavior_(NSWindowCollectionBehaviorCanJoinAllSpaces
                                              | NSWindowCollectionBehaviorFullScreenAuxiliary)
        AppHelper.callAfter(apply)
    except Exception as e:
        log.debug("float everywhere: %s", e)


# ---- entry point -------------------------------------------------------------
def _window_size():
    width, height = 1240, 820
    try:
        screen = webview.screens[0]
        width = min(width, screen.width - 60)
        height = min(height, screen.height - 80)
    except Exception:
        pass
    return max(width, 980), max(height, 660)


def main():
    setup_logging()
    log.info("Airglide %s starting", __version__)
    app = App()
    instance = system.SingleInstance(on_show=app.show_main)
    if not instance.acquire():
        log.info("Airglide is already running - showing the existing window")
        return

    width, height = _window_size()
    app.window = webview.create_window(
        "Airglide",
        url=view_url("app.html"),
        js_api=Api(app),
        width=width,
        height=height,
        min_size=(980, 660),
        background_color="#F3F5FB",
        text_select=True,
    )
    app.window.events.closing += app.on_closing

    def on_closed():
        app.window = None
        app.quit()

    app.window.events.closed += on_closed
    try:
        webview.start(app.on_started)
    finally:
        app.shutdown()
        instance.release()
        log.info("Airglide stopped")
