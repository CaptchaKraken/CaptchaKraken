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


def test_a_board_answered_the_same_way_three_times_ends_the_solve():
    """No solve ever followed a third identical answer; the loops left would only cost the board 3-7s each."""
    from captchakraken.page_solver import CaptchaSolveError, _now

    solver = PageSolver(config=PageSolverConfig(max_solve_loops=6, video_solve_enabled=False))
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
        assert "same answer 3 times" in str(exc), str(exc)
    assert len(rounds) == 3, f"spent {len(rounds)} rounds on a board the model cannot read"
