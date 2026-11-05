"""Measured: predictions 80-105px out at native size against 1-4px once upscaled. A flat band (min == max) normalises every image by design; (w-1)*(h-1) because ceil rounds both sides up."""

from __future__ import annotations

import base64
import io
import re

import pytest
from PIL import Image

from captchakraken import planner as P
from captchakraken import prompts


class _Resp:
    ok = True

    @staticmethod
    def json():
        return {"choices": [{"message": {"content": "{}"}}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1}}


@pytest.fixture
def captured(monkeypatch):
    seen = {}

    def fake_post(self, url, headers=None, json=None, timeout=None):
        seen["payload"] = json
        return _Resp()

    monkeypatch.setattr(P.requests.Session, "post", fake_post)
    monkeypatch.setattr(P, "ensure_server", lambda *a, **k: None)
    return seen


def _sent_images(payload):
    out = []
    for part in payload["messages"][-1]["content"]:
        if part.get("type") != "image_url":
            continue
        b64 = re.sub(r"^data:[^;]+;base64,", "", part["image_url"]["url"])
        out.append(Image.open(io.BytesIO(base64.b64decode(b64))))
    return out


def test_a_small_image_is_upscaled_to_the_training_floor(tmp_path, captured):
    small = tmp_path / "slider.png"
    Image.new("RGB", (277, 285), "white").save(small)
    assert 277 * 285 < prompts.DEFAULT_PIXEL_BUDGET.minimum, "fixture must start below the floor"

    P.ActionPlanner(api_key="k", base_url="http://x/v1",
                    model="CaptchaKraken/CaptchaKraken-Lora-v1.2")._chat_with_images(
        "prompt", [str(small)])

    (sent,) = _sent_images(captured["payload"])
    w, h = sent.size
    assert w * h >= prompts.DEFAULT_PIXEL_BUDGET.minimum, (
        f"sent {w}x{h} = {w * h} px, below the {prompts.DEFAULT_PIXEL_BUDGET.minimum} px training floor — "
        "this is the geometry mismatch that put slider coordinates 80-105 px out")
    assert abs((w / h) - (277 / 285)) < 0.01, "aspect ratio must be preserved"


def test_an_image_inside_an_open_band_is_left_alone(tmp_path):
    big = tmp_path / "grid.png"
    Image.new("RGB", (400, 580), "white").save(big)
    raw = big.read_bytes()
    open_band = prompts.PixelBudget(minimum=prompts.DEFAULT_PIXEL_BUDGET.minimum, maximum=None, source="test")
    assert 400 * 580 > open_band.minimum

    _, b64 = P._encode_image(str(big), open_band)

    assert base64.b64decode(b64) == raw, (
        "the file was re-encoded despite already clearing the floor")


def test_a_flat_band_normalises_every_image(tmp_path):
    img = tmp_path / "grid.png"
    Image.new("RGB", (400, 580), "white").save(img)
    flat = prompts.PixelBudget(minimum=518_400, maximum=518_400, source="test")

    _, b64 = P._encode_image(str(img), flat)
    sent = Image.open(io.BytesIO(base64.b64decode(b64)))

    w, h = sent.size
    assert w * h >= flat.minimum, f"sent {w}x{h} = {w * h}, under the flat band"
    assert abs((w / h) - (400 / 580)) < 0.01, "aspect ratio must be preserved"


def test_the_planner_uses_the_pinned_models_band_not_the_module_default(tmp_path, captured):
    img = tmp_path / "grid.png"
    Image.new("RGB", (400, 580), "white").save(img)
    planner = P.ActionPlanner(api_key="k", base_url="http://x/v1")

    planner._chat_with_images("prompt", [str(img)])

    (sent,) = _sent_images(captured["payload"])
    w, h = sent.size
    assert w * h >= planner.pixel_budget.minimum, (
        f"sent {w}x{h} = {w * h} px, under the pinned model's floor of "
        f"{planner.pixel_budget.minimum} ({planner.pixel_budget.source})")
    if planner.pixel_budget.maximum:
        assert (w - 1) * (h - 1) <= planner.pixel_budget.maximum, (
            f"sent {w}x{h} = {w * h} px, more than a rounding step above the "
            f"pinned ceiling of {planner.pixel_budget.maximum}")
