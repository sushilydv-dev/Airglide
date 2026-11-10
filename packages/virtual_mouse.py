"""Virtual mouse.

  Index finger up            -> move the cursor
  Index + middle, pinched    -> click (once per pinch)
  Index + middle + ring up   -> scroll by moving the hand up / down
  Hold the pause gesture     -> pause / resume (L-shape by default, held still ~1.5 s)
"""
import threading
import time

import pyautogui

from packages.handlogic import CursorMapper, HoldStill, pinch_ratio
from packages.logs import log
from packages.settings import settings
from packages.vision import vision

CLICK_COOLDOWN_S = 0.4
SCROLL_GAIN = 0.12       # scroll steps per pixel of hand movement
PAUSE_HOLD_S = 1.5


class VirtualMouse:
    def __init__(self, notify=print):
        self._notify = notify
        self._thread = None
        self._stop = threading.Event()
        self.paused = False

    @property
    def running(self):
        return self._thread is not None and self._thread.is_alive()

    def start(self):
        if self.running:
            return
        self._stop.clear()
        self.paused = False
        self._thread = threading.Thread(target=self._run, name="mouse", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=3)
        self._thread = None

    def toggle_pause(self):
        self.paused = not self.paused
        self._notify("Virtual mouse paused" if self.paused else "Virtual mouse resumed")
        return self.paused

    def _run(self):
        vision.acquire("mouse")
        screen_w, screen_h = pyautogui.size()
        cursor = CursorMapper(screen_w, screen_h, settings.get("mouse_margin"),
                              settings.get("mouse_smoothing"), pyautogui.position())
        pause_hold = HoldStill(PAUSE_HOLD_S)
        pinched, last_click = False, 0.0
        scroll_y, scroll_acc = None, 0.0
        frame_id = None
        last_settings = time.time()
        self._notify("Virtual mouse on")
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
                if now - last_settings > 1:
                    cursor.smoothing = max(1.0, float(settings.get("mouse_smoothing")))
                    cursor.margin_frac = settings.get("mouse_margin")
                    last_settings = now

                hand = frame.primary
                pose = hand.pose if hand else None
                h, w = frame.image.shape[:2]
                # Pause only when the pause pose is held *still*: pointing with a
                # relaxed thumb looks like an L-shape, but it moves.
                is_pause_pose = bool(pose) and settings.get("gesture_map").get(pose) == "pause"
                if pause_hold.update(is_pause_pose, hand.landmarks[5] if hand else None, w, now):
                    self.toggle_pause()
                label = "Hold still to " + ("resume" if self.paused else "pause") \
                    if is_pause_pose and pause_hold.progress > 0.25 else None
                if hand and not self.paused:
                    f = hand.fingers
                    lm = hand.landmarks
                    if f[1] and not f[2]:
                        x, y = cursor.update(lm[8], w, h)
                        pyautogui.moveTo(x, y, _pause=False)
                        label = label or "Move"
                    is_pinch = bool(f[1] and f[2] and not f[3]
                                    and pinch_ratio(lm, 8, 12) < settings.get("click_pinch"))
                    if is_pinch and not pinched and now - last_click > CLICK_COOLDOWN_S:
                        pyautogui.click(_pause=False)
                        last_click = now
                    if is_pinch:
                        label = "Click"
                    pinched = is_pinch
                    if f[1] and f[2] and f[3] and not f[4]:
                        y = lm[9][1]
                        if scroll_y is not None:
                            scroll_acc += (scroll_y - y) * SCROLL_GAIN
                            steps = int(scroll_acc)
                            if steps:
                                pyautogui.scroll(steps, _pause=False)
                                scroll_acc -= steps
                        scroll_y = y
                        label = "Scroll"
                    else:
                        scroll_y, scroll_acc = None, 0.0
                else:
                    pinched, scroll_y, scroll_acc = False, None, 0.0
                vision.set_overlay("mouse", label=label,
                                   progress=pause_hold.progress if is_pause_pose else 0.0,
                                   paused=self.paused)
        except Exception as e:
            log.exception("Virtual mouse crashed")
            self._notify(f"Virtual mouse error: {e}")
        finally:
            vision.clear_overlay("mouse")
            vision.release("mouse")
            self._notify("Virtual mouse off")
