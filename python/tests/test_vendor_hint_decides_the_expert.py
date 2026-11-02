"""The vendor hint is whichever SELECTORS entry named the widget, keyed on the `hcaptcha` substring rather than the apex host
(challenges come off newassets.hcaptcha.com). A named vendor the grid expert never trained on gets the pixel expert;
`unknown` stays permissive for both grid shapes, because the CLI and the offline grader name no vendor."""

import json
from pathlib import Path

import pytest

from captchakraken.kinds import FrameRole, Vendor
from captchakraken.page_solver import PageSolver, PageSolverConfig
from captchakraken.selectors import SELECTORS
from captchakraken.solver import _grid_dims
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


def test_naming_hcaptcha_refuses_a_lattice_it_does_not_ship():
    assert _grid_dims(16, "hcaptcha") is None, \
        "hCaptcha ships no 4x4 — a 16-cell detection there is find_grid on the bands"
    assert _grid_dims(9, "hcaptcha") == (3, 3), "an hCaptcha 3x3 is a real grid"


def test_failing_to_name_the_vendor_lets_that_same_lattice_through():
    assert _grid_dims(16, "unknown") == (4, 4), (
        "if this ever starts refusing, the pairing below is no longer the "
        "reason the mis-route mattered — re-read the finding before relaxing it")
    widget = _detect([FakeNode([HCAPTCHA_CHALLENGE], src=FIXTURE_CHALLENGE)])
    assert _grid_dims(16, widget.vendor) is None, (
        "the fixture's hCaptcha board is being allowed a 4x4 again — the shape "
        "gate is off and find_grid's false positives reach the grid expert")


def test_only_the_vendors_the_grid_expert_was_trained_on_reach_it():
    for v in SELECTORS:
        want = {Vendor.RECAPTCHA: {9, 16}, Vendor.HCAPTCHA: {9}, Vendor.UNKNOWN: {9, 16}}.get(v, set())
        got = {n for n in (9, 16) if _grid_dims(n, v)}
        assert got == want, f"{v.value}: grids of {sorted(got)} cells reach the grid expert, not {sorted(want)}"
