"""A model on a video generation is shown the clip and answers WHEN with `t`; an older one still gets keyframes.

The generation decides it, per model: sending a generation-2 model a video, or a generation-3 model numbered
stills, does not error — the model answers a question it was never trained on, and every animated solve is
quietly worse.
"""

import base64
import json
from pathlib import Path

import cv2
import numpy as np
import pytest

from captchakraken import clipvideo, prompts
from captchakraken import planner as P
from captchakraken.solver import CaptchaSolver, cut_recording

BAND = 128 * 128
REGISTRY = {
    "latest": "Acme/Stills",
    "models": {
        "Acme/Stills": {"prompt_version": "2", "pixel_budget": {"min": BAND, "max": BAND}},
        "Acme/Video": {"prompt_version": "3", "pixel_budget": {"min": BAND, "max": BAND}},
        "Acme/Unbanded": {"prompt_version": "3"},
    },
}


@pytest.fixture
def registry(monkeypatch):
    for name in (prompts.MIN_PIXELS_ENV, prompts.MAX_PIXELS_ENV, "CAPTCHA_PROMPTS_FILE"):
        monkeypatch.delenv(name, raising=False)
    prompts.clear_cache()
    monkeypatch.setattr(prompts, "_load_registry", lambda: json.loads(json.dumps(REGISTRY)))
    yield
    prompts.clear_cache()


@pytest.fixture
def wire(monkeypatch):
    """Every request body, and the answer the fake server gives back."""
    state = {"sent": [], "answer": {}}

    class _Resp:
        ok = True

        @staticmethod
        def json():
            return {"choices": [{"message": {"content": json.dumps(state["answer"])}}]}

    def fake_post(self, url, headers=None, json=None, timeout=None):
        state["sent"].append(json)
        return _Resp()

    monkeypatch.setattr(P.requests.Session, "post", fake_post)
    monkeypatch.setattr(P, "ensure_server", lambda *a, **k: None)
    return state


def _clip_frames(n=30):
    """A square crossing the board once, so every frame is a different moment."""
    frames = []
    for i in range(n):
        f = np.full((120, 160, 3), 255, np.uint8)
        x = 5 + i * 4
        cv2.rectangle(f, (x, 40), (x + 20, 60), (0, 0, 200), -1)
        frames.append(f)
    return frames


def _parts(body):
    return body["messages"][-1]["content"]


def test_a_video_generation_sends_one_video_part_with_the_general_prompt(registry, wire, tmp_path):
    wire["answer"] = {"t": 1.3, "action": "click", "points": [[500, 400]]}
    recording = cut_recording(_clip_frames(), 10.0, str(tmp_path))
    CaptchaSolver(model="Acme/Video").solve_animated(recording)

    parts = _parts(wire["sent"][-1])
    assert [p["type"] for p in parts] == ["video_url", "text"]
    url = parts[0]["video_url"]["url"]
    assert url.startswith("data:video/jpeg;base64,")
    clip = clipvideo.clip_video(recording.frames, recording.fps, max_pixels=BAND)
    assert len(url.split(",")) - 1 == len(clip.frames), "one JPEG per frame the model is to watch"
    first = cv2.imdecode(np.frombuffer(base64.b64decode(url.split(",")[1]), np.uint8), cv2.IMREAD_COLOR)
    assert first.shape[0] * first.shape[1] <= BAND, "frames are cut to the model's pixel ceiling"
    assert parts[1]["text"] == prompts.BUILTIN_PROMPTS["3"]["general"]


def test_the_driver_waits_for_the_exact_frame_the_answer_names(registry, wire, tmp_path):
    # 1.7 s is recorded frame 16, which no keyframe is cut from (they sit at 12 and 17): the reference has to be
    # the frame the model watched, not the nearest keyframe.
    wire["answer"] = {"t": 1.7, "action": "click", "points": [[500, 400]]}
    recording = cut_recording(_clip_frames(), 10.0, str(tmp_path))
    [action] = CaptchaSolver(model="Acme/Video").solve_animated(recording)

    clip = clipvideo.clip_video(recording.frames, recording.fps, max_pixels=BAND)
    source = clipvideo.time_to_index(clip, 1.7)
    assert source not in [kf.source_index for kf in recording.keyframes.keyframes]
    assert action.t == 1.7 and action.frame is None
    assert action.await_keyframe in recording.keyframe_paths, \
        "the reference must sit among its sibling screens, or the wait gate's recurrence check has none"
    waited = cv2.imread(action.await_keyframe)
    assert np.array_equal(waited, recording.frames[source])


def test_a_time_outside_the_clip_is_dropped_not_clamped(registry, wire, tmp_path):
    wire["answer"] = {"t": 60.0, "action": "click", "points": [[500, 400]]}
    recording = cut_recording(_clip_frames(), 10.0, str(tmp_path))
    [action] = CaptchaSolver(model="Acme/Video").solve_animated(recording)
    assert action.t is None and action.await_keyframe is None


def test_a_keyframe_generation_still_gets_numbered_stills(registry, wire, tmp_path):
    wire["answer"] = {"frame": 2, "action": "click", "points": [[500, 400]]}
    recording = cut_recording(_clip_frames(), 10.0, str(tmp_path))
    [action] = CaptchaSolver(model="Acme/Stills").solve_animated(recording)

    parts = _parts(wire["sent"][-1])
    assert [p["type"] for p in parts] == ["image_url"] * len(recording.keyframe_paths) + ["text"]
    assert "still keyframes" in parts[-1]["text"]
    assert action.frame == 2 and action.t is None
    assert action.await_keyframe == recording.keyframe_paths[1]


def test_each_entry_point_refuses_the_other_generation(registry):
    with pytest.raises(ValueError, match="get_video_actions"):
        P.ActionPlanner(model="Acme/Video", api_key="k").get_keyframe_actions(["a.png"])
    with pytest.raises(ValueError, match="get_keyframe_actions"):
        P.ActionPlanner(model="Acme/Stills", api_key="k").get_video_actions(
            clipvideo.clip_video(_clip_frames(), 10.0, max_pixels=BAND))


def test_a_video_model_with_no_pixel_ceiling_fails_loudly(registry, wire, tmp_path):
    recording = cut_recording(_clip_frames(), 10.0, str(tmp_path))
    with pytest.raises(ValueError, match="pixel ceiling"):
        CaptchaSolver(model="Acme/Unbanded").solve_animated(recording)
    assert wire["sent"] == [], "nothing is sent at a size the model was not trained on"


def test_a_pinned_prompts_file_takes_its_input_from_the_generation(registry, monkeypatch, tmp_path):
    pin = tmp_path / "prompts.json"
    pin.write_text(json.dumps({"prompt_version": "3", "templates": {"general": "overridden"}}))
    monkeypatch.setenv("CAPTCHA_PROMPTS_FILE", str(pin))
    prompts.clear_cache()
    ps = prompts.resolve("candidate-20261023")
    assert ps.version == "3" and ps.sends_video and ps.video_prompt() == "overridden"


def test_the_managed_server_reads_the_clip_as_sent():
    """The server the client starts must take one video and keep every frame at the rate it was cut at."""
    from captchakraken import server_manager

    cmd = server_manager.build_serve_command()
    flags = dict(zip(cmd, cmd[1:]))
    assert json.loads(flags["--media-io-kwargs"]) == clipvideo.media_io_kwargs()
    assert json.loads(flags["--limit-mm-per-prompt"])["video"] >= 1
    docs = (Path(__file__).resolve().parents[2] / "docs" / "self-hosting.md").read_text()
    assert f"--media-io-kwargs '{json.dumps(clipvideo.media_io_kwargs())}'" in docs, \
        "the documented equivalent command must carry the same flag"


def test_the_page_driver_cuts_its_burst_into_a_recording(tmp_path):
    # The driver's own slicer, not the solver's: a missing import here only surfaced on a live animated board.
    from captchakraken.page_solver import PageSolver, PageSolverConfig

    solver = PageSolver(config=PageSolverConfig(detection_timeout_ms=0))
    recording, keyframe_dir = solver._slice(_clip_frames(), 1000.0)
    try:
        assert len(recording.frames) == len(_clip_frames())
        assert recording.keyframe_paths and all(Path(p).exists() for p in recording.keyframe_paths)
    finally:
        import shutil

        shutil.rmtree(keyframe_dir, ignore_errors=True)
