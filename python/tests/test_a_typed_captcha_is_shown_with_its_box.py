"""A typed captcha is photographed with its text box (`page_solver._WithAnswerBox`).

BotDetect's widget is a 280x50 strip holding only the image, and every board the pointer trained on shows the
text box under it. Live, on the bare strip the pointer answered a click (p(type) 0.46) or typed R99VK for R9VK;
the same frame with its box read R9VK at p >= 0.89 per character.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from captchakraken.page_solver import _WithAnswerBox


class _Handle:
    tag = "image"

    def __init__(self, x, y, w, h):
        self.box = {"x": x, "y": y, "width": w, "height": h}

    def bounding_box(self):
        return dict(self.box)

    def content_frame(self):
        return None


def test_the_shot_covers_the_image_and_the_text_box_under_it():
    el = _WithAnswerBox(_Handle(10, 10, 280, 50), _Handle(10, 64, 200, 22))
    assert el.bounding_box() == {"x": 10, "y": 10, "width": 280, "height": 76}
    assert el.tag == "image" and el.content_frame() is None


def test_a_text_box_far_from_the_image_leaves_the_shot_alone():
    el = _WithAnswerBox(_Handle(10, 10, 280, 50), _Handle(10, 600, 200, 22))
    assert el.bounding_box() == {"x": 10, "y": 10, "width": 280, "height": 50}
