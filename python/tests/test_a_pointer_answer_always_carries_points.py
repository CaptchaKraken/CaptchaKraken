"""The pointer's decision vector and the answer read from it (`pointer/layout.py`)."""
import os
import sys

import pytest

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from captchakraken.pointer import layout as L


def packed(action="click", count=0, drags=1, slots=None, text=(), moment=0, n_elements=0):
    """A decision vector as the heads would pack it."""
    v = [1.0 if a == action else 0.0 for a in L.ACTIONS]
    v += [1.0 if k == count else 0.0 for k in range(L.N_COUNTS)]
    v += [1.0 if k == drags - 1 else 0.0 for k in range(L.N_DRAG_COUNTS)]
    slots = slots or {}
    for name, _ in L.SLOTS:
        tok, dx, dy, el = slots.get(name, (0, 0.0, 0.0, -1))
        v += [tok, dx, dy, 0.9, el, 0.8]
    ids = list(text) + [-1] * (L.MAX_TEXT - len(text))
    v += ids + [moment, 0.7]
    assert len(v) == L.PACKED
    return v


def test_every_question_has_its_own_marker():
    assert len(set(L.QUESTIONS)) == len(L.QUESTIONS)
    text = L.prompt_text([], (640, 640))
    assert text.count(L.Q_END) == len(L.QUESTIONS)


def test_a_plain_board_lists_no_elements_and_a_marked_one_lists_each_once():
    els = [{"class": "cell", "box": [0, 0, 64, 64]}, {"class": "button", "box": [100, 600, 200, 630]}]
    assert "Elements:" not in L.prompt_text([], (640, 640))
    text = L.prompt_text(els, (640, 640))
    assert text.count(L.EL_END) == 2
    assert "<|object_ref_start|>2 button<|object_ref_end|><|box_start|>(156,938),(312,984)" in text


def test_a_board_is_shown_on_the_64px_lattice_within_the_pixel_cap():
    for w, h in [(300, 150), (520, 570), (1280, 720), (2000, 2000), (64, 64)]:
        W, H = L.board_size(w, h)
        assert W % 64 == 0 and H % 64 == 0 and W * H <= L.MAX_PIXELS


def test_a_token_and_its_offset_become_a_point():
    # Token 21 on a 20x24 grid is row 1, column 1: (1.5/20, 1.5/24) of the board,
    # (75, 62.5), and 62.5 rounds to even.
    assert L.to_point({"token": 21, "dx": 0.0, "dy": 0.0}, (20, 24)) == [75, 62]
    grid = (20, 24)
    # token 0 is the top-left cell; its centre is half a token in.
    assert L.to_point({"token": 0, "dx": 0.0, "dy": 0.0}, grid) == [25, 21]
    # the last token, nudged half a token right and down, is the corner.
    assert L.to_point({"token": 20 * 24 - 1, "dx": 0.5, "dy": 0.5}, grid) == [1000, 1000]


def test_a_click_names_the_element_each_point_lands_on():
    v = packed("click", count=2, slots={"click1": (21, 0.0, 0.0, 4), "click2": (22, 0.0, 0.0, -1)})
    ans = L.answer(L.unpack(v), (20, 24))
    assert ans == {"action": "click", "points": [[75, 62], [125, 62]], "ids": [5, None]}


def test_a_click_on_nothing_numbered_has_points_and_no_ids():
    v = packed("click", count=1, slots={"click1": (21, 0.0, 0.0, -1)})
    assert L.answer(L.unpack(v), (20, 24)) == {"action": "click", "points": [[75, 62]]}


def test_nothing_matching_is_an_empty_click():
    assert L.answer(L.unpack(packed("click", count=0)), (20, 24)) == {"action": "click", "points": []}


def test_a_drag_gives_both_ends_and_their_elements():
    v = packed("drag", drags=1, slots={"drag1 from": (0, 0.0, 0.0, 0), "drag1 to": (21, 0.0, 0.0, -1)})
    ans = L.answer(L.unpack(v), (20, 24))
    assert ans == {"action": "drag", "drags": [{"from": [25, 21], "to": [75, 62], "from_id": 1}]}


def test_a_slide_gives_handle_piece_and_slot():
    v = packed("slide", slots={"slide handle": (460, 0, 0, 2), "slide from": (61, 0, 0, 0), "slide to": (75, 0, 0, 1)})
    ans = L.answer(L.unpack(v), (20, 24))
    assert set(ans) == {"action", "handle", "from", "to", "handle_id"}
    assert ans["handle_id"] == 3


def test_a_hold_presses_exactly_one_point():
    v = packed("hold", count=3, slots={"click1": (21, 0, 0, -1)})
    assert L.answer(L.unpack(v), (20, 24))["points"] == [[75, 62]]


def test_a_typed_answer_is_its_text():
    assert L.answer(L.unpack(packed("type")), (20, 24), text="QN5K") == {"action": "type", "text": "QN5K"}


def test_a_video_answer_names_the_moment_by_its_label():
    v = packed("click", count=1, moment=2, slots={"click1": (21, 0, 0, -1)})
    ans = L.answer(L.unpack(v), (22, 22), timestamps=[0.1, 0.5, 0.9])
    assert ans["t"] == 0.9 and list(ans)[0] == "t"


def test_a_vector_of_the_wrong_length_is_refused():
    with pytest.raises(ValueError):
        L.unpack([0.0] * (L.PACKED - 1))
