# The second look is a QUESTION, and the clip it records is the answer. Declaring the board animated before
# filming it sent every board that merely failed once to the video expert, which can only answer a still with
# a frame number no widget will take — and then the answer repeated until the no-progress fence tripped.
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

from captchakraken.kinds import FrameRole, SettleVerdict, Vendor
from captchakraken.page_solver import PageSolver, PageSolverConfig, Widget
from captchakraken.solver import AnimatedRecording


def _armed(verdict: SettleVerdict) -> PageSolver:
    solver = PageSolver(config=PageSolverConfig())
    solver._reset_animated_state()
    solver._wait_for_element_settled = lambda _element: verdict
    solver._arm_animated_probe()
    return solver


def test_the_probe_records_without_declaring_the_board_animated():
    solver = _armed(SettleVerdict.SETTLED)
    assert solver._settle_or_animated(object()) is True, "an armed probe still buys its recording"
    assert solver._known_animated is False, "the probe called the board animated before filming it"


def test_a_measured_animation_needs_no_probe():
    solver = _armed(SettleVerdict.ANIMATED)
    assert solver._settle_or_animated(object()) is True
    assert solver._known_animated is True


def test_the_probe_is_spent_once():
    solver = _armed(SettleVerdict.SETTLED)
    solver._settle_or_animated(object())
    solver._arm_animated_probe()
    assert solver._settle_or_animated(object()) is False, "a second recording per solve"


def test_the_recording_reports_whether_the_board_moved(monkeypatch):
    solver = PageSolver(config=PageSolverConfig())
    solver._reset_animated_state()
    monkeypatch.setattr(solver, "_burst",
                        lambda _element, known=frozenset(), max_ms=None:
                        (["f0", "f1"], ["a", "b"], False, 4200.0, False))
    monkeypatch.setattr(solver, "_slice", lambda _frames, _ms: (["k0", "k1"], "/tmp/ck_kf"))
    assert solver._record_keyframes(object()) == (["k0", "k1"], "/tmp/ck_kf", False)


def _round(tmp_path, monkeypatch, moved: bool, verdict: SettleVerdict = SettleVerdict.SETTLED):
    """One `_solve_single` on a board whose probe is armed; returns which expert was asked."""
    asked: list = []
    keyframes = [str(tmp_path / f"k{i}.png") for i in range(2)]
    for i, path in enumerate(keyframes):
        Path(path).write_bytes(b"screen-%d" % i)

    solver = _armed(verdict)
    monkeypatch.setattr(solver, "_answer_box", lambda *_a: None)
    monkeypatch.setattr(solver, "is_captcha_solved", lambda _page: False)
    monkeypatch.setattr(solver, "_wait_for_board_painted", lambda _element: None)
    monkeypatch.setattr(solver, "_screenshot", lambda _el, path, **_kw: Path(path).write_bytes(b"board"))
    recording = AnimatedRecording(frames=[], fps=10.0, keyframes=None, keyframe_paths=keyframes)
    monkeypatch.setattr(solver, "_record_keyframes", lambda _el: (recording, str(tmp_path), moved))
    monkeypatch.setattr(solver, "_should_speculate", lambda *_a: False)
    monkeypatch.setattr(solver, "_get_verify_button", lambda _scope: None)
    monkeypatch.setattr(solver, "_get_keyframe_solution", lambda _recording: (asked.append("video"), ([], []))[1])
    monkeypatch.setattr(solver, "_get_solution", lambda *_a, **_kw: (asked.append("still"), ([], []))[1])

    element = type("El", (), {"content_frame": lambda self: None, "bounding_box": lambda self: None})()
    widget = Widget(element=element, at=object(), vendor=Vendor.GEETEST, role=FrameRole.CHALLENGE)
    solver._solve_single(object(), widget, None)
    return asked


def test_a_clip_that_never_moved_goes_back_to_the_still_expert(tmp_path, monkeypatch):
    assert _round(tmp_path, monkeypatch, moved=False) == ["still"]


def test_a_clip_that_moved_is_the_video_expert_s(tmp_path, monkeypatch):
    assert _round(tmp_path, monkeypatch, moved=True) == ["video"]


def test_a_measured_animation_is_not_demoted_by_its_own_clip(tmp_path, monkeypatch):
    # The clip can only PROMOTE: an animation the classifier caught stays one even when the film that
    # follows ends on a settled screen, which is what a board that plays once and stops films like.
    assert _round(tmp_path, monkeypatch, moved=False, verdict=SettleVerdict.ANIMATED) == ["video"]
