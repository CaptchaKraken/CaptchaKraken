"""A slider whose track sits outside the widget is photographed with it (`page_solver._track_outside`).

Yidun's float layout pops its 320x175 picture (.yidun_panel) above a separate 320x40 bar (.yidun_control) holding
the slide handle; the two are siblings under .yidun. Every board the pointer trained on shows the bar; on the bare
panel it had no handle to name and dragged the piece, which Yidun ignores (live 0/8 on 2026-11-12). The shot takes
the handle's track, not the handle: the handle's box moves as it slides, and a frame that changed size mid-slide
lost the tracker the piece.
"""
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from captchakraken import page_solver
from captchakraken.page_solver import SLIDER_TRACK_MAX_GROWTH, PageSolver, _WithAnswerBox

# The live page, 2026-11-12
PANEL = {"x": 630.5, "y": 621, "width": 320, "height": 175}
BAR = {"x": 630.5, "y": 796, "width": 320, "height": 40}
SLIDER = {"x": 631.5, "y": 797, "width": 40, "height": 38}
PIECE = {"x": 640, "y": 690, "width": 40, "height": 40}


class _Handle:
    """A located element: its own handle, and `xpath=..` reads its parent."""

    def __init__(self, box, parent=None):
        self.box, self.parent = box, parent

    def bounding_box(self):
        return dict(self.box)

    def element_handle(self, timeout=None):
        return self

    def locator(self, q):
        assert q == "xpath=.."
        return self.parent or _Gone()


class _Gone:
    def element_handle(self, timeout=None):
        raise RuntimeError("no such element")


class _At:
    """The widget's locator: its ancestors are named, so a test can say which one holds what."""

    def locator(self, q):
        return {"xpath=ancestor::*[1]": "parent", "xpath=ancestor::*[2]": "grandparent"}[q]


def _solver():
    return SimpleNamespace(_sel=SimpleNamespace(selectors={"yidun": SimpleNamespace(slider_handle=(".yidun_slider", ".yidun_jigsaw")),
                                                           "plain": SimpleNamespace(slider_handle=())}))


@pytest.fixture
def dom(monkeypatch):
    """`where -> [elements]`, read by the solver's own `_visible`."""
    found = {}
    monkeypatch.setattr(page_solver, "_visible", lambda where, sels: list(found.get(where, [])))
    return found


def test_the_shot_covers_the_yidun_panel_and_the_bar_under_it(dom):
    bar = _Handle(BAR)
    dom.update({"panel": [_Handle(PIECE)], "parent": [_Handle(SLIDER, parent=bar), _Handle(PIECE)]})
    assert PageSolver._track_outside(_solver(), "panel", "yidun", _Handle(PANEL), _At()) is bar
    el = _WithAnswerBox(_Handle(PANEL), bar, SLIDER_TRACK_MAX_GROWTH)
    assert el.bounding_box() == {"x": 630.5, "y": 621, "width": 320, "height": 215}


def test_a_handle_whose_parent_cannot_be_read_is_its_own_track(dom):
    slider = _Handle(SLIDER)
    dom.update({"parent": [slider]})
    assert PageSolver._track_outside(_solver(), "panel", "yidun", _Handle(PANEL), _At()) is slider


def test_the_piece_inside_the_panel_is_not_taken_for_the_handle(dom):
    dom.update({"panel": [_Handle(PIECE)]})
    assert PageSolver._track_outside(_solver(), "panel", "yidun", _Handle(PANEL), _At()) is None


def test_without_the_widgets_locator_only_the_widget_is_searched(dom):
    dom.update({"parent": [_Handle(SLIDER)]})
    assert PageSolver._track_outside(_solver(), "panel", "yidun", _Handle(PANEL)) is None


def test_a_vendor_without_its_own_handle_is_not_widened(dom):
    dom.update({"panel": [_Handle(SLIDER)]})
    assert PageSolver._track_outside(_solver(), "panel", "plain", _Handle(PANEL), _At()) is None


def test_a_scope_that_cannot_be_searched_leaves_the_shot_alone(monkeypatch):
    def boom(where, sels):
        raise RuntimeError("frame was detached")
    monkeypatch.setattr(page_solver, "_visible", boom)
    assert PageSolver._track_outside(_solver(), "panel", "yidun", _Handle(PANEL), _At()) is None


def test_a_track_that_would_more_than_double_the_shot_leaves_it_alone():
    far = {"x": 630.5, "y": 1100, "width": 320, "height": 40}
    assert _WithAnswerBox(_Handle(PANEL), _Handle(far), SLIDER_TRACK_MAX_GROWTH).bounding_box() == PANEL


# Yidun's click modes (请依次点击): the same 320x40 bar holds the prompt naming the marks and their order, and no slider
# handle at all. On the bare panel the pointer saw no prompt and went 0/6 live on 2026-11-13.
def _bar_solver():
    yidun = SimpleNamespace(bar=(".yidun_control",), slider_handle=(".yidun_slider", ".yidun_jigsaw"))
    return SimpleNamespace(_sel=SimpleNamespace(selectors={"yidun": yidun}))


def test_a_click_board_is_shown_with_its_prompt_bar(dom):
    bar = _Handle(BAR)
    dom.update({"parent": [bar]})
    assert PageSolver._track_outside(_bar_solver(), "panel", "yidun", _Handle(PANEL), _At()) is bar
    assert _WithAnswerBox(_Handle(PANEL), bar, SLIDER_TRACK_MAX_GROWTH).bounding_box()["height"] == 215


def test_the_bar_is_taken_itself_not_its_parent(dom):
    bar = _Handle(BAR, parent=_Handle({"x": 630.5, "y": 621, "width": 320, "height": 215}))
    dom.update({"parent": [bar]})
    assert PageSolver._track_outside(_bar_solver(), "panel", "yidun", _Handle(PANEL), _At()) is bar


def test_the_shipped_config_names_yiduns_bar():
    from captchakraken.selectors import DEFAULT_TABLE, Vendor
    assert ".yidun_control" in DEFAULT_TABLE.selectors[Vendor.YIDUN].bar
