"""A board of tall tiles must not be read as a lattice of tile PAIRS.

A 6x3 board read as a 3x3 is routed to the expert trained on photo grids
instead of the one trained on it, so the detector must return every tile.
"""

import os
import sys
import tempfile

import numpy as np
import pytest

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from captchakraken.tool_calls.find_grid import find_grid

from drawing import hsv_bgr, imwrite


def _board(rows, cols, tile_w, tile_h, gutter=8, margin=16):
    width = 2 * margin + cols * tile_w + (cols - 1) * gutter
    height = 2 * margin + rows * tile_h + (rows - 1) * gutter
    canvas = np.full((height, width, 3), (200, 205, 210), dtype=np.uint8)
    rng = np.random.default_rng(11)
    for r in range(rows):
        for c in range(cols):
            y, x = margin + r * (tile_h + gutter), margin + c * (tile_w + gutter)
            hue = int((r * cols + c) * 9) % 180
            base = hsv_bgr(hue, 190, 180)
            patch = np.full((tile_h, tile_w, 3), base, dtype=np.int16)
            patch += rng.integers(-20, 21, (tile_h, tile_w, 3), dtype=np.int16)
            canvas[y:y + tile_h, x:x + tile_w] = np.clip(patch, 0, 255).astype(np.uint8)
    fd, path = tempfile.mkstemp(suffix=".png")
    os.close(fd)
    imwrite(path, canvas)
    return path


def _boxes(*shape):
    path = _board(*shape)
    try:
        return find_grid(path)
    finally:
        os.unlink(path)


def test_six_columns_of_tall_tiles_are_not_a_3x3():
    boxes = _boxes(3, 6, 56, 92)
    assert not boxes or len(boxes) != 9, (
        "a 6x3 board of tall tiles was read as a 3x3 of tile pairs")


def test_a_square_3x3_is_still_found():
    boxes = _boxes(3, 3, 90, 90)
    assert boxes is not None and len(boxes) == 9, f"expected a 3x3, got {boxes and len(boxes)}"
