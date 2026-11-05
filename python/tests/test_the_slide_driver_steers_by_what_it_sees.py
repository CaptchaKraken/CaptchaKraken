"""The slide driver against boards that render what the page would show for wherever the pointer is.

The handle, the part it moves and the target come from the answer; the driver presses, nudges, and steers by the
tracker's reading of the shots alone. A generation-3 slide must never ask the page for a selector, and a
generation-2 sourceless drag still lands with the handle found by one.
"""

from typing import Any, List, Optional, Tuple

import numpy as np
import pytest
from PIL import Image
from slide_boards import CarriedBoard, DiscBoard, JigsawBoard

from captchakraken.action_types import DragAction, SlideAction
from captchakraken.page_solver import PageSolver, PageSolverConfig
from captchakraken.selectors import PIECE_SELECTORS, SLIDER_HANDLE_SELECTORS

ORIGIN = (100.0, 60.0)    # where the widget sits on the page, in CSS pixels


class _Pointer:
    """The humanizer, reduced to where the pointer is and whether it is down."""

    def __init__(self) -> None:
        self.at: Optional[Tuple[float, float]] = None
        self.down_at: Optional[Tuple[float, float]] = None
        self.presses = self.releases = 0
        self.moves = 0

    def move(self, _page: Any, xy: Tuple[float, float]) -> None:
        self.at = (float(xy[0]), float(xy[1]))
        self.moves += 1

    def press(self, _page: Any) -> None:
        self.presses += 1
        self.down_at = self.at

    def release(self, _page: Any) -> None:
        self.releases += 1

    def pause(self, _kind: Any) -> None:
        pass


class _NoSelectors:
    """A page that remembers every selector asked of it. Raising would not do: the driver skips a selector that errors."""

    def __init__(self) -> None:
        self.asked: List[str] = []

    def locator(self, selector: str) -> Any:
        self.asked.append(selector)
        return _Locator([])


def _rig(board, scope: Any = None):
    """A PageSolver whose screenshots are the board after the handle travelled as far as the pointer has."""
    solver = PageSolver(config=PageSolverConfig(detection_timeout_ms=0))
    pointer = _Pointer()
    solver._human = pointer
    k = board.k

    def travel() -> Any:
        if pointer.down_at is None:
            return 0.0
        dx = (pointer.at[0] - pointer.down_at[0]) * k
        dy = (pointer.at[1] - pointer.down_at[1]) * k
        return (dx, dy) if isinstance(board, CarriedBoard) else dx

    shots: List[Any] = []

    def screenshot(_element: Any, path: str, **_kw: Any) -> None:
        shots.append(travel())
        # The boards draw in BGR; a page screenshot is RGB.
        Image.fromarray(np.ascontiguousarray(board.render(travel())[..., ::-1])).save(path)

    solver._screenshot = screenshot
    box = {"x": ORIGIN[0], "y": ORIGIN[1], "width": board.w / k, "height": board.h / k}
    return solver, pointer, box, scope or _NoSelectors(), travel


def _norm(point: Tuple[float, float], board) -> List[float]:
    x, y = point[0] / board.w, point[1] / board.h
    return [x - 0.01, y - 0.01, x + 0.01, y + 0.01]


def _slide(board, seed, goal) -> SlideAction:
    return SlideAction(action="slide", handle_bounding_box=_norm(board.handle(), board),
                       source_bounding_box=_norm(seed, board), target_bounding_box=_norm(goal, board))


def _run(board, action, scope: Any = None):
    solver, pointer, box, scope, travel = _rig(board, scope)
    assert solver._execute_slide(None, None, scope, action.model_dump(), box) is True
    if isinstance(scope, _NoSelectors):
        assert scope.asked == [], f"a generation-3 slide read the page: {scope.asked}"
    return pointer, travel()


@pytest.mark.parametrize("ratio", [0.8, 1.0, 1.27])
def test_a_jigsaw_piece_is_seated_on_its_slot_whatever_the_handle_ratio(ratio):
    board = JigsawBoard(ratio=ratio)
    pointer, s = _run(board, _slide(board, board.centre(), board.goal))
    x, y = board.centre(s)
    assert abs(x - board.goal[0]) <= 2.0 and abs(y - board.goal[1]) <= 2.0, (ratio, s, (x, y), board.goal)
    assert (pointer.presses, pointer.releases) == (1, 1)


def test_the_handle_is_pressed_where_the_answer_names_it():
    board = JigsawBoard()
    pointer, _ = _run(board, _slide(board, board.centre(), board.goal))
    hx, hy = board.handle()
    assert pointer.down_at == pytest.approx((ORIGIN[0] + hx, ORIGIN[1] + hy), abs=0.01)


def test_a_turned_picture_is_turned_upright():
    board = DiscBoard()
    _, s = _run(board, _slide(board, board.seed_point(), board.goal))
    assert abs(board.angle(s)) <= 1.5, f"left {board.angle(s):+.1f} degrees off upright"


def test_a_piece_the_pointer_carries_is_put_down_on_its_slot():
    board = CarriedBoard()
    _, s = _run(board, _slide(board, board.centre(), board.goal))
    x, y = board.centre(0)
    x, y = x + s[0], y + s[1]
    assert abs(x - board.goal[0]) <= 2.0 and abs(y - board.goal[1]) <= 2.0


def test_a_hidpi_screen_steers_in_css_pixels_and_still_seats_the_piece():
    board = JigsawBoard(ratio=1.27, scale=2.0)
    _, s = _run(board, _slide(board, board.centre(), board.goal))
    x, _ = board.centre(s)
    assert abs(x - board.goal[0]) <= 2.0 * board.k


def test_a_part_that_never_moves_is_released_not_steered_blind():
    board = JigsawBoard(ratio=0.0, badge=False)
    pointer, s = _run(board, _slide(board, board.centre(), board.goal))
    assert (pointer.presses, pointer.releases) == (1, 1)
    assert pointer.moves == 2, "pressed and probed, then let go without guessing a sweep"


class _Handle:
    def __init__(self, box):
        self._box = box

    def element_handle(self, **_kw):
        return self

    def bounding_box(self):
        return self._box


class _Locator:
    def __init__(self, found):
        self._found = found

    def filter(self, **_kw):
        return self

    def all(self):
        return list(self._found)


class _OneControl:
    """A generation-2 page: one control answers the first selector of its table, nothing else answers anything."""

    def __init__(self, board, table):
        hx, hy = board.handle()
        self.box = {"x": ORIGIN[0] + hx - 18, "y": ORIGIN[1] + hy - 14, "width": 36.0, "height": 28.0}
        self.selector = table[0]

    def locator(self, selector: str):
        return _Locator([_Handle(self.box)] if selector == self.selector else [])


def test_a_generation_2_slide_finds_its_handle_by_selector_and_still_lands():
    board = JigsawBoard(ratio=1.27)
    legacy = DragAction(action="drag", source_bounding_box=None, target_bounding_box=_norm(board.goal, board))
    _, s = _run(board, legacy, scope=_OneControl(board, SLIDER_HANDLE_SELECTORS))
    x, _ = board.centre(s)
    assert abs(x - board.goal[0]) <= 2.0


def test_a_generation_2_piece_with_no_track_is_carried_onto_its_slot():
    board = CarriedBoard()
    legacy = DragAction(action="drag", source_bounding_box=None, target_bounding_box=_norm(board.goal, board))
    _, s = _run(board, legacy, scope=_OneControl(board, PIECE_SELECTORS))
    x, y = board.centre(0)
    assert abs(x + s[0] - board.goal[0]) <= 2.0 and abs(y + s[1] - board.goal[1]) <= 2.0
