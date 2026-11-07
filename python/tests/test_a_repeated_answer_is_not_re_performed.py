import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

from captchakraken.page_solver import PageSolver, PageSolverConfig

ANSWER = [{"action": "click", "target_bounding_boxes": [[0.31, 0.226, 0.334, 0.25]]}]


def test_a_repeated_answer_is_reported_so_the_round_performs_nothing():
    solver = PageSolver(config=PageSolverConfig())
    solver._reset_animated_state()
    assert solver._note_answer(ANSWER, None) is False, "the first answer runs"
    assert solver._note_answer(ANSWER, None) is True, "the same answer again already ran and changed nothing"
    assert solver._no_progress_rounds == 1


def test_a_different_answer_resets_the_count():
    solver = PageSolver(config=PageSolverConfig())
    solver._reset_animated_state()
    solver._note_answer(ANSWER, None)
    solver._note_answer(ANSWER, None)
    other = [{"action": "click", "target_bounding_boxes": [[0.5, 0.5, 0.6, 0.6]]}]
    assert solver._note_answer(other, None) is False
    assert solver._no_progress_rounds == 0


def test_a_repeat_with_nothing_else_to_try_ends_the_solve():
    """At temperature 0 a third ask of the same board returns the same answer, and a repeat presses nothing."""
    from captchakraken.page_solver import CaptchaSolveError, _now

    solver = PageSolver(config=PageSolverConfig(max_solve_loops=6, video_solve_enabled=False))
    solver._solver = None
    solver._reset_animated_state()
    rounds = []

    def solve_single(page, widget, retry_mode):
        rounds.append(1)
        solver._note_answer(ANSWER, retry_mode)   # the model answers this board the same way every round
        return False, []

    solver.detect_captcha = lambda page: object()
    solver._solve_single = solve_single
    solver.is_captcha_solved = lambda page: False
    solver._banner_kind = lambda page: None
    solver._is_challenge_freshly_rendered = lambda page: False
    try:
        solver._solve_impl(object(), _now(), [])
        raise AssertionError("expected the solve to end")
    except CaptchaSolveError as exc:
        assert "same answer 2 times" in str(exc), str(exc)
    assert len(rounds) == 2, f"spent {len(rounds)} rounds on a board the model cannot read"


def _pointer_solver(**config):
    from captchakraken import planner as P
    pl = P.ActionPlanner.__new__(P.ActionPlanner)
    pl.pointer_answers, pl.pointer_fallbacks, pl.avoid_refused, pl.pointer_has_actions = [], [], False, False
    pl.prompts = type("Prompts", (), {"pointer": True})()
    solver = PageSolver(config=PageSolverConfig(**config), solver=type("S", (), {"planner": pl})())
    solver._reset_animated_state()
    return solver


def test_a_repeat_goes_on_while_a_recording_is_left_to_take():
    """A board that cycles reads as a still and repeats, and filming it is the one recovery that can still work."""
    solver = _pointer_solver(video_solve_enabled=True)
    solver._note_answer(ANSWER, None)
    solver._note_answer(ANSWER, None)
    assert solver._another_move_left(None) is True
    solver._animated_probe_armed = False
    solver._animated_probe_done = True
    solver._solver.planner.avoid_refused = False
    assert solver._another_move_left(None) is False, "the film is spent and no plan was earned"
    assert solver._another_move_left("missed_tiles") is True, "a retry mode is a different question"


def test_a_repeat_goes_on_while_the_model_has_another_plan():
    solver = _pointer_solver(video_solve_enabled=False)
    solver._note_answer(ANSWER, None)
    solver._note_answer(ANSWER, None)
    assert solver._solver.planner.avoid_refused is True
    assert solver._another_move_left(None) is True


def test_an_answer_pressed_earlier_on_this_picture_is_a_repeat_after_another_plan():
    """Dealing the same picture again clears the plans, and the first answer came back and was pressed again."""
    solver = _pointer_solver()
    other = [{"action": "click", "target_bounding_boxes": [[0.5, 0.5, 0.6, 0.6]]}]
    solver._guard_fallbacks_to_board("board")
    assert solver._note_answer(ANSWER, None) is False
    assert solver._note_answer(other, None) is False
    assert solver._note_answer(ANSWER, None) is True


def test_a_paged_puzzle_may_come_back_to_a_page():
    """The earlier screens are part of the question, so the same page later is not the same ask."""
    solver = _pointer_solver()
    other = [{"action": "click", "target_bounding_boxes": [[0.5, 0.5, 0.6, 0.6]]}]
    solver._guard_fallbacks_to_board("page-1")
    solver._note_answer(ANSWER, None)
    solver._pointer_history.append("page-1.png")
    solver._note_answer(other, None)
    assert solver._note_answer(ANSWER, None) is False


def test_a_refresh_that_brings_the_same_board_back_ends_the_solve():
    from captchakraken.page_solver import CaptchaSolveError
    solver = _pointer_solver()
    solver._guard_fallbacks_to_board("board")
    assert solver._note_answer([{"action": "refresh"}], None) is False
    solver._guard_fallbacks_to_board("another board")
    try:
        solver._guard_fallbacks_to_board("board")
        raise AssertionError("expected the solve to end")
    except CaptchaSolveError as exc:
        assert "unchanged after a refresh" in str(exc)


def test_the_failure_reported_is_the_last_rounds_not_an_earlier_ones():
    from captchakraken.page_solver import CaptchaSolveError, _now
    solver = PageSolver(config=PageSolverConfig(max_solve_loops=3, video_solve_enabled=True,
                                                post_solve_outcome_timeout_ms=0))
    solver._solver = None
    solver._reset_animated_state()
    answers = iter([ANSWER, ANSWER, [{"action": "click", "target_bounding_boxes": [[0.5, 0.5, 0.6, 0.6]]}]])
    solver.detect_captcha = lambda page: object()
    solver._solve_single = lambda page, widget, retry_mode: (not solver._note_answer(next(answers), retry_mode), [])
    solver.is_captcha_solved = lambda page: False
    solver._banner_kind = lambda page: None
    solver._is_challenge_freshly_rendered = lambda page: False
    try:
        solver._solve_impl(object(), _now(), [])
        raise AssertionError("expected the solve to end")
    except CaptchaSolveError as exc:
        assert "after 3 solve loops" in str(exc) and "same answer" not in str(exc), str(exc)
