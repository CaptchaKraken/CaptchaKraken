"""The compatibility claim against a REAL browser: a fake cannot catch Playwright changing a method the driver calls.

The launch walks every installed Chromium build because the pinned-build check once reported four errors on a box
that had a browser; skipping is reserved for a box with none.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Any, List

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

sync_playwright = pytest.importorskip(
    "playwright.sync_api", reason="playwright not installed"
).sync_playwright

from captchakraken.watcher import CaptchaWatcher

LAUNCH_ARGS = ["--no-sandbox", "--disable-dev-shm-usage"]

HTML = """
<body style="height:3000px">
  <div id="target" data-vendor="recaptcha">hello captcha</div>
  <div id="hidden" style="display:none">nope</div>
  <input id="field" />
  <iframe id="frame" srcdoc="<div id='inner'>inner text</div>"></iframe>
</body>
"""


def _installed_chromiums() -> List[str]:
    cache = Path.home() / ".cache" / "ms-playwright"
    rels = ("chrome-linux64/chrome", "chrome-linux/chrome",
            "chrome-mac/Chromium.app/Contents/MacOS/Chromium",
            "chrome-win/chrome.exe")
    found = []
    for d in sorted(cache.glob("chromium-*"), reverse=True):
        for rel in rels:
            if (d / rel).exists():
                found.append(str(d / rel))
                break
    return found


@pytest.fixture(scope="module")
def page():
    with sync_playwright() as p:
        attempts: List[dict] = [{}]
        attempts += [{"executable_path": exe} for exe in _installed_chromiums()]
        browser = None
        failures = []
        for kwargs in attempts:
            try:
                browser = p.chromium.launch(headless=True, args=LAUNCH_ARGS, **kwargs)
                break
            except Exception as exc:
                failures.append(f"{kwargs.get('executable_path', 'pinned build')}: "
                                f"{str(exc).splitlines()[0]}")
        if browser is None:
            pytest.skip("no launchable Chromium on this box; tried "
                        + "; ".join(failures))
        try:
            ctx = browser.new_context(viewport={"width": 1280, "height": 720})
            yield ctx.new_page()
        finally:
            browser.close()


def test_a_real_page_provides_every_member_the_driver_duck_types(page: Any) -> None:
    page.set_content(HTML)

    target = page.locator("#target").element_handle(timeout=1000)
    assert target is not None, "locator.element_handle"
    assert page.locator("div").count() >= 2, "locator.count"
    assert len(page.locator("div").filter(visible=True).all()) == 1, "locator.filter(visible).all excludes display:none"

    assert target.get_attribute("data-vendor") == "recaptcha", "get_attribute"
    assert (target.text_content() or "").strip() == "hello captcha", "text_content"
    assert target.is_visible() is True, "is_visible (visible element)"
    assert page.locator("#hidden").element_handle(timeout=1000).is_visible() is False, "is_visible (display:none)"
    assert target.bounding_box()["width"] > 0, "bounding_box"
    target.scroll_into_view_if_needed()
    assert len(target.screenshot()) > 0, "element screenshot"
    assert len(page.screenshot(timeout=5000, animations="disabled")) > 0, "viewport screenshot"

    assert page.evaluate("() => document.title") == "", "evaluate"
    assert target.evaluate("el => el.id") == "target", "handle.evaluate"
    assert page.viewport_size == {"width": 1280, "height": 720}, "viewport_size"

    frame = page.locator("#frame").element_handle(timeout=1000).content_frame()
    assert frame is not None, "content_frame"
    assert frame.locator("#inner").count() == 1, "frame.locator"
    assert frame.locator("#inner").locator("xpath=ancestor::body[1]").count() == 1, "locator.locator (xpath axis)"
    assert frame.wait_for_selector("#inner", state="visible", timeout=5000), "frame.wait_for_selector"
    frame.wait_for_function("() => !!document.querySelector('#inner')", timeout=5000)

    page.mouse.move(100, 100, steps=4)
    page.mouse.down(button="left")
    page.mouse.up(button="left")
    page.focus("#field")
    page.keyboard.type("abc", delay=1)
    field = page.locator("#field").element_handle(timeout=1000)
    assert field.input_value() == "abc", "keyboard.type / handle.input_value"
    page.keyboard.press("Control+A")
    page.keyboard.press("Backspace")
    assert field.input_value() == "", "select-all + delete"

    assert page.is_closed() is False, "is_closed"


def test_the_watcher_solves_a_captcha_that_appears_after_it_is_installed(page: Any) -> None:
    page.set_content("<body></body>")
    solved: List[Any] = []

    class Solver:
        def detect_captcha(self, p: Any) -> Any:
            return p.locator("#late-captcha").count() > 0

        def solve(self, p: Any) -> Any:
            p.locator("#late-captcha").evaluate("el => el.remove()")
            solved.append(True)
            return {"is_solved": True}

    watcher = CaptchaWatcher(solver=Solver(), page=page, interval_ms=25)

    page.evaluate(
        "() => setTimeout(() => {"
        "  const el = document.createElement('div');"
        "  el.id = 'late-captcha';"
        "  document.body.appendChild(el);"
        "}, 100)"
    )

    watcher.run(timeout_ms=1500)

    assert len(solved) == 1, f"solved {len(solved)} times, expected exactly once"


def test_poll_once_drives_a_real_page_without_blocking(page: Any) -> None:
    page.set_content('<body><div id="late-captcha"></div></body>')

    class Solver:
        def detect_captcha(self, p: Any) -> Any:
            return p.locator("#late-captcha").count() > 0

        def solve(self, p: Any) -> Any:
            p.locator("#late-captcha").evaluate("el => el.remove()")
            return {"is_solved": True}

    watcher = CaptchaWatcher(solver=Solver(), page=page, interval_ms=10_000)

    started = time.monotonic()
    assert watcher.poll_once() is not None, "did not solve the captcha already on the page"
    assert watcher.poll_once() is None, "solved twice — the challenge was gone"
    assert time.monotonic() - started < 2.0, "poll_once waited an interval; run() owns the cadence"


def test_one_watcher_covers_every_navigation_on_the_page(page: Any) -> None:
    """The claim the per-page design rests on: installed once, the watcher must keep working across every `goto`."""
    solved: List[Any] = []

    class Solver:
        def detect_captcha(self, p: Any) -> Any:
            return p.locator("#c").count() > 0

        def solve(self, p: Any) -> Any:
            p.locator("#c").evaluate("el => el.remove()")
            solved.append(True)
            return {"is_solved": True}

    watcher = CaptchaWatcher(solver=Solver(), page=page, interval_ms=25)

    page.goto("data:text/html,<body>one</body>")
    watcher.run(timeout_ms=200)
    page.goto("data:text/html,<body>two</body>")
    watcher.run(timeout_ms=200)
    assert solved == [], "solved something on a page with no captcha"

    page.goto("data:text/html,<body><div id='c'></div>three</body>")
    watcher.run(timeout_ms=800)
    assert len(solved) == 1, "the watcher did not survive navigation"

    page.goto("data:text/html,<body><div id='c'></div>four</body>")
    watcher.run(timeout_ms=800)
    assert len(solved) == 2, "the watcher stopped arming after its first solve"


CAPTURE_FIXTURE = """
<body style="margin:0;height:2400px;background:#fafafa;font:14px sans-serif">
  <div id="board" style="position:absolute;left:37.5px;top:61.25px;width:301.3px;height:151.6px;border:3px solid #222;
       background:linear-gradient(90deg,#c33,#3c3 40%,#33c)">a still board</div>
  <iframe id="framed" style="position:absolute;left:420px;top:40px;width:260px;height:180px;border:1px solid #888"
          srcdoc="<body style='margin:0;background:#fe9'><div style='margin:20px;width:90px;height:60px;background:#069'></div>framed</body>">
  </iframe>
  <div id="below" style="position:absolute;left:50px;top:1500px;width:200px;height:120px;background:#9c6">below the fold</div>
</body>
"""


@pytest.mark.parametrize("dpr", [1, 2])
def test_the_viewport_crop_is_what_an_element_screenshot_shows(page: Any, dpr: int, tmp_path: Path) -> None:
    """The model-facing picture did not change when the capture did: same rect, same scale, same pixels."""
    import io

    import numpy as np
    from PIL import Image

    from captchakraken.page_solver import PageSolver

    context = page.context.browser.new_context(viewport={"width": 1280, "height": 720}, device_scale_factor=dpr)
    try:
        real = context.new_page()
        real.set_content(CAPTURE_FIXTURE)
        real.locator("#framed").element_handle().content_frame().wait_for_selector("div")
        solver = PageSolver()
        solver._page = real
        for selector in ("#board", "#framed", "#below"):
            handle = real.locator(selector).element_handle()
            path = tmp_path / f"{selector[1:]}.png"
            solver._screenshot(handle, str(path))
            ours = np.array(Image.open(path))
            theirs = np.array(Image.open(io.BytesIO(handle.screenshot(animations="disabled"))))
            assert ours.shape == theirs.shape, f"{selector} at dpr {dpr}: {ours.shape} against {theirs.shape}"
            assert (ours == theirs).all(), f"{selector} at dpr {dpr}: the crop differs from the element screenshot"
    finally:
        context.close()
