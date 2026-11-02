"""A repeated answer is counted per board, and from the first repeat every ask names the refused answers so the
pointer returns its likeliest other one. Re-asks stay greedy: (0.0, 0.35, 0.7) scored 0/5 against 4/5."""

import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

from captchakraken.page_solver import PageSolver, PageSolverConfig


class _Planner:
    def __init__(self):
        self.avoid_refused = False
        self.pointer_answers = []


def _solver(**kw):
    s = PageSolver(config=PageSolverConfig(**kw))
    s._solver.planner = _Planner()
    s._reset_animated_state()
    return s


def _answer(n):
    return [{"action": "click", "target_coordinates": [n, n]}]


def test_the_first_look_at_a_board_avoids_nothing():
    s = _solver()
    s._note_answer(_answer(1), None)
    assert s._solver.planner.avoid_refused is False


def test_a_repeated_answer_turns_on_avoiding_it():
    s = _solver()
    s._note_answer(_answer(1), None)
    s._note_answer(_answer(1), None)
    assert s._refused_rounds > 0
    assert s._solver.planner.avoid_refused is True


def test_a_fresh_board_goes_back_to_zero():
    s = _solver()
    s._note_answer(_answer(1), None)
    s._note_answer(_answer(1), None)
    s._fresh_board()
    assert s._refused_rounds == 0
    assert s._solver.planner.avoid_refused is False


def test_a_new_solve_starts_at_zero():
    s = _solver()
    s._note_answer(_answer(1), None)
    s._note_answer(_answer(1), None)
    s._reset_animated_state()
    assert s._refused_rounds == 0
