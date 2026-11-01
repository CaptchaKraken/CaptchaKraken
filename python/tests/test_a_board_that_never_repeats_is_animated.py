# A continuous animation never shows a screen twice and never holds one, so a burst that only knew "a screen came
# back" or "nothing new for a floor window" filmed it to the ceiling and called it a still. The JS port already
# treats many screens still arriving as animated; this pins the Python port to the same verdict.
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

from captchakraken import page_solver
from captchakraken.page_solver import BURST_ANIMATED_SCREENS, PageSolver, PageSolverConfig
from virtual_clock import install


def _burst(monkeypatch, screen_for_frame):
    import numpy as np

    clock = install(monkeypatch, page_solver)
    solver = PageSolver(config=PageSolverConfig())
    solver._reset_animated_state()
    frame = {"n": 0}

    def fake_shot(element, path, animations="allow", **_kw):
        frame["n"] += 1
        clock.now += 0.005
        Path(path).write_bytes(b"screen-%d" % screen_for_frame(frame["n"]) + b"\x00" * 64)

    monkeypatch.setattr(solver, "_screenshot", fake_shot)
    monkeypatch.setattr("captchakraken.keyframes.read_frame", lambda p: np.zeros((4, 4, 3), dtype=np.uint8))
    _frames, order, moved, _ms, _cycled = solver._burst(object())
    return order, moved


def test_a_board_that_never_repeats_is_animated(monkeypatch):
    order, moved = _burst(monkeypatch, lambda n: n)
    assert len(order) > BURST_ANIMATED_SCREENS
    assert moved, "screens still arriving past the floor with no repeat read as a still"


def test_a_board_that_moved_once_and_held_is_still(monkeypatch):
    order, moved = _burst(monkeypatch, lambda n: min(n, 2))
    assert len(order) == 2
    assert not moved


def test_a_cycle_is_still_animated(monkeypatch):
    order, moved = _burst(monkeypatch, lambda n: n % 3)
    assert len(order) == 3
    assert moved
