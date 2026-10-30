"""The outlines and numbers drawn over a board's elements.

Each numbered element gets a 1 px outline traced from its MASK, not its box: a
box around a long twisty shape (a chain, a line, a snake of tiles) covers half
the board and names nothing. Its number sits in a small tag of the outline's
colour just outside the object's top edge, so the tag hides the object's
background rather than the object.

The digits are a 5x7 pixel font defined here, not a system font: what the model
was trained on must be what it is shown, on every machine, to the pixel. Each
font pixel is drawn `SCALE` x `SCALE`, so a digit is 15x21 px with 3 px strokes
and spans more than one 16 px vision patch; at 1x a digit was a fifth of a
patch, too small to tell 3 from 8 from 9. The look is frozen. Changing anything
here changes the model's input and needs a retrain.
"""
from __future__ import annotations

from typing import Dict, List, Sequence, Tuple

import numpy as np
from PIL import Image

_GLYPHS = {
    "0": ("01110", "10001", "10011", "10101", "11001", "10001", "01110"),
    "1": ("00100", "01100", "00100", "00100", "00100", "00100", "01110"),
    "2": ("01110", "10001", "00001", "00010", "00100", "01000", "11111"),
    "3": ("11110", "00001", "00001", "01110", "00001", "00001", "11110"),
    "4": ("00010", "00110", "01010", "10010", "11111", "00010", "00010"),
    "5": ("11111", "10000", "11110", "00001", "00001", "10001", "01110"),
    "6": ("00110", "01000", "10000", "11110", "10001", "10001", "01110"),
    "7": ("11111", "00001", "00010", "00100", "01000", "01000", "01000"),
    "8": ("01110", "10001", "10001", "01110", "10001", "10001", "01110"),
    "9": ("01110", "10001", "10001", "01111", "00001", "00010", "01100"),
}
GLYPH_W, GLYPH_H = 5, 7
#: Board pixels per font pixel.
SCALE = 3
#: Tag padding around the digits, px.
PAD = 2
#: Outline and tag colours, by element number: saturated, mutually distinct, and
#: dark enough that white digits read on every one of them.
PALETTE = [
    (230, 25, 75), (0, 130, 200), (60, 160, 40), (145, 30, 180), (245, 110, 0),
    (0, 140, 140), (200, 30, 160), (110, 80, 20), (70, 70, 220), (160, 120, 0),
]


def colour(n: int) -> Tuple[int, int, int]:
    """The colour of element number `n` (1-based)."""
    return PALETTE[(n - 1) % len(PALETTE)]


def _digits(text: str) -> np.ndarray:
    cols = []
    for k, ch in enumerate(text):
        if k:
            cols.append(np.zeros((GLYPH_H, 1), bool))
        cols.append(np.array([[c == "1" for c in row] for row in _GLYPHS[ch]], bool))
    return np.kron(np.hstack(cols), np.ones((SCALE, SCALE), bool))


def tag_size(n: int) -> Tuple[int, int]:
    d = _digits(str(n))
    return d.shape[1] + 2 * PAD, d.shape[0] + 2 * PAD


def outline(mask: Tuple[Tuple[int, int], np.ndarray]) -> List[np.ndarray]:
    """The mask's outer contours, as (N, 2) int arrays of board pixels."""
    import cv2
    (x, y), m = mask
    if not m.size or not m.any():
        return []
    cs, _ = cv2.findContours(np.pad(m.astype(np.uint8), 1), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    return [c.reshape(-1, 2) + np.array([x - 1, y - 1]) for c in cs]


def _anchors(cs: Sequence[np.ndarray], tw: int, th: int) -> List[Tuple[int, int]]:
    """Tag positions (top-left) to try, best first: above the topmost point, left of
    the leftmost, below the bottommost, right of the rightmost."""
    pts = np.vstack(cs)
    top = pts[np.lexsort((pts[:, 0], pts[:, 1]))[0]]
    left = pts[np.lexsort((pts[:, 1], pts[:, 0]))[0]]
    bot = pts[np.lexsort((pts[:, 0], -pts[:, 1]))[0]]
    right = pts[np.lexsort((pts[:, 1], -pts[:, 0]))[0]]
    return [(int(top[0]) - tw // 2, int(top[1]) - th), (int(left[0]) - tw, int(left[1]) - th // 2),
            (int(bot[0]) - tw // 2, int(bot[1]) + 1), (int(right[0]) + 1, int(right[1]) - th // 2),
            (int(top[0]) - tw // 2, int(top[1]) + 1)]


def _overlap(a, b) -> int:
    return max(0, min(a[2], b[2]) - max(a[0], b[0])) * max(0, min(a[3], b[3]) - max(a[1], b[1]))


def draw(image: Image.Image, elements: Sequence[Dict]) -> Image.Image:
    """The board with every element outlined and numbered (1-based, in list order).
    A None keeps its number but draws nothing: a video frame is drawn with
    `elements.on_frame`, so an element carries its track's number on every frame."""
    out = np.array(image.convert("RGB"))
    H, W = out.shape[:2]
    plans = []
    for n, e in enumerate(elements, 1):
        if e is None:                 # a video track absent from this frame
            continue
        cs = outline(e["mask"])
        if not cs:
            x0, y0, x1, y1 = (int(round(v)) for v in e["box"])
            cs = [np.array([[x0, y0], [x1, y0], [x1, y1], [x0, y1]])]
        plans.append((n, cs))
    for n, cs in plans:
        c = colour(n)
        for poly in cs:
            p = np.clip(poly, [0, 0], [W - 1, H - 1])
            out[p[:, 1], p[:, 0]] = c
            # Contours are 8-connected; fill the diagonal steps so the line never
            # reads as dotted at 1 px.
            q = np.roll(p, -1, axis=0)
            diag = (p[:, 0] != q[:, 0]) & (p[:, 1] != q[:, 1])
            out[p[diag, 1], q[diag, 0]] = c
    placed: List[Tuple[int, int, int, int]] = []
    for n, cs in plans:
        tw, th = tag_size(n)
        best = None
        for ax, ay in _anchors(cs, tw, th):
            ax = min(max(ax, 0), W - tw)
            ay = min(max(ay, 0), H - th)
            r = (ax, ay, ax + tw, ay + th)
            cost = sum(_overlap(r, o) for o in placed)
            if best is None or cost < best[0]:
                best = (cost, r)
            if cost == 0:
                break
        x0, y0, x1, y1 = best[1]
        out[y0:y1, x0:x1] = colour(n)
        d = _digits(str(n))
        out[y0 + PAD:y0 + PAD + d.shape[0], x0 + PAD:x0 + PAD + d.shape[1]][d] = (255, 255, 255)
        placed.append(best[1])
    return Image.fromarray(out)
