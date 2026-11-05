# ONE FILM, ONE BOARD, at the point the board actually changes.
#
# The film accumulates across rounds so each ask sees more of the board, and a recorded answer may be reused
# once — the widget refuses it, the no-progress fence spots the repeat, and the next round re-asks. That reuse
# was never bounded to the board it was cut from, so when the vendor dealt a DIFFERENT puzzle the plan
# survived it and the next animated round replayed the old board's coordinates onto the new one.
#
# Measured live on 2026-09-16 (Abyss, hCaptcha, attempt 17 of the diagnosis run): a keyframe answer cut from
# round 3's board — [[0.809, 0.088, 0.833, 0.112]], the top-right of the banner, where hCaptcha paints the
# REFERENCE PHOTO — was replayed in round 5 against a board two deals later, logged as "reusing the recorded
# answer — same board, same screens". Nothing checked that claim. Six rounds produced no real attempt.
#
# `_fresh_board()` is the seam the verdict loop calls the moment a next round has painted, and it is where the
# film has to end: `_stop_animated_film` already documents that a gone board's film can never describe the
# next one. These pin that it is actually called from there.
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

from captchakraken.page_solver import PageSolver, PageSolverConfig


def _solver_holding_a_plan(tmp_path):
    """A solver mid-solve on an animated board: a sliced film, an answer from it, and the animated verdict."""
    solver = PageSolver(config=PageSolverConfig())
    slice_dir = tmp_path / "ck_slice_fake"
    slice_dir.mkdir()
    (slice_dir / "frame_01.png").write_bytes(b"keyframe")
    solver._animated_plan = (
        [str(slice_dir / "frame_01.png")],
        str(slice_dir),
        [{"action": "click", "target_bounding_boxes": [[0.809, 0.088, 0.833, 0.112]]}],
        [],
    )
    solver._known_animated = True
    solver._animated_probe_done = True
    return solver, slice_dir


def test_a_new_board_drops_the_recorded_answer(tmp_path):
    solver, _ = _solver_holding_a_plan(tmp_path)
    solver._fresh_board()
    assert solver._animated_plan is None, (
        "a plan that outlives its board gets replayed onto the next one"
    )


def test_a_new_board_drops_the_animated_verdict(tmp_path):
    # Stickiness is the other half: once any board in an attempt read as animated, every later board was
    # forced down the animated path, including a still grid the vendor dealt afterwards.
    solver, _ = _solver_holding_a_plan(tmp_path)
    solver._fresh_board()
    assert solver._known_animated is False, (
        "the previous board's animation verdict was carried onto a board nobody has looked at yet"
    )
    assert solver._animated_probe_done is False, (
        "the new board never gets its own second look"
    )


def test_a_new_board_frees_the_slice(tmp_path):
    solver, slice_dir = _solver_holding_a_plan(tmp_path)
    solver._fresh_board()
    assert not slice_dir.exists(), (
        "the slice is frames on what is a tmpfs on plenty of boxes; a board that is gone must free them"
    )


def test_the_refused_rounds_still_resets(tmp_path):
    # The behaviour `_fresh_board` already had, pinned so the film teardown is an addition rather than a swap.
    solver, _ = _solver_holding_a_plan(tmp_path)
    solver._refused_rounds = 3
    solver._acted_on_board = True
    solver._fresh_board()
    assert solver._refused_rounds == 0
    assert solver._acted_on_board is False
