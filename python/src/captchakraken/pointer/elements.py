"""Detector output -> the numbered elements a board is shown with.

An element is {"class", "box": [x0, y0, x1, y1], "score", "mask": ((x, y), bool
array)} in board pixels; the mask is cropped to its own extent and placed at
(x, y), as `detector.Detector.detect` returns it. Numbers are 1-based in reading
order (rows of ~12 px, then left to right), so a grid's cells number row-major.

`element_at` is the inverse question training asks: which numbered element does
a gold point land on? That decides the id a slot is trained to give.
"""
from __future__ import annotations

from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

from .layout import MAX_ELEMENTS

#: Detector classes that are numbered. `grid` is acted on through its cells, and
#: `click_area` is the well a free click lands in: it holds every point on the
#: board and so names none of them. The detector's `submit` is a button.
NUMBERED = ("cell", "item", "draggable", "drop_target", "slider", "button", "text_input")
RENAME = {"submit": "button"}
#: A point this close to an element's mask (px) still lands on it: anti-aliased edges.
EDGE_PX = 3
#: Detections below this score are not shown. A spare outline costs the model one
#: more option to reject; a missing one cannot be chosen at all.
MIN_SCORE = 0.5


def number(dets: Sequence[Dict], min_score: float = MIN_SCORE) -> List[Dict]:
    """Detector output -> the numbered elements, in reading order."""
    els = []
    for d in dets:
        cls = RENAME.get(d["class"], d["class"])
        if cls in NUMBERED and d["score"] >= min_score:
            els.append({**d, "class": cls})
    els.sort(key=lambda d: (round(((d["box"][1] + d["box"][3]) / 2) / 12),
                            (d["box"][0] + d["box"][2]) / 2))
    return els[:MAX_ELEMENTS]


def scale(els: Sequence[Dict], fx: float, fy: float) -> List[Dict]:
    """Elements detected on one size of a board, moved onto another (fx, fy = new/old)."""
    import cv2
    out = []
    for e in els:
        (x, y), m = e["mask"]
        x0, y0 = int(round(x * fx)), int(round(y * fy))
        w, h = max(1, int(round(m.shape[1] * fx))), max(1, int(round(m.shape[0] * fy)))
        mm = (cv2.resize(m.astype(np.uint8), (w, h), interpolation=cv2.INTER_NEAREST) > 0
              if m.size else np.zeros((0, 0), bool))
        b = e["box"]
        out.append({**e, "box": [b[0] * fx, b[1] * fy, b[2] * fx, b[3] * fy], "mask": ((x0, y0), mm)})
    return out


def _solid(mask) -> Tuple[Tuple[int, int], np.ndarray]:
    """The mask with its enclosed holes filled (a ring's centre is ON the ring) and
    grown by EDGE_PX. An open gap (a chain's break) is not enclosed, so it stays out."""
    import cv2
    (x, y), m = mask
    m = np.pad(m.astype(np.uint8), EDGE_PX + 1)
    filled = m.copy()
    ff = np.zeros((m.shape[0] + 2, m.shape[1] + 2), np.uint8)
    cv2.floodFill(filled, ff, (0, 0), 1)
    m = m | (filled == 0)
    k = np.ones((2 * EDGE_PX + 1, 2 * EDGE_PX + 1), np.uint8)
    m = cv2.dilate(m.astype(np.uint8), k) > 0
    return (x - EDGE_PX - 1, y - EDGE_PX - 1), m


def element_at(pt: Sequence[float], size: Tuple[int, int], els: Sequence[Dict]) -> Optional[int]:
    """0-based index of the smallest element (by mask area) whose mask holds the
    0-1000 point `pt` on a board of `size`, or None."""
    x = int(round(pt[0] * size[0] / 1000.0))
    y = int(round(pt[1] * size[1] / 1000.0))
    best, area = None, None
    for i, e in enumerate(els):
        if not e["mask"][1].size:
            continue
        (mx, my), m = _solid(e["mask"])
        if 0 <= y - my < m.shape[0] and 0 <= x - mx < m.shape[1] and m[y - my, x - mx]:
            a = int(e["mask"][1].sum())
            if area is None or a < area:
                best, area = i, a
    return best
