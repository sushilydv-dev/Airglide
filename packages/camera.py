"""One camera shared by the preview, presenter and virtual mouse.

Opening the same webcam from several places at once fails or freezes on most
systems, so a single background thread owns the capture and every feature
reads the latest frame from here.
"""
import sys
import threading
import time

import cv2

from packages.logs import log


def open_capture(source):
    """cv2.VideoCapture with the fastest backend for the OS.

    On Windows the default Media Foundation backend can take 5-15 s to open a
    webcam; DirectShow opens in well under a second. Other platforms (and
    phone-camera URLs) use OpenCV's default.
    """
    if sys.platform == "win32" and isinstance(source, int):
        cap = cv2.VideoCapture(source, cv2.CAP_DSHOW)
        if cap.isOpened():
            return cap
        cap.release()
    return cv2.VideoCapture(source)


class SharedCamera:
    def __init__(self):
        self._lock = threading.Lock()
        self._new_frame = threading.Condition(self._lock)  # wakes readers when a frame arrives
        self._users = set()
        self._source = 0
        self._thread = None
        self._running = False
        self._frame = None
        self._frame_id = 0
        self._gen = 0  # bumps on every start so a stale thread knows to exit
        self.error = None

    # ---- lifecycle -------------------------------------------------------
    def acquire(self, user):
        with self._lock:
            self._users.add(user)
            if not self._running:
                self._start_locked()

    def release(self, user):
        with self._lock:
            self._users.discard(user)
            old = self._stop_locked() if not self._users else None
        self._join(old)

    def set_source(self, source):
        """Switch between the laptop camera (0) and an IP camera URL."""
        with self._lock:
            if source == self._source:
                return
            self._source = source
            if not self._running:
                return
            old = self._stop_locked()
        self._join(old)
        with self._lock:
            if self._users and not self._running:
                self._start_locked()

    def shutdown(self):
        with self._lock:
            self._users.clear()
            old = self._stop_locked()
        self._join(old)

    def _start_locked(self):
        self._running = True
        self._gen += 1
        self.error = None
        self._thread = threading.Thread(target=self._loop, args=(self._source, self._gen), daemon=True)
        self._thread.start()

    def _stop_locked(self):
        # The caller joins the returned thread *after* releasing the lock,
        # because the capture thread needs the lock to publish frames.
        self._running = False
        thread, self._thread = self._thread, None
        self._frame = None
        return thread

    @staticmethod
    def _join(thread):
        if thread and thread is not threading.current_thread():
            thread.join(timeout=3)

    # ---- capture ---------------------------------------------------------
    def _open(self, source):
        cap = open_capture(source)
        if not cap.isOpened() and source != 0:
            log.warning("Could not open camera %s; falling back to the laptop camera", source)
            self.error = "Phone camera unavailable, using laptop camera"
            cap.release()
            cap = open_capture(0)
        if not cap.isOpened():
            self.error = "No camera found (check camera permissions)"
            return None
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        return cap

    def _alive(self, gen):
        return self._running and gen == self._gen

    def _loop(self, source, gen):
        cap = self._open(source)
        if cap is None:
            with self._lock:
                if gen == self._gen:
                    self._running = False
            return
        failures = 0
        try:
            while self._alive(gen):
                ok, frame = cap.read()
                if not ok or frame is None:
                    failures += 1
                    if failures > 50:  # ~2.5 s without frames: try reopening
                        cap.release()
                        cap = self._open(source)
                        if cap is None:
                            break
                        failures = 0
                    time.sleep(0.05)
                    continue
                failures = 0
                frame = cv2.flip(frame, 1)  # mirror so movement feels natural
                with self._lock:
                    if not self._alive(gen):
                        break
                    self._frame = frame
                    self._frame_id += 1
                    self._new_frame.notify_all()
        finally:
            if cap is not None:
                cap.release()

    def read(self, last_id=None, timeout=1.0):
        """Return (frame_id, frame). Waits for a frame newer than last_id."""
        deadline = time.monotonic() + timeout
        with self._new_frame:
            while self._frame is None or self._frame_id == last_id:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return last_id, None
                self._new_frame.wait(remaining)
            return self._frame_id, self._frame.copy()

    @property
    def running(self):
        return self._running


camera = SharedCamera()
