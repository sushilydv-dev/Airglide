"""Pure gesture logic: finger detection, poses, debouncing, calibration and
cursor mapping. No camera / MediaPipe imports, so it is fast to unit test.

Landmarks are 21 (x, y) points in MediaPipe order:
0 wrist, 1-4 thumb, 5-8 index, 9-12 middle, 13-16 ring, 17-20 pinky.
"""
import math

FINGER_NAMES = ["thumb", "index", "middle", "ring", "pinky"]

# Extension ratio above which a finger counts as "up". Ratios are scale and
# rotation independent, so they work at any distance and hand angle.
DEFAULT_THRESHOLDS = [1.25, 1.4, 1.4, 1.4, 1.35]

POSES = {
    (0, 0, 0, 0, 0): "fist",
    (1, 0, 0, 0, 1): "shaka",
    (0, 1, 1, 1, 1): "four",
    (0, 0, 0, 0, 1): "pinky",
    (1, 1, 1, 1, 1): "palm",
    (0, 1, 0, 0, 0): "point",
    (0, 1, 1, 0, 0): "peace",
    (0, 1, 0, 0, 1): "rock",
    (1, 1, 0, 0, 0): "L",
    (0, 1, 1, 1, 0): "three",
    (1, 0, 0, 0, 0): "thumb",
}

POSE_LABELS = {
    "fist": "✊ Fist",
    "shaka": "🤙 Thumb + pinky",
    "four": "✋ Four fingers",
    "pinky": "Pinky only",
    "palm": "🖐 Open palm",
    "point": "☝️ Index only",
    "peace": "✌️ Index + middle",
    "rock": "🤘 Index + pinky",
    "L": "👆 L-shape (thumb + index)",
    "three": "Three fingers",
    "thumb": "👍 Thumb only",
}

# Plain-text names for drawing on video frames (OpenCV can't draw emoji).
POSE_NAMES = {
    "fist": "Fist", "shaka": "Thumb+pinky", "four": "Four fingers", "pinky": "Pinky",
    "palm": "Open palm", "point": "Index", "peace": "Index+middle", "rock": "Index+pinky",
    "L": "L-shape", "three": "Three fingers", "thumb": "Thumb",
}

# Poses that must be held longer, because firing them by accident is costly.
LONG_HOLD_POSES = {"L"}
LONG_HOLD_FACTOR = 6


def dist(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def palm_size(lm):
    return dist(lm[0], lm[9]) or 1.0


def extension_ratios(lm):
    """How extended each finger is (≈1 folded, ≈2 straight)."""
    wrist = lm[0]
    thumb = dist(lm[4], lm[17]) / (dist(lm[2], lm[17]) or 1.0)
    others = [
        dist(lm[tip], wrist) / (dist(lm[mcp], wrist) or 1.0)
        for tip, mcp in ((8, 5), (12, 9), (16, 13), (20, 17))
    ]
    return [thumb] + others


def fingers_up(lm, thresholds=None):
    thresholds = thresholds or DEFAULT_THRESHOLDS
    return [int(r > t) for r, t in zip(extension_ratios(lm), thresholds)]


def pose_of(fingers):
    return POSES.get(tuple(fingers))


def pinch_ratio(lm, a=4, b=8):
    """Distance between two fingertips relative to palm size (thumb-index by default)."""
    return dist(lm[a], lm[b]) / palm_size(lm)


class GestureRecognizer:
    """Fires a pose once it has been held for `hold_frames` frames.

    * A held pose fires only once; change pose to fire again.
    * At least `cooldown_s` seconds between two firings.
    * `progress` (0..1) tells the UI how close the current pose is to firing.
    """

    def __init__(self, hold_frames=4, cooldown_s=1.0, long_poses=None):
        self.hold_frames = max(1, int(hold_frames))
        self.long_poses = set(LONG_HOLD_POSES if long_poses is None else long_poses)
        self.cooldown_s = float(cooldown_s)
        self.candidate = None
        self.streak = 0
        self.fired_current = False
        self.last_fire = -1e9
        self.progress = 0.0

    def required_frames(self, pose):
        return self.hold_frames * (LONG_HOLD_FACTOR if pose in self.long_poses else 1)

    def update(self, pose, now):
        if pose != self.candidate:
            self.candidate, self.streak, self.fired_current = pose, 0, False
        if pose is None:
            self.progress = 0.0
            return None
        self.streak += 1
        need = self.required_frames(pose)
        self.progress = 1.0 if self.fired_current else min(self.streak / need, 1.0)
        if self.fired_current or self.streak < need or now - self.last_fire < self.cooldown_s:
            return None
        self.fired_current = True
        self.last_fire = now
        return pose

    def reset(self):
        self.candidate, self.streak, self.fired_current, self.progress = None, 0, False, 0.0


class CursorMapper:
    """Maps a fingertip in the camera frame to a smoothed screen position.

    * The active area sits a little low in the frame (hands rest below the
      face), so the bottom of the screen is reachable without leaving the view.
    * Smoothing adapts to speed: small movements are damped heavily (no
      jitter), big movements follow quickly (no lag). A tiny dead zone keeps
      the cursor still while the hand rests.
    """

    DEADZONE_PX = 2.0

    def __init__(self, screen_w, screen_h, margin_frac=0.15, smoothing=7, start=None):
        self.screen_w, self.screen_h = screen_w, screen_h
        self.margin_frac = margin_frac
        self.smoothing = max(1.0, float(smoothing))
        self.x, self.y = start if start else (screen_w / 2, screen_h / 2)

    def target(self, point, frame_w, frame_h):
        m = self.margin_frac
        x0, x1 = frame_w * m, frame_w * (1 - m)
        y0 = frame_h * m * 0.6
        y1 = max(frame_h * (1 - m * 2.2), y0 + frame_h * 0.3)
        return (_interp(point[0], x0, x1, 0, self.screen_w - 1),
                _interp(point[1], y0, y1, 0, self.screen_h - 1))

    def update(self, point, frame_w, frame_h):
        tx, ty = self.target(point, frame_w, frame_h)
        dx, dy = tx - self.x, ty - self.y
        d = math.hypot(dx, dy)
        if d > self.DEADZONE_PX:
            base = 1.0 / self.smoothing
            speed = min(d / (0.25 * max(self.screen_w, self.screen_h)), 1.0) ** 2
            alpha = base + (1.0 - base) * speed * 0.75
            self.x += dx * alpha
            self.y += dy * alpha
        # Stay off the exact corners so pyautogui's fail-safe never trips.
        return (min(max(self.x, 1), self.screen_w - 2), min(max(self.y, 1), self.screen_h - 2))


class HoldStill:
    """Fires once when a pose is held *without moving* for `seconds`.

    Used for pause/resume, so pointing around can never trigger it by accident.
    """

    def __init__(self, seconds=1.5, tolerance=0.06):
        self.seconds = seconds
        self.tolerance = tolerance   # allowed drift, as a fraction of the frame width
        self.anchor = None
        self.since = None
        self.fired = False
        self.progress = 0.0

    def update(self, active, point, frame_w, now):
        if not active or point is None:
            self.anchor, self.since, self.fired, self.progress = None, None, False, 0.0
            return False
        if self.anchor is None or dist(point, self.anchor) > self.tolerance * frame_w:
            self.anchor, self.since, self.fired = point, now, False
        self.progress = 1.0 if self.fired else min((now - self.since) / self.seconds, 1.0)
        if not self.fired and now - self.since >= self.seconds:
            self.fired = True
            return True
        return False


def _interp(v, lo, hi, out_lo, out_hi):
    if hi <= lo:
        return out_lo
    t = min(max((v - lo) / (hi - lo), 0.0), 1.0)
    return out_lo + t * (out_hi - out_lo)


class ZoomTracker:
    """Two-hand zoom: both hands pointing, then move them apart / together."""

    def __init__(self, step=1.3):
        self.step = step
        self.baseline = None

    def update(self, hands_points):
        """hands_points: list of index-tip points for hands that are 'point'-ing.
        Returns 'zoom_in', 'zoom_out' or None."""
        if len(hands_points) < 2:
            self.baseline = None
            return None
        d = dist(hands_points[0], hands_points[1])
        if self.baseline is None:
            self.baseline = d
            return None
        if d > self.baseline * self.step:
            self.baseline = d
            return "zoom_in"
        if d < self.baseline / self.step:
            self.baseline = d
            return "zoom_out"
        return None


def compute_calibration(open_samples, fist_samples, min_gap=0.15):
    """Per-finger thresholds from extension-ratio samples of an open palm and a fist.

    Returns (thresholds, problems). Fingers whose open/closed ratios are too
    close keep the default threshold and are reported in `problems`.
    """
    if not open_samples or not fist_samples:
        return list(DEFAULT_THRESHOLDS), ["No hand detected during calibration"]
    thresholds, problems = [], []
    for i, name in enumerate(FINGER_NAMES):
        o = _median([s[i] for s in open_samples])
        c = _median([s[i] for s in fist_samples])
        if o - c < min_gap:
            thresholds.append(DEFAULT_THRESHOLDS[i])
            problems.append(f"{name} was hard to tell apart; using the default")
        else:
            thresholds.append(round(c + (o - c) * 0.5, 3))
    return thresholds, problems


def _median(values):
    s = sorted(values)
    n = len(s)
    return (s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2) if n else 0.0
