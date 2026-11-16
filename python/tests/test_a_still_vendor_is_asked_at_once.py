"""A slider or a hold is never animated, yet every one was filmed for 4s before the model's answer was used: on the
5.0 Tier 3 run that was a quarter of each board's budget. DataDome's pass is painted inside its own frame and the
page reloads a second later; unread, the next round filmed the closing frame and spent its 9s settle on it."""

from captchakraken.kinds import Vendor
from captchakraken.page_solver import PageSolver, PageSolverConfig, _still_shown
from captchakraken.selectors import load_config
from fake_dom import FakeHandle, FakeNode, fake_scope

DATADOME_FRAME = 'iframe[src*="captcha-delivery.com/captcha"]'
DATADOME_PASS = ".sliderContainer.slider-success .slider"


def _solver() -> PageSolver:
    return PageSolver(config=PageSolverConfig())


def test_only_vendors_that_can_animate_are_filmed():
    table = load_config().vendors
    for still in (Vendor.TENCENT, Vendor.DATADOME, Vendor.HUMAN, Vendor.FUNCAPTCHA, Vendor.DINGXIANG):
        assert table[still].stills_only, f"{still.value} is all sliders and holds, yet it would be filmed"
    for moving in (Vendor.HCAPTCHA, Vendor.GEETEST, Vendor.CYBERSIARA):
        assert not table[moving].stills_only, f"{moving.value} deals animated boards; it must stay filmed"


def test_a_still_vendor_is_asked_without_a_burst():
    solver = _solver()
    assert solver._should_speculate(Vendor.TENCENT, False) is False
    assert solver._should_speculate(Vendor.HCAPTCHA, False) is True


def test_datadome_s_pass_inside_its_frame_is_a_solve():
    frame = [FakeNode([DATADOME_PASS])]
    assert _solver().is_captcha_solved(fake_scope([FakeNode([DATADOME_FRAME], frame=frame)])) is True


def test_an_unfinished_datadome_slide_is_not_a_solve():
    frame = [FakeNode([".sliderContainer .slider"])]
    assert _solver().is_captcha_solved(fake_scope([FakeNode([DATADOME_FRAME], frame=frame)])) is False


def test_a_closed_widget_is_not_polled_for_its_whole_window():
    solver = _solver()
    gone = FakeHandle(FakeNode(["x"], visible=False))
    shots = []

    def fail(*_a, **_kw):
        shots.append(1)
        raise RuntimeError("frame was detached")

    solver._screenshot = fail
    assert solver._poll(gone, 9_000, 10, lambda *_a: None, "settle") is None
    assert len(shots) == 1, "a widget that has closed was shot again"


def test_a_handle_that_cannot_be_asked_is_gone():
    class Detached:
        def is_visible(self):
            raise RuntimeError("element is not attached")

    assert _still_shown(Detached()) is False
    assert _still_shown(FakeHandle(FakeNode(["x"]))) is True
