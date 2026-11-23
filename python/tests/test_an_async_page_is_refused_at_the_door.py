"""The Python driver is synchronous, and an async page is refused before anything is done with it.

Handed an `async_playwright` page, `solve()` used to run a whole attempt against coroutines nobody awaited: every
locator came back empty, and it died in its own "no captcha found" message with `'coroutine' object is not
iterable`, which says nothing about the actual mistake.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from captchakraken.page_solver import PageSolver  # noqa: E402


class AsyncPage:
    """The shape of an async_api Page: its methods are coroutine functions."""

    def __init__(self) -> None:
        self.calls = 0

    async def evaluate(self, *_args, **_kwargs):
        self.calls += 1

    def locator(self, *_args, **_kwargs):
        self.calls += 1
        raise AssertionError("an async page was driven")


@pytest.mark.parametrize(
    "entry",
    ["solve", "watch", "capture", "detect_captcha", "is_captcha_solved", "has_interactive_widget_in_dom", "vendors_on_the_wire"],
)
def test_every_entry_point_refuses_an_async_page(entry):
    page = AsyncPage()
    with pytest.raises(TypeError, match="synchronous"):
        getattr(PageSolver(), entry)(page)
    assert page.calls == 0
