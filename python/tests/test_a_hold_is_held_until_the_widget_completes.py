"""Press & Hold (prompt generation 3): a `hold` answer is one press, kept down until the widget completes.

A click on the right button fails the widget, so the verb must survive the parser; and a press released early
fails it too, so the executor holds until the widget's own picture says it is done.
"""

from __future__ import annotations

import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Any, List

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from captchakraken import humanize, page_solver
from captchakraken.action_types import HoldAction
from captchakraken.humanize import MouseHumanizer, hold
from captchakraken.kinds import ActionKind, PixelAnswerKind
from captchakraken.page_solver import PageSolver
from captchakraken.planner import ActionPlanner
from captchakraken.solver import CaptchaSolver


@pytest.fixture(autouse=True)
def _no_sleeping(monkeypatch):
    monkeypatch.setattr(humanize, "_delay", lambda ms: None)


class Mouse:
    def __init__(self) -> None:
        self.events: List[Any] = []

    def move(self, x: float, y: float) -> None:
        self.events.append(("move", round(x), round(y)))

    def down(self) -> None:
        self.events.append(("down",))

    def up(self) -> None:
        self.events.append(("up",))


class Page:
    def __init__(self) -> None:
        self.mouse = Mouse()
        self.viewport_size = {"width": 800, "height": 600}


def _kinds(page: Page) -> List[str]:
    return [e[0] for e in page.mouse.events]


def test_a_hold_answer_parses_as_one_hold_not_a_click():
    out = ActionPlanner._normalize_pixel(
        {"action": "hold", "subjects": ["hold button"], "points": [[500, 520], [100, 100]]})
    assert out == [{"kind": PixelAnswerKind.HOLD, "points": [(0.5, 0.52)]}]
    # The same point list under the click verb is still a click.
    click = ActionPlanner._normalize_pixel({"action": "click", "subjects": ["b"], "points": [[500, 520]]})
    assert click[0]["kind"] == PixelAnswerKind.CLICK


def test_a_parsed_hold_becomes_a_hold_action_on_its_point():
    (action,) = CaptchaSolver._to_actions(object(), [{"kind": PixelAnswerKind.HOLD, "points": [(0.5, 0.52)]}])
    assert isinstance(action, HoldAction) and action.action == ActionKind.HOLD
    x1, y1, x2, y2 = action.target_bounding_box
    assert abs((x1 + x2) / 2 - 0.5) < 1e-9 and abs((y1 + y2) / 2 - 0.52) < 1e-9


def test_the_press_lasts_until_the_widget_says_done():
    page, h = Page(), MouseHumanizer()
    looks = iter([False, False, False, True])
    assert hold(h, page, (100, 100), lambda: next(looks), max_ms=60_000) is True
    kinds = _kinds(page)
    assert kinds.count("down") == 1 and kinds.count("up") == 1 and kinds[-1] == "up"
    held = kinds[kinds.index("down") + 1:kinds.index("up")]
    assert len(held) >= 4 and set(held) == {"move"}, "the hand drifts while it holds, it does not let go"


def test_the_press_is_released_at_the_cap_and_when_the_check_fails():
    page, h = Page(), MouseHumanizer()
    assert hold(h, page, (100, 100), lambda: False, max_ms=0) is False
    assert _kinds(page)[-1] == "up"

    page = Page()

    def boom() -> bool:
        raise RuntimeError("page went away")

    with pytest.raises(RuntimeError):
        hold(MouseHumanizer(), page, (100, 100), boom, max_ms=60_000)
    assert _kinds(page)[-1] == "up", "a held button is never left down"


class Element:
    def __init__(self) -> None:
        self.box = {"x": 0, "y": 0, "width": 400, "height": 300}

    def bounding_box(self):
        return self.box


def _solver(monkeypatch, hashes):
    s = PageSolver.__new__(PageSolver)
    s._human = MouseHumanizer()
    s._acted_on_board = False

    @contextmanager
    def gesture():
        yield

    s._gesture = gesture
    s.is_captcha_solved = lambda page: False
    it = iter(hashes)
    last = [None]

    def frame_hash(el):
        last[0] = next(it, last[0])
        return last[0]

    s._element_frame_hash = frame_hash
    return s


def test_the_executor_lets_go_once_the_fill_has_finished(monkeypatch):
    # Unchanged, then the fill moving, then the finished widget sitting still.
    clock = iter(x * 0.25 for x in range(1000))
    monkeypatch.setattr(page_solver.time, "monotonic", lambda: next(clock))
    s = _solver(monkeypatch, ["a", "a", "b", "c", "d", "d", "d", "d", "d", "d", "d"])
    page = Page()
    action = {"action": ActionKind.HOLD, "target_bounding_box": [0.45, 0.45, 0.55, 0.55]}
    assert s._execute_hold(page, action, Element().box, Element()) is True
    assert _kinds(page).count("down") == 1 and _kinds(page)[-1] == "up"
    assert s._acted_on_board


def test_a_widget_that_never_changes_is_held_to_the_cap(monkeypatch):
    monkeypatch.setattr(page_solver, "HOLD_MAX_MS", 0)
    s = _solver(monkeypatch, ["a"])
    page = Page()
    action = {"action": ActionKind.HOLD, "target_bounding_box": [0.45, 0.45, 0.55, 0.55]}
    assert s._execute_hold(page, action, Element().box, Element()) is False
    assert _kinds(page)[-1] == "up"
