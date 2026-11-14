"""The vendor hint is whichever SELECTORS entry named the widget, keyed on the `hcaptcha` substring rather than the apex host
(challenges come off newassets.hcaptcha.com)."""

import json
from pathlib import Path

import pytest

from captchakraken.kinds import FrameRole, Vendor
from captchakraken.page_solver import PageSolver, PageSolverConfig
from fake_dom import FakeNode, fake_scope

HCAPTCHA_CHALLENGE = 'iframe[src*="hcaptcha"][src*="frame=challenge"]'
FIXTURE_CHALLENGE = "http://127.0.0.1:8080/frame?hcaptcha.html#frame=challenge"


def _detect(nodes):
    return PageSolver(config=PageSolverConfig()).detect_captcha(fake_scope(nodes))


def test_an_hcaptcha_frame_not_served_off_the_apex_host_is_still_hcaptcha():
    widget = _detect([FakeNode([HCAPTCHA_CHALLENGE], src=FIXTURE_CHALLENGE)])
    assert (widget.vendor, widget.role) == (Vendor.HCAPTCHA, FrameRole.CHALLENGE)


def test_the_hint_matches_the_same_substring_the_dom_selectors_do():
    src = Path(__file__).resolve().parents[1] / "src" / "captchakraken"
    config = Path(__file__).resolve().parents[2] / "captchakraken.config.json"
    assert HCAPTCHA_CHALLENGE in json.loads(config.read_text())["vendors"]["hcaptcha"]["challenge"], (
        "the challenge selector moved")
    assert "'hcaptcha.com' in" not in (src / "page_solver.py").read_text(), (
        "the apex host is being matched again somewhere; the shape gate will not engage")


@pytest.mark.parametrize("selector,vendor", [
    ('iframe[src*="recaptcha/api2/bframe"]', Vendor.RECAPTCHA),
    (".geetest_box", Vendor.GEETEST),
    (".yidun_panel", Vendor.YIDUN),
])
def test_every_vendor_names_itself(selector, vendor):
    assert _detect([FakeNode([selector])]).vendor == vendor


def test_nothing_on_the_page_is_no_widget():
    assert _detect([]) is None
