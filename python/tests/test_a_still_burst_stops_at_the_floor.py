# The burst is a wall-clock window, and the frames it holds are however many the camera managed in that window. On a virtual
# clock the count is exact, and the two things a real clock could never pin — a stalled frame, a late transition — are pinned too.
import sys
from pathlib import Path
from typing import List, Sequence, Tuple

SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

from captchakraken import page_solver
from captchakraken.page_solver import PageSolver, PageSolverConfig
from virtual_clock import install

_PNG_A = b"screen-A" + b"\x00" * 64
_PNG_B = b"screen-B" + b"\x11" * 64
_PNG_C = b"screen-C" + b"\x22" * 64

CFG = PageSolverConfig()
INTERVAL_MS = 1000.0 / CFG.video_burst_fps
FLOOR = round(CFG.video_burst_duration_ms / INTERVAL_MS)
CEILING = round(CFG.video_burst_max_ms / INTERVAL_MS)
QUICK_MS = 5.0


class _Kf:
    def __init__(self, n):
        self.mode = "still"
        self.steady_screens = 1
        self.frames = list(range(n))


def _burst(monkeypatch, payloads: Sequence[bytes], work_ms: Sequence[float] = ()) -> Tuple[int, float, List[float]]:
    """Film `payloads` in order; frame i costs `work_ms[i]` (QUICK_MS past the end). Returns (frames, burst_ms, capture times)."""
    import numpy as np

    clock = install(monkeypatch, page_solver)
    solver = PageSolver(config=PageSolverConfig())
    solver._reset_animated_state()
    solver._deadline_ms = None
    captured: List[float] = []

    def fake_shot(element, path, animations="allow"):
        i = len(captured)
        captured.append(clock.now * 1000.0)
        clock.now += (work_ms[i] if i < len(work_ms) else QUICK_MS) / 1000.0
        with open(path, "wb") as fh:
            fh.write(payloads[min(i, len(payloads) - 1)])

    monkeypatch.setattr(solver, "_screenshot", fake_shot)
    monkeypatch.setattr("captchakraken.keyframes.read_frame", lambda p: np.zeros((4, 4, 3), dtype=np.uint8))
    frames, _order, _moved, burst_ms, _cycled = solver._burst(object())
    return len(frames), burst_ms, captured


def test_a_board_that_never_changes_stops_at_the_burst_floor(monkeypatch):
    assert CEILING > FLOOR, "this test is meaningless if the two are equal"
    n, burst_ms, _ = _burst(monkeypatch, [_PNG_A])
    assert n == FLOOR + 1, (
        f"a still board filmed {n} frames; the floor is {FLOOR} and the ceiling {CEILING}. One screen can never "
        f"close a cycle, so without a still exit the recording always runs to the ceiling")
    assert CFG.video_burst_duration_ms <= burst_ms < CFG.video_burst_max_ms


def test_the_js_port_has_the_same_still_exit():
    js = (Path(__file__).resolve().parents[2] / "js" / "src" / "solver.ts").read_text()
    assert "Date.now() - lastNewAt >= floorMs" in js, (
        "the JS burst has no settled exit: a board that stops producing new "
        "screens can never close a cycle, so it films to videoBurstMaxMs while "
        "the python port stops once it has settled")


def test_a_board_that_moves_once_and_holds_also_stops(monkeypatch):
    n, _, _ = _burst(monkeypatch, [_PNG_A, _PNG_B])
    assert n == FLOOR + 2, (
        f"a board that moved once and then held filmed {n} of {CEILING} frames "
        f"— it settled after one transition and the burst did not notice")


def test_a_genuinely_cycling_board_is_not_cut_short(monkeypatch):
    payloads = ([_PNG_A] * 10 + [_PNG_B] * 10 + [_PNG_C] * 10) * 8
    n, burst_ms, _ = _burst(monkeypatch, payloads)
    assert n == FLOOR + 1, f"a cycling board stopped at {n} frames, off the floor"
    assert burst_ms >= CFG.video_burst_duration_ms


def test_a_stalled_frame_drops_its_slot_rather_than_bunching(monkeypatch):
    stall = [QUICK_MS] * 20 + [3.5 * INTERVAL_MS]
    n, burst_ms, captured = _burst(monkeypatch, [_PNG_A], stall)
    assert n == FLOOR - 1, f"one stall of 3.5 intervals should cost the two slots it covered, not {FLOOR + 1 - n}"
    assert burst_ms >= CFG.video_burst_duration_ms, "the window is wall-clock; a slow camera still films all of it"
    gaps = [b - a for a, b in zip(captured, captured[1:])]
    assert min(gaps) >= INTERVAL_MS - 1e-6, f"frames bunched after the stall: {sorted(gaps)[:3]}"


def test_a_late_transition_extends_the_stillness_window(monkeypatch):
    n, burst_ms, captured = _burst(monkeypatch, [_PNG_A, _PNG_B], [QUICK_MS, 1.5 * INTERVAL_MS])
    assert n == FLOOR + 3, f"filmed {n}; the window is measured from when the last new screen was captured"
    assert burst_ms - captured[1] >= CFG.video_burst_duration_ms, "less than a floor of stillness after the change"
