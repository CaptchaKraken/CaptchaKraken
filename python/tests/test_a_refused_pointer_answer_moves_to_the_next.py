"""A retry asks the pointer for its likeliest answer not yet refused, not the same one again.

The heads are an argmax, so a sampled retry cannot move them: live, the text captcha was typed XK4XWP three
times and the GeeTest match swap repeated until the no-progress fence gave up. Each slot's runner-up tokens
and each typed character's runner-up travel in the decision vector; the client names the answers the board
already refused (`avoid`), and the server walks `layout.variants`, cheapest change first, past them.
"""
import os
import sys

import numpy as np
import pytest

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from captchakraken import planner as P
from captchakraken.pointer import layout as L
from captchakraken.pointer import server as Srv
from captchakraken.pointer import service as Svc

GRID = (20, 20)
SIZE = (640, 640)
STOP = 0


def decision(action="click", count=0, slots=None, text=(), text_p=(), text_alt=(), text_alt_p=()):
    """An unpacked decision: `slots` {name: (token, p, [(alt token, alt p), ...])}."""
    d = {"action_p": [0.9 if a == action else 0.02 for a in L.ACTIONS],
         "count_p": [0.8 if k == count else 0.01 for k in range(L.N_COUNTS)],
         "drag_count_p": [1.0] + [0.0] * (L.N_DRAG_COUNTS - 1), "slots": {}, "moment": 0, "moment_p": 1.0}
    for name, _ in L.SLOTS:
        tok, p, alts = (slots or {}).get(name, (0, 0.9, []))
        alts = list(alts) + [(0, 0.0)] * (L.ALTS - len(alts))
        d["slots"][name] = {"token": tok, "dx": 0.0, "dy": 0.0, "p_point": p, "element": 0, "p_element": 0.0,
                            "alts": [{"token": t, "dx": 0.0, "dy": 0.0, "p_point": q} for t, q in alts]}
    pad = L.MAX_TEXT - len(text)
    d["text_ids"] = list(text) + [STOP] * pad
    d["text_p"] = list(text_p) + [0.99] * pad
    d["text_alt_ids"] = list(text_alt) + [STOP] * pad
    d["text_alt_p"] = list(text_alt_p) + [0.0] * pad
    return d


def read(d, refused=0, els=()):
    """The answer after `refused` earlier ones were each performed and refused."""
    avoid = []
    for _ in range(refused + 1):
        ans = Svc.read_answer(d, SIZE, list(els), lambda ids: "".join(map(chr, ids)), STOP, None, avoid)
        avoid.append(ans)
    return ans


def element(token):
    """A detected element covering exactly one vision token."""
    r, c = divmod(token, GRID[0])
    box = [c * 32.0, r * 32.0, c * 32.0 + 32, r * 32.0 + 32]
    return {"class": "tile", "box": box, "score": 0.9, "mask": ((int(box[0]), int(box[1])), np.ones((32, 32), bool))}


def test_the_least_sure_typed_character_is_the_first_one_changed():
    d = decision("type", text=[ord(c) for c in "XK4XWP"], text_p=[.9, .9, .9, .5, .9, .9],
                 text_alt=[ord(c) for c in "YH4KVR"], text_alt_p=[.05, .05, .05, .4, .05, .05])
    assert [read(d, k)["text"] for k in range(3)] == ["XK4XWP", "XK4KWP", "YK4XWP"]


def test_a_retry_moves_the_least_sure_point():
    d = decision(count=2, slots={"click1": (21, 0.9, [(22, 0.05)]), "click2": (100, 0.5, [(140, 0.4)])})
    first, second = read(d, 0), read(d, 1)
    assert first["points"][0] == second["points"][0]
    assert first["points"][1] != second["points"][1]
    assert second["checks"]["retry"] == "click2 place 2"


def test_a_runner_up_on_the_same_element_is_not_a_different_answer():
    pair = element(100)                       # one element over tokens 100 and 101
    pair["box"][2] += 32
    pair["mask"] = ((0, 160), np.ones((32, 64), bool))
    d = decision(count=1, slots={"click1": (100, 0.6, [(101, 0.3), (300, 0.05)])})
    retry = read(d, 1, [pair])
    assert retry["checks"]["retry"] != "click1 place 2"
    assert retry != read(d, 0, [pair])


def test_two_clicks_on_one_element_press_it_once():
    d = decision(count=2, slots={"click1": (21, 0.9, []), "click2": (21, 0.9, [])})
    d["slots"]["click2"]["dx"] = 0.3
    ans = read(d, 0, [element(21)])
    assert ans["ids"] == [1] and len(ans["points"]) == 1


def wide(cls):
    """One detected element across vision tokens 21 to 25."""
    return {**element(21), "class": cls, "box": [32.0, 32.0, 192.0, 64.0],
            "mask": ((32, 32), np.ones((32, 160), bool))}


def test_two_clicks_apart_in_one_cell_press_it_once():
    d = decision(count=2, slots={"click1": (21, 0.9, []), "click2": (25, 0.9, [])})
    ans = read(d, 0, [wide("cell")])
    assert ans["ids"] == [1] and len(ans["points"]) == 1


def test_two_clicks_apart_on_one_item_are_both_pressed():
    """A line is one detected item, and its two ends are two answers."""
    d = decision(count=2, slots={"click1": (21, 0.9, []), "click2": (25, 0.9, [])})
    ans = read(d, 0, [wide("item")])
    assert ans["ids"] == [1, 1] and len(ans["points"]) == 2


def test_two_clicks_in_one_place_are_one_click_with_no_elements_to_read():
    d = decision(count=2, slots={"click1": (21, 0.9, []), "click2": (21, 0.9, [])})
    assert len(read(d, 0)["points"]) == 1


def test_a_retry_never_returns_to_an_answer_already_refused():
    """Live, GeeTest match's second look moved one point, and the 'next' answer moved it back onto the first
    look's refused swap. Every refused answer is avoided, not only the last."""
    d = decision(count=2, slots={"click1": (21, 0.9, [(22, 0.05)]), "click2": (100, 0.5, [(140, 0.4)])})
    first_look = read(d, 1)                   # what an earlier, slightly different board was answered
    avoid = [read(d, 0), first_look]
    ans = Svc.read_answer(d, SIZE, [], lambda ids: "", STOP, None, avoid)
    assert not any(Svc.same_effect(ans, a) for a in avoid)


def test_two_points_a_hair_apart_are_the_same_answer():
    a = {"action": "click", "points": [[486, 715], [192, 489]]}
    assert Svc.same_effect(a, {"action": "click", "points": [[192, 489], [488, 713]]})
    assert not Svc.same_effect(a, {"action": "click", "points": [[192, 489], [782, 490]]})
    assert Svc.same_effect({"action": "click", "points": [[100, 100]], "ids": [3]},
                           {"action": "click", "points": [[300, 300]], "ids": [3]})


def test_with_every_variant_refused_the_heads_own_answer_comes_back():
    d = decision(count=1, slots={"click1": (21, 1.0, [])})
    d["action_p"] = [1.0 if a == "click" else 0.0 for a in L.ACTIONS]
    assert read(d, 80) == read(d, 0)


def test_the_server_takes_the_refused_answers():
    import base64
    import io
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (64, 64)).save(buf, "PNG")
    img = base64.b64encode(buf.getvalue()).decode()
    refused = [{"action": "type", "text": "XK4XWP"}]
    assert Srv.parse({"image": img, "avoid": refused})["avoid"] == refused
    assert Srv.parse({"image": img})["avoid"] == []
    with pytest.raises(ValueError):
        Srv.parse({"image": img, "avoid": ["XK4XWP"]})


def test_the_planner_uses_the_three_actions_before_asking_again(monkeypatch, tmp_path):
    from PIL import Image
    sent = []
    first = {"action": "click", "points": [[100, 100]]}
    second = {"action": "click", "points": [[200, 200]]}
    third = {"action": "click", "points": [[300, 300]]}

    class _Resp:
        ok = True

        @staticmethod
        def json():
            return {"answer": first, "actions": [first, second, third]}

    monkeypatch.setattr(P.requests.Session, "post", lambda self, url, headers=None, json=None, timeout=None:
                        sent.append(json) or _Resp())
    monkeypatch.setattr(P, "ensure_server", lambda *a, **k: None)
    img = tmp_path / "b.png"
    Image.new("RGB", (64, 64)).save(img)
    pl = P.ActionPlanner(model="x", base_url="http://127.0.0.1:1/v1", api_key="k")

    first_actions = pl.get_pointer_actions(str(img))
    pl.avoid_refused = True
    second_actions = pl.get_pointer_actions(str(img))
    third_actions = pl.get_pointer_actions(str(img))
    refresh = pl.get_pointer_actions(str(img))

    assert first_actions[0]["kind"] == "click"
    assert second_actions[0]["points"] != first_actions[0]["points"]
    assert third_actions[0]["points"] != second_actions[0]["points"]
    assert refresh[0]["kind"] == "refresh"
    assert len(sent) == 1
    assert pl.pointer_fallback_actions() == [[{"kind": "refresh", "points": []}]]


def test_the_server_returns_the_three_likeliest_actions():
    d = decision(count=2, slots={"click1": (21, 0.9, [(22, 0.05)]), "click2": (100, 0.5, [(140, 0.4)])})
    answers = Svc.read_answers(d, SIZE, [], lambda ids: "", STOP, top=3)
    assert len(answers) == 3
    assert answers[0] == Svc.read_answer(d, SIZE, [], lambda ids: "", STOP)
    assert all(not Svc.same_effect(a, b) for i, a in enumerate(answers) for b in answers[i + 1:])
    out = Srv.reply({"answer": answers[0], "answers": answers, "size": SIZE, "elements": []})
    assert out["actions"] == answers and out["answer"] == answers[0]


def test_the_planner_names_the_refused_answers_once_told_to(monkeypatch):
    sent = []
    answers = iter([{"action": "type", "text": "AB", "checks": {}}, {"action": "type", "text": "AC"}, {}])

    class _Resp:
        ok = True

        @staticmethod
        def json():
            return {"answer": next(answers)}

    monkeypatch.setattr(P.requests.Session, "post", lambda self, url, headers=None, json=None, timeout=None:
                        sent.append(json) or _Resp())
    monkeypatch.setattr(P, "ensure_server", lambda *a, **k: None)
    pl = P.ActionPlanner(model="x", base_url="http://127.0.0.1:1/v1", api_key="k")
    pl._ask_pointer({"image": "AA"})
    assert "avoid" not in sent[0]
    pl.avoid_refused = True
    pl._ask_pointer({"image": "AA"})
    pl._ask_pointer({"image": "AA"})
    assert sent[1]["avoid"] == [{"action": "type", "text": "AB"}]
    assert sent[2]["avoid"] == [{"action": "type", "text": "AB"}, {"action": "type", "text": "AC"}]


def _drag(*pairs):
    return {"action": "drag", "drags": [{"from": list(a), "to": list(b)} for a, b in pairs]}


def test_a_repeated_drag_is_not_a_new_answer():
    a, again = ((100, 500), (800, 200)), ((101, 500), (801, 201))
    assert Svc._distinct_drags(_drag(a, again)) == _drag(a)
    assert Svc.same_effect(Svc._distinct_drags(_drag(a, again)), _drag(a))
    other = ((100, 500), (300, 700))
    assert Svc._distinct_drags(_drag(a, other)) == _drag(a, other)


def test_dropping_a_repeated_drag_renumbers_the_checks_of_the_ones_after_it():
    a, again, b = ((100, 500), (800, 200)), ((101, 500), (801, 201)), ((300, 300), (600, 600))
    names = [f"drag{k} {end}" for k in (1, 2, 3) for end in ("from", "to")]
    ans = {**_drag(a, again, b), "checks": {"slots": [{"slot": n, "tag": n} for n in names]}}
    slots = Svc._distinct_drags(ans)["checks"]["slots"]
    assert [(s["slot"], s["tag"]) for s in slots] == [("drag1 from", "drag1 from"), ("drag1 to", "drag1 to"),
                                                       ("drag2 from", "drag3 from"), ("drag2 to", "drag3 to")]


def _planner_answering(monkeypatch, actions):
    pl = P.ActionPlanner.__new__(P.ActionPlanner)
    pl.base_url, pl.api_key, pl.model, pl.request_timeout_s = "http://x", "k", "m", None
    pl.pointer_answers, pl.pointer_fallbacks, pl.pointer_history = [], [], []
    pl.pointer_has_actions, pl.avoid_refused = False, False
    pl._log = lambda *_: None

    class Resp:
        ok = True

        def json(self):
            return {"answer": actions[0], "actions": actions}
    pl._http = type("H", (), {"post": lambda self, *a, **k: Resp()})()
    monkeypatch.setattr(P.config, "is_hosted_endpoint", lambda *_: False)
    return pl


def test_a_plan_that_only_repeats_the_refused_drag_never_comes_back(monkeypatch):
    """Live: `[A]`, `[A, A']`, `[A, A', A'']` from one server, so a refused drag was pressed five more times."""
    a, a2, a3 = ((100, 500), (800, 200)), ((101, 500), (801, 201)), ((100, 501), (800, 199))
    pl = _planner_answering(monkeypatch, [_drag(a), _drag(a, a2), _drag(a, a2, a3)])
    pl._ask_pointer({})
    assert pl.pointer_fallbacks == []
    assert pl.pointer_fallback_actions() == [[{"kind": "refresh", "points": []}]]


def test_a_plan_that_moves_something_else_stays(monkeypatch):
    a, b = ((100, 500), (800, 200)), ((300, 300), (600, 600))
    moved = ((100, 500), (300, 700))
    pl = _planner_answering(monkeypatch, [_drag(a), _drag(moved), _drag(a, b)])
    pl._ask_pointer({})
    assert len(pl.pointer_fallbacks) == 2
    plans = pl.pointer_fallback_actions()
    assert [len(p) for p in plans] == [1, 2, 1] and plans[-1][0]["kind"] == "refresh"
