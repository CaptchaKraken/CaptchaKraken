# A replaced board has failed nothing yet, so it gets no second look.
#
# The second look buys a recording for a board that failed a round as a still. "One film, one board" gave every
# board its own look by resetting `_animated_probe_done` in `_fresh_board()`, but the solve loop armed the probe
# at every loop head from attempt 2 — a stand-in for "the last round failed" that only holds while the SAME
# board is up. On a vendor that deals a new board after every answer, that filmed every still board after the
# solve's first miss. Measured in Tier 3 on a five-board fixture that re-deals after every answer, the way
# hCaptcha does: seven second looks, 28.8s of recording in a 48.3s session, against the client's own 45s
# budget. The same client without the per-board reset ran it in 41.8s; JS, which arms only on evidence, in 35s.
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

from captchakraken.page_solver import CaptchaSolveError, PageSolver, PageSolverConfig, _now


def _drive(replaces_board: bool, loops: int = 4):
    """Run the solve loop over a widget that never passes; returns the probe's arm state at each round's start."""
    solver = PageSolver(config=PageSolverConfig(max_solve_loops=loops, post_solve_outcome_timeout_ms=1))
    solver._reset_animated_state()
    armed_at_round = []

    def solve_single(page, widget, retry_mode):
        armed_at_round.append(solver._animated_probe_armed)
        solver._acted_on_board = True  # what every gesture does
        return True, []

    solver.detect_captcha = lambda page: object()
    solver._solve_single = solve_single
    solver.is_captcha_solved = lambda page: False
    solver._banner_kind = lambda page: None
    solver._is_challenge_freshly_rendered = lambda page: replaces_board
    try:
        solver._solve_impl(object(), _now(), [])
    except CaptchaSolveError:
        pass  # the loop ceiling, which is not what is under test
    return armed_at_round


def test_a_vendor_that_deals_a_new_board_every_round_never_arms_the_second_look():
    assert _drive(replaces_board=True) == [False, False, False, False], (
        "a board nobody has answered yet was armed for a recording because the one before it failed"
    )


def test_a_board_that_failed_and_is_still_up_still_gets_its_second_look():
    armed = _drive(replaces_board=False)
    assert armed[0] is False and armed[1] is True, (
        "the second look is the only retry a still-looking animated board has; it must survive this fix"
    )


def test_a_replaced_board_drops_an_arm_the_previous_board_set():
    # `_note_answer` and the freshness guard arm the probe too. Spent on the board that set it or not, it is
    # evidence about that board.
    solver = PageSolver(config=PageSolverConfig())
    solver._reset_animated_state()
    solver._arm_animated_probe()
    solver._fresh_board()
    assert solver._animated_probe_armed is False
