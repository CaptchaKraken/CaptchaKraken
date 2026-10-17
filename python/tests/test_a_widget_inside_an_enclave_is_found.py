"""hCaptcha's secure-api.js draws no frame on the host page. Every frame it owns sits inside a full-viewport enclave
iframe, one enclave per render, and only the visible one holds the open challenge.

Measured on a live job-board posting on 2026-10-15: after hcaptcha.execute() the host page held two enclaves and nothing else, so
detection found no widget, and the tripwire blamed the selector table for a challenge that was on screen and still
matched every selector inside its frame. The JS test of the same name drives the same cases.
"""

from __future__ import annotations

import struct
import sys
import threading
from contextlib import contextmanager
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Iterator, List, Optional

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fake_dom import FakeHandle, FakeNode, fake_scope, iframe_matches  # noqa: E402

from captchakraken.action_types import ClickAction  # noqa: E402
from captchakraken.kinds import FrameRole, Vendor  # noqa: E402
from captchakraken.page_solver import PageSolver, PageSolverConfig  # noqa: E402
from captchakraken.selectors import ENCLAVE_SELECTORS, VENDORS, WIDGET_PROBES  # noqa: E402

ASSETS = "https://newassets.hcaptcha.com/captcha/v1/06f8dac28bb865a058d94cbd615a79d63217dd86/static"
ENCLAVE = f"{ASSETS}/hcaptcha-enclave.html#frame=enclave&_channel=1vx5ycvkplus&host=careers.example.com"
INVISIBLE = f"{ASSETS}/hcaptcha.html#frame=checkbox-invisible"


def _challenge_src(widget_id: str) -> str:
    return f"{ASSETS}/hcaptcha.html#frame=challenge&id={widget_id}&host=careers.example.com&size=invisible"


# Every iframe selector the driver reads on a host page, so a fake frame answers to exactly what a CSS engine would.
HOST_IFRAME_SELECTORS = tuple(dict.fromkeys([
    *(p.selector for p in WIDGET_PROBES), *ENCLAVE_SELECTORS,
    *(sel for _, s in VENDORS for sel in (*s.passive, *(f'iframe[src*="{h}"]' for h in s.hosts))),
]))


def _iframe(src: str, **node: Any) -> FakeNode:
    return FakeNode(matches=iframe_matches(src, HOST_IFRAME_SELECTORS), **node)


def _enclave(visible: bool, frame: List[FakeNode]) -> FakeNode:
    return _iframe(ENCLAVE, visible=visible, frame=frame)


def _response(value: str = "") -> FakeNode:
    return FakeNode(matches=['[name="h-captcha-response"]'], visible=False, value=value)


def test_the_open_challenge_is_found_inside_the_visible_enclave_not_the_hidden_one():
    # The hidden enclave's challenge is not hidden inside its own document, so the enclave's visibility is what decides.
    idle = _iframe(_challenge_src("0ewuzu8hdfwo"))
    live = _iframe(_challenge_src("0so2b8l008q"))
    page = fake_scope([
        _enclave(False, [idle, _iframe(INVISIBLE, visible=False), _response()]),
        _enclave(True, [live, _iframe(INVISIBLE, visible=False), _response()]),
    ])
    widget = PageSolver().detect_captcha(page)
    assert widget is not None, "nothing detected through the enclave"
    assert (widget.vendor, widget.role) == (Vendor.HCAPTCHA, FrameRole.CHALLENGE)
    assert isinstance(widget.element, FakeHandle) and widget.element.node is live, "detected the hidden enclave's challenge"


def test_an_enclave_nobody_has_raised_holds_no_widget():
    page = fake_scope([_enclave(False, [_iframe(_challenge_src("a"))]), _enclave(False, [_iframe(_challenge_src("b"))])])
    assert PageSolver().detect_captcha(page) is None


def test_the_invisible_checkbox_is_never_a_checkbox_to_click():
    assert iframe_matches(INVISIBLE, [p.selector for p in WIDGET_PROBES]) == [], "a probe names the invisible checkbox frame"
    assert PageSolver().detect_captcha(fake_scope([_enclave(True, [_iframe(INVISIBLE)])])) is None


def test_a_token_written_inside_the_enclave_is_a_solve():
    solver = PageSolver()
    assert solver.is_captcha_solved(fake_scope([_enclave(True, [_iframe(_challenge_src("a")), _response()])])) is False
    assert solver.is_captcha_solved(fake_scope([_enclave(True, [_iframe(_challenge_src("a")), _response("P1_eyJ0")])]))


def test_an_enclave_is_not_a_frame_the_selector_table_missed():
    solver = PageSolver()
    quiet = fake_scope([_enclave(True, [_iframe(INVISIBLE, visible=False)]), _enclave(False, [])])
    assert solver._unmatched_vendor_frames(quiet) == [], "blamed the table for a frame that is never interactive"
    # A frame inside the enclave that no selector names IS the table going stale, and must still say so.
    renamed = fake_scope([_enclave(True, [_iframe(f"{ASSETS}/hcaptcha.html#frame=puzzle&id=a")])])
    assert solver._unmatched_vendor_frames(renamed) == [Vendor.HCAPTCHA]


# The same page through a real browser: two origins, two levels of frames, the layout that page served.
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "hcaptcha_enclave"
# Where the live enclave puts its challenge: the wrapper's offset plus its 1px border, at the frame's own size.
CHALLENGE_BOX = {"x": 441, "y": 151, "width": 400, "height": 600}


def _tile(n: int) -> List[float]:
    """Tile `n` of the recorded 3x3, as the model answers: fractions of the challenge frame."""
    col, row = (n - 1) % 3, (n - 1) // 3
    x, y = 10 + col * 130, 130 + row * 130
    return [x / 400, y / 600, (x + 120) / 400, (y + 120) / 600]


class _FixtureHandler(SimpleHTTPRequestHandler):
    NAMES = {"host.html": "host.html", "hcaptcha-enclave.html": "enclave.html", "hcaptcha.html": "challenge.html"}

    def do_GET(self) -> None:  # noqa: N802 - the stdlib's name
        name = self.NAMES.get(self.path.split("?")[0].rsplit("/", 1)[-1])
        if name is None:
            self.send_error(404)
            return
        body = (FIXTURES / name).read_text().replace("FRAMES_ORIGIN", f"http://localhost:{self.server.server_port}")
        self.send_response(200)
        self.send_header("content-type", "text/html")
        self.end_headers()
        self.wfile.write(body.encode())

    def log_message(self, *_: Any) -> None:
        pass


@contextmanager
def _served_fixtures() -> Iterator[str]:
    """host.html on one origin; the enclaves and the challenge on another, as hCaptcha serves them."""
    server = ThreadingHTTPServer(("127.0.0.1", 0), _FixtureHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/host.html"
    finally:
        server.shutdown()
        server.server_close()


@pytest.fixture
def recorded_page() -> Iterator[Any]:
    sync_playwright = pytest.importorskip("playwright.sync_api", reason="playwright not installed").sync_playwright
    with _served_fixtures() as url, sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
        try:
            page = browser.new_page(viewport={"width": 1280, "height": 900})
            page.goto(url)
            page.frame_locator('iframe[src*="/live/"]').frame_locator('iframe[src*="frame=challenge"]') \
                .locator(".button-submit").wait_for()
            yield page
        finally:
            browser.close()


def _live_challenge(page: Any) -> Any:
    return next(f for f in page.frames if "/live/hcaptcha.html#frame=challenge" in f.url)


def test_through_real_frames_the_challenge_is_found_where_it_is_on_screen(recorded_page):
    widget = PageSolver().detect_captcha(recorded_page)
    assert widget is not None, "nothing detected through the enclave"
    assert widget.role == FrameRole.CHALLENGE
    assert widget.element.content_frame() == _live_challenge(recorded_page), "detected the hidden enclave's challenge"
    # Clicks and crops are placed in page coordinates, so the box must be measured from the top frame.
    assert widget.element.bounding_box() == CHALLENGE_BOX


def test_through_real_frames_a_solve_clicks_the_tiles_it_was_told_to_and_reads_the_token(recorded_page):
    solver = PageSolver(config=PageSolverConfig(humanization="none", video_solve_enabled=False, max_solve_loops=1,
                                                detection_timeout_ms=2_000, post_solve_outcome_timeout_ms=2_000))
    shown: List[Optional[tuple]] = []

    def answer(image_path: str, *_: Any, **__: Any):
        shown.append(struct.unpack(">II", Path(image_path).read_bytes()[16:24]))
        return [ClickAction(action="click", target_bounding_boxes=[_tile(2), _tile(6)])], []

    solver._get_solution = answer
    solver._solver.planner.report_outcome = lambda *_: False

    result = solver.solve(recorded_page)
    pressed = _live_challenge(recorded_page).locator('.task[aria-pressed="true"]').evaluate_all(
        "tasks => tasks.map((t) => t.getAttribute('aria-label'))")
    assert pressed == ["Challenge Image 2", "Challenge Image 6"], "the clicks landed on other tiles"
    assert shown == [(CHALLENGE_BOX["width"], CHALLENGE_BOX["height"])], "the model was shown something other than the challenge"
    assert result.is_solved, "the token the enclave received was not read as a solve"
