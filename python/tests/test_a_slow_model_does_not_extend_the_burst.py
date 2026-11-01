# The burst runs on a virtual clock: a loop that waited on the model would film to the ceiling in virtual time while the
# model's real wait ran, so the count still tells them apart, and the test no longer measures the runner's cadence.
import sys
import time
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

from captchakraken import page_solver
from captchakraken.page_solver import PageSolver, PageSolverConfig
from virtual_clock import install

_STILL = b"one-screen-forever" + b"\x00" * 64


class _Kf:
    def __init__(self, n):
        self.mode = "still"
        self.steady_screens = 1
        self.frames = list(range(n))


def _run(monkeypatch, model_seconds):
    import numpy as np

    clock = install(monkeypatch, page_solver)
    solver = PageSolver(config=PageSolverConfig())
    solver._reset_animated_state()
    solver._deadline_ms = None

    shots = {"n": 0}

    def fake_shot(element, path, animations="allow", **_kw):
        shots["n"] += 1
        clock.now += 0.005
        with open(path, "wb") as fh:
            fh.write(_STILL)

    def slow_model(*_a, **_kw):
        time.sleep(model_seconds)
        return [], []

    phases: list = []

    import contextlib

    @contextlib.contextmanager
    def recording_phase(name):
        phases.append(name)
        yield

    monkeypatch.setattr(solver, "_screenshot", fake_shot)
    monkeypatch.setattr(solver, "_get_solution", slow_model)
    monkeypatch.setattr(solver, "_phase", recording_phase)
    monkeypatch.setattr("captchakraken.keyframes.read_frame",
                        lambda p: np.zeros((4, 4, 3), dtype=np.uint8))
    monkeypatch.setattr("captchakraken.keyframes.extract_keyframes",
                        lambda frames, fps: _Kf(len(frames)))
    monkeypatch.setattr("captchakraken.keyframes.write_keyframes",
                        lambda kfset, d, stem: [])

    solver._speculate(object(), "shot.png", "unknown", None, False)
    return shots["n"], phases


def _floor_and_ceiling():
    cfg = PageSolverConfig()
    per_frame = 1000.0 / cfg.video_burst_fps
    return (round(cfg.video_burst_duration_ms / per_frame),
            round(cfg.video_burst_max_ms / per_frame))


def test_a_still_board_films_the_floor_however_slow_the_model_is(monkeypatch):
    floor, ceiling = _floor_and_ceiling()
    assert ceiling > floor, "this test is meaningless if the two are equal"
    filmed, _ = _run(monkeypatch, model_seconds=0.3)
    assert filmed == floor + 1, (
        f"a still board filmed {filmed} frames against a {floor}-frame floor "
        f"and a {ceiling}-frame ceiling — the burst is still waiting on the "
        f"model rather than on the board")


def test_the_floor_is_still_filmed(monkeypatch):
    floor, _ = _floor_and_ceiling()
    filmed, _ = _run(monkeypatch, model_seconds=0.0)
    assert filmed == floor + 1, f"filmed {filmed} frames against a {floor}-frame floor"


def test_the_wait_for_the_model_is_named(monkeypatch):
    _, phases = _run(monkeypatch, model_seconds=0.2)
    assert phases.count("burst") == 1, phases
    assert "inference" in phases, (
        f"the post-burst wait for the model is outside every phase: {phases}. "
        f"Its cost is then reported as nothing at all.")


def test_the_js_burst_does_not_wait_on_its_inference_either():
    js = (Path(__file__).resolve().parents[2] / "js" / "src" / "solver.ts").read_text()
    marker = "Date.now() - lastNewAt >= floorMs"
    assert marker in js, "the JS burst has lost its settled exit"
    line = next(l for l in js.splitlines() if marker in l)
    assert "done" not in line and "await" not in line, (
        f"the JS settled exit now waits on something: {line.strip()!r}")
