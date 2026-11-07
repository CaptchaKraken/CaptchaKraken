"""A repeated answer is a refusal only if the widget said anything since it was pressed.

A board that takes presses without telling its server anything has refused nothing, and another plan is one
more press a vendor scores. The same board also has to read as the same board however the round's picture was
taken, or the repeat is never seen and the same answer is pressed again.
"""
import os
import sys

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from captchakraken.page_solver import PageSolver, PageSolverConfig
from captchakraken.verdicts import VerdictLog

ANSWER = [{"action": "click", "target_bounding_boxes": [[0.1, 0.1, 0.2, 0.2]]}]


class Request:
    def __init__(self, resource_type):
        self.resource_type = resource_type


class Response:
    url, status = "https://widget.example/round", 200

    def __init__(self, resource_type):
        self.request = Request(resource_type)

    def body(self):
        return b""


class Page:
    def __init__(self):
        self.listeners = []

    def on(self, _event, listener):
        self.listeners.append(listener)

    def remove_listener(self, _event, listener):
        self.listeners.remove(listener)

    def say(self, resource_type):
        for listener in self.listeners:
            listener(Response(resource_type))


def _solver(page):
    s = PageSolver(config=PageSolverConfig())
    s._verdicts = VerdictLog(page)
    return s


def test_a_repeat_on_a_board_that_never_answered_earns_no_further_press():
    page = Page()
    s = _solver(page)
    s._note_answer(ANSWER, None)
    page.say("image")
    assert s._note_answer(ANSWER, None) is True
    assert s._refused_rounds == 0


def test_a_repeat_after_the_widget_answered_moves_to_the_next_plan():
    page = Page()
    s = _solver(page)
    s._note_answer(ANSWER, None)
    page.say("fetch")
    assert s._note_answer(ANSWER, None) is True
    assert s._refused_rounds == 1


def test_a_page_that_cannot_be_listened_to_keeps_the_repeat_as_its_only_evidence():
    s = _solver(object())
    s._note_answer(ANSWER, None)
    assert s._note_answer(ANSWER, None) is True
    assert s._refused_rounds == 1


def test_a_filmed_picture_and_a_plain_one_of_the_same_board_are_one_board(tmp_path):
    plain = b"the board, as the element paints it"
    filmed = tmp_path / "filmed.png"
    filmed.write_bytes(b"the same board, out of a recording")
    shot = tmp_path / "shot.png"
    shot.write_bytes(plain)

    s = _solver(object())
    s._screenshot = lambda _element, path, **_kw: open(path, "wb").write(plain)
    assert s._board_hash(None, str(filmed), filmed=True) == s._board_hash(None, str(shot), filmed=False)
