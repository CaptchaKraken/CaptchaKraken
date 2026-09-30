"""A checkbox is ticked, never treated as a board: no load poll, no film, no model call.

Measured before this: one solve polled the checkbox 28 times while waiting for it to "paint", filmed it for 4s
(42 frames), and asked the model about the checkbox picture three times — twice it answered with a drag.
Mirror of `js/src/a-checkbox-is-clicked-not-watched.test.ts`.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import cv2
import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from captchakraken.kinds import FrameRole, HumanizationMode, Vendor  # noqa: E402
from captchakraken.page_solver import PageSolver, PageSolverConfig, Widget  # noqa: E402

WIDGET_BOX = {"x": 33.0, "y": 237.0, "width": 302.0, "height": 76.0}
TICK_BOX = {"x": 49.0, "y": 260.0, "width": 30.0, "height": 30.0}


class Mouse:
    def __init__(self) -> None:
        self.at = (0.0, 0.0)
        self.pressed_at: List[tuple] = []

    def move(self, x: float, y: float, **_: Any) -> None:
        self.at = (x, y)

    def down(self, **_: Any) -> None:
        self.pressed_at.append(self.at)

    def up(self, **_: Any) -> None:
        pass


class Page:
    def __init__(self) -> None:
        self.mouse = Mouse()
        self.viewport_size = {"width": 1280, "height": 900}


class Handle:
    def __init__(self, box: Dict[str, float], frame: Any = None) -> None:
        self.box = box
        self.frame = frame

    def bounding_box(self) -> Dict[str, float]:
        return self.box

    def content_frame(self) -> Any:
        return self.frame

    def scroll_into_view_if_needed(self, **_: Any) -> None:
        pass


class CheckboxFrame:
    def __init__(self, box: Optional[Handle]) -> None:
        self.box = box
        self.asked: List[str] = []

    def wait_for_selector(self, selector: str, **_: Any) -> Handle:
        self.asked.append(selector)
        if self.box is None:
            raise TimeoutError("Timeout 10ms exceeded.")
        return self.box


def _checkbox_picture(path: str) -> None:
    """What a checkbox widget photographs as: the tick box at the left of a pale strip."""
    img = np.full((76, 302, 3), 249, dtype=np.uint8)
    cv2.rectangle(img, (16, 23), (46, 53), (140, 140, 140), 2)
    cv2.imwrite(path, img)


def _round(vendor: Vendor, frame: Optional[CheckboxFrame]):
    solver = PageSolver(config=PageSolverConfig(humanization=HumanizationMode.NONE, post_solve_outcome_poll_ms=1))
    page = Page()
    solver._page = page
    element = Handle(WIDGET_BOX, frame)
    checkbox = Widget(element, None, vendor, FrameRole.CHECKBOX)
    challenge = Widget(Handle({"x": 90, "y": 11, "width": 520, "height": 570}), None, vendor, FrameRole.CHALLENGE)
    seen = {"captures": 0, "asks": 0, "detects": 0}

    def capture(_el: Any, path: str, **_: Any) -> None:
        seen["captures"] += 1
        _checkbox_picture(path)

    def ask(*_: Any, **__: Any):
        seen["asks"] += 1
        raise AssertionError("the model was asked about a checkbox")

    def detect(_page: Any) -> Widget:
        seen["detects"] += 1
        return checkbox if seen["detects"] < 3 else challenge

    def board_path(*_: Any, **__: Any):
        raise AssertionError("a checkbox went down the board path")

    solver._screenshot = capture
    solver._get_solution = ask
    solver._get_keyframe_solution = ask
    solver._wait_for_board_painted = board_path
    solver._settle_or_animated = board_path
    solver._burst = board_path
    solver.detect_captcha = detect
    solver.is_captcha_solved = lambda _page: False
    performed, usage = solver._solve_single(page, checkbox, None)
    return performed, usage, page, seen


def _inside(point: tuple, box: Dict[str, float]) -> bool:
    return box["x"] <= point[0] <= box["x"] + box["width"] and box["y"] <= point[1] <= box["y"] + box["height"]


@pytest.mark.parametrize("vendor", [Vendor.HCAPTCHA, Vendor.RECAPTCHA])
def test_a_checkbox_the_dom_can_reach_is_ticked_with_no_capture_and_no_model(vendor: Vendor) -> None:
    frame = CheckboxFrame(Handle(TICK_BOX))
    performed, usage, page, seen = _round(vendor, frame)

    assert frame.asked, "the box was not looked for inside the checkbox frame"
    assert seen["captures"] == 0, f"{seen['captures']} capture(s) of a checkbox"
    assert seen["asks"] == 0 and usage == []
    assert performed and len(page.mouse.pressed_at) == 1, "the box was not clicked exactly once"
    assert _inside(page.mouse.pressed_at[0], TICK_BOX), f"clicked {page.mouse.pressed_at[0]}, outside the tick box"
    assert seen["detects"] == 3, "the round returned before the challenge had opened, so the next one re-clicks"


@pytest.mark.parametrize("frame", [None, CheckboxFrame(None)], ids=["no-dom-selector", "frame-refuses-access"])
def test_a_box_the_dom_cannot_reach_is_found_on_one_capture_with_no_model(frame: Optional[CheckboxFrame]) -> None:
    vendor = Vendor.TURNSTILE if frame is None else Vendor.HCAPTCHA
    performed, usage, page, seen = _round(vendor, frame)

    assert seen["captures"] == 1, f"{seen['captures']} captures; one photograph finds a box that does not move"
    assert seen["asks"] == 0 and usage == []
    assert performed and len(page.mouse.pressed_at) == 1
    assert _inside(page.mouse.pressed_at[0], {"x": 33 + 16, "y": 237 + 23, "width": 30, "height": 30}), (
        f"clicked {page.mouse.pressed_at[0]}, outside the tick box OpenCV found")
