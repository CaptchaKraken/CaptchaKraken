"""DingXiang's restore: the handle rolls one of two picture strips by its background, which strip and how far per
handle pixel dealt per board (measured live: 0.52 to 1.77, and on some boards the upper strip rolls instead). The slide
must stop when the strip has rolled as far as the answer's two points are apart, read off the DOM, whatever the handle
travelled to get there.
"""

from typing import Any, List, Optional, Tuple

import pytest
from PIL import Image

from captchakraken.action_types import SlideAction
from captchakraken.kinds import Vendor
from captchakraken.page_solver import PageSolver, PageSolverConfig, band_roll
from captchakraken.tool_calls import slide_tracker

# The live card, 412x335: picture x 16..396, cut 92 px below its top at y 54, handle at (51, 252).
ELEMENT = {"x": 434.0, "y": 326.0, "width": 412.0, "height": 335.0}
HANDLE = (51.0, 252.0)
UPPER = {"x": ELEMENT["x"] + 16, "y": ELEMENT["y"] + 54, "width": 380.0, "height": 92.0}
LOWER = {"x": ELEMENT["x"] + 16, "y": ELEMENT["y"] + 146, "width": 380.0, "height": 73.0}
PERIOD = 380.0


class _Pointer:
    def __init__(self) -> None:
        self.at: Tuple[float, float] = (0.0, 0.0)
        self.down_at: Optional[Tuple[float, float]] = None

    def move(self, _page: Any, xy: Tuple[float, float]) -> None:
        self.at = (float(xy[0]), float(xy[1]))

    def press(self, _page: Any) -> None:
        self.down_at = self.at

    def release(self, _page: Any) -> None:
        pass

    def pause(self, _kind: Any) -> None:
        pass

    def travel(self) -> float:
        return self.at[0] - self.down_at[0] if self.down_at else 0.0


class _Band:
    """A strip whose background sits `slope` px right per px the handle has travelled, if it is the one that rolls."""

    def __init__(self, box, rolls: bool, slope: float, pointer: _Pointer) -> None:
        self.box, self.rolls, self.slope, self.pointer = box, rolls, slope, pointer

    def element_handle(self, **_kw: Any) -> "_Band":
        return self

    def bounding_box(self):
        return self.box

    def evaluate(self, _js: str) -> List[float]:
        return [self.slope * self.pointer.travel() if self.rolls else 0.0, PERIOD]


class _Card:
    def __init__(self, bands) -> None:
        self.bands = bands

    def locator(self, selector: str) -> Any:
        card = self

        class _At:
            def filter(self, **_kw: Any) -> "_At":
                return self

            def all(self) -> List[_Band]:
                return [b for name, b in card.bands if name == selector]

        return _At()


def _box(x: float, y: float) -> List[float]:
    return [(x - 2) / ELEMENT["width"], (y - 2) / ELEMENT["height"], (x + 2) / ELEMENT["width"], (y + 2) / ELEMENT["height"]]


def _restore(src: float, dst: float) -> dict:
    """The answer as trained: a point on the lower strip just below the cut, and where it belongs just above it."""
    return SlideAction(action="slide", handle_bounding_box=_box(*HANDLE), source_bounding_box=_box(src, 149),
                       target_bounding_box=_box(dst, 142)).model_dump()


def _drive(action: dict, rolls: Optional[str], slope: float, monkeypatch) -> Tuple[float, list]:
    solver = PageSolver(config=PageSolverConfig(detection_timeout_ms=0))
    pointer = _Pointer()
    solver._human = pointer
    solver._screenshot = lambda _el, path, **_kw: Image.new("RGB", (412, 335), "white").save(path)
    tracked: list = []

    def tracker(*args: Any, **kw: Any):
        tracked.append(kw)
        raise slide_tracker.TrackingError("the pixel tracker was asked")

    monkeypatch.setattr(slide_tracker, "slide_step", tracker)
    upper, lower = (_Band(UPPER, rolls == "upper", slope, pointer), _Band(LOWER, rolls == "lower", slope, pointer))
    card = _Card([(".dx_captcha_basic_pic .upper", upper), (".dx_captcha_basic_pic .lower", lower)])
    assert solver._execute_slide(None, None, card, action, ELEMENT, Vendor.DINGXIANG) is True
    return slope * pointer.travel(), tracked


@pytest.mark.parametrize("slope", [0.52, 0.72, 0.92, 1.15, 1.77])
def test_the_lower_strip_stops_where_it_has_rolled_the_answer_at_every_live_slope(slope, monkeypatch):
    rolled, tracked = _drive(_restore(60, 180), "lower", slope, monkeypatch)
    assert abs(rolled - 120) <= 2, f"slope {slope}: rolled {rolled:.1f}px for a 120px answer"
    assert tracked == [], "a strip the DOM measures is not handed to the pixel tracker"


def test_when_the_upper_strip_rolls_it_carries_the_target_round_to_the_point(monkeypatch):
    # The target is 250 px right of the point; rolling the upper strip right brings it round in 380 - 250 = 130 px.
    rolled, _ = _drive(_restore(40, 290), "upper", 0.6, monkeypatch)
    assert abs(rolled - 130) <= 2, f"rolled {rolled:.1f}px, wanted 130"


def test_a_slide_no_strip_follows_is_handed_to_the_pixel_tracker(monkeypatch):
    _, tracked = _drive(_restore(60, 180), None, 1.0, monkeypatch)
    assert len(tracked) == 1


def test_the_roll_is_read_the_way_the_probe_went_within_one_turn():
    def read(x: float, top: float) -> dict:
        return {"x": x, "top": top, "bottom": top + 50, "period": 380.0}

    rest = [read(0, 0), read(0, 50)]
    # The point's own strip rolls right: target 30 px LEFT of it means nearly a whole turn.
    assert band_roll(rest, [read(0, 0), read(4, 50)], (100, 60), (70, 40)) == (1, 350)
    # A strip that rolls left reaches the meeting the other way round, as a negative roll.
    assert band_roll(rest, [read(0, 0), read(-4, 50)], (100, 60), (130, 40)) == (1, -350)
    assert band_roll(rest, [read(0.2, 0), read(0, 50)], (100, 60), (130, 40)) is None, "under half a pixel is no roll"
