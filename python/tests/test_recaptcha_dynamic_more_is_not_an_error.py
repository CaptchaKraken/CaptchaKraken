from __future__ import annotations

import pytest

from captchakraken.page_solver import PageSolver
from fake_dom import FakeNode, fake_scope

BFRAME = 'iframe[src*="recaptcha/api2/bframe"]'


def _page(selector: str | None, text: str = "banner"):
    banner = [FakeNode([selector], text=text)] if selector else []
    return fake_scope([FakeNode([BFRAME], frame=banner)])


@pytest.mark.parametrize(
    "selector,text,expected",
    [
        (".rc-imageselect-incorrect-response", "Please try again.", "rejected"),
        (".rc-imageselect-error-select-more", "Please select all matching images.", "select-more"),
        (".rc-imageselect-error-dynamic-more", "Please also check the new images.", "dynamic-more"),
        (None, "", None),
    ],
)
def test_each_banner_is_named_separately(selector, text, expected):
    assert PageSolver()._banner_kind(_page(selector, text)) == expected


def test_an_empty_banner_is_a_placeholder_not_a_verdict():
    assert PageSolver()._banner_kind(_page(".rc-imageselect-incorrect-response", "  ")) is None


@pytest.mark.parametrize("selector,text,missed", [
    (".rc-imageselect-error-select-more", "Please select all matching images.", True),
    (".rc-imageselect-error-dynamic-more", "Please also check the new images.", False),
    (".rc-imageselect-incorrect-response", "Please try again.", False),
])
def test_only_an_under_selection_asks_for_the_missed_tiles(selector, text, missed):
    assert (PageSolver()._banner_kind(_page(selector, text)) == "select-more") is missed
