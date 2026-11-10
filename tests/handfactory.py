"""Builds synthetic but anatomically plausible hand landmarks for tests."""
import math

# Palm: wrist at origin, fingers point "up" (negative y). Units ~ pixels.
_MCP = {"thumb": (-35, -30), "index": (-30, -95), "middle": (-5, -100),
        "ring": (18, -95), "pinky": (38, -85)}
_SEGMENTS = {"thumb": [30, 28, 25], "index": [40, 25, 22], "middle": [45, 28, 24],
             "ring": [42, 26, 22], "pinky": [32, 20, 18]}
_ORDER = ["thumb", "index", "middle", "ring", "pinky"]


def make_hand(fingers, origin=(320, 400), scale=1.0, angle_deg=0.0):
    """fingers: 5 ints (thumb..pinky), 1 = extended. Returns 21 (x, y) points."""
    pts = [(0.0, 0.0)] * 21
    for i, name in enumerate(_ORDER):
        base = 1 + i * 4
        mx, my = _MCP[name]
        if name == "thumb":
            # CMC (1) near the wrist, MCP (2) further out.
            pts[1] = (-20.0, -15.0)
            pts[2] = (mx, my)
            if fingers[i]:
                direction = (-0.85, -0.5)    # sticking out sideways
                x, y = mx, my
                for j, seg in enumerate(_SEGMENTS[name][1:], start=3):
                    x, y = x + direction[0] * seg, y + direction[1] * seg
                    pts[j] = (x, y)
            else:
                # folded across the palm towards the ring finger base
                pts[3] = (-15.0, -55.0)
                pts[4] = (8.0, -62.0)
            continue
        pts[base] = (mx, my)
        if fingers[i]:
            x, y = mx, my
            for j, seg in enumerate(_SEGMENTS[name]):
                y -= seg
                pts[base + 1 + j] = (x, y)
        else:
            # curled: PIP up a bit, DIP and tip back down into the palm
            pts[base + 1] = (mx, my - 28)
            pts[base + 2] = (mx + 2, my - 15)
            pts[base + 3] = (mx + 3, my + 20)
    a = math.radians(angle_deg)
    out = []
    for x, y in pts:
        rx = x * math.cos(a) - y * math.sin(a)
        ry = x * math.sin(a) + y * math.cos(a)
        out.append((origin[0] + rx * scale, origin[1] + ry * scale))
    return out
