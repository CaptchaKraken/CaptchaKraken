"""A generation-4 model is the pointer: the client sends the bare board to /pointer and nothing else.

No prompt (the server owns it), no numbered grid overlay (the server's element detector numbers every element,
grid cells included), and no find_grid: a board is a board. The answer comes back in generation 3's shape and
is performed by the same code.
"""

import base64
import json

import cv2
import numpy as np
import pytest
from PIL import Image

from captchakraken import prompts
from captchakraken import planner as P
from captchakraken import solver as S
from captchakraken.solver import CaptchaSolver, cut_recording

REGISTRY = {
    "latest": "Acme/General",
    "models": {
        "Acme/General": {"prompt_version": "3", "pixel_budget": {"min": 128 * 128, "max": 128 * 128}},
        "Acme/Pointer": {"prompt_version": "4", "pixel_budget": {"min": 128 * 128, "max": 720 * 720}},
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
    state = {"urls": [], "sent": [], "answer": {}}

    class _Resp:
        ok = True

        @staticmethod
        def json():
            return {"answer": state["answer"], "elements": [], "size": [640, 640]}

    def fake_post(self, url, headers=None, json=None, timeout=None):
        state["urls"].append(url)
        state["sent"].append(json)
        return _Resp()

    monkeypatch.setattr(P.requests.Session, "post", fake_post)
    monkeypatch.setattr(P, "ensure_server", lambda *a, **k: None)
    return state


def grid_board(path):
    """A 3x3 lattice find_grid would number."""
    im = np.full((400, 400, 3), 255, np.uint8)
    for r in range(3):
        for c in range(3):
            cv2.rectangle(im, (20 + 120 * c, 20 + 120 * r), (130 + 120 * c, 130 + 120 * r), (60, 120, 40), -1)
    cv2.imwrite(str(path), im)
    return str(path)


def test_generation_4_is_the_pointer_and_sends_video():
    p = prompts.builtin("4")
    assert p.pointer and p.sends_video and p.general is None


def test_a_still_goes_to_the_pointer_endpoint_as_it_was_captured(registry, wire, tmp_path):
    path = grid_board(tmp_path / "board.png")
    wire["answer"] = {"action": "click", "points": [[188, 188], [812, 500]], "ids": [1, 6]}
    CaptchaSolver(model="Acme/Pointer").solve(path)
    assert wire["urls"][-1].endswith("/pointer")
    body = wire["sent"][-1]
    assert set(body) == {"model", "image"}
    assert base64.b64decode(body["image"]) == open(path, "rb").read()


def test_a_grid_is_never_found_by_find_grid_under_the_pointer(registry, wire, tmp_path, monkeypatch):
    def refuse(*a, **k):
        raise AssertionError("find_grid ran under generation 4")
    monkeypatch.setattr(S, "find_grid", refuse)
    path = grid_board(tmp_path / "board.png")
    wire["answer"] = {"action": "click", "points": [[188, 188]], "ids": [1]}
    actions = CaptchaSolver(model="Acme/Pointer").solve(path)
    acts = actions if isinstance(actions, list) else [actions]
    assert acts[0].action == "click"


def test_the_pointer_answer_is_performed_like_generation_3s(registry, wire, tmp_path):
    path = grid_board(tmp_path / "board.png")
    answer = {"action": "slide", "handle": [100, 900], "from": [150, 300], "to": [700, 300], "handle_id": 3}
    wire["answer"] = answer
    pointer = CaptchaSolver(model="Acme/Pointer").planner.get_pixel_actions(path)
    general = P.ActionPlanner._normalize_general(answer)
    assert pointer == general and pointer[0]["kind"] == "slide"


def test_a_video_goes_as_its_cut_frames_and_its_moment_comes_back(registry, wire, tmp_path):
    frames = []
    for i in range(30):
        f = np.full((120, 160, 3), 255, np.uint8)
        cv2.rectangle(f, (5 + 4 * i, 40), (25 + 4 * i, 60), (0, 0, 200), -1)
        frames.append(f)
    wire["answer"] = {"t": 0.9, "action": "click", "points": [[500, 400]]}
    rec = cut_recording(frames, 10.0, str(tmp_path))
    actions = CaptchaSolver(model="Acme/Pointer").solve_animated(rec)
    body = wire["sent"][-1]
    assert set(body) == {"model", "frames", "fps"} and body["fps"] == 5.0
    first = np.asarray(Image.open(__import__("io").BytesIO(base64.b64decode(body["frames"][0]))))
    assert first.shape[0] % 64 == 0 and first.shape[1] % 64 == 0
    assert actions and getattr(actions[0], "t", 0.9) is not None


def test_a_reply_without_an_answer_is_an_error_not_an_empty_solve(registry, wire, tmp_path, monkeypatch):
    class _Bad:
        ok = True

        @staticmethod
        def json():
            return {"elements": []}
    monkeypatch.setattr(P.requests.Session, "post", lambda *a, **k: _Bad())
    with pytest.raises(RuntimeError):
        CaptchaSolver(model="Acme/Pointer").planner.get_pixel_actions(grid_board(tmp_path / "b.png"))
