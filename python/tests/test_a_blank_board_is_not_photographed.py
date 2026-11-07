"""Measured on gt4.geetest.com over ten live attempts: six of fifty-two requests carried a board under 5% ink and every one came back dead centre. The blank panel is the stillest state, so the settle gate cannot catch it; the middle is measured because chrome paints early; the floor is blank-vs-anything (0.000-0.004 against 0.19-0.56), not puzzle density."""

import os
import sys
import tempfile

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from captchakraken import page_solver
from captchakraken.keyframes import write_frame
from captchakraken.page_solver import PageSolver, PageSolverConfig
from virtual_clock import install
from captchakraken.tool_calls.board_painted import (
    TEXTURE_FLOOR, board_is_painted, centre_texture,
)

def _png(pixels) -> str:
    fd, path = tempfile.mkstemp(suffix=".png")
    os.close(fd)
    write_frame(path, pixels)
    return path


def test_a_flat_panel_carries_no_texture():
    path = _png(np.full((400, 340), 255, dtype=np.uint8))
    try:
        assert centre_texture(path) == 0.0
        assert board_is_painted(path)["painted"] is False
    finally:
        os.unlink(path)


def test_chrome_alone_does_not_count_as_a_puzzle():
    img = np.full((400, 340), 255, dtype=np.uint8)
    img[10:40, 40:300] = 0
    img[360:390, 20:120] = 0
    path = _png(img)
    try:
        assert board_is_painted(path)["painted"] is False
    finally:
        os.unlink(path)


def test_a_pale_puzzle_still_reads_as_painted():
    img = np.full((400, 340), 255, dtype=np.uint8)
    for x in range(60, 280, 24):
        img[120:280, x:x + 2] = 20
    path = _png(img)
    try:
        assert centre_texture(path) > TEXTURE_FLOOR
        assert board_is_painted(path)["painted"] is True
    finally:
        os.unlink(path)


def test_an_unreadable_image_is_not_a_blank_one():
    assert board_is_painted("/nonexistent/board.png")["painted"] is None


class _Element:

    def __init__(self, blank_for: int, throw_first: bool = False):
        self.blank_for = blank_for
        self.throw_first = throw_first
        self.grabs = 0

    def screenshot(self, **kw):
        self.grabs += 1
        if self.throw_first and self.grabs == 1:
            raise RuntimeError("element is detaching")
        img = np.full((400, 340), 255, dtype=np.uint8)
        if self.grabs > self.blank_for:
            img[110:290, 50:290] = np.random.default_rng(0).integers(
                0, 255, (180, 240), dtype=np.uint8)
        write_frame(kw["path"], img)


def _solver(**cfg):
    s = PageSolver(config=PageSolverConfig(
        board_paint_poll_ms=1, board_paint_timeout_ms=80, **cfg))
    s._screenshot = lambda el, path, **kw: el.screenshot(path=path)
    return s


# On the virtual clock only sleeps move time, so the wait measures the polling code and not the runner's load.
def test_a_painted_board_is_photographed_at_once(monkeypatch):
    install(monkeypatch, page_solver)
    s, el = _solver(), _Element(blank_for=0)
    assert s._wait_for_board_painted(el) == 0
    assert el.grabs == 1


def test_a_blank_board_is_polled_until_it_paints():
    s, el = _solver(), _Element(blank_for=3)
    s._wait_for_board_painted(el)
    assert el.grabs == 4, "should have kept looking until there was a puzzle"


def test_a_board_that_never_paints_falls_through(monkeypatch):
    install(monkeypatch, page_solver)
    s, el = _solver(), _Element(blank_for=10_000)
    waited = s._wait_for_board_painted(el)
    assert 80 <= waited < 2_000, f"must be bounded by board_paint_timeout_ms, waited {waited}ms"


def test_a_screenshot_that_throws_is_a_skipped_poll():
    s, el = _solver(), _Element(blank_for=0, throw_first=True)
    s._wait_for_board_painted(el)
    assert el.grabs == 2, "one flaky grab must not wave a blank board through"


def test_the_freshness_resolve_waits_for_paint():
    src = open(os.path.join(os.path.dirname(__file__), "..", "src",
                            "captchakraken", "page_solver.py")).read()
    at = src.index('_tmp_png("freshsolve")')
    assert "self._wait_for_board_painted(element)" in src[max(0, at - 1200):at], (
        "the freshness re-solve must wait for the board to paint before grabbing "
        "a fresh frame — it fires precisely when the board is mid-rebuild")
