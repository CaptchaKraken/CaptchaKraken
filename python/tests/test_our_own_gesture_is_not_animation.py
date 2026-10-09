"""A board that changed only because we pointed at it is a still board.

Measured before this: after a refused answer the cursor sat on the board, the "second look" recording saw the
hover and press feedback come and go, read "a screen came back" as a cycle, and filmed a still board as animated
(+29s on the recording path). Mirror of `js/src/our-own-gesture-is-not-animation.test.ts`.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, List, Tuple

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from captchakraken.humanize import Humanizer  # noqa: E402
from captchakraken.page_solver import INPUT_SETTLE_MS, PageSolver, PageSolverConfig, _now  # noqa: E402

BOARD = {"x": 100.0, "y": 100.0, "width": 300.0, "height": 300.0}


class Pointer(Humanizer):
    hovers = True

    def __init__(self, at: Tuple[float, float]) -> None:
        super().__init__(at)
        self.moves: List[Tuple[float, float]] = []

    def move(self, page: Any, to: Tuple[float, float]) -> None:
        self.moves.append(to)
        self.at = to


class Page:
    viewport_size = {"width": 1280, "height": 800}


class Board:
    def bounding_box(self):
        return BOARD


def _solver(at: Tuple[float, float], **config: Any) -> Tuple[PageSolver, Pointer]:
    pointer = Pointer(at)
    return PageSolver(config=PageSolverConfig(humanizer=pointer, **config)), pointer


def _outside_the_board(p: Tuple[float, float]) -> bool:
    return not (BOARD["x"] <= p[0] <= BOARD["x"] + BOARD["width"] and BOARD["y"] <= p[1] <= BOARD["y"] + BOARD["height"])


def test_the_pointer_leaves_the_board_before_the_board_is_judged() -> None:
    solver, pointer = _solver((150.0, 250.0))
    solver._acted_on_board = True
    solver._last_input_ms = _now()
    solver._step_off_the_board(Page(), Board())

    assert len(pointer.moves) == 1, "the pointer stayed on the board it was about to judge"
    x, y = pointer.moves[0]
    assert _outside_the_board((x, y)) and 0 <= x < 1280 and 0 <= y < 800, f"moved to {(x, y)}"
    assert x < BOARD["x"], "left by a far edge instead of the nearest one"
    assert _now() - solver._last_input_ms >= INPUT_SETTLE_MS - 1, "judged while our own feedback was still fading"


def test_a_board_dealt_under_a_resting_pointer_is_not_stepped_off() -> None:
    """Nothing of ours is on a board we have not pointed at, so stepping off it would only cost the round a gesture."""
    solver, pointer = _solver((150.0, 250.0))
    t0 = _now()
    solver._step_off_the_board(Page(), Board())
    assert pointer.moves == [], "moved off a board we never touched"
    assert _now() - t0 < INPUT_SETTLE_MS / 2, "waited out feedback that was never there"


def test_a_pointer_already_off_the_board_is_not_moved() -> None:
    solver, pointer = _solver((20.0, 20.0))
    solver._step_off_the_board(Page(), Board())
    assert pointer.moves == []


def _png(path: str, shade: int) -> None:
    cv2.imwrite(path, np.full((8, 8, 3), shade, dtype=np.uint8))


def test_a_board_that_only_changed_under_our_gesture_films_as_still() -> None:
    """Hover feedback flickers between two looks for 350ms after we move — a CSS transition — then the still board shows."""
    solver, _ = _solver((20.0, 20.0), video_burst_duration_ms=500, video_burst_max_ms=500, video_burst_fps=20)
    touched = _now()
    solver._last_input_ms = touched
    flicker = iter(range(1_000))

    def capture(_el: Any, path: str, **_: Any) -> None:
        if _now() - touched < 350:
            _png(path, 10 * (next(flicker) % 2))
        else:
            _png(path, 200)

    solver._screenshot = capture
    _frames, order, moved, _ms, cycled = solver._burst(object())
    assert not moved and not cycled, "our own hover feedback was filmed as the board animating"
    assert len(order) == 1, f"{len(order)} screens of a board that never moved by itself"
