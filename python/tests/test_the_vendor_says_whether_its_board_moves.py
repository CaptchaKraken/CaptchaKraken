"""A board's motion is read off the file the vendor deals it as, and the 4s burst is kept for boards nobody described.

Measured 2026-11-14 on the live demos: hCaptcha loads every still board as image/jpeg and every animated one as
video/webm; GeeTest v4's /load names the challenge type, and only its svg types move. Filming a board to find that
out cost every still hCaptcha and GeeTest board a 4s floor.
"""
import os
import sys

import pytest

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from captchakraken.kinds import Vendor
from captchakraken.page_solver import PageSolver, PageSolverConfig
from captchakraken.verdicts import VerdictLog

HC_DEAL = "https://api.hcaptcha.com/getcaptcha/7fcac73c-0096-446a-9c58-c080553a6fa8?s=1"
HC_BOARD = "https://imgs3.hcaptcha.com/tip/310c65b96dbc0a2f92ed212cc49e88ade109b81f71ca21795dc0ae47f048e367"
GT_LOAD = "https://gcaptcha4.geetest.com/load?captcha_id=x&callback=geetest_1"


class Request:
    def __init__(self, resource_type):
        self.resource_type = resource_type


class Response:
    def __init__(self, url, content_type="", body=b"", resource_type="image", status=200):
        self.url, self.status, self._body = url, status, body
        self.headers = {"content-type": content_type}
        self.request = Request(resource_type)

    def body(self):
        return self._body


class Page:
    def __init__(self):
        self.listeners = []

    def on(self, _event, listener):
        self.listeners.append(listener)

    def remove_listener(self, _event, listener):
        self.listeners.remove(listener)

    def send(self, *responses):
        for r in responses:
            for listener in self.listeners:
                listener(r)


def _hc_deal():
    return Response(HC_DEAL, "application/octet-stream", b"\xc4=\xaf\xc9X", "xhr")


def _gt_load(kind):
    body = ('geetest_1({"status": "success", "data": {"lot_number": "8916", "captcha_type": "%s"}})' % kind).encode()
    return Response(GT_LOAD, "text/javascript;charset=UTF-8", body, "script")


def test_an_hcaptcha_board_dealt_as_a_video_moves_and_one_dealt_as_a_jpeg_is_still():
    page = Page()
    log = VerdictLog(page)
    assert log.board_motion(Vendor.HCAPTCHA) is None
    page.send(_hc_deal(), Response(HC_BOARD, "video/webm", resource_type="media", status=206))
    assert log.board_motion(Vendor.HCAPTCHA) is True
    page.send(_hc_deal())
    assert log.board_motion(Vendor.HCAPTCHA) is None, "the next deal inherited the last board's motion"
    page.send(Response(HC_BOARD, "image/jpeg"))
    assert log.board_motion(Vendor.HCAPTCHA) is False


def test_one_moving_file_makes_the_board_a_moving_one():
    page = Page()
    log = VerdictLog(page)
    page.send(_hc_deal(), Response(HC_BOARD, "video/webm", resource_type="media"), Response(HC_BOARD, "image/jpeg"))
    assert log.board_motion(Vendor.HCAPTCHA) is True


@pytest.mark.parametrize("kind, moves", [("svg_icon", True), ("svg_seed", True), ("slide", False),
                                          ("nine", False), ("match", False), ("ai", None)])
def test_geetest_names_its_board_and_only_the_svg_types_move(kind, moves):
    page = Page()
    log = VerdictLog(page)
    page.send(_gt_load(kind))
    assert log.board_motion(Vendor.GEETEST) is moves


def test_a_type_nobody_measured_keeps_the_film():
    page = Page()
    log = VerdictLog(page)
    page.send(_gt_load("svg_icon"), _gt_load("ai"))
    assert log.board_motion(Vendor.GEETEST) is None


def _solver(page):
    s = PageSolver(config=PageSolverConfig())
    s._verdicts = VerdictLog(page)
    return s


def test_a_still_file_is_asked_at_once_and_an_undescribed_board_is_still_filmed():
    page = Page()
    s = _solver(page)
    assert s._should_speculate(Vendor.HCAPTCHA, False) is True
    page.send(_hc_deal(), Response(HC_BOARD, "image/jpeg"))
    assert s._should_speculate(Vendor.HCAPTCHA, False) is False
    assert s._should_speculate(Vendor.CYBERSIARA, False) is True, "a vendor with no signal lost its burst"


def test_a_board_dealt_as_a_video_is_filmed_without_waiting_for_it_to_settle():
    page = Page()
    s = _solver(page)
    page.send(_hc_deal(), Response(HC_BOARD, "video/webm", resource_type="media"))

    def settle(_el):
        raise AssertionError("waited for a video to settle")

    s._wait_for_element_settled = settle
    assert s._dealt_as_video(Vendor.HCAPTCHA) is True
    assert s._known_animated
    assert _solver(Page())._dealt_as_video(Vendor.HCAPTCHA) is False, "an undescribed board skipped its settle"


def test_with_no_listener_nothing_changes():
    s = PageSolver(config=PageSolverConfig())
    assert s._board_motion(Vendor.HCAPTCHA) is None
    assert s._should_speculate(Vendor.HCAPTCHA, False) is True
