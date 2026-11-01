"""Has the widget painted its puzzle yet, or are we photographing the rebuild hole?

Measured on gt4.geetest.com's slide demo (2026-09-12): 6 of 52 requests carried a board with under 5% ink and
every one came back dead centre. The settle gate cannot catch it because a blank panel is perfectly still.
Structure is measured, not ink, because geetest_v4_svg is line art on white. A caller must treat False as
"wait a moment longer", never "give up": a gate that can refuse to ever take a picture is worse than the blank one.
"""

from __future__ import annotations

from typing import Optional, Sequence

# Trimmed in from every edge: the caption and icon row are chrome that paints early, on a blank board too.
CENTRE_BOX = (0.15, 0.25, 0.85, 0.75)

# Below this is JPEG noise and anti-aliasing on a flat fill.
LEVEL_DELTA = 12

# Blank-versus-anything, not a puzzle density: measured 0.000-0.004 blank against 0.19-0.56 painted.
TEXTURE_FLOOR = 0.015


def centre_texture(path: str, box: Optional[Sequence[float]] = None) -> Optional[float]:
    import numpy as np

    from ..keyframes import read_frame, to_gray

    frame = read_frame(path)
    if frame is None:
        return None
    img = to_gray(frame)
    h, w = img.shape[:2]
    b = tuple(box) if box is not None else CENTRE_BOX
    x1, y1 = int(b[0] * w), int(b[1] * h)
    x2, y2 = int(b[2] * w), int(b[3] * h)
    if x2 - x1 < 8 or y2 - y1 < 8:
        return None
    region = img[y1:y2, x1:x2].astype("int16")
    ground = float(np.median(region))
    return float((abs(region - ground) > LEVEL_DELTA).mean())


def board_is_painted(path: str, floor: Optional[float] = None,
                     box: Optional[Sequence[float]] = None) -> dict:
    f = TEXTURE_FLOOR if floor is None else float(floor)
    t = centre_texture(path, box)
    if t is None:
        return {"painted": None, "texture": None, "floor": f}
    return {"painted": bool(t >= f), "texture": round(t, 5), "floor": f}
