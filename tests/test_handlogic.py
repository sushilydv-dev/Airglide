import itertools

import pytest

from packages.handlogic import (DEFAULT_THRESHOLDS, LONG_HOLD_FACTOR, POSES, CursorMapper,
                                GestureRecognizer, HoldStill, ZoomTracker, compute_calibration,
                                extension_ratios, fingers_up, pinch_ratio, pose_of)
from tests.handfactory import make_hand


@pytest.mark.parametrize("fingers", [list(p) for p in POSES])
def test_every_pose_is_recognised(fingers):
    assert fingers_up(make_hand(fingers)) == fingers


@pytest.mark.parametrize("fingers", [[1, 1, 1, 1, 1], [0, 0, 0, 0, 0], [1, 0, 0, 0, 1], [0, 1, 1, 0, 0]])
@pytest.mark.parametrize("scale,angle", [(0.5, 0), (2.0, 0), (1.0, 25), (1.0, -30), (0.7, 15)])
def test_detection_is_scale_and_rotation_independent(fingers, scale, angle):
    assert fingers_up(make_hand(fingers, scale=scale, angle_deg=angle)) == fingers


def test_pose_names():
    assert pose_of([1, 1, 1, 1, 1]) == "palm"
    assert pose_of([0, 0, 0, 0, 0]) == "fist"
    assert pose_of([1, 0, 1, 0, 1]) is None


def test_all_pose_tuples_are_unique_and_valid():
    assert len(POSES) == len(set(POSES))
    assert all(len(p) == 5 and set(p) <= {0, 1} for p in POSES)


def test_recognizer_needs_hold_and_fires_once():
    r = GestureRecognizer(hold_frames=3, cooldown_s=0)
    assert [r.update("fist", t) for t in range(5)] == [None, None, "fist", None, None]


def test_recognizer_progress():
    r = GestureRecognizer(hold_frames=4, cooldown_s=0)
    r.update("fist", 0)
    assert r.progress == pytest.approx(0.25)
    r.update("fist", 1)
    assert r.progress == pytest.approx(0.5)
    r.update(None, 2)
    assert r.progress == 0


def test_recognizer_cooldown_delays_second_gesture():
    r = GestureRecognizer(hold_frames=1, cooldown_s=1.0)
    assert r.update("fist", 0.0) == "fist"
    assert r.update("palm", 0.5) is None      # still cooling down
    assert r.update("palm", 1.2) == "palm"    # fires once cooldown has passed


def test_recognizer_flicker_does_not_fire():
    r = GestureRecognizer(hold_frames=3, cooldown_s=0)
    seq = ["fist", "palm", "fist", "palm", "fist", "palm"]
    assert all(r.update(p, i) is None for i, p in enumerate(seq))


def test_long_hold_pose_takes_longer():
    r = GestureRecognizer(hold_frames=2, cooldown_s=0)
    results = [r.update("L", t) for t in range(2 * LONG_HOLD_FACTOR + 2)]
    assert results.index("L") == 2 * LONG_HOLD_FACTOR - 1


def test_long_poses_are_configurable():
    r = GestureRecognizer(hold_frames=2, cooldown_s=0, long_poses={"rock"})
    assert r.update("L", 0) is None and r.update("L", 1) == "L"   # L is now a normal pose
    assert r.required_frames("rock") == 2 * LONG_HOLD_FACTOR


def test_cursor_mapper_clamps_to_screen():
    m = CursorMapper(1920, 1080, margin_frac=0.1, smoothing=1, start=(0, 0))
    assert m.update((0, 0), 640, 480) == (1, 1)            # kept off the fail-safe corner
    assert m.update((640, 480), 640, 480) == (1918, 1078)


def test_bottom_of_screen_reachable_without_leaving_frame():
    m = CursorMapper(1920, 1080, margin_frac=0.15, smoothing=1, start=(0, 0))
    _, y = m.update((320, 480 * 0.7), 640, 480)            # hand at 70% of the frame height
    assert y >= 1078


def test_cursor_adaptive_smoothing_and_deadzone():
    m = CursorMapper(1000, 1000, margin_frac=0, smoothing=8, start=(500, 500))
    # tiny jitter (< dead zone) does not move the cursor
    assert m.update((320 + 0.5, 240), 640, 480)[0] == 500
    # a small move is heavily damped...
    small = CursorMapper(1000, 1000, margin_frac=0, smoothing=8, start=(500, 500))
    sx, _ = small.update((320 + 16, 240), 640, 480)          # target ~525
    assert 500 < sx < 506
    # ...while a big move responds much faster than plain 1/8 smoothing
    big = CursorMapper(1000, 1000, margin_frac=0, smoothing=8, start=(0, 500))
    bx, _ = big.update((640, 240), 640, 480)                # target ~999
    assert bx > 999 / 8 * 3


def test_hold_still_fires_only_when_still():
    hs = HoldStill(seconds=1.0, tolerance=0.05)
    assert not any(hs.update(True, (100 + i * 40, 100), 640, i * 0.1) for i in range(20))  # moving
    hs = HoldStill(seconds=1.0, tolerance=0.05)
    fired = [hs.update(True, (100 + (i % 2), 100), 640, i * 0.1) for i in range(15)]
    assert fired.count(True) == 1 and fired.index(True) == 10
    assert hs.update(False, None, 640, 2.0) is False and hs.progress == 0


def test_zoom_tracker():
    z = ZoomTracker(step=1.3)
    assert z.update([(100, 100), (200, 100)]) is None   # sets baseline
    assert z.update([(100, 100), (240, 100)]) == "zoom_in"
    assert z.update([(100, 100), (150, 100)]) == "zoom_out"
    assert z.update([(100, 100)]) is None               # one hand resets


def test_pinch_ratio():
    hand = make_hand([1, 1, 0, 0, 0])
    assert pinch_ratio(hand) > 0.4
    pinched = list(hand)
    pinched[4] = (hand[8][0] + 3, hand[8][1] + 3)
    assert pinch_ratio(pinched) < 0.1


def test_calibration_between_open_and_fist():
    palm = [extension_ratios(make_hand([1, 1, 1, 1, 1], scale=s)) for s in (0.8, 1.0, 1.2)]
    fist = [extension_ratios(make_hand([0, 0, 0, 0, 0], scale=s)) for s in (0.8, 1.0, 1.2)]
    thresholds, problems = compute_calibration(palm, fist)
    assert problems == []
    for t, o, c in zip(thresholds, palm[1], fist[1]):
        assert c < t < o
    # Calibrated thresholds still classify every pose correctly.
    for pose in POSES:
        assert fingers_up(make_hand(list(pose)), thresholds) == list(pose)


def test_calibration_with_bad_samples_keeps_defaults():
    same = [[1.5] * 5]
    thresholds, problems = compute_calibration(same, same)
    assert thresholds == DEFAULT_THRESHOLDS
    assert len(problems) == 5
    thresholds, problems = compute_calibration([], [])
    assert thresholds == DEFAULT_THRESHOLDS and problems


def test_no_pose_is_ambiguous_with_defaults():
    # Each 5-finger combination maps to at most one pose name.
    combos = list(itertools.product([0, 1], repeat=5))
    names = [POSES.get(c) for c in combos]
    assert len([n for n in names if n]) == len(POSES)
