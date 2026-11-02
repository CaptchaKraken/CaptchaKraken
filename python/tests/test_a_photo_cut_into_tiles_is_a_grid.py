"""`_is_real_grid` tells a photo grid from a sprite board by what lies behind the cells.

A reCAPTCHA 4x4 is ONE photograph cut into sixteen tiles, so a tile of sky is nearly
flat. The line tracer's flat-cell gate (mean stddev < 25) refused 24 of 343 real 4x4
boards once the element detector's cells stopped at the white gutters; it caught no
click board the background check does not. A sprite board, icons on one colour, is
still refused.
"""
import numpy as np
from PIL import Image

from captchakraken.solver import CaptchaSolver


def _cells(n=4, tile=90, gap=6, x0=10, y0=120):
    return [(x0 + c * (tile + gap), y0 + r * (tile + gap), x0 + c * (tile + gap) + tile, y0 + r * (tile + gap) + tile)
            for r in range(n) for c in range(n)]


def _accepts(path, cells):
    solver = CaptchaSolver.__new__(CaptchaSolver)
    solver._temp_files = []
    return solver._is_real_grid(str(path), cells)


def test_a_smooth_photo_cut_into_sixteen_tiles_is_a_grid(tmp_path):
    """Sky shading top to bottom and left to right: every tile is nearly flat, no two alike."""
    h, w = 520, 400
    yy, xx = np.mgrid[:h, :w].astype(np.float32)
    img = np.stack([90 + 0.25 * xx, 140 + 0.15 * yy, 230 - 0.10 * yy], axis=-1)
    img += np.random.default_rng(0).normal(0, 4, img.shape)
    board = np.clip(img, 0, 255).astype(np.uint8)
    cells = _cells()
    for x1, y1, x2, y2 in cells:                       # white gutters between the tiles
        board[y1 - 3:y1, x1:x2] = board[y2:y2 + 3, x1:x2] = 255
    per_tile = np.mean([board[y1:y2, x1:x2].reshape(-1, 3).std(axis=0).mean() for x1, y1, x2, y2 in cells])
    assert per_tile < 25, "the board must be as flat per tile as the boards the old gate refused"
    path = tmp_path / "sky_4x4.png"
    Image.fromarray(board).save(path)
    assert _accepts(path, cells)


def test_icons_on_one_background_are_a_click_board(tmp_path):
    rng = np.random.default_rng(1)
    board = np.full((520, 400, 3), (236, 240, 244), np.uint8)
    cells = _cells(n=3, tile=110)
    for x1, y1, x2, y2 in cells:
        board[y1 + 35:y2 - 35, x1 + 35:x2 - 35] = rng.integers(0, 255, 3)
    path = tmp_path / "sprites_3x3.png"
    Image.fromarray(board).save(path)
    assert not _accepts(path, cells)
