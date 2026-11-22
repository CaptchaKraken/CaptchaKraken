"""A widget is found inside a frame that is not the vendor's: a bot-protection block page, a modal, an embed.

Imperva's block page holds one same-origin iframe and nothing else, and the captcha is drawn inside that iframe's
document. Detection read only the top page and the vendor's own enclaves, so it found no widget on a page with a
challenge open on it. The JS test of the same name drives the same cases.
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
from captchakraken.page_solver import PageSolver, PageSolverConfig, _host_scopes  # noqa: E402
from captchakraken.selectors import DEFAULT_TABLE, FRAME_SELECTORS, VENDORS, WIDGET_PROBES  # noqa: E402

BLOCK_PAGE = "/_Incapsula_Resource?SWUDNSAI=30&xinfo=1-11111111-0&incident_id=000000000000000000-000000000000000000"
ASSETS = "https://newassets.hcaptcha.com/captcha/v1/06f8dac28bb865a058d94cbd615a79d63217dd86/static"
CHECKBOX = f"{ASSETS}/hcaptcha.html#frame=checkbox&id=0so2b8l008q&host=example.com"
CHALLENGE = f"{ASSETS}/hcaptcha.html#frame=challenge&id=0so2b8l008q&host=example.com"
ANCHOR = "https://www.google.com/recaptcha/api2/anchor?k=6LeSYNTHETIC&co=aHR0cHM6Ly9leGFtcGxlLmNvbQ"

# Every iframe selector the driver reads on a host page, so a fake frame answers to exactly what a CSS engine would.
HOST_IFRAME_SELECTORS = tuple(dict.fromkeys([
    *(p.selector for p in WIDGET_PROBES), *FRAME_SELECTORS,
    *(sel for _, s in VENDORS for sel in (*s.passive, *(f'iframe[src*="{h}"]' for h in s.hosts))),
]))


def _iframe(src: str, **node: Any) -> FakeNode:
    return FakeNode(matches=iframe_matches(src, HOST_IFRAME_SELECTORS), **node)


def _block_page(frame: List[FakeNode], visible: bool = True) -> FakeNode:
    return _iframe(BLOCK_PAGE, visible=visible, frame=frame)


def _response(value: str = "") -> FakeNode:
    return FakeNode(matches=['[name="h-captcha-response"]'], visible=False, value=value)


def test_a_checkbox_inside_the_block_page_is_found():
    box = _iframe(CHECKBOX)
    widget = PageSolver().detect_captcha(fake_scope([_block_page([box, _response()])]))
    assert widget is not None, "nothing detected through the block page's frame"
    assert (widget.vendor, widget.role) == (Vendor.HCAPTCHA, FrameRole.CHECKBOX)
    assert isinstance(widget.element, FakeHandle) and widget.element.node is box


def test_the_open_challenge_inside_the_block_page_comes_before_its_checkbox():
    live = _iframe(CHALLENGE)
    widget = PageSolver().detect_captcha(fake_scope([_block_page([_iframe(CHECKBOX), live, _response()])]))
    assert widget is not None and widget.role == FrameRole.CHALLENGE
    assert isinstance(widget.element, FakeHandle) and widget.element.node is live


def test_a_widget_two_frames_down_is_found():
    # A modal with no src of its own (srcdoc) around a site's embed around the vendor's frame.
    anchor = _iframe(ANCHOR)
    modal = FakeNode(matches=iframe_matches("about:srcdoc", HOST_IFRAME_SELECTORS),
                     frame=[_iframe("https://forms.example.com/embed/contact", frame=[anchor])])
    widget = PageSolver().detect_captcha(fake_scope([modal]))
    assert widget is not None, "nothing detected two frames below the page"
    assert (widget.vendor, widget.role) == (Vendor.RECAPTCHA, FrameRole.CHECKBOX)
    assert isinstance(widget.element, FakeHandle) and widget.element.node is anchor


def test_a_frame_holding_nothing_of_a_vendors_is_walked_through_but_not_read():
    # An ad frame, and a modal whose only content is a site's embed: neither is a scope the probes are read in, but the
    # embed inside the modal, holding the vendor's frame, is.
    ad = _iframe("https://ads.example.net/slot/1", frame=[FakeNode(matches=["div"]), _iframe("about:blank", frame=[])])
    modal = _iframe("about:srcdoc", frame=[_iframe("https://forms.example.com/embed/contact", frame=[_iframe(ANCHOR)])])
    assert len(_host_scopes(fake_scope([ad]), DEFAULT_TABLE)) == 1, "an ad frame is read as a page"
    assert len(_host_scopes(fake_scope([ad, modal]), DEFAULT_TABLE)) == 2, "the walk kept the wrong frames"


def test_a_hidden_frame_is_not_searched():
    # Playwright judges visibility within the frame's own document, so the hidden frame's checkbox reads as visible.
    assert PageSolver().detect_captcha(fake_scope([_block_page([_iframe(CHECKBOX)], visible=False)])) is None


def test_a_vendors_own_frame_is_never_a_frame_to_search():
    # Inside a widget's frame is the vendor's business: the probes there are read through that frame, not as a page.
    for src in (CHECKBOX, CHALLENGE, ANCHOR):
        assert iframe_matches(src, FRAME_SELECTORS) == [], f"{src} would be searched as a page"
    assert iframe_matches(BLOCK_PAGE, FRAME_SELECTORS), "the block page's frame is not searched"


def test_a_token_written_inside_the_block_page_is_a_solve():
    solver = PageSolver()
    assert solver.is_captcha_solved(fake_scope([_block_page([_iframe(CHALLENGE), _response()])])) is False
    assert solver.is_captcha_solved(fake_scope([_block_page([_iframe(CHALLENGE), _response("P1_eyJ0")])]))


def test_a_frame_inside_the_block_page_that_no_selector_names_is_the_table_going_stale():
    page = fake_scope([_block_page([_iframe(f"{ASSETS}/hcaptcha.html#frame=puzzle&id=a")])])
    assert PageSolver()._unmatched_vendor_frames(page) == [Vendor.HCAPTCHA]


# The same page through a real browser: the archived block page, wrapping the recorded enclave and its challenge.
FIXTURES = Path(__file__).resolve().parent / "fixtures"
SERVED = {
    "host.html": FIXTURES / "imperva_block_page" / "host.html",
    "_Incapsula_Resource": FIXTURES / "imperva_block_page" / "incapsula.html",
    "hcaptcha-enclave.html": FIXTURES / "hcaptcha_enclave" / "enclave.html",
    "hcaptcha.html": FIXTURES / "hcaptcha_enclave" / "challenge.html",
}
# The block page's frame has no border and sits at the origin, so the challenge is where the enclave puts it.
CHALLENGE_BOX = {"x": 441, "y": 151, "width": 400, "height": 600}


def _tile(n: int) -> List[float]:
    """Tile `n` of the recorded 3x3, as the model answers: fractions of the challenge frame."""
    col, row = (n - 1) % 3, (n - 1) // 3
    x, y = 10 + col * 130, 130 + row * 130
    return [x / 400, y / 600, (x + 120) / 400, (y + 120) / 600]


class _FixtureHandler(SimpleHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 - the stdlib's name
        file = SERVED.get(self.path.split("?")[0].rsplit("/", 1)[-1])
        if file is None:
            self.send_error(404)
            return
        body = file.read_text().replace("FRAMES_ORIGIN", f"http://localhost:{self.server.server_port}")
        self.send_response(200)
        self.send_header("content-type", "text/html")
        self.end_headers()
        self.wfile.write(body.encode())

    def log_message(self, *_: Any) -> None:
        pass


@contextmanager
def _served_fixtures() -> Iterator[str]:
    """The block page and its frame on one origin, the vendor's frames on another, as they are served."""
    server = ThreadingHTTPServer(("127.0.0.1", 0), _FixtureHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/host.html"
    finally:
        server.shutdown()
        server.server_close()


@pytest.fixture
def block_page() -> Iterator[Any]:
    sync_playwright = pytest.importorskip("playwright.sync_api", reason="playwright not installed").sync_playwright
    with _served_fixtures() as url, sync_playwright() as p:
        try:
            browser = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
        except Exception as e:
            if "Executable doesn't exist" not in str(e):
                raise
            pytest.skip("the Playwright browser is not installed")
        try:
            page = browser.new_page(viewport={"width": 1280, "height": 900})
            page.goto(url)
            page.frame_locator("#main-iframe").frame_locator('iframe[src*="frame=enclave"]') \
                .frame_locator('iframe[src*="frame=challenge"]').locator(".button-submit").wait_for()
            yield page
        finally:
            browser.close()


def _challenge(page: Any) -> Any:
    return next(f for f in page.frames if "/live/hcaptcha.html#frame=challenge" in f.url)


def test_through_real_frames_the_challenge_inside_the_block_page_is_found_where_it_is_on_screen(block_page):
    widget = PageSolver().detect_captcha(block_page)
    assert widget is not None, "nothing detected through the block page's frame"
    assert widget.role == FrameRole.CHALLENGE
    assert widget.element.content_frame() == _challenge(block_page)
    assert widget.element.bounding_box() == CHALLENGE_BOX


def test_through_real_frames_a_solve_on_the_block_page_clicks_its_tiles_and_reads_the_token(block_page):
    solver = PageSolver(config=PageSolverConfig(humanization="none", video_solve_enabled=False, max_solve_loops=1,
                                                detection_timeout_ms=2_000, post_solve_outcome_timeout_ms=2_000))
    shown: List[Optional[tuple]] = []

    def answer(image_path: str, *_: Any, **__: Any):
        shown.append(struct.unpack(">II", Path(image_path).read_bytes()[16:24]))
        return [ClickAction(action="click", target_bounding_boxes=[_tile(2), _tile(6)])], []

    solver._get_solution = answer
    solver._solver.planner.report_outcome = lambda *_: False

    result = solver.solve(block_page)
    pressed = _challenge(block_page).locator('.task[aria-pressed="true"]').evaluate_all(
        "tasks => tasks.map((t) => t.getAttribute('aria-label'))")
    assert pressed == ["Challenge Image 2", "Challenge Image 6"], "the clicks landed on other tiles"
    assert shown == [(CHALLENGE_BOX["width"], CHALLENGE_BOX["height"])], "the model was shown something other than the challenge"
    assert result.is_solved, "the token the enclave received was not read as a solve"
