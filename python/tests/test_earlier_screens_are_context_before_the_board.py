"""A multi-screen puzzle (FunCaptcha's option pager) is asked with every earlier
screen of it before the current one, so the model can remember a token the
person hid two screens ago. Each request extends the one before it, so vLLM's
prefix cache keeps every earlier screen's work; points land only on the last
screen, which is the board being answered."""
import base64
import io
import os
import sys

import pytest
import torch
from PIL import Image

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from captchakraken.pointer import heads as Hd
from captchakraken.pointer import layout as L
from captchakraken.pointer import server as S

from test_every_captcha_is_asked_the_same_prompt import Template


def _upto_board(text):
    """The prompt up to and including its last vision block."""
    return text[:text.rindex(L.IMAGE_PAD) + len(L.IMAGE_PAD)]


def test_earlier_screens_sit_between_the_instruction_and_the_board():
    text = L.chat(Template(), False, history=2)
    assert text.count(L.IMAGE_PAD) == 3
    before, after = text.split(L.IMAGE_PAD, 1)
    assert L.INSTRUCTION in before
    assert L.Q_END not in _upto_board(text)
    assert text[text.rindex(L.IMAGE_PAD):].count(L.Q_END) == len(L.QUESTIONS)


def test_each_request_is_a_prefix_of_the_next_up_to_its_board():
    """Step t's prompt up to its board is how step t+1's begins: the cache keeps it."""
    for k in range(L.MAX_HISTORY):
        assert L.chat(Template(), False, history=k + 1).startswith(_upto_board(L.chat(Template(), False, history=k)))


def test_a_video_has_no_earlier_screens():
    with pytest.raises(ValueError):
        L.chat(Template(), True, history=1)


IDS = {L.Q_END: 1, L.IMAGE_PAD: 2, L.VIDEO_PAD: 3, L.VISION_END: 4}
VS = 5  # vision_start


def _prompt(blocks):
    ids = [9, 9]
    for n in blocks:
        ids += [VS] + [IDS[L.IMAGE_PAD]] * n + [IDS[L.VISION_END]]
    return torch.tensor(ids + [7] + [IDS[L.Q_END]] * len(L.QUESTIONS))


def test_points_land_only_on_the_last_screen():
    pos = Hd.Positions(_prompt([4, 4, 6]), IDS)
    assert pos.n_moments == 1 and pos.per_moment == 6
    assert pos.history == 2
    last_start = 2 + (1 + 4 + 1) * 2 + 1
    assert pos.vis.tolist() == list(range(last_start, last_start + 6))


def test_a_lone_screen_reads_as_before():
    pos = Hd.Positions(_prompt([6]), IDS)
    assert (pos.n_moments, pos.per_moment, pos.history) == (1, 6, 0)


def _b64(color):
    buf = io.BytesIO()
    Image.new("RGB", (64, 64), color).save(buf, "PNG")
    return base64.b64encode(buf.getvalue()).decode()


def test_the_server_takes_earlier_screens_oldest_first_and_bounds_them():
    got = S.parse({"image": _b64("red"), "history": [_b64("blue"), _b64("green")]})
    assert [im.getpixel((0, 0)) for im in got["history"]] == [(0, 0, 255), (0, 128, 0)]
    assert S.parse({"image": _b64("red")})["history"] == []
    with pytest.raises(ValueError):
        S.parse({"image": _b64("red"), "history": [_b64("blue")] * (L.MAX_HISTORY + 1)})
    with pytest.raises(ValueError):
        S.parse({"frames": [_b64("red")] * 2, "history": [_b64("blue")]})


def test_the_service_sends_earlier_screens_as_images_before_the_board():
    from captchakraken.pointer.service import PointerService
    svc = object.__new__(PointerService)
    svc.processor, svc.detector = Template(), None
    now, a, b = (Image.new("RGB", (300, 200), c) for c in ("red", "blue", "green"))
    req = svc.prepare(image=now, history=[a, b])["request"]
    ims = req["multi_modal_data"]["image"]
    assert [im.getpixel((0, 0)) for im in ims] == [(0, 0, 255), (0, 128, 0), (255, 0, 0)]
    assert req["prompt"].count(L.IMAGE_PAD) == 3
    lone = svc.prepare(image=now)["request"]
    assert lone["multi_modal_data"]["image"].getpixel((0, 0)) == (255, 0, 0)
    assert lone["prompt"].count(L.IMAGE_PAD) == 1
