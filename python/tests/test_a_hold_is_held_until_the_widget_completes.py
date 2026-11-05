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


# ── a hold that names its fill: press, from, to ──────────────────────────────

def test_a_hold_with_a_fill_line_parses_as_its_press_and_both_ends():
    out = ActionPlanner._normalize_general({"action": "hold", "press": [100, 500], "from": [200, 500],
                                            "to": [700, 500]})
    assert out == [{"kind": PixelAnswerKind.HOLD, "points": [(0.1, 0.5)], "src": (0.2, 0.5), "dst": (0.7, 0.5)}]
    # One end alone says nothing about where to let go: the press is still held, to the widget's own finish.
    half = ActionPlanner._normalize_general({"action": "hold", "press": [100, 500], "to": [700, 500]})
    assert half == [{"kind": PixelAnswerKind.HOLD, "points": [(0.1, 0.5)]}]
    # The old shape still parses.
    old = ActionPlanner._normalize_general({"action": "hold", "points": [[500, 520]]})
    assert old == [{"kind": PixelAnswerKind.HOLD, "points": [(0.5, 0.52)]}]


def test_a_parsed_fill_line_rides_on_the_hold_action():
    (action,) = CaptchaSolver._to_actions(
        object(), [{"kind": PixelAnswerKind.HOLD, "points": [(0.1, 0.5)], "src": (0.2, 0.5), "dst": (0.7, 0.5)}])
    assert isinstance(action, HoldAction)
    for box, (x, y) in ((action.fill_from_bounding_box, (0.2, 0.5)), (action.fill_to_bounding_box, (0.7, 0.5))):
        assert abs((box[0] + box[2]) / 2 - x) < 1e-9 and abs((box[1] + box[3]) / 2 - y) < 1e-9
    (plain,) = CaptchaSolver._to_actions(object(), [{"kind": PixelAnswerKind.HOLD, "points": [(0.5, 0.5)]}])
    assert plain.fill_from_bounding_box is None and plain.fill_to_bounding_box is None


def _bar(edge: int, mark: int = 300):
    """A 400x100 grey bar on white, filled blue from x=50 to `edge`, with a dark line at `mark`."""
    import numpy as np
    a = np.full((100, 400, 3), 255, np.uint8)
    a[40:60, 50:350] = 200
    a[40:60, 50:edge] = (200, 90, 30)
    a[35:65, mark - 1:mark + 1] = 20
    return a


def test_the_tracker_finds_the_fills_leading_edge():
    from captchakraken.tool_calls.fill_tracker import fill_step
    first = _bar(50)
    r = fill_step(first, _bar(180), start=(50, 50), end=(300, 50), t=1.0)
    assert abs(r["edge"] - 129) <= 2 and not r["release"]
    assert fill_step(first, first, start=(50, 50), end=(300, 50), t=1.0)["edge"] is None


def test_the_tracker_lets_go_at_the_mark_and_ahead_of_a_fast_fill():
    from captchakraken.tool_calls.fill_tracker import fill_step
    first = _bar(50)
    assert fill_step(first, _bar(299), start=(50, 50), end=(300, 50), t=1.0)["release"]
    assert fill_step(first, _bar(330), start=(50, 50), end=(300, 50), t=1.0)["release"], "past the mark is late"
    # 40 px short, moving 400 px/s: it arrives a tenth of a second after this shot, before the next look, so the
    # release is timed for then rather than made on a look that would land 60 px past.
    hist = [{"t": 0.75, "edge": 110.0}]
    r = fill_step(first, _bar(260), start=(50, 50), end=(300, 50), t=1.0, history=hist, poll_s=0.25)
    assert r["speed"] == pytest.approx(400, abs=10) and r["release"]
    assert r["release_in"] == pytest.approx(0.1 + 0.06, abs=0.01), "a hair late: early restarts a widget that fills to its end"
    assert fill_step(first, _bar(299), start=(50, 50), end=(300, 50), t=1.0)["release_in"] == 0
    slow = [{"t": 0.0, "edge": 110.0}]
    assert not fill_step(first, _bar(260), start=(50, 50), end=(300, 50), t=1.0, history=slow, poll_s=0.25)["release"]


def test_the_pace_is_fitted_over_several_looks():
    """A slow fill moves ~10 px a look, so a pixel of edge noise between the last two is a tenth of its pace."""
    from captchakraken.tool_calls.fill_tracker import fill_step
    first = _bar(50)
    # 40 px/s; the 0.75 s look read a pixel ahead, which two looks alone would take for 36 px/s.
    hist = [{"t": 0.0, "edge": 100.0}, {"t": 0.25, "edge": 110.0}, {"t": 0.5, "edge": 120.0}, {"t": 0.75, "edge": 131.0}]
    r = fill_step(first, _bar(190), start=(50, 50), end=(300, 50), t=1.0, history=hist)
    assert r["edge"] == pytest.approx(139, abs=2) and r["speed"] == pytest.approx(40, abs=2)


def test_the_first_look_has_a_pace_from_where_the_fill_was_at_the_press():
    """A mark near the start is reached within a look or two; waiting for two looks with an edge passes it."""
    from captchakraken.tool_calls.fill_tracker import fill_step
    # Shot at t=0.2 with the fill at x=80, now at t=0.5 with it at x=200: 400 px/s, 100 px short of the mark at 300.
    r = fill_step(_bar(80), _bar(200), start=(50, 50), end=(300, 50), t=0.5, first_t=0.2, poll_s=0.3)
    assert r["speed"] == pytest.approx(400, abs=15) and r["release"]
    assert r["release_in"] == pytest.approx(0.25 + 0.06, abs=0.02)
    assert fill_step(_bar(80), _bar(200), start=(50, 50), end=(300, 50), t=0.5)["speed"] is None


def test_the_executor_lets_go_when_the_fill_reaches_the_mark(monkeypatch, tmp_path):
    """The bar keeps filling past the mark, so only the line can end this hold before the cap."""
    from PIL import Image
    clock = iter(x * 0.25 for x in range(1000))
    monkeypatch.setattr(page_solver.time, "monotonic", lambda: next(clock))
    s = _solver(monkeypatch, [str(k) for k in range(1000)])
    s.config = type("C", (), {"element_screenshot_timeout_ms": 1000, "slide_tolerance_px": 2.0})()
    edges = iter([50, 90, 140, 190, 240, 290, 340, 349, 349])
    shots = []

    def screenshot(el, path, timeout_ms=None):
        e = next(edges)
        shots.append(e)
        Image.fromarray(_bar(e)).save(path)

    s._screenshot = screenshot
    page = Page()
    box = {"x": 0, "y": 0, "width": 400, "height": 100}
    action = {"action": ActionKind.HOLD, "target_bounding_box": [0.08, 0.45, 0.12, 0.55],
              "fill_from_bounding_box": [0.12, 0.49, 0.13, 0.51], "fill_to_bounding_box": [0.745, 0.49, 0.755, 0.51]}
    el = Element()
    el.box = box
    assert s._execute_hold(page, action, box, el) is True
    assert shots[-1] in (290, 340) and 349 not in shots, shots
    assert _kinds(page).count("down") == 1 and _kinds(page)[-1] == "up"


# ── a widget that completes on its own: HUMAN's button ───────────────────────

def test_a_self_completing_widget_is_held_past_its_mark_until_it_settles(monkeypatch):
    """HUMAN's button verifies only once it has drawn its done state, and resets when let go at full. The fill
    reaching `to` is therefore not a release: the fill line is never tracked, and the hold ends on the widget's
    own signal — here its finished picture sitting still."""
    clock = iter(x * 0.25 for x in range(1000))
    monkeypatch.setattr(page_solver.time, "monotonic", lambda: next(clock))
    # Unchanged, the fill moving, the check drawing itself in, then the done state sitting still.
    s = _solver(monkeypatch, ["a", "a", "b", "c", "d", "e", "e", "e", "e", "e", "e", "e"])

    def screenshot(*_a, **_k):
        raise AssertionError("a self-completing hold never tracks its fill line")

    s._screenshot = screenshot
    page = Page()
    box = {"x": 0, "y": 0, "width": 400, "height": 100}
    action = {"action": ActionKind.HOLD, "target_bounding_box": [0.45, 0.45, 0.55, 0.55],
              "fill_from_bounding_box": [0.12, 0.49, 0.13, 0.51], "fill_to_bounding_box": [0.87, 0.49, 0.88, 0.51]}
    el = Element()
    el.box = box
    assert s._execute_hold(page, action, box, el, completes_itself=True) is True
    assert _kinds(page).count("down") == 1 and _kinds(page)[-1] == "up"


def test_the_vendors_whose_hold_completes_on_its_own_are_named():
    from captchakraken.selectors import SELECTORS
    from captchakraken.kinds import Vendor
    assert SELECTORS[Vendor.HUMAN].hold_completes and SELECTORS[Vendor.FUNCAPTCHA].hold_completes
    # A hold graded on where it lets go (a line to fill to a mark) is released at the mark.
    assert not SELECTORS[Vendor.UNKNOWN].hold_completes


def test_your_own_entry_is_released_at_its_mark_unless_it_says_it_completes():
    from captchakraken.kinds import Vendor
    from captchakraken.selectors import SelectorTable, VendorSelectors
    gauge = SelectorTable(VendorSelectors(hosts=(), widget=("#gauge",)))
    assert not gauge.selectors[Vendor.UNKNOWN].hold_completes
    button = SelectorTable(VendorSelectors(hosts=(), widget=("#button",), hold_completes=True))
    assert button.selectors[Vendor.UNKNOWN].hold_completes
