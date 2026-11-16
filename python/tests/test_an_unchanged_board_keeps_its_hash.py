"""An unchanged board keeps its hash: the verdict toast a widget shows after a miss is not part of the board.

The board's identity was the sha1 of its whole photograph, toast included. On an hCaptcha-style line board the
"Please try again" toast is up for 2.2s after a wrong answer, so whether a round's shot caught it was down to timing:
one unchanged board read 5fe699bd, 80c5b1fd, 80c5b1fd, 5fe699bd over four rounds. The new hash in round 2 let the same
wrong answer be pressed again, and the change back in round 4 threw away three armed fallback plans. Mirror of
`js/src/an-unchanged-board-keeps-its-hash.test.ts`.
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path
from typing import Any, Callable, Dict, Optional

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from captchakraken.page_solver import PageSolver  # noqa: E402
from captchakraken.selectors import DEFAULT_TABLE  # noqa: E402

# The widget as a test fixture draws it: a board, and a toast pinned to its bottom edge that fades in after a miss.
WIDGET = (
    '<div id="widget" style="position:relative;width:240px;height:240px;background:#8ac">'
    '<div style="position:absolute;left:40px;top:40px;width:60px;height:60px;background:#c84"></div>'
    '<div id="ck-toast" style="position:absolute;left:0;right:0;bottom:0;z-index:9999;padding:8px;'
    'background:#d33;color:#fff;font:14px sans-serif;display:none">Please try again</div></div>'
)


class FakePage:
    viewport_size = {"width": 800, "height": 600}

    @staticmethod
    def evaluate(*_: Any) -> Dict[str, float]:
        # Wider than the viewport: the element is photographed by itself, so no viewport capture needs cropping.
        return {"width": 1200, "scale": 1}


class FakeWidget:
    """Photographs itself with the toast drawn unless the capture's stylesheet hides it."""

    def __init__(self, toast_shown: Callable[[], bool]) -> None:
        self._toast_shown = toast_shown

    def screenshot(self, path: str, style: Optional[str] = None, **_: Any) -> None:
        hidden = '[id*="toast" i] { display: none !important; }' in (style or "")
        Path(path).write_bytes(b"board with a toast" if self._toast_shown() and not hidden else b"board")


def test_the_board_reads_the_same_hash_with_and_without_its_verdict_toast() -> None:
    toast = {"shown": False}
    widget = FakeWidget(lambda: toast["shown"])
    solver = PageSolver()
    solver._page = FakePage()

    before = solver._board_hash(widget)
    toast["shown"] = True
    assert solver._board_hash(widget) == before, "the toast changed the board's identity"
    toast["shown"] = False
    assert solver._board_hash(widget) == before


def test_every_vendor_s_own_verdict_banner_is_left_out_of_the_identity_too() -> None:
    for vendor, s in DEFAULT_TABLE.vendors:
        for selector, _kind in s.banners:
            assert selector in DEFAULT_TABLE.feedback, f"{vendor}'s banner {selector} is part of the board's identity"


def test_in_a_browser_an_unchanged_board_keeps_its_hash_while_the_toast_comes_and_goes(tmp_path: Path) -> None:
    sync_playwright = pytest.importorskip("playwright.sync_api", reason="playwright not installed").sync_playwright
    cache = Path.home() / ".cache" / "ms-playwright"
    builds = [{}] + [{"executable_path": str(exe)} for exe in sorted(cache.glob("chromium-*/chrome-*/chrome"), reverse=True)]
    with sync_playwright() as p:
        failures = []
        for kwargs in builds:
            try:
                browser = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"], **kwargs)
                break
            except Exception as exc:  # noqa: BLE001
                failures.append(str(exc).splitlines()[0])
        else:
            pytest.skip(f"no chromium: {failures}")
        try:
            page = browser.new_page()
            page.set_content(WIDGET)
            solver = PageSolver()
            solver._page = page
            widget = page.query_selector("#widget")

            def toast(shown: bool) -> None:
                page.evaluate("s => { document.getElementById('ck-toast').style.display = s ? 'block' : 'none'; }", shown)

            def photo() -> str:
                out = tmp_path / "photo.png"
                solver._screenshot(widget, str(out))
                return hashlib.sha1(out.read_bytes()).hexdigest()

            before = solver._board_hash(widget)
            plain = photo()
            toast(True)
            assert solver._board_hash(widget) == before, "the toast changed the board's identity"
            # Only the identity leaves the toast out: the photograph the model reads still shows it.
            assert photo() != plain, "the toast never reached the photograph, so this test proves nothing"
            toast(False)
            assert solver._board_hash(widget) == before
        finally:
            browser.close()


def test_a_playwright_without_style_still_takes_the_shot():
    # Playwright before 1.41 has no `style`; the capture must still happen, just unmasked.
    from captchakraken.page_solver import _shot

    calls = []

    def old_screenshot(*, timeout, animations):
        calls.append((timeout, animations))
        return b"png"

    assert _shot(old_screenshot, "x{}", timeout=1, animations="disabled") == b"png"
    assert calls == [(1, "disabled")]
