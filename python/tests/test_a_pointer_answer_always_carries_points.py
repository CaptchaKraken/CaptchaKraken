"""The pointer's decision vector and the answer read from it (`pointer/layout.py`)."""
import os
import sys

import pytest

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from captchakraken.pointer import layout as L


def packed(action="click", count=0, drags=1, slots=None, text=(), moment=0):
    """A decision vector as the heads would pack it."""
    v = [1.0 if a == action else 0.0 for a in L.ACTIONS]
    v += [1.0 if k == count else 0.0 for k in range(L.N_COUNTS)]
    v += [1.0 if k == drags - 1 else 0.0 for k in range(L.N_DRAG_COUNTS)]
    slots = slots or {}
    for name, _ in L.SLOTS:
        tok, dx, dy, *el = slots.get(name, (0, 0.0, 0.0))
        v += [tok, dx, dy, 0.9, el[0] if el else 0, 0.8]
    ids = list(text) + [-1] * (L.MAX_TEXT - len(text))
    v += ids + [moment, 0.7]
    assert len(v) == L.PACKED
    return v


def shape(ans):
    """The generation-3 answer without its `checks`."""
    return {k: v for k, v in ans.items() if k != "checks"}


def test_every_question_has_its_own_marker():
    assert len(set(L.QUESTIONS)) == len(L.QUESTIONS)
    assert L.QUESTION_TEXT.count(L.Q_END) == len(L.QUESTIONS)


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


def test_a_click_is_its_points():
    """Element numbers are added after, from what is under each point
    (`elements.ids_for`, tests/test_every_captcha_is_asked_the_same_prompt.py)."""
    v = packed("click", count=2, slots={"click1": (21, 0.0, 0.0), "click2": (22, 0.0, 0.0)})
    assert shape(L.answer(L.unpack(v), (20, 24))) == {"action": "click", "points": [[75, 62], [125, 62]]}


def test_nothing_matching_is_an_empty_click():
    assert shape(L.answer(L.unpack(packed("click", count=0)), (20, 24))) == {"action": "click", "points": []}


def test_a_drag_gives_both_ends():
    v = packed("drag", drags=1, slots={"drag1 from": (0, 0.0, 0.0), "drag1 to": (21, 0.0, 0.0)})
    ans = shape(L.answer(L.unpack(v), (20, 24)))
    assert ans == {"action": "drag", "drags": [{"from": [25, 21], "to": [75, 62]}]}


def test_a_slide_gives_handle_piece_and_slot():
    v = packed("slide", slots={"slide handle": (460, 0, 0), "slide from": (61, 0, 0), "slide to": (75, 0, 0)})
    ans = shape(L.answer(L.unpack(v), (20, 24)))
    assert set(ans) == {"action", "handle", "from", "to"}


def test_a_hold_is_its_press_and_the_fills_line():
    v = packed("hold", count=3, slots={"hold press": (21, 0, 0), "hold from": (22, 0, 0), "hold to": (25, 0, 0)})
    assert shape(L.answer(L.unpack(v), (20, 24))) == {"action": "hold", "press": [75, 62], "from": [125, 62],
                                                       "to": [275, 62]}


def test_a_typed_answer_is_its_text():
    assert shape(L.answer(L.unpack(packed("type")), (20, 24), text="QN5K")) == {"action": "type", "text": "QN5K"}


def test_a_video_answer_names_the_moment_by_its_label():
    v = packed("click", count=1, moment=2, slots={"click1": (21, 0, 0)})
    ans = L.answer(L.unpack(v), (22, 22), timestamps=[0.1, 0.5, 0.9])
    assert ans["t"] == 0.9 and list(ans)[0] == "t"


def test_a_vector_of_the_wrong_length_is_refused():
    with pytest.raises(ValueError):
        L.unpack([0.0] * (L.PACKED - 1))


def test_every_decision_says_how_sure_it_was():
    v = packed("click", count=2, slots={"click1": (21, 0.0, 0.0, 7), "click2": (22, 0.0, 0.0)})
    checks = L.answer(L.unpack(v), (20, 24))["checks"]
    assert checks["action_p"] == 1.0 and checks["count_p"] == 1.0
    assert checks["slots"] == [{"slot": "click1", "p_point": 0.9, "element": 7, "p_element": 0.8},
                               {"slot": "click2", "p_point": 0.9, "element": None, "p_element": 0.8}]


def test_a_drags_checks_follow_its_ends_in_order():
    v = packed("drag", drags=2)
    names = [s["slot"] for s in L.answer(L.unpack(v), (20, 24))["checks"]["slots"]]
    assert names == ["drag1 from", "drag1 to", "drag2 from", "drag2 to"]


def test_a_slot_finds_its_point_in_the_answer():
    ans = {"action": "drag", "drags": [{"from": [1, 2], "to": [3, 4]}], "handle": [5, 6], "points": [[7, 8]]}
    assert L.slot_point(ans, "drag1 to") == [3, 4] and L.slot_point(ans, "drag2 from") is None
    assert L.slot_point(ans, "slide handle") == [5, 6] and L.slot_point(ans, "click1") == [7, 8]
    assert L.slot_point(ans, "click2") is None
