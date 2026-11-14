"""Where the driver clicks first, before any model runs: the tick box of a vendor's
checkbox widget, found in a screenshot of the widget with plain pixel arithmetic.

An unticked tick box is a square of one flat colour (white, near-black or the
widget's own background) closed in by an outline. So: mark every pixel whose
neighbours are the same shade, split those into connected regions, and keep a
region that fills a square, does not touch the screenshot's edge, and is big
next to the widget. A ticked box has a check mark inside, so it is not flat; a
spinner or a passed badge is round, so it does not fill its square; a letter
like ロ is a square too, but a small one. The largest square left is the box.

Neither a false positive nor a false negative raises. Measured on the widgets in
`tests/fixtures/checkbox/` (reCAPTCHA, hCaptcha, Turnstile and CaptchaFox, light
and dark, 1x to 2x, in a language none of the thresholds were tuned against).
"""

from typing import Optional, Tuple

import numpy as np
from PIL import Image
from scipy import ndimage

#: A pixel is flat when its grey level differs from its neighbours (two apart, on
#: each axis) by less than this. Outlines and antialiased glyph edges are well above it.
FLAT_GRADIENT = 24.0
#: The flat region must cover this share of its bounding square: a round spinner
#: or badge covers pi/4 of it.
MIN_FILL = 0.88
#: Width over height, both ways.
MAX_ASPECT = 1.25
#: The box's inside, as a share of the widget's height. Every tick box measured is
#: at least 0.16 of it; a letter of the widget's text is at most 0.06.
MIN_SIDE_OF_HEIGHT = 0.10
#: A flat region larger than this share of the height is a panel, not a box.
MAX_SIDE_OF_HEIGHT = 0.60
#: Smaller than this many pixels is a glyph or a speck, whatever the widget's size.
MIN_SIDE_PX = 12


def _flat(grey: np.ndarray) -> np.ndarray:
    gx = np.zeros_like(grey)
    gy = np.zeros_like(grey)
    gx[:, 1:-1] = grey[:, 2:] - grey[:, :-2]
    gy[1:-1] = grey[2:] - grey[:-2]
    return np.hypot(gx, gy) < FLAT_GRADIENT


def find_checkbox(image_path: str) -> Optional[Tuple[int, int, int, int]]:
    """(x, y, w, h) of the tick box in pixels, or None."""
    try:
        with Image.open(image_path) as im:
            grey = np.asarray(im.convert("L"), np.float32)
    except Exception:
        return None
    h_img, w_img = grey.shape
    if h_img < 3 or w_img < 3:
        return None
    labels, _ = ndimage.label(_flat(grey))
    best = None
    for i, sl in enumerate(ndimage.find_objects(labels), 1):
        if sl is None:
            continue
        y0, y1, x0, x1 = sl[0].start, sl[0].stop, sl[1].start, sl[1].stop
        if y0 == 0 or x0 == 0 or y1 == h_img or x1 == w_img:
            continue
        w, h = x1 - x0, y1 - y0
        side = (w + h) / 2
        if min(w, h) < MIN_SIDE_PX or not 1 / MAX_ASPECT <= w / h <= MAX_ASPECT:
            continue
        if not MIN_SIDE_OF_HEIGHT * h_img <= side <= MAX_SIDE_OF_HEIGHT * h_img:
            continue
        if (labels[sl] == i).sum() < MIN_FILL * w * h:
            continue
        if best is None or side > best[0]:
            best = (side, x0, y0, w, h)
    if best is None:
        return None
    # The flat inside stops a pixel or two short of the outline; grow it back to the box.
    side, x0, y0, w, h = best
    pad = int(round(0.06 * side)) + 1
    x0, y0 = max(0, x0 - pad), max(0, y0 - pad)
    return x0, y0, min(w_img - x0, w + 2 * pad), min(h_img - y0, h + 2 * pad)
