# A round is decided from the board it can see.
#
# Two questions open every round, and both are answered from the widget as it stands at that instant:
# WHICH EXPERT answers it, read out of the DOM as "is there a text box in here", and WHETHER THE BOARD
# CYCLES, read off its motion. A widget that has not drawn yet answers both wrongly in the same way —
# it holds no text box to find, and the only motion it has is its own arrival.
#
# Measured on 2026-09-17: a resolved vendor frame holding zero elements sent a distorted-text board to
# the still expert, and a classifier that started before the board painted spent its window on a blank
# widget and called a board that cycles a still — which is then answered from one screen, clicked, and
# refused. Both are the same mistake, so both are fixed by asking after the paint rather than before.
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

from captchakraken.kinds import FrameRole, Vendor  # noqa: E402
from captchakraken.page_solver import PageSolver, PageSolverConfig, Widget  # noqa: E402

JS_SOLVER = Path(__file__).resolve().parents[2] / "js" / "src" / "solver.ts"


class _Stop(Exception):
    """Ends the round at the point every question above it has been asked."""


class _Element:
    def content_frame(self):
        return None

    def bounding_box(self):
        return {"x": 0, "y": 0, "width": 300, "height": 200}


def _round(*, vendor=Vendor.UNKNOWN, has_text_box=True, grid=False):
    """Drive one round over a widget that only holds its text box once it has painted.

    Returns `(trace, text_mode)` — the order the round asked its questions in, and the expert it chose.
    `grid` puts a 3x3 lattice in the widget, which is the branch reCAPTCHA takes instead of both questions.
    """
    solver = PageSolver(config=PageSolverConfig())
    solver._reset_animated_state()
    trace: list = []
    painted = {"yet": False}
    chose: list = []

    def wait_for_board_painted(element):
        painted["yet"] = True
        trace.append("paint")
        return 0

    def answer_box(scope, at=None):
        trace.append("route")
        return "box" if has_text_box and painted["yet"] else None

    def settle_or_animated(element):
        trace.append("watch")
        return False

    def should_speculate(puzzle_source, text_mode):
        chose.append(text_mode)
        raise _Stop()

    solver._wait_for_board_painted = wait_for_board_painted
    solver._answer_box = answer_box
    solver._settle_or_animated = settle_or_animated
    solver._should_speculate = should_speculate
    solver.is_captcha_solved = lambda page: False
    solver._screenshot = lambda *a, **k: None
    solver._step_off_the_board = lambda page, element: None
    if grid:
        def solve_grid(*a, **kw):
            trace.append("grid")
            raise _Stop()

        solver._wait_for_grid_cells_loaded = lambda element: True
        solver._get_grid_boxes = lambda element: {"boxes": [], "size": 3,
                                                  "screenshot_w": 300, "screenshot_h": 300}
        solver._solve_recaptcha_grid = solve_grid

    widget = Widget(element=_Element(), at=None, vendor=vendor, role=FrameRole.CHALLENGE)
    with pytest.raises(_Stop):
        solver._solve_single(object(), widget, None)
    return trace, (chose[0] if chose else None)


def test_the_board_paints_before_the_round_is_routed():
    trace, text_mode = _round()
    assert trace.index("paint") < trace.index("route"), (
        f"the expert was chosen before the board had drawn anything: {trace}")
    assert text_mode is True, "a distorted-text board was sent to the still expert"


def test_the_board_paints_before_it_is_watched_for_motion():
    trace, _ = _round(has_text_box=False)
    assert trace.index("paint") < trace.index("watch"), (
        f"the board was classified while it was still arriving: {trace}")


def test_a_grid_board_waits_on_its_cells_and_not_twice():
    """reCAPTCHA is asked neither question and reads its board through the grid gate, which waits on the
    cells themselves. Waiting for the paint in front of that gate measured 0.8-1.8s a round on the family
    with the tightest per-board budget, and bought nothing: the gate below covers the same board."""
    trace, _ = _round(vendor=Vendor.RECAPTCHA, grid=True)
    assert trace == ["grid"], f"a grid round paid for a wait it does not use: {trace}"


def test_a_vendor_that_never_types_is_not_asked():
    """hCaptcha and reCAPTCHA have no text box by definition; asking costs a DOM query every round."""
    trace, text_mode = _round(vendor=Vendor.HCAPTCHA)
    assert "route" not in trace
    assert text_mode is False


def test_the_js_port_paints_before_it_routes():
    """The JS port drives its own DOM, so the order is pinned at the source: a port that kept the old
    one would send the same board to a different expert with nothing to catch it."""
    src = JS_SOLVER.read_text()
    paint = src.index("Phase.BOARD_PAINT")
    route = src.index("const textMode =")
    classify = src.index("this.classifyByRecording(")
    assert paint < route, "solver.ts chooses the expert before it waits for the board to paint"
    assert paint < classify, "solver.ts starts the classifier before the board has painted"
    assert "puzzleSource === Vendor.RECAPTCHA ? null" in src[:paint][-200:], (
        "solver.ts makes a grid round wait for a paint it does not use")
