# A round that performed nothing gave the page nothing to react to.
#
# A refused answer, a repeated one, or an answer with nothing to execute leaves the page exactly as it was, so the
# next round can start at once. Each of them used to pay the post-round dwell (1.2-1.5s) and then the stale-element
# backoff (0.9s) on top: a board the model kept missing spent over two seconds a round waiting on nothing, and its
# per-board time doubled. Only a widget caught mid-transition — a stale handle, a board that would not screenshot —
# is worth waiting out, and it still is.
import sys
import time
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

from captchakraken.page_solver import CaptchaSolveError, PageSolver, PageSolverConfig, _now


def _driver(round_result, **config):
    """A solver every round of which is `round_result()`; the dwell and backoff keep their defaults."""
    solver = PageSolver(config=PageSolverConfig(max_solve_loops=4, video_solve_enabled=False, **config))
    solver._reset_animated_state()
    rounds = []

    def solve_single(page, widget, retry_mode):
        rounds.append(1)
        return round_result()

    solver.detect_captcha = lambda page: object()
    solver._solve_single = solve_single
    solver.is_captcha_solved = lambda page: False
    solver._banner_kind = lambda page: None
    solver._is_challenge_freshly_rendered = lambda page: False
    return solver, rounds


def _elapsed_ms(solver) -> float:
    t0 = time.perf_counter()
    try:
        solver._solve_impl(object(), _now(), [])
    except CaptchaSolveError:
        pass
    return (time.perf_counter() - t0) * 1000.0


def test_rounds_that_performed_nothing_do_not_dwell_or_back_off():
    solver, rounds = _driver(lambda: (False, []))
    elapsed = _elapsed_ms(solver)
    assert len(rounds) == 4
    # Four rounds at the old dwell plus backoff cost at least 4 x 2.1s.
    assert elapsed < 1_000, f"four rounds that did nothing took {elapsed:.0f}ms"


def test_a_widget_caught_mid_transition_is_still_waited_out():
    def stale():
        raise RuntimeError("Element is not attached to the DOM")

    solver, rounds = _driver(stale, stale_element_backoff_ms=150)
    elapsed = _elapsed_ms(solver)
    assert len(rounds) == 4
    assert elapsed >= 4 * 150, f"a widget in transition was not waited out ({elapsed:.0f}ms for four rounds)"
