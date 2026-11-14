"""Every capture is one unclipped viewport screenshot, cropped here.

A clipped capture — an element screenshot, or `page.screenshot(clip=...)` — makes a headed Chromium repaint the page
at the clip's size for that frame, and the user watches the page flash and jump on every poll and every burst
frame. Mirror of `js/src/a-capture-never-clips-the-page.test.ts`.
"""

from __future__ import annotations

import io
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from captchakraken.page_solver import (_STALE_HANDLE_RE, CaptureRect, PageSolver, crop_png,  # noqa: E402
                                       enclosing_rect)


def _viewport_png(width: int, height: int) -> bytes:
    """Every pixel distinct, so a crop that is off by one pixel anywhere cannot match."""
    ys, xs = np.mgrid[0:height, 0:width]
    pixels = np.stack([xs % 256, ys % 256, (xs // 256) * 16 + (ys // 256)], axis=-1).astype(np.uint8)
    out = io.BytesIO()
    Image.fromarray(pixels, "RGB").save(out, format="PNG")
    return out.getvalue()


def _pixels(png: bytes) -> np.ndarray:
    return np.array(Image.open(io.BytesIO(png)))


class FakePage:
    def __init__(self, viewport: Optional[Dict[str, float]] = None, dpr: int = 1,
                 inner: Optional[Dict[str, float]] = None) -> None:
        self.viewport_size = viewport
        self._inner = inner
        self._dpr = dpr
        self.shots: List[Dict[str, Any]] = []

    def screenshot(self, **kwargs: Any) -> bytes:
        self.shots.append(kwargs)
        view = self.viewport_size or self._inner
        return _viewport_png(int(view["width"] * self._dpr), int(view["height"] * self._dpr))

    def evaluate(self, *_: Any) -> Optional[Dict[str, float]]:
        # A real window always answers; when nothing says otherwise its layout is the viewport.
        return self._inner if self._inner is not None else self.viewport_size


class FakeElement:
    def __init__(self, box: Optional[Dict[str, float]], scrolled_to: Optional[Dict[str, float]] = None) -> None:
        self.box = box
        self._scrolled_to = scrolled_to
        self.scrolls = 0
        self.element_shots = 0

    def bounding_box(self) -> Optional[Dict[str, float]]:
        return self.box

    def scroll_into_view_if_needed(self, **_: Any) -> None:
        self.scrolls += 1
        self.box = self._scrolled_to or self.box

    def screenshot(self, path: str, **_: Any) -> None:
        self.element_shots += 1
        Path(path).write_bytes(_viewport_png(4, 4))


def _solver(page: FakePage) -> PageSolver:
    solver = PageSolver()
    solver._page = page
    return solver


@pytest.mark.parametrize("dpr", [1, 2])
def test_the_crop_is_the_element_s_whole_pixels_at_the_capture_s_scale(dpr: int) -> None:
    png = _viewport_png(640 * dpr, 480 * dpr)
    rect = enclosing_rect({"x": 37.5, "y": 61.25, "width": 301.3, "height": 151.6})
    assert rect == CaptureRect(37, 61, 302, 152), "not the rect Playwright's element screenshot clips to"
    got = _pixels(crop_png(png, rect, 640))
    want = _pixels(png)[61 * dpr:213 * dpr, 37 * dpr:339 * dpr]
    assert got.shape == want.shape and (got == want).all()


@pytest.mark.parametrize("animations", ["disabled", "allow"])
def test_every_capture_is_one_viewport_shot_with_no_clip(tmp_path: Path, animations: str) -> None:
    page = FakePage({"width": 640, "height": 480}, dpr=2)
    element = FakeElement({"x": 10, "y": 20, "width": 100, "height": 50})
    out = tmp_path / "shot.png"
    _solver(page)._screenshot(element, str(out), timeout_ms=1234, animations=animations)

    assert page.shots == [{"timeout": 1234, "animations": animations}], (
        f"the capture was not one unclipped viewport screenshot: {page.shots}")
    assert element.element_shots == 0, "the element photographed itself, which repaints the page"
    assert _pixels(out.read_bytes()).shape == (100, 200, 3), "the crop lost the device pixel ratio"


def test_an_element_below_the_fold_is_scrolled_in_once_not_per_shot(tmp_path: Path) -> None:
    page = FakePage({"width": 640, "height": 480})
    element = FakeElement({"x": 10, "y": 900, "width": 100, "height": 50},
                          scrolled_to={"x": 10, "y": 200, "width": 100, "height": 50})
    solver = _solver(page)
    for i in range(3):
        solver._screenshot(element, str(tmp_path / f"{i}.png"))
    assert element.scrolls == 1
    assert len(page.shots) == 3 and element.element_shots == 0


def test_an_element_bigger_than_the_viewport_photographs_itself(tmp_path: Path) -> None:
    page = FakePage({"width": 640, "height": 480})
    element = FakeElement({"x": 0, "y": 0, "width": 700, "height": 50})
    _solver(page)._screenshot(element, str(tmp_path / "big.png"))
    assert element.element_shots == 1 and page.shots == [] and element.scrolls == 0


def test_a_context_without_a_viewport_asks_the_window(tmp_path: Path) -> None:
    page = FakePage(None, inner={"width": 320, "height": 240})
    out = tmp_path / "shot.png"
    _solver(page)._screenshot(FakeElement({"x": 0, "y": 0, "width": 30, "height": 20}), str(out))
    assert _pixels(out.read_bytes()).shape == (20, 30, 3)


def test_an_element_with_no_box_reads_as_a_stale_handle(tmp_path: Path) -> None:
    with pytest.raises(Exception) as raised:
        _solver(FakePage({"width": 640, "height": 480}))._screenshot(FakeElement(None), str(tmp_path / "x.png"))
    assert _STALE_HANDLE_RE.search(str(raised.value)), "the solve loop would not re-detect after this"


def test_a_mobile_layout_zoomed_out_to_fit_photographs_the_element(tmp_path: Path) -> None:
    """Pixel 7 on a desktop page: a 412px device, a 981px layout shown at 0.42. The box speaks layout pixels and the
    capture does not, so a crop scaled by the device width cut the board out of the wrong place."""
    page = FakePage(viewport={"width": 412, "height": 839}, inner={"width": 981, "height": 1996, "scale": 0.42})
    element = FakeElement({"x": 0, "y": 0, "width": 320, "height": 257})
    _solver(page)._screenshot(element, str(tmp_path / "shot.png"))
    assert element.element_shots == 1
    assert page.shots == []
