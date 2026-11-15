"""Two driver guards from the 2026-11-14 Tier 3 rerun (client 2383fbf).

DataDome: a model that answered a slide-to-end bar with its handle point on the target and its source on the real
handle pressed empty track. The page names the handle that moves, so the press goes to the source instead, and only
then. Proton: the board, its pieces and its Next live a frame below the widget's frame, and Verify was looked for in the
wrong one. The board's frame becomes the scope, but only a frame INSIDE the widget's, never the host page.
"""

from typing import Any, Dict, List, Optional

from captchakraken.page_solver import PageSolver, PageSolverConfig, _board_frame

ELEMENT = {"x": 100.0, "y": 50.0, "width": 600.0, "height": 200.0}
NAMED = {"x": 140.0, "y": 130.0, "width": 40.0, "height": 40.0}   # the page's handle: board px 40-80, 80-120
TARGET = (400.0, 80.0, 440.0, 120.0)                              # board px


class _El:
    def __init__(self, box: Dict[str, float]) -> None:
        self._box = box

    def element_handle(self, **_kw: Any) -> "_El":
        return self

    def bounding_box(self) -> Dict[str, float]:
        return self._box


class _Locator:
    def __init__(self, found: List[Any]) -> None:
        self._found = found

    def filter(self, **_kw: Any) -> "_Locator":
        return self

    def all(self) -> List[Any]:
        return list(self._found)


class _Scope:
    def __init__(self, boxes: List[Dict[str, float]]) -> None:
        self.boxes = boxes
        self.asked: List[str] = []

    def locator(self, selector: str) -> _Locator:
        self.asked.append(selector)
        return _Locator([_El(b) for b in self.boxes])


def _press(scope: _Scope, handle, seed):
    return PageSolver(config=PageSolverConfig(detection_timeout_ms=0))._press_point(scope, ELEMENT, handle, seed, TARGET)


def test_a_handle_answered_on_its_target_is_pressed_on_the_named_handle():
    assert _press(_Scope([NAMED]), (420.0, 100.0), (60.0, 100.0)) == (60.0, 100.0)


def test_a_handle_away_from_its_target_is_pressed_where_the_answer_names_it_and_the_page_is_not_read():
    scope = _Scope([NAMED])
    assert _press(scope, (60.0, 100.0), (300.0, 100.0)) == (60.0, 100.0)
    assert scope.asked == [], "a generation-3 slide whose handle is off its target must not read the page"


def test_a_source_on_no_named_handle_leaves_the_answer_alone():
    assert _press(_Scope([NAMED]), (420.0, 100.0), (250.0, 100.0)) == (420.0, 100.0)
    assert _press(_Scope([]), (420.0, 100.0), (60.0, 100.0)) == (420.0, 100.0)


def test_a_handle_point_that_is_itself_on_a_named_handle_is_kept():
    on_target = {"x": 500.0, "y": 130.0, "width": 40.0, "height": 40.0}   # board px 400-440: a handle on the target
    assert _press(_Scope([NAMED, on_target]), (420.0, 100.0), (60.0, 100.0)) == (420.0, 100.0)


class _Frame:
    def __init__(self, parent: Optional["_Frame"] = None) -> None:
        self.parent_frame = parent


class _Owned:
    def __init__(self, owner: Optional[_Frame]) -> None:
        self._owner = owner

    def owner_frame(self) -> Optional[_Frame]:
        return self._owner


def test_a_board_in_a_frame_below_the_widget_becomes_the_scope():
    page = _Frame()
    widget = _Frame(page)
    board = _Frame(_Frame(widget))
    assert _board_frame(_Owned(board), widget) is board


def test_the_widget_frame_and_the_host_page_are_no_board():
    page = _Frame()
    widget = _Frame(page)
    assert _board_frame(_Owned(widget), widget) is None
    assert _board_frame(_Owned(page), widget) is None, "the widget's iframe element lives in the host page"
    assert _board_frame(_Owned(_Frame(page)), widget) is None, "a sibling frame is not inside the widget"
    assert _board_frame(_Owned(None), widget) is None
    assert _board_frame(_Owned(_Frame(widget)), None) is None
    assert _board_frame(object(), widget) is None
