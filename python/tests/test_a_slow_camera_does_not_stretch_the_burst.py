import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

from captchakraken import page_solver
from captchakraken.page_solver import PageSolver, PageSolverConfig

_PNG_A = b"screen-A" + b"\x00" * 64
_PNG_B = b"screen-B" + b"\x11" * 64
_PNG_C = b"screen-C" + b"\x22" * 64


class _Clock:

    def __init__(self) -> None:
        self.t = 0.0

    def monotonic(self) -> float:
        return self.t

    def sleep(self, seconds: float) -> None:
        self.t += max(0.0, float(seconds))

    def tick(self, seconds: float) -> None:
        self.t += seconds


class _Kf:
    def __init__(self, n: int) -> None:
        self.mode = "static"
        self.steady_screens = 1
        self.frames = list(range(n))


def _burst(monkeypatch, payloads, frame_cost_ms, which="record", **cfg_kw):
    import numpy as np

    clock = _Clock()
    monkeypatch.setattr(page_solver, "time", clock)

    solver = PageSolver(config=PageSolverConfig(**cfg_kw))
    solver._reset_animated_state()
    solver._deadline_ms = None
    calls = {"n": 0}

    def fake_shot(element, path, animations="allow", **kw):
        payload = payloads[calls["n"] % len(payloads)]
        calls["n"] += 1
        with open(path, "wb") as fh:
            fh.write(payload)
        clock.tick(frame_cost_ms / 1000.0)

    monkeypatch.setattr(solver, "_screenshot", fake_shot)
    monkeypatch.setattr("captchakraken.keyframes.read_frame", lambda p: np.zeros((4, 4, 3), dtype=np.uint8))
    monkeypatch.setattr("captchakraken.keyframes.extract_keyframes",
                        lambda frames, fps: _Kf(len(frames)))
    monkeypatch.setattr("captchakraken.keyframes.write_keyframes",
                        lambda kfset, d, stem: [])

    if which == "record":
        try:
            solver._record_keyframes(object())
        except Exception:
            pass
    else:
        monkeypatch.setattr(solver, "_get_solution", lambda *a, **k: ([], []))
        try:
            solver._speculate(object(), "shot.png", "hcaptcha", None, False)
        except Exception:
            pass
    return calls["n"], clock.t * 1000.0


def test_a_slow_camera_does_not_stretch_the_still_window(monkeypatch):
    cfg = PageSolverConfig()
    floor_ms = cfg.video_burst_duration_ms
    n, elapsed = _burst(monkeypatch, [_PNG_A], frame_cost_ms=183.5)
    assert elapsed <= floor_ms * 1.35, (
        f"a still board held the burst for {elapsed:.0f}ms against a "
        f"{floor_ms}ms floor ({n} frames). The window is counted in frames, so "
        f"a camera slower than the interval spends the budget it was given")


def test_a_slow_camera_does_not_stretch_the_speculative_window(monkeypatch):
    cfg = PageSolverConfig()
    floor_ms = cfg.video_burst_duration_ms
    n, elapsed = _burst(monkeypatch, [_PNG_A], frame_cost_ms=183.5,
                        which="speculate")
    assert elapsed <= floor_ms * 1.35, (
        f"the speculative burst held a still board for {elapsed:.0f}ms against "
        f"a {floor_ms}ms floor ({n} frames)")


def test_the_ceiling_is_wall_clock_too(monkeypatch):
    cfg = PageSolverConfig()
    ceiling_ms = cfg.video_burst_max_ms
    payloads = [_PNG_A, _PNG_B, _PNG_C] * 400
    n, elapsed = _burst(monkeypatch, payloads, frame_cost_ms=183.5)
    assert elapsed <= ceiling_ms * 1.2, (
        f"a board that never settles filmed for {elapsed:.0f}ms against a "
        f"{ceiling_ms}ms ceiling ({n} frames)")


def test_a_fast_camera_still_films_the_whole_window(monkeypatch):
    cfg = PageSolverConfig()
    floor_ms = cfg.video_burst_duration_ms
    n, elapsed = _burst(monkeypatch, [_PNG_A], frame_cost_ms=15.8)
    assert elapsed >= floor_ms, (
        f"a still board was filmed for only {elapsed:.0f}ms against a "
        f"{floor_ms}ms floor ({n} frames)")


def test_a_cycling_board_is_still_judged_on_its_screens(monkeypatch):
    cfg = PageSolverConfig()
    floor_ms = cfg.video_burst_duration_ms
    payloads = ([_PNG_A] * 5 + [_PNG_B] * 5 + [_PNG_C] * 5) * 40
    n, elapsed = _burst(monkeypatch, payloads, frame_cost_ms=183.5)
    assert elapsed >= floor_ms, (
        f"a cycling board was cut at {elapsed:.0f}ms, under the {floor_ms}ms floor")
    assert elapsed <= cfg.video_burst_max_ms * 1.2, (
        f"a cycling board filmed {elapsed:.0f}ms; it closes its cycle well "
        f"inside the ceiling")


def test_a_fast_camera_does_not_spin_at_the_ceiling(monkeypatch):
    # The last frame before the ceiling used to DECLINE TO SLEEP rather than end the burst, so from there the
    # loop ran flat out at whatever rate the camera returned — and a ceiling that is not a whole number of
    # intervals always leaves such a tail. Measured with a zero-cost camera: 2487 frames in a 150ms window,
    # all of them the same tail of the clip, all of them handed to the slicer.
    cfg = PageSolverConfig(video_burst_duration_ms=300, video_burst_max_ms=1_250, video_burst_fps=10)
    # Every frame a new screen, so the burst never cycles and never settles: it runs to the ceiling.
    payloads = [b"screen-%03d" % i + b"\x00" * 64 for i in range(400)]
    n, elapsed = _burst(monkeypatch, payloads, frame_cost_ms=5.0,
                        video_burst_duration_ms=cfg.video_burst_duration_ms,
                        video_burst_max_ms=cfg.video_burst_max_ms,
                        video_burst_fps=cfg.video_burst_fps)
    paced = cfg.video_burst_max_ms / (1000.0 / cfg.video_burst_fps)
    assert n <= paced + 2, (
        f"a {cfg.video_burst_max_ms}ms burst at {cfg.video_burst_fps}fps filmed {n} frames where the pacing "
        f"allows {paced:.0f}: the tail of the clip was filmed flat out, which is both wasted work and a "
        f"slicing weighted towards the last few hundred milliseconds")
    assert elapsed <= cfg.video_burst_max_ms, (
        f"the burst ran {elapsed:.0f}ms past its {cfg.video_burst_max_ms}ms ceiling")


def test_the_js_port_counts_the_same_window_in_milliseconds():
    js = (Path(__file__).resolve().parents[2] / "js" / "src" / "solver.ts").read_text()
    # A wall-clock subtraction, whatever it is spelled: `lastNewAt` is a timestamp rather than an offset
    # since a continuous film measures its settle window from the CUT, not from when the camera started.
    assert "Date.now() - lastNewAt >= floorMs" in js, (
        "the JS burst still counts its settled window in frames: a camera "
        "slower than the interval stretches the window there while the python "
        "port holds it to videoBurstDurationMs")


def test_the_js_port_ends_at_the_ceiling_rather_than_spinning():
    js = (Path(__file__).resolve().parents[2] / "js" / "src" / "solver.ts").read_text()
    assert "if (nextAt - t0 >= ceilingMs) break;" in js, (
        "the JS recorder still only declines to SLEEP for a frame past the ceiling, so it spends the tail of "
        "every burst filming flat out while this port ends there")
