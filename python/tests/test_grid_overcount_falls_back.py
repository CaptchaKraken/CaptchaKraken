"""Vendor chrome below a board must not turn its 3x3 into a 4x3: comb-reported footer bands dragged the pitch median
down, the grid's own bottom border corroborated, and one generator went 20/20 -> 5/20 until the pitch was
estimated over gaps that could actually be a cell.
"""

import os
import sys
import tempfile

import numpy as np
import pytest

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from captchakraken.tool_calls.find_grid import find_grid

from drawing import fill_circle, fill_rect, hsv_bgr, imwrite

LEFT, TOP, TILE_W, TILE_H, GUTTER, WIDTH = 16, 60, 94, 79, 8, 340
GRID_BOTTOM = TOP + 3 * TILE_H + 2 * GUTTER


def _widget(height):
    canvas = np.full((height, WIDTH, 3), 255, dtype=np.uint8)
    rng = np.random.default_rng(7)
    for r in range(3):
        for c in range(3):
            y, x = TOP + r * (TILE_H + GUTTER), LEFT + c * (TILE_W + GUTTER)
            hue = int((r * 3 + c) * 20)
            base = hsv_bgr(hue, 200, 170)
            patch = np.full((TILE_H, TILE_W, 3), base, dtype=np.int16)
            patch += rng.integers(-18, 19, (TILE_H, TILE_W, 3), dtype=np.int16)
            canvas[y:y + TILE_H, x:x + TILE_W] = np.clip(patch, 0, 255).astype(np.uint8)
    fill_rect(canvas, (0, 0), (WIDTH, 4), (230, 120, 40))
    fill_rect(canvas, (LEFT, 26), (LEFT + 150, 40), (70, 70, 70))
    fill_circle(canvas, (WIDTH - 30, 33), 11, (40, 40, 40))
    for i in range(4):
        x0 = 36 + i * 42
        fill_rect(canvas, (x0, 328), (x0 + 22, 338), (115, 115, 115))
    fill_rect(canvas, (240, 350), (322, 360), (135, 135, 135))
    fill_rect(canvas, (36, 372), (120, 382), (150, 150, 150))
    fd, path = tempfile.mkstemp(suffix=".png")
    os.close(fd)
    imwrite(path, canvas)
    return path


def _boxes(height):
    path = _widget(height)
    try:
        return find_grid(path)
    finally:
        os.unlink(path)


def test_a_short_widget_still_reports_its_3x3():
    """Vendor chrome right under the board (a footer of buttons and labels) is not a row of cells."""
    boxes = _boxes(385)
    assert boxes is not None, "no grid detected on a 3x3 above an ordinary footer"
    assert len(boxes) == 9, f"expected a 3x3, got {len(boxes)} cells"


def test_a_tall_widget_does_not_grow_a_row_into_the_footer():
    """With room below, the line tracer read the footer as a regular fourth row and handed the caller a 4x3 that
    does not exist (it shipped as a known, strict xfail). The element detector sees where the board ends."""
    boxes = _boxes(430)
    assert boxes is not None, "no grid detected"
    assert len(boxes) == 9, f"the footer was read as a fourth row: {len(boxes)} cells"
    assert max(b[3] for b in boxes) <= GRID_BOTTOM + GUTTER, "a cell reaches into the footer"
