"""A reCAPTCHA grid's cells come from the challenge frame's own tiles, not from the picture.

The client used to find the lattice in the screenshot with an element detector. It has none
now: the frame says where every `td.rc-imageselect-tile` is, and those rectangles, in the
frame's CSS pixels, scale onto the screenshot by its size over the iframe's.
"""

from __future__ import annotations

from PIL import Image

from captchakraken.page_solver import PageSolver, PageSolverConfig

#: A 3x3 board of 100px tiles, 4px apart, under a 120px banner, in a 400x580 iframe.
TILES = [[10 + c * 104, 120 + r * 104, 110 + c * 104, 220 + r * 104] for r in range(3) for c in range(3)]


class _Frame:
    def __init__(self, rects):
        self.rects = rects
        self.selectors = []

    def evaluate(self, script, sel):
        self.selectors.append(sel)
        return self.rects


class _Iframe:
    def __init__(self, frame, box=None):
        self.frame = frame
        self.box = box or {"x": 300, "y": 50, "width": 400, "height": 580}

    def content_frame(self):
        return self.frame

    def bounding_box(self):
        return self.box


def _shot(tmp_path, w, h):
    path = tmp_path / "board.png"
    Image.new("RGB", (w, h)).save(path)
    return str(path)


def _solver():
    return PageSolver(PageSolverConfig(), solver=object())


def test_tiles_scale_onto_a_2x_screenshot(tmp_path):
    frame = _Frame(TILES)
    boxes = _solver()._dom_grid(_Iframe(frame), _shot(tmp_path, 800, 1160))
    assert boxes == [tuple(2 * v for v in t) for t in TILES]
    assert frame.selectors == ["td.rc-imageselect-tile"]


def test_tiles_land_unscaled_on_a_1x_screenshot(tmp_path):
    assert _solver()._dom_grid(_Iframe(_Frame(TILES)), _shot(tmp_path, 400, 580)) == [tuple(t) for t in TILES]


def test_fewer_than_four_tiles_is_no_grid(tmp_path):
    assert _solver()._dom_grid(_Iframe(_Frame(TILES[:3])), _shot(tmp_path, 400, 580)) is None


def test_no_frame_or_a_frame_that_throws_is_no_grid(tmp_path):
    shot = _shot(tmp_path, 400, 580)
    assert _solver()._dom_grid(_Iframe(None), shot) is None

    class Gone(_Frame):
        def evaluate(self, script, sel):
            raise RuntimeError("frame detached")

    assert _solver()._dom_grid(_Iframe(Gone([])), shot) is None
