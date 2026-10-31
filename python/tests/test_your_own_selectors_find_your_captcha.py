"""A captcha the built-in table does not know is found and driven through the caller's own selectors. Mirrors
js/src/your-own-selectors-find-your-captcha.test.ts."""

from __future__ import annotations

import pytest

from captchakraken.kinds import FrameRole, Vendor
from captchakraken.page_solver import PageSolver, PageSolverConfig
from captchakraken.selectors import DEFAULT_TABLE, SelectorTable, VendorSelectors
from fake_dom import FakeNode, fake_scope

# A site's own image captcha: a picture and a code box in a container of its own, with a button that says "Check".
SIGNUP = VendorSelectors(hosts=(), widget=("#signup-captcha",), text_input=("#signup-code",),
                         submit=("#signup-check",), refresh=("#signup-new-image",))


def test_a_captcha_only_your_selectors_name_is_found():
    page = fake_scope([FakeNode(["#signup-captcha"])])
    assert PageSolver(config=PageSolverConfig()).detect_captcha(page) is None
    widget = PageSolver(config=PageSolverConfig(custom_selectors=SIGNUP)).detect_captcha(page)
    assert widget is not None and (widget.vendor, widget.role) == (Vendor.UNKNOWN, FrameRole.UNKNOWN)


def test_your_controls_are_tried_before_the_generic_ones():
    table = SelectorTable(SIGNUP)
    assert table.text_input[0] == "#signup-code"
    assert table.refresh[0] == "#signup-new-image"
    check = FakeNode(["#signup-check"], text="Check")
    found = PageSolver(config=PageSolverConfig(custom_selectors=SIGNUP))._get_verify_button(fake_scope([check]))
    assert found is not None and found.node is check, "the site's own Check button was not pressed"


def test_your_selectors_leave_every_other_solver_alone():
    PageSolver(config=PageSolverConfig(custom_selectors=SIGNUP))
    assert "#signup-captcha" not in {p.selector for p in DEFAULT_TABLE.widget_probes}
    assert PageSolver(config=PageSolverConfig()).detect_captcha(fake_scope([FakeNode(["#signup-captcha"])])) is None


def test_an_entry_that_names_nothing_to_detect_is_refused():
    with pytest.raises(ValueError, match="nothing to detect"):
        PageSolver(config=PageSolverConfig(custom_selectors=VendorSelectors(hosts=(), text_input=("#code",))))
