"""A gutter that is nearly one colour is still a gutter: vendor gutters are literally constant, and a capture's
JPEG or scaling dither once ended the line tracer's walk. Fixtures are synthesised so the test needs no private corpus.
"""

import os
import sys
import tempfile

import numpy as np
import pytest
from scipy import ndimage

from drawing import imwrite

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from captchakraken.tool_calls.find_grid import find_grid


TILE, GAP, PAD = 130, 4, 12
SIDE = PAD * 2 + TILE * 3 + GAP * 2


def _grid_image(gutter_noise=0.0, seed=0):
    rng = np.random.default_rng(seed)
    img = np.full((SIDE, SIDE, 3), 255, np.uint8)
    for r in range(3):
        for c in range(3):
            y = PAD + r * (TILE + GAP)
            x = PAD + c * (TILE + GAP)
            base = rng.integers(25, 110, size=3)
            tile = np.clip(base + rng.normal(0, 16, (TILE, TILE, 3)), 0, 255)
            img[y:y + TILE, x:x + TILE] = tile.astype(np.uint8)
    if gutter_noise:
        white = img.max(axis=2) > 240
        noise = rng.normal(0, gutter_noise, img.shape[:2])
        for ch in range(3):
            ch_v = img[:, :, ch].astype(float)
            ch_v[white] = np.clip(ch_v[white] + noise[white], 0, 255)
            img[:, :, ch] = ch_v.astype(np.uint8)
    return img


def _detect(img):
    path = tempfile.mktemp(suffix=".png")
    imwrite(path, img)
    try:
        return find_grid(path)
    finally:
        os.unlink(path)


def test_a_pristine_grid_is_detected():
    boxes = _detect(_grid_image(gutter_noise=0.0, seed=1))
    assert boxes and len(boxes) == 9


@pytest.mark.parametrize("noise", [3.0, 6.0, 9.0])
def test_a_dithered_gutter_is_still_detected(noise):
    boxes = _detect(_grid_image(gutter_noise=noise, seed=7))
    assert boxes and len(boxes) == 9, (
        f"a grid whose gutters carry {noise} L-units of dither was not detected")


def test_pure_texture_is_still_rejected():
    rng = np.random.default_rng(3)
    photo = np.clip(rng.normal(128, 45, (SIDE, SIDE, 3)), 0, 255).astype(np.uint8)
    photo = ndimage.gaussian_filter(photo, sigma=(1.4, 1.4, 0))
    assert _detect(photo) is None


def test_a_gutter_that_never_returns_is_not_bridged():
    """Spike tolerance is bounded: a tile bleeding across the separator must still end the line."""
    img = _grid_image(gutter_noise=0.0, seed=11)
    x = PAD + TILE
    img[SIDE // 2:, x:x + GAP] = 40
    boxes = _detect(img)
    if boxes:
        col_edges = sorted({b[0] for b in boxes})
        assert x not in col_edges, "walked through a gutter that never recovered"
