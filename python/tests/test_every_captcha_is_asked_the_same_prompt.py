"""The pointer's prompt is one fixed text with the board between its halves, so
everything before the board is a prefix every request shares (and vLLM caches),
and a marked video is drawn and numbered like a still, frame by frame."""
import os
import sys

import numpy as np
import pytest

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from captchakraken.pointer import elements as E
from captchakraken.pointer import layout as L


class Template:
    """Qwen's chat template, reduced to the order it writes a user turn in."""

    def apply_chat_template(self, msgs, tokenize=False, add_generation_prompt=False):
        out = "<|im_start|>user\n"
        for part in msgs[0]["content"]:
            if part["type"] == "text":
                out += part["text"]
            else:
                out += f"<|vision_start|><|{part['type']}_pad|><|vision_end|>"
        return out + "<|im_end|>\n"


@pytest.mark.parametrize("video", [False, True])
def test_the_instruction_comes_before_the_board_and_the_questions_after(video):
    text = L.chat(Template(), video)
    pad = L.VIDEO_PAD if video else L.IMAGE_PAD
    before, after = text.split(pad)
    assert L.INSTRUCTION in before and L.Q_END not in before
    assert after.count(L.Q_END) == len(L.QUESTIONS)


def test_no_board_changes_the_prompt_text():
    """Nothing about a board's elements is written into the prompt: the drawn
    outlines carry them, so two boards send one identical text."""
    assert L.chat(Template(), False) == L.chat(Template(), False)
    assert "<|box_end|>" not in L.chat(Template(), False)


def _el(cls, x0, y0, x1, y1):
    m = np.ones((y1 - y0, x1 - x0), bool)
    return {"class": cls, "box": [x0, y0, x1, y1], "score": 1.0, "mask": ((x0, y0), m)}


def test_a_video_element_keeps_its_number_across_the_clip():
    """A sprite drifting right is one element on every frame; one that appears
    late gets its own number; numbers follow reading order of first sighting."""
    frames = [
        [_el("item", 10 + 4 * f, 50, 40 + 4 * f, 80)] + ([_el("item", 100, 10, 130, 40)] if f >= 2 else [])
        for f in range(5)
    ]
    tracks = E.track(frames)
    assert len(tracks) == 2
    top, drifting = tracks              # reading order: the y-10 one first
    assert [e is not None for e in drifting["frames"]] == [True] * 5
    assert [e is not None for e in top["frames"]] == [False, False, True, True, True]
    assert E.on_frame(tracks, 0)[0] is None and E.on_frame(tracks, 0)[1] is not None


def test_an_answer_names_the_element_under_its_point():
    els = [_el("cell", 0, 0, 50, 50), None, _el("cell", 50, 0, 100, 50)]
    ans = E.ids_for({"action": "click", "points": [[750, 500], [250, 500]]}, (100, 50), els)
    assert ans["ids"] == [3, 1]
    drag = E.ids_for({"action": "drag", "drags": [{"from": [250, 500], "to": [990, 990]}]}, (100, 50), els)
    assert (drag["drags"][0]["from_id"], drag["drags"][0]["to_id"]) == (1, 3)
    assert "ids" not in E.ids_for({"action": "click", "points": [[1, 1]]}, (100, 50), [])
