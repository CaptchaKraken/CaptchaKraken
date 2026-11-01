"""The tick box the driver clicks, found by the element detector on real vendor widgets.

A false positive clicks the page background; a false negative never starts the solve.
The widgets in `fixtures/checkbox/` were photographed in a language the detector never
trained on, so passing them means it reads the widget, not that it remembers the picture.
"""

import os

import numpy as np
import pytest
from PIL import Image

from captchakraken.tool_calls.find_checkbox import find_checkbox

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "checkbox")
GRIDS = os.path.join(os.path.dirname(__file__), "fixtures", "grid")

#: Widget picture -> the tick box on it (x0, y0, x1, y1), as the vendor's DOM placed it.
#: GeeTest v4 draws no tick box: its whole "click to verify" bar is the target.
TICK_BOXES = {
    "recaptcha_light.png": (13, 23, 41, 51),
    "recaptcha_dark_compact_2x.png": (26, 57, 82, 113),
    "hcaptcha_dark.png": (16, 23, 46, 53),
    "hcaptcha_light_compact_hover_1.5x.png": (19.5, 24, 64.5, 69),
    "turnstile_light.png": (9, 20.5, 33, 44.5),
    "turnstile_dark_flexible_2x.png": (18, 41, 66, 89),
    "captchafox.png": (16, 18, 40, 42),
    "geetest_v4_bar.png": (0, 0, 260, 50),
}
#: A ticked or passed widget has nothing left to click.
TICKED = ["recaptcha_ticked_1.5x.png", "hcaptcha_ticked.png", "turnstile_passed.png"]


def _iou(a, b):
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    return inter / ((a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter)


@pytest.mark.parametrize("name", sorted(TICK_BOXES))
def test_the_tick_box_of_every_vendor_widget_is_found(name):
    found = find_checkbox(os.path.join(FIXTURES, name))
    assert found is not None, f"no tick box found on {name}"
    x, y, w, h = found
    want = TICK_BOXES[name]
    cx, cy = x + w / 2, y + h / 2
    assert want[0] <= cx <= want[2] and want[1] <= cy <= want[3], (
        f"{name}: the click at {(cx, cy)} lands outside the tick box {want}")
    assert _iou((x, y, x + w, y + h), want) >= 0.5, f"{name}: found {(x, y, w, h)}, not the box {want}"


@pytest.mark.parametrize("name", TICKED)
def test_a_ticked_widget_has_no_box_to_click(name):
    assert find_checkbox(os.path.join(FIXTURES, name)) is None


def test_a_blank_page_reports_nothing_rather_than_guessing(tmp_path):
    path = str(tmp_path / "blank.png")
    Image.fromarray(np.full((300, 400, 3), 255, np.uint8)).save(path)
    assert find_checkbox(path) is None


def test_an_unreadable_path_returns_none_instead_of_raising(tmp_path):
    assert find_checkbox(str(tmp_path / "does-not-exist.png")) is None


def test_a_file_that_is_not_an_image_returns_none_instead_of_raising(tmp_path):
    path = tmp_path / "torn.png"
    path.write_bytes(b"\x89PNG\r\n\x1a\n not the rest of a png")
    assert find_checkbox(str(path)) is None


@pytest.mark.parametrize("name", ["photos_3x3_offcentre.png", "groceries_6x3_mac.png"])
def test_a_tile_of_a_puzzle_board_is_not_a_tick_box(name):
    """A grid tile is a square in a frame; clicking it as the widget would answer the puzzle at random."""
    assert find_checkbox(os.path.join(GRIDS, name)) is None
