# An answer with nothing to execute is not proof the page is stuck.
#
# A round that executes nothing counts one loop, and the loops are its only bound. An answer the driver could
# not USE is not a dead page: on an animated board it is exactly what a still expert returns when the board is
# not a still, so the round after it is armed for a recording.
#
# Measured on the hosted arms, 2026-09-17: an animated hCaptcha board was answered with
# `{"action": "drag", "source_bounding_box": null, ...}`; the driver logged "slide action, but the widget has
# neither a slider nor a draggable piece", performed nothing, and aborted 6.0s into a 45s budget with the
# recording never taken. Three video types failed 0/2 that way while the same boards solved on the other
# adapter. One second look costs a round; giving up costs the solve.
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

from captchakraken.page_solver import CaptchaSolveError, PageSolver, PageSolverConfig, _now


def _driver(rounds_answered_with_nothing: int, video_solve_enabled: bool = True):
    """A solver whose answers execute nothing for the first N rounds; records what each round was armed with."""
    solver = PageSolver(config=PageSolverConfig(max_solve_loops=4, post_solve_outcome_timeout_ms=1,
                                                post_solve_delay_ms=1, stale_element_backoff_ms=0,
                                                video_solve_enabled=video_solve_enabled))
    solver._reset_animated_state()
    armed = []

    def solve_single(page, widget, retry_mode):
        armed.append(solver._animated_probe_armed)
        if len(armed) <= rounds_answered_with_nothing:
            return False, []      # an answer the widget could not take
        solver._acted_on_board = True
        return True, []

    solver.detect_captcha = lambda page: object()
    solver._solve_single = solve_single
    solver.is_captcha_solved = lambda page: False
    solver._banner_kind = lambda page: None
    solver._is_challenge_freshly_rendered = lambda page: False
    return solver, armed


def test_the_recording_path_gets_a_round_after_an_unusable_answer():
    solver, armed = _driver(rounds_answered_with_nothing=1)
    try:
        solver._solve_impl(object(), _now(), [])
    except CaptchaSolveError:
        pass
    assert len(armed) >= 2, "the driver gave up instead of taking a second look"
    assert armed[1] is True, "the round after an unusable answer was not armed for a recording"


def test_a_page_that_never_takes_an_answer_gives_up_when_the_loops_are_spent():
    """Not before: every unusable answer is a round, and the loops are what bound them."""
    solver, armed = _driver(rounds_answered_with_nothing=99)
    try:
        solver._solve_impl(object(), _now(), [])
        raise AssertionError("expected the solve to end")
    except CaptchaSolveError as exc:
        assert "after 4 solve loops" in str(exc) and "performed no interactions" in str(exc)
    assert len(armed) == 4, f"used {len(armed)} of 4 loops"


def test_a_caller_with_recording_off_never_arms_a_recording():
    solver, armed = _driver(rounds_answered_with_nothing=99, video_solve_enabled=False)
    try:
        solver._solve_impl(object(), _now(), [])
        raise AssertionError("expected the solve to end")
    except CaptchaSolveError as exc:
        assert "performed no interactions" in str(exc)
    assert armed == [False] * 4, "recording is off; there is no second look to buy"
