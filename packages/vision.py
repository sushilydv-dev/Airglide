"""Vision service: one thread reads the camera and tracks hands once per frame.

The presenter, virtual mouse, previews and calibration all read results from
here, so hand tracking never runs twice on the same frame. Features publish
what they are doing (gesture label, hold progress, pointer mode, paused) into
`overlay`, and the previews draw it on the video.
"""
import threading
import time
from dataclasses import dataclass, field

import cv2

from packages.camera import camera
from packages.handlogic import (DEFAULT_THRESHOLDS, POSE_NAMES, extension_ratios,
                                palm_size, pose_of)
from packages.logs import log
from packages.settings import settings

HAND_CONNECTIONS = [
    (0, 1), (1, 2), (2, 3), (3, 4), (0, 5), (5, 6), (6, 7), (7, 8), (5, 9), (9, 10),
    (10, 11), (11, 12), (9, 13), (13, 14), (14, 15), (15, 16), (13, 17), (17, 18),
    (18, 19), (19, 20), (0, 17),
]


@dataclass
class Hand:
    landmarks: list
    ratios: list
    fingers: list
    pose: str
    size: float


@dataclass
class Frame:
    id: int
    image: object
    hands: list = field(default_factory=list)
    ts: float = 0.0

    @property
    def primary(self):
        return self.hands[0] if self.hands else None


def camera_source_from_settings():
    choice = settings.get("camera_source")
    if choice == "phone" and settings.get("phone_cam_url"):
        return settings.get("phone_cam_url")
    try:
        return int(choice)
    except ValueError:
        return 0


class VisionService:
    def __init__(self):
        self._lock = threading.Lock()
        self._new_frame = threading.Condition()  # wakes readers when a result is published
        self._users = set()
        self._running = False
        self._gen = 0
        self._thread = None
        self._frame = None
        self._rebuild_tracker = False
        self.error = None
        self._overlay = {}
        self._overlay_owner = None
        self.thresholds = settings.get("calibration") or list(DEFAULT_THRESHOLDS)
        settings.subscribe(self._on_settings)
        camera.set_source(camera_source_from_settings())

    def _on_settings(self, changed):
        if "calibration" in changed:
            self.thresholds = settings.get("calibration") or list(DEFAULT_THRESHOLDS)
        if "detection_confidence" in changed:
            self._rebuild_tracker = True
        if "camera_source" in changed or "phone_cam_url" in changed:
            camera.set_source(camera_source_from_settings())

    # ---- consumers -------------------------------------------------------
    def acquire(self, user):
        with self._lock:
            self._users.add(user)
            if not self._running:
                self._running = True
                self._gen += 1
                self._thread = threading.Thread(target=self._loop, args=(self._gen,),
                                                name="vision", daemon=True)
                self._thread.start()

    def release(self, user):
        with self._lock:
            self._users.discard(user)
            if not self._users:
                self._running = False
                self._frame = None

    def shutdown(self):
        with self._lock:
            self._users.clear()
            self._running = False
            thread = self._thread
        if thread:
            thread.join(timeout=3)
        camera.shutdown()

    def read(self, last_id=None, timeout=1.0):
        deadline = time.monotonic() + timeout
        with self._new_frame:
            while self._frame is None or self._frame.id == last_id:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return None
                self._new_frame.wait(remaining)
            return self._frame

    def status_error(self):
        return self.error or camera.error

    # ---- overlay ---------------------------------------------------------
    def set_overlay(self, owner, **values):
        with self._lock:
            if self._overlay_owner != owner:
                self._overlay = {}
                self._overlay_owner = owner
            self._overlay.update(values)

    def clear_overlay(self, owner):
        with self._lock:
            if self._overlay_owner == owner:
                self._overlay, self._overlay_owner = {}, None

    def overlay(self):
        with self._lock:
            return dict(self._overlay)

    # ---- worker ----------------------------------------------------------
    def _alive(self, gen):
        return self._running and gen == self._gen

    def _make_tracker(self):
        from packages.hands import HandTracker  # heavy import, only when needed
        return HandTracker(detection_confidence=settings.get("detection_confidence"))

    def _loop(self, gen):
        cam_user = f"vision-{gen}"  # unique, so a stale thread can't release a newer one's camera
        camera.acquire(cam_user)
        tracker = None
        frame_id = None
        try:
            while self._alive(gen):
                frame_id, image = camera.read(frame_id)
                if image is None:
                    continue
                if tracker is None or self._rebuild_tracker:
                    if tracker:
                        tracker.close()
                    self._rebuild_tracker = False
                    try:
                        tracker = self._make_tracker()
                        self.error = None
                    except Exception as e:
                        tracker = None
                        self.error = f"Hand tracking unavailable: {e}"
                        log.error(self.error)
                        time.sleep(2)
                        continue
                hands = []
                for lm in tracker.find(image):
                    ratios = extension_ratios(lm)
                    fingers = [int(r > t) for r, t in zip(ratios, self.thresholds)]
                    hands.append(Hand(lm, ratios, fingers, pose_of(fingers), palm_size(lm)))
                hands.sort(key=lambda h: h.size, reverse=True)  # nearest hand first
                if self._alive(gen):
                    with self._new_frame:
                        self._frame = Frame(frame_id, image, hands, time.time())
                        self._new_frame.notify_all()
        except Exception:
            log.exception("Vision loop crashed")
            self.error = "Camera processing stopped unexpectedly (see log)"
        finally:
            if tracker:
                tracker.close()
            camera.release(cam_user)


vision = VisionService()


# ---- drawing for previews -------------------------------------------------
GREEN, WHITE, RED, BLUE, AMBER = (90, 200, 120), (240, 240, 240), (60, 60, 230), (230, 160, 60), (40, 180, 250)


def draw_overlay(frame, overlay):
    """Return a copy of the frame with hand skeletons and feature status drawn on it."""
    img = frame.image.copy()
    h, w = img.shape[:2]
    for i, hand in enumerate(frame.hands):
        lm = hand.landmarks
        color = GREEN if i == 0 else BLUE
        for a, b in HAND_CONNECTIONS:
            cv2.line(img, lm[a], lm[b], color, 2, cv2.LINE_AA)
        for p in lm:
            cv2.circle(img, p, 3, WHITE, -1, cv2.LINE_AA)

    primary = frame.primary
    pose_text = POSE_NAMES.get(primary.pose, "Unknown pose") if primary else "No hand"
    label = overlay.get("label") or pose_text
    _text(img, label, (12, 30), 0.8)
    if overlay.get("label") and primary:
        _text(img, pose_text, (12, 58), 0.55)

    progress = overlay.get("progress", 0.0)
    if primary and progress > 0:
        cx, cy = primary.landmarks[9]
        r = max(18, int(primary.size * 0.5))
        cv2.ellipse(img, (cx, cy), (r, r), -90, 0, 360, (80, 80, 80), 3, cv2.LINE_AA)
        cv2.ellipse(img, (cx, cy), (r, r), -90, 0, int(360 * progress),
                    GREEN if progress >= 1 else AMBER, 4, cv2.LINE_AA)

    mode = overlay.get("mode")
    if mode and mode != "off":
        _badge(img, mode.upper(), (w - 12, 30), RED if mode == "laser" else BLUE)
    if overlay.get("paused"):
        cv2.rectangle(img, (0, h - 44), (w, h), (30, 30, 30), -1)
        _text(img, "PAUSED - hold L-shape to resume", (12, h - 15), 0.6, color=AMBER)
    return img


def _text(img, text, org, scale, color=WHITE):
    cv2.putText(img, text, org, cv2.FONT_HERSHEY_SIMPLEX, scale, (0, 0, 0), 4, cv2.LINE_AA)
    cv2.putText(img, text, org, cv2.FONT_HERSHEY_SIMPLEX, scale, color, 2, cv2.LINE_AA)


def _badge(img, text, right_top, color):
    (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 2)
    x2, y = right_top
    cv2.rectangle(img, (x2 - tw - 16, y - th - 10), (x2, y + 8), color, -1)
    cv2.putText(img, text, (x2 - tw - 8, y), cv2.FONT_HERSHEY_SIMPLEX, 0.6, WHITE, 2, cv2.LINE_AA)
