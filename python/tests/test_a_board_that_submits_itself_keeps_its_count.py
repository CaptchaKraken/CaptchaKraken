"""A click board with no Verify submits itself at a count, and every plan queued for it is held to that count.

Tier 3, 2026-11-15, Yidun 点击两下 on both ports: the first answer's queue was cut to two-click plans, the re-ask on
the same board brought a fresh queue led by a one-click plan, and that press stayed on the board as a stray mark.
"""
import sys
from pathlib import Path
from types import SimpleNamespace

SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

from captchakraken.page_solver import PageSolver, PageSolverConfig


def click(n):
    return {"action": "click", "points": [[0.2, 0.2]] * n}


def answer(n):
    return [{"action": "click", "target_bounding_boxes": [[0.2, 0.2, 0.3, 0.3]] * n}]


def _solver(queue):
    solver = PageSolver(config=PageSolverConfig())
    solver._reset_animated_state()
    solver._solver = SimpleNamespace(planner=SimpleNamespace(pointer_fallbacks=list(queue)))
    return solver


def test_a_re_asks_fresh_plans_are_held_to_the_count_the_board_showed():
    solver = _solver([click(1), click(2), click(1)])
    solver._keep_plans_of_this_many_clicks(answer(2))
    assert solver._solver.planner.pointer_fallbacks == [click(2)]
    solver._solver.planner.pointer_fallbacks = [click(1), click(2), click(1)]   # the re-ask's fresh queue
    solver._hold_fallbacks_to_submit_count()
    assert solver._solver.planner.pointer_fallbacks == [click(2)]


def test_a_new_solve_forgets_the_count():
    solver = _solver([])
    solver._keep_plans_of_this_many_clicks(answer(2))
    solver._reset_animated_state()
    solver._solver.planner.pointer_fallbacks = [click(1), click(3)]
    solver._hold_fallbacks_to_submit_count()
    assert len(solver._solver.planner.pointer_fallbacks) == 2


def test_a_fresh_board_forgets_the_count():
    solver = _solver([])
    solver._keep_plans_of_this_many_clicks(answer(2))
    solver._fresh_board()
    solver._solver.planner.pointer_fallbacks = [click(1), click(3)]
    solver._hold_fallbacks_to_submit_count()
    assert len(solver._solver.planner.pointer_fallbacks) == 2
