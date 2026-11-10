"""Presenter mode: control a slideshow with hand gestures.

Which gesture does what comes from settings["gesture_map"]; keyboard shortcuts
for the presentation app come from packages/profiles.py.

Pointer modes (cycled with the "pointer_cycle" gesture, open palm by default):
  laser - the index finger moves PowerPoint's laser pointer
  pen   - the index finger moves the pen; pinch thumb + index to draw
  off   - normal gesture control
"""
import os
import subprocess
import sys
import threading
import time
import webbrowser

import pyautogui

from packages.handlogic import CursorMapper, GestureRecognizer, ZoomTracker, pinch_ratio
from packages.logs import log
from packages.library import present_url
from packages.profiles import PROFILES, pointer_modes, resolve
from packages.settings import ACTIONS, settings
from packages.vision import vision

VOLUME_STEPS = 5
LABEL_SECONDS = 1.5
OPEN_WAIT_S = 6        # time for the presentation app to open the file
BROWSER_WAIT_S = 4     # time to switch to the browser for Google Slides


def is_url(path):
    return str(path).startswith(("https://", "http://"))


def open_file(path):
    if is_url(path):
        webbrowser.open(path)
    elif sys.platform == "win32":
        os.startfile(path)  # noqa: S606 - the user's own file
    elif sys.platform == "darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])


def change_volume(direction):
    """Raise (+1) or lower (-1) the system volume by VOLUME_STEPS key presses' worth.

    On macOS, pyautogui sends volume keys as ordinary key codes, which the
    system ignores (real volume keys are media-key events), so set the output
    volume directly instead."""
    if sys.platform == "darwin":
        step = 6 * VOLUME_STEPS * direction  # macOS volume runs 0-100; a key press is ~6
        script = ("set v to output volume of (get volume settings)\n"
                  f"set volume output volume (v + ({step}))\n"
                  "if (v + ({step})) > 0 then set volume without output muted")
        try:
            subprocess.run(["osascript", "-e", script], capture_output=True, timeout=3)
        except (OSError, subprocess.SubprocessError) as e:
            log.warning("Volume change failed: %s", e)
    else:
        pyautogui.press("volumeup" if direction > 0 else "volumedown", presses=VOLUME_STEPS)


class Presenter:
    def __init__(self, notify=print, on_update=None):
        self._notify = notify
        self._on_update = on_update or (lambda state: None)
        self._thread = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self.paused = False
        self._reset_state()

    def _reset_state(self):
        self.slide, self.total, self.titles = 1, 0, []
        self.plan = []
        self.mode = "off"
        self.started_at = None
        self.last_action, self.last_action_t = "", 0.0
        self.profile_id = None

    # ---- control ---------------------------------------------------------
    @property
    def running(self):
        return self._thread is not None and self._thread.is_alive()

    def start(self, path, slides, plan=None):
        if self.running:
            return
        self._stop.clear()
        self._reset_state()
        self.paused = False
        self.profile_id = resolve(settings.get("presenter_profile"), path)
        if PROFILES[self.profile_id].get("document"):
            # Documents are paged, not slid: a slide counter or plan would be wrong.
            self.total, self.titles, self.plan = 0, [], []
        else:
            self.total = len(slides)
            self.titles = [s.get("title", "") for s in slides]
            self.plan = plan or []
        self._thread = threading.Thread(target=self._run, args=(path,), name="presenter", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=3)
        self._thread = None

    def toggle_pause(self):
        self.paused = not self.paused
        self._notify("Gestures paused" if self.paused else "Gestures resumed")
        self._push()
        return self.paused

    def goto_slide(self, number):
        """Jump to a slide by typing its number + Enter (PowerPoint, Keynote, Slides, Impress)."""
        if not self.running or not self.started_at:
            return {"ok": False, "message": "Start presenting first"}
        if not PROFILES[self.profile_id].get("goto"):
            return {"ok": False, "message": "This app can't jump to a slide number"}
        number = int(number)
        if not 1 <= number <= max(self.total, 1):
            return {"ok": False, "message": "No such slide"}
        pyautogui.write(str(number))
        pyautogui.press("enter")
        self.slide = number
        self._label(f"Go to slide {number}")
        self._push()
        return {"ok": True}

    def _schedule(self, elapsed):
        """Seconds ahead (+) / behind (-) the talk plan, or None without a plan."""
        if not self.plan or not self.started_at or not 0 < self.slide <= len(self.plan):
            return None
        p = self.plan[self.slide - 1]
        if elapsed > p["start"] + p["duration"]:
            return -(elapsed - p["start"] - p["duration"])
        if elapsed < p["start"]:
            return p["start"] - elapsed
        return 0

    def state(self):
        nxt = self.titles[self.slide] if 0 <= self.slide < len(self.titles) else ""
        elapsed = int(time.time() - self.started_at) if self.started_at else 0
        return {
            "started": self.started_at is not None,
            "schedule": self._schedule(elapsed),
            "planned_total": sum(p["duration"] for p in self.plan),
            "running": self.running,
            "paused": self.paused,
            "slide": self.slide,
            "total": self.total,
            "title": self.titles[self.slide - 1] if 0 < self.slide <= len(self.titles) else "",
            "next_title": nxt,
            "elapsed": elapsed,
            "mode": self.mode,
            "last_action": self.last_action if time.time() - self.last_action_t < 3 else "",
            "profile": PROFILES[self.profile_id]["label"] if self.profile_id else "",
            "document": bool(self.profile_id and PROFILES[self.profile_id].get("document")),
        }

    def current_slide(self):
        """(number, title) of the slide we believe is showing, for the chatbot."""
        if not self.running or not self.total:
            return None
        return self.slide, self.state()["title"]

    def _push(self):
        try:
            self._on_update(self.state())
        except Exception as e:
            log.debug("Presenter update failed: %s", e)

    # ---- actions ---------------------------------------------------------
    def _keys(self, action):
        return PROFILES[self.profile_id]["keys"].get(action)

    def _press(self, action):
        keys = self._keys(action)
        if not keys:
            return False
        pyautogui.hotkey(*keys)
        return True

    def _label(self, text):
        self.last_action, self.last_action_t = text, time.time()

    def _do(self, action):
        """Run a mapped action. Returns False when the slideshow should end."""
        if action == "none":
            return True
        if action == "pause":
            self.toggle_pause()
        elif action == "pointer_cycle":
            self._cycle_pointer()
        elif action in ("volume_up", "volume_down"):
            change_volume(1 if action == "volume_up" else -1)
        elif action in ("next", "prev", "first", "last", "blank", "exit"):
            if not self._press(action):
                self._label(f"{ACTIONS[action]} isn't supported here")
                return True
            if action == "next":
                self.slide = min(self.slide + 1, self.total or self.slide + 1)
            elif action == "prev":
                self.slide = max(self.slide - 1, 1)
            elif action == "first":
                self.slide = 1
            elif action == "last" and self.total:
                self.slide = self.total
            elif action == "exit":
                self._label("Exit slideshow")
                return False
        self._label(self._action_label(action))
        log.info("presenter action: %s", action)
        self._push()
        return True

    DOC_LABELS = {"next": "Page down", "prev": "Page up", "first": "Top of document",
                  "last": "End of document"}

    def _action_label(self, action):
        if self.profile_id and PROFILES[self.profile_id].get("document") and action in self.DOC_LABELS:
            return self.DOC_LABELS[action]
        return ACTIONS.get(action, action)

    def _cycle_pointer(self):
        modes = pointer_modes(self.profile_id)
        nxt = modes[(modes.index(self.mode) + 1) % len(modes)] if self.mode in modes else modes[0]
        if self.mode == "pen":
            pyautogui.mouseUp(_pause=False)
        self._press("arrow" if nxt == "off" else nxt)
        self.mode = nxt
        if len(modes) == 1:
            self._label("This app has no laser/pen shortcut")
        else:
            self._label({"laser": "Laser pointer", "pen": "Pen (pinch to draw)", "off": "Pointer off"}[nxt])

    # ---- main loop -------------------------------------------------------
    def _run(self, path):
        vision.acquire("presenter")  # start the camera now so it warms up while the app opens
        try:
            self._session(path)
        except Exception as e:
            log.exception("Presenter crashed")
            self._notify(f"Presenter error: {e}")
        finally:
            vision.clear_overlay("presenter")
            vision.release("presenter")
            self.mode = "off"
            self._notify("Presenter off")
            self._thread_done()

    def _session(self, path):
        profile = PROFILES[self.profile_id]
        if is_url(path):
            # Google Slides link: open it straight in present mode in the browser.
            self._notify("Opening your Google Slides deck in the browser…")
            open_file(present_url(path))
            if self._stop.wait(BROWSER_WAIT_S + 2):
                return
        elif profile["open_file"]:
            self._notify(f"Opening {os.path.basename(path)}…")
            open_file(path)
            if self._stop.wait(OPEN_WAIT_S):
                return
            self._press("start")
        else:
            self._notify(f"Switch to your {profile['label']} tab, starting in {BROWSER_WAIT_S} s")
            if self._stop.wait(BROWSER_WAIT_S):
                return
            self._press("start")
        self.started_at = time.time()
        self._notify(f"Presenter on ({profile['label']})")

        gesture_map = settings.get("gesture_map")
        recognizer = GestureRecognizer(settings.get("hold_frames"), settings.get("cooldown_s"),
                                       long_poses={p for p, a in gesture_map.items() if a in ("pause", "exit")})
        zoom = ZoomTracker()
        screen_w, screen_h = pyautogui.size()
        cursor = None
        pen_down = False
        map_read = time.time()
        last_push = 0.0
        frame_id = None
        try:
            while not self._stop.is_set():
                frame = vision.read(frame_id)
                if frame is None:
                    if vision.status_error():
                        self._notify(vision.status_error())
                        self._stop.wait(1)
                    continue
                frame_id = frame.id
                now = time.time()
                if now - map_read > 1:  # pick up settings changes while presenting
                    gesture_map, map_read = settings.get("gesture_map"), now
                    recognizer.hold_frames = settings.get("hold_frames")
                    recognizer.cooldown_s = settings.get("cooldown_s")
                    recognizer.long_poses = {p for p, a in gesture_map.items() if a in ("pause", "exit")}

                hand = frame.primary
                pose = hand.pose if hand else None
                action_of = lambda p: gesture_map.get(p, "none") if p else None  # noqa: E731

                if self.paused:
                    fired = recognizer.update(pose if action_of(pose) == "pause" else None, now)
                    if fired:
                        self._do("pause")
                elif self.mode != "off" and hand:
                    # Pointer mode: the index finger drives the pointer. Only the
                    # pointer, pause and exit gestures still work.
                    if action_of(pose) in ("pointer_cycle", "pause", "exit"):
                        fired = recognizer.update(pose, now)
                        if fired and not self._do(action_of(fired)):
                            break
                    else:
                        recognizer.update(None, now)
                        if cursor is None:
                            cursor = CursorMapper(screen_w, screen_h, settings.get("mouse_margin"),
                                                  settings.get("mouse_smoothing"), pyautogui.position())
                        h, w = frame.image.shape[:2]
                        x, y = cursor.update(hand.landmarks[8], w, h)
                        pyautogui.moveTo(x, y, _pause=False)
                        if self.mode == "pen":
                            pinched = pinch_ratio(hand.landmarks) < settings.get("click_pinch") + 0.05
                            if pinched != pen_down:
                                (pyautogui.mouseDown if pinched else pyautogui.mouseUp)(_pause=False)
                                pen_down = pinched
                else:
                    if self.mode == "off":
                        cursor = None
                    if pen_down:
                        pyautogui.mouseUp(_pause=False)
                        pen_down = False
                    pointing = [h.landmarks[8] for h in frame.hands[:2] if h.pose == "point"]
                    if settings.get("two_hand_zoom") and len(pointing) == 2:
                        recognizer.update(None, now)
                        z = zoom.update(pointing)
                        if z:
                            self._label("Zoom in" if z == "zoom_in" else "Zoom out")
                            if not self._press(z):
                                self._label("Zoom isn't supported here")
                    else:
                        zoom.update([])
                        fired = recognizer.update(pose, now)
                        if fired and not self._do(action_of(fired)):
                            break

                label = self.last_action if now - self.last_action_t < LABEL_SECONDS else None
                vision.set_overlay("presenter", label=label, progress=recognizer.progress,
                                   mode=self.mode, paused=self.paused)
                if now - last_push > 0.5:
                    self._push()
                    last_push = now
        finally:
            if pen_down:
                pyautogui.mouseUp(_pause=False)

    def _thread_done(self):
        self.started_at = None
        final = {**self.state(), "running": False}  # thread is still alive at this point
        try:
            self._on_update(final)
        except Exception as e:
            log.debug("Presenter update failed: %s", e)
