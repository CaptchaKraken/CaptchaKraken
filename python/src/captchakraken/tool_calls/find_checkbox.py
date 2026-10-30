"""Where the driver clicks first, before any model runs. Neither a false positive nor a false negative raises."""

import cv2
import numpy as np
from typing import Optional, Tuple

Box = Tuple[int, int, int, int]


def find_checkbox(image_path: str) -> Optional[Box]:
    img = cv2.imread(image_path)
    if img is None:
        return None

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    # A dark-theme widget draws a light outline round a near-black box: the light-theme search on the negative.
    return _find(gray) or _find(255 - gray)


def _inside(a: Box, b: Box) -> bool:
    return b[0] <= a[0] and b[1] <= a[1] and a[0] + a[2] <= b[0] + b[2] and a[1] + a[3] <= b[1] + b[3]


def _find(gray: np.ndarray) -> Optional[Box]:
    _, binary = cv2.threshold(gray, 200, 255, cv2.THRESH_BINARY_INV)

    # Every contour, not only the outermost: a widget's own frame encloses its box.
    contours, _ = cv2.findContours(binary, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)

    height, width = gray.shape[:2]
    image_area = width * height

    candidates = []

    for cnt in contours:
        x, y, w, h = cv2.boundingRect(cnt)
        area = w * h
        aspect_ratio = float(w) / h

        if not (0.8 < aspect_ratio < 1.2):
            continue

        # Below 20px a glyph is indistinguishable from a box.
        if w < 20 or h < 20:
            continue

        # Above 5% of the image it is a panel or the challenge frame, not the checkbox inside one.
        if not (0.001 * image_area < area < 0.05 * image_area):
            continue

        # Every checkbox widget puts its box at the left; a square on the right is a logo or a badge.
        if x + w / 2 > width / 2:
            continue

        contour_area = cv2.contourArea(cnt)
        extent = contour_area / area
        if extent < 0.8:
            continue

        # A checkbox is empty inside; without this the first tile of a 3x3 grid gets clicked as the widget.
        roi = gray[y+5:y+h-5, x+5:x+w-5]
        if roi.size > 0:
            std_dev = np.std(roi)
            if std_dev > 35.0:
                continue

        # A widget sets its box on a flat panel; a square hole cut in a photo is surrounded by the photo.
        x0, y0 = max(0, x - 6), max(0, y - 6)
        ring = gray[y0:y + h + 6, x0:x + w + 6].astype(float)
        ring[y - y0:y - y0 + h, x - x0:x - x0 + w] = np.nan
        if np.nanstd(ring) > 20:
            continue

        candidates.append((x, y, w, h))

    # An outline traces twice, round its outside and round its hole; the hole is the same box.
    candidates = [c for c in candidates if not any(o is not c and _inside(c, o) for o in candidates)]

    # Many candidates means a grid, not a checkbox page.
    if len(candidates) > 2:
        return None

    if not candidates:
        return None

    best_candidate = max(candidates, key=lambda c: c[2] * c[3])
    return best_candidate
