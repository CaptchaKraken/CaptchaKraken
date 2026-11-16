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
#: A box whose flat inside bleeds out through one low-contrast edge (hCaptcha's dark
#: theme: the bottom outline is nearly the panel's shade, so a ragged tail hangs off
#: the square and fill drops to 0.87) still has a solid core: most rows run nearly
#: edge to edge and almost every column is mostly filled. A disc does neither (about
#: 0.31 of its rows and 0.60 of its columns), nor does a spinner arc or a badge (0).
MIN_FILL_SOLID_CORE = 0.80
SOLID_ROW_FILL, MIN_SOLID_ROWS = 0.95, 0.65
SOLID_COL_FILL, MIN_SOLID_COLS = 0.80, 0.90
#: A tick box is painted one colour: its inside spans at most this many grey levels
#: (5th to 95th percentile). A smooth patch of photo (sky, asphalt, a pail's side)
#: is flat by the gradient test yet spans tens of levels; every tick box measured
#: spans 0.
MAX_SPREAD = 8.0
#: The box sits at the widget's leading edge (left, or right in a right-to-left
#: locale), inset from it by this many box-widths. A flat square further in, or one
#: flush against the edge, is part of a puzzle: a grid tile, a slider handle.
LEADING_INSET = (0.3, 1.2)
#: Around the box is the widget's own flat panel: on at least MIN_PANEL_SIDES sides,
#: PANEL_SHARE of a band just outside the outline sits within MAX_SPREAD grey levels
#: of the band's median. A share, not a range: a label or a test key's warning may
#: crowd a side (live 2026-11-13, German and Russian widgets). Every tick box
#: measured has a second side at least 0.87 flat; a drag card on a puzzle's tray
#: reaches 0.81, a cartoon-grid tile 0.60.
PANEL_BAND = (0.25, 0.30)
MIN_PANEL_SIDES = 2
PANEL_SHARE = 0.85
#: A tick box is painted a neutral shade (white, near-black, grey): the median of
#: max(R,G,B) - min(R,G,B) inside it is 0 on every widget measured. A puzzle's
#: flat coloured tile (a road piece, a red cube face) is well above this.
MAX_CHROMA = 24
#: An unticked box is empty: whatever its flat inside encloses (a check mark, a
#: drag card's drawing, a dot on a counting card) may cover at most this share of it.
MAX_ENCLOSED = 0.01
#: Width over height, both ways.
MAX_ASPECT = 1.25
#: The box's inside, as a share of the widget's height. Every tick box measured is
#: at least 0.16 of it; a letter of the widget's text is at most 0.06.
MIN_SIDE_OF_HEIGHT = 0.10
#: A flat region larger than this share of the height is a panel, not a box.
MAX_SIDE_OF_HEIGHT = 0.60
#: Nor more than this share of the width: the widest measured is hCaptcha's compact
#: card at 0.19, and a tile of a 4x4 puzzle grid is a quarter of its board.
MAX_SIDE_OF_WIDTH = 0.23
#: Smaller than this many pixels is a glyph or a speck, whatever the widget's size.
MIN_SIDE_PX = 12


def _flat(grey: np.ndarray) -> np.ndarray:
    gx = np.zeros_like(grey)
    gy = np.zeros_like(grey)
    gx[:, 1:-1] = grey[:, 2:] - grey[:, :-2]
    gy[1:-1] = grey[2:] - grey[:-2]
    return np.hypot(gx, gy) < FLAT_GRADIENT


def _fills_its_square(mask: np.ndarray) -> bool:
    fill = mask.mean()
    if fill >= MIN_FILL:
        return True
    return (fill >= MIN_FILL_SOLID_CORE
            and (mask.mean(axis=1) >= SOLID_ROW_FILL).mean() >= MIN_SOLID_ROWS
            and (mask.mean(axis=0) >= SOLID_COL_FILL).mean() >= MIN_SOLID_COLS)


def _at_leading_edge(x0: int, x1: int, side: float, w_img: int) -> bool:
    lo, hi = LEADING_INSET
    return any(lo * side <= inset <= hi * side for inset in (x0, w_img - x1))


def _sits_on_a_panel(grey: np.ndarray, x0: int, y0: int, x1: int, y1: int, side: float) -> bool:
    o = max(2, int(round(PANEL_BAND[0] * side)))
    k = max(3, int(round(PANEL_BAND[1] * side)))
    X0, Y0, X1, Y1 = max(0, x0 - o), max(0, y0 - o), x1 + o, y1 + o
    flat_sides = 0
    for band in (grey[max(0, Y0 - k):Y0, X0:X1], grey[Y1:Y1 + k, X0:X1],
                 grey[Y0:Y1, max(0, X0 - k):X0], grey[Y0:Y1, X1:X1 + k]):
        if band.size and np.mean(np.abs(band - np.median(band)) <= MAX_SPREAD) >= PANEL_SHARE:
            flat_sides += 1
    return flat_sides >= MIN_PANEL_SIDES


def find_checkbox(image_path: str) -> Optional[Tuple[int, int, int, int]]:
    """(x, y, w, h) of the tick box in pixels, or None."""
    try:
        with Image.open(image_path) as im:
            rgb = np.asarray(im.convert("RGB"), np.int16)
        grey = np.asarray(Image.fromarray(rgb.astype(np.uint8)).convert("L"), np.float32)
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
        if side > MAX_SIDE_OF_WIDTH * w_img:
            continue
        inside = labels[sl] == i
        if not _fills_its_square(inside):
            continue
        if ndimage.binary_fill_holes(inside).sum() - inside.sum() > MAX_ENCLOSED * inside.size:
            continue
        shade = grey[sl][inside]
        if np.percentile(shade, 95) - np.percentile(shade, 5) > MAX_SPREAD:
            continue
        paint = rgb[sl][inside]
        if np.median(paint.max(axis=1) - paint.min(axis=1)) > MAX_CHROMA:
            continue
        if not _at_leading_edge(x0, x1, side, w_img) or not _sits_on_a_panel(grey, x0, y0, x1, y1, side):
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
