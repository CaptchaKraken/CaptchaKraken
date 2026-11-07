# A board the model has no answer for is skipped, as a person would.
#
# Measured on the Tier 3 gauntlet, 2026-10-27: the engine raised "cannot solve" on an unknown board, which bypassed
# "an empty plan still presses Verify/Skip". The driver re-asked about the same, pixel-identical board until the
# loop cap (~30s) instead of pressing Skip for a new one.
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

from captchakraken.kinds import FrameRole, Vendor  # noqa: E402
from captchakraken.page_solver import PageSolver, PageSolverConfig, Widget  # noqa: E402
from captchakraken.solver import UnsupportedCaptchaError  # noqa: E402


class _Element:
    def content_frame(self):
        return None

    def bounding_box(self):
        return {"x": 0, "y": 0, "width": 300, "height": 200}


def _round(*, text_mode=False, vendor=Vendor.HCAPTCHA):
    solver = PageSolver(config=PageSolverConfig())
    solver._reset_animated_state()
    pressed = []

    class _Engine:
        planner = type("P", (), {"token_usage": []})()

        def solve(self, *a, **kw):
            raise UnsupportedCaptchaError("Cannot solve this kind of captcha")

    solver._solver = _Engine()
    solver._wait_for_board_painted = lambda element: 0
    solver._answer_box = lambda scope, at=None: "box" if text_mode else None
    solver._settle_or_animated = lambda element: False
    solver._should_speculate = lambda puzzle_source, text_mode: False
    solver._solve_frame_freshness_guarded = lambda element, shot, ask: ask(shot)
    solver.is_captcha_solved = lambda page: False
    solver._screenshot = lambda *a, **k: None
    solver._step_off_the_board = lambda page, element: None
    solver._get_verify_button = lambda scope: "skip"
    solver._move_and_click = lambda page, button: pressed.append(button)
    solver._element_frame_hash = lambda element: None

    widget = Widget(element=_Element(), at=None, vendor=vendor, role=FrameRole.CHALLENGE)
    performed, _ = solver._solve_single(object(), widget, None)
    return performed, pressed


def test_a_board_with_no_answer_presses_skip():
    performed, pressed = _round()
    assert pressed == ["skip"], "no answer for this board, and the driver did not press Skip for a new one"
    assert performed


def test_an_unreadable_text_captcha_is_not_submitted_empty():
    """A typed captcha with an empty box is a wrong answer, not a skip; it stays unsupported."""
    try:
        _round(text_mode=True, vendor=Vendor.UNKNOWN)  # hCaptcha never types
        raise AssertionError("expected the unread text captcha to stay unsupported")
    except UnsupportedCaptchaError:
        pass
