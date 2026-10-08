"""A board of tall tiles must not be read as a lattice of tile PAIRS.

Six columns of tall tiles fail the near-square cell gate, but every other gutter
spaces a lattice whose cells (two tiles wide) pass it, so a 6x3 board came back
as a 3x3. A 3x3 is what the grid expert answers, so such a board was routed to
an expert trained on photo grids instead of the one trained on it. A candidate
whose every cell is split down its middle by a detected gutter is a sub-sampling
of a finer lattice, not the board.
"""

import os
import sys
import tempfile

import numpy as np
import pytest

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from captchakraken.tool_calls.find_grid import find_grid

cv2 = pytest.importorskip("cv2")


def _board(rows, cols, tile_w, tile_h, gutter=8, margin=16):
    width = 2 * margin + cols * tile_w + (cols - 1) * gutter
    height = 2 * margin + rows * tile_h + (rows - 1) * gutter
    canvas = np.full((height, width, 3), (200, 205, 210), dtype=np.uint8)
    rng = np.random.default_rng(11)
    for r in range(rows):
        for c in range(cols):
            y, x = margin + r * (tile_h + gutter), margin + c * (tile_w + gutter)
            hue = int((r * cols + c) * 9) % 180
            base = cv2.cvtColor(np.uint8([[[hue, 190, 180]]]), cv2.COLOR_HSV2BGR)[0, 0]
            patch = np.full((tile_h, tile_w, 3), base, dtype=np.int16)
            patch += rng.integers(-20, 21, (tile_h, tile_w, 3), dtype=np.int16)
            canvas[y:y + tile_h, x:x + tile_w] = np.clip(patch, 0, 255).astype(np.uint8)
    fd, path = tempfile.mkstemp(suffix=".png")
    os.close(fd)
    cv2.imwrite(path, canvas)
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
