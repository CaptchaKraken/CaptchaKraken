"""Each test is one of the five gates: a false positive clicks the page background, a false negative never starts the solve."""

import cv2
import numpy as np
import pytest

from captchakraken.tool_calls.find_checkbox import find_checkbox


def _canvas(path, size=(400, 300)):
    img = np.full((size[1], size[0], 3), 255, dtype=np.uint8)
    return img


def _save(path, img):
    cv2.imwrite(str(path), img)
    return str(path)


def _draw_square(img, x, y, side, thickness=3, colour=(0, 0, 0)):
    cv2.rectangle(img, (x, y), (x + side, y + side), colour, thickness)
    return img


def test_a_plain_square_outline_is_found(tmp_path):
    img = _draw_square(_canvas(tmp_path), 120, 90, 40)
    box = find_checkbox(_save(tmp_path / "cb.png", img))

    assert box is not None, "a 40px square outline on a white page was not detected"
    x, y, w, h = box
    assert abs(x - 120) <= 6 and abs(y - 90) <= 6, f"box landed at {(x, y)}, not near (120, 90)"
    assert abs(w - h) <= 4, "a checkbox must come back roughly square"


def test_a_blank_page_reports_nothing_rather_than_guessing(tmp_path):
    assert find_checkbox(_save(tmp_path / "blank.png", _canvas(tmp_path))) is None


def test_an_unreadable_path_returns_none_instead_of_raising(tmp_path):
    assert find_checkbox(str(tmp_path / "does-not-exist.png")) is None


def test_a_wide_rectangle_is_not_a_checkbox(tmp_path):
    img = _canvas(tmp_path)
    cv2.rectangle(img, (100, 100), (280, 145), (0, 0, 0), 3)
    assert find_checkbox(_save(tmp_path / "wide.png", img)) is None


def test_a_tiny_square_is_not_a_checkbox(tmp_path):
    """Below 20px a glyph is indistinguishable from a box."""
    img = _draw_square(_canvas(tmp_path), 150, 120, 12, thickness=2)
    assert find_checkbox(_save(tmp_path / "tiny.png", img)) is None


def test_a_square_full_of_detail_is_not_a_checkbox(tmp_path):
    """Without the content gate the first tile of a 3x3 grid gets clicked as if it were the widget."""
    img = _canvas(tmp_path)
    x, y, side = 140, 110, 44
    _draw_square(img, x, y, side)
    rng = np.random.default_rng(0)
    noise = rng.integers(0, 255, size=(side - 10, side - 10, 3), dtype=np.uint8)
    img[y + 5:y + side - 5, x + 5:x + side - 5] = noise

    assert find_checkbox(_save(tmp_path / "busy.png", img)) is None


def test_a_square_larger_than_a_widget_is_not_a_checkbox(tmp_path):
    img = _draw_square(_canvas(tmp_path), 20, 20, 200)
    assert find_checkbox(_save(tmp_path / "huge.png", img)) is None


def test_a_square_on_the_right_of_the_widget_is_not_its_tick_box(tmp_path):
    """The vendors put the box at the left and a logo or badge at the right."""
    img = _draw_square(_canvas(tmp_path), 300, 120, 40)
    assert find_checkbox(_save(tmp_path / "right.png", img)) is None


def test_the_box_is_found_on_a_checkbox_widget_s_own_proportions(tmp_path):
    """A 300x74 strip, box at the left and a square logo at the right: the shape a checkbox widget photographs as."""
    img = np.full((74, 300, 3), 249, dtype=np.uint8)
    _draw_square(img, 16, 23, 28, thickness=2, colour=(140, 140, 140))
    _draw_square(img, 250, 22, 30, thickness=2, colour=(90, 90, 90))
    x, y, w, h = find_checkbox(_save(tmp_path / "widget.png", img))
    assert abs(x - 16) <= 3 and abs(y - 23) <= 3 and 24 <= w <= 34, f"found {(x, y, w, h)}, not the box at (16, 23)"
