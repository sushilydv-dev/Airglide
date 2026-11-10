"""MediaPipe hand tracking (used only by packages/vision.py).

Uses the MediaPipe Tasks HandLandmarker (the legacy `mp.solutions` API was
removed from MediaPipe). The model file is downloaded once on first use.
"""
import os
import shutil
import time
import urllib.request

import cv2
import mediapipe as mp
from mediapipe.tasks.python import BaseOptions, vision

from packages.config import BUNDLED_MODELS_DIR, DATA_DIR, ssl_context

MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/hand_landmarker/"
    "hand_landmarker/float16/latest/hand_landmarker.task"
)
MODEL_PATH = os.path.join(DATA_DIR, "models", "hand_landmarker.task")


def ensure_model():
    bundled = os.path.join(BUNDLED_MODELS_DIR, "hand_landmarker.task")
    if os.path.exists(bundled):  # shipped inside the installed app
        return bundled
    if os.path.exists(MODEL_PATH):
        return MODEL_PATH
    os.makedirs(os.path.dirname(MODEL_PATH), exist_ok=True)
    print(f"[hands] Downloading hand tracking model to {MODEL_PATH} …")
    tmp = MODEL_PATH + ".part"
    try:
        with urllib.request.urlopen(MODEL_URL, timeout=60, context=ssl_context()) as resp, \
                open(tmp, "wb") as out:
            shutil.copyfileobj(resp, out)
    except Exception as e:
        raise RuntimeError(
            f"Could not download the hand tracking model ({e}). "
            f"Download it manually from {MODEL_URL} to {MODEL_PATH}"
        ) from e
    os.replace(tmp, MODEL_PATH)
    return MODEL_PATH


def _read_model():
    with open(ensure_model(), "rb") as f:
        return f.read()


class HandTracker:
    def __init__(self, detection_confidence=0.7, tracking_confidence=0.6, num_hands=2):
        options = vision.HandLandmarkerOptions(
            # Load from memory: MediaPipe can't open model paths containing
            # non-ASCII characters on Windows (e.g. C:\\Users\\José\\...).
            base_options=BaseOptions(model_asset_buffer=_read_model()),
            running_mode=vision.RunningMode.VIDEO,
            num_hands=num_hands,
            min_hand_detection_confidence=detection_confidence,
            min_hand_presence_confidence=detection_confidence,
            min_tracking_confidence=tracking_confidence,
        )
        self._landmarker = vision.HandLandmarker.create_from_options(options)
        self._last_ts = 0

    def find(self, frame_bgr):
        """Return a list of hands, each a list of 21 (x, y) pixel landmarks."""
        h, w = frame_bgr.shape[:2]
        image = mp.Image(image_format=mp.ImageFormat.SRGB,
                         data=cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB))
        ts = max(int(time.monotonic() * 1000), self._last_ts + 1)  # must strictly increase
        self._last_ts = ts
        result = self._landmarker.detect_for_video(image, ts)
        return [[(int(p.x * w), int(p.y * h)) for p in hand] for hand in result.hand_landmarks]

    def close(self):
        self._landmarker.close()
