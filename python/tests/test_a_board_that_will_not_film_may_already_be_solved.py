# A recording that catches NOTHING is not a verdict about the board.
#
# `_burst` returns no frames only when EVERY screenshot in its window failed. A still photographs
# fine, so nothing coming back does not mean "this board is static" — it means the widget would not
# screenshot at all, and the commonest reason for that is that it is CLOSING, because the answer was
# accepted.
#
# Every other failure in `_solve_impl` asked `is_captcha_solved` before giving up; this one re-raised.
# Measured: prosopo_grid_3x3 solved 8/8 across six runs on 09-12 and 09-13, then lost four attempts
# on 09-17 to exactly this. Each one had its FIRST board come back from the fixture's own /fx/verify
# graded `solved: true, score 1.0, pred == gt`, and died on the second board the vendor dealt — so the
# gate reported a failure on an attempt whose answers the board had already taken.
#
# The vendors that deal more than one board are where this costs the most: the accepted board buys
# nothing if the solve dies on the next one.
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

from captchakraken.page_solver import (  # noqa: E402
    AnimatedChallengeError, CaptchaSolveError, PageSolver, PageSolverConfig, _now,
)


def _driver(*, rounds_before_blank: int, solved_after: bool, raises=AnimatedChallengeError, every_round: bool = False):
    """A solver whose Nth round (or every round from it on) cannot film, and whose widget reports `solved_after` afterwards."""
    solver = PageSolver(config=PageSolverConfig(max_solve_loops=6, post_solve_outcome_timeout_ms=1,
                                                post_solve_delay_ms=1, stale_element_backoff_ms=0))
    solver._reset_animated_state()
    state = {"rounds": 0, "solved": False}

    def solve_single(page, widget, retry_mode):
        state["rounds"] += 1
        if state["rounds"] == rounds_before_blank + 1 or (every_round and state["rounds"] > rounds_before_blank):
            state["solved"] = solved_after
            raise raises("could not record the animated challenge (no frame screenshotted)")
        solver._acted_on_board = True
        return True, []

    solver.detect_captcha = lambda page: object()
    solver._solve_single = solve_single
    solver.is_captcha_solved = lambda page: state["solved"]
    solver._banner_kind = lambda page: None
    solver._is_challenge_freshly_rendered = lambda page: False
    return solver, state


def test_a_board_the_vendor_took_is_not_lost_because_the_next_one_would_not_film():
    """The prosopo shape: board 1 accepted, board 2 unscreenshottable, whole solve discarded."""
    solver, state = _driver(rounds_before_blank=1, solved_after=True)
    result = solver._solve_impl(object(), _now(), [])
    assert result.is_solved is True, "an accepted board was thrown away by a failed recording"


def test_the_question_is_asked_before_giving_up():
    solver, state = _driver(rounds_before_blank=1, solved_after=True)
    asked = []
    inner = solver.is_captcha_solved
    solver.is_captcha_solved = lambda page: (asked.append(1), inner(page))[1]
    solver._solve_impl(object(), _now(), [])
    assert asked, "the solve ended without ever asking whether the board had been accepted"


def test_a_board_that_will_not_film_and_is_not_solved_is_re_detected():
    """Not solved is not dead either: the handle is stale for the same reason, so retry it."""
    solver, state = _driver(rounds_before_blank=1, solved_after=False)
    try:
        solver._solve_impl(object(), _now(), [])
    except CaptchaSolveError:
        pass
    assert state["rounds"] > 2, f"gave up after {state['rounds']} rounds instead of re-detecting"


def test_the_retry_is_bounded_by_the_solve_loops():
    """Without a bound this is an infinite loop on a widget that never screenshots again."""
    solver, state = _driver(rounds_before_blank=0, solved_after=False, every_round=True)
    with pytest.raises(CaptchaSolveError, match="after 6 solve loops"):
        solver._solve_impl(object(), _now(), [])
    assert state["rounds"] == 6


def test_a_first_round_that_cannot_film_is_not_the_end_of_the_solve():
    """Nothing has been answered yet, so there is nothing to lose by looking again; the loops are the bound."""
    solver, state = _driver(rounds_before_blank=0, solved_after=False)
    with pytest.raises(CaptchaSolveError):
        solver._solve_impl(object(), _now(), [])
    assert state["rounds"] == 6, f"gave up after {state['rounds']} rounds with loops still in hand"


def test_a_proven_animated_board_that_will_not_film_is_filmed_again():
    """It keeps its animated verdict, so the next round films it rather than answering it as a still."""
    solver, state = _driver(rounds_before_blank=1, solved_after=False, raises=AnimatedChallengeError)
    with pytest.raises(CaptchaSolveError):
        solver._solve_impl(object(), _now(), [])
    assert state["rounds"] == 6


def test_a_board_that_will_not_film_with_recording_off_is_a_hard_stop():
    """A caller who switched recording off asked for animated boards to be refused, and gets that at once."""
    solver, state = _driver(rounds_before_blank=0, solved_after=False, raises=AnimatedChallengeError)
    solver.config.video_solve_enabled = False
    with pytest.raises(AnimatedChallengeError):
        solver._solve_impl(object(), _now(), [])
    assert state["rounds"] == 1


def _solver_that_films_nothing(known_animated: bool):
    solver = PageSolver(config=PageSolverConfig())
    solver._reset_animated_state()
    solver._known_animated = known_animated
    solver._grant_video_budget = lambda: None
    solver._burst = lambda element, known=frozenset(), max_ms=None: ([], [], False, 0.0, False)
    return solver


def test_a_failed_film_keeps_the_boards_animated_verdict():
    """Measured before: a failed film that dropped the verdict answered every later round as a still, and two video
    types went from 3 solved and 10 keyframe calls to 0 and 0. The next round must film the board again."""
    solver = _solver_that_films_nothing(known_animated=True)
    with pytest.raises(AnimatedChallengeError):
        solver._record_keyframes(object())
    assert solver._known_animated is True
