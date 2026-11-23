"""AsyncPageSolver against a REAL async_playwright page: every member the driver duck-types works through the bridge,
the caller's loop keeps running while the driver waits, and a cancelled solve stops touching the page."""

from __future__ import annotations

import asyncio
import io
import sys
import time
from pathlib import Path
from typing import Any, Callable, List

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

async_api = pytest.importorskip("playwright.async_api", reason="playwright not installed")

import test_browser_compat as compat  # noqa: E402

from captchakraken import AsyncPageSolver, PageSolver  # noqa: E402
from captchakraken.async_page_solver import SolveCancelled, _on_worker  # noqa: E402
from captchakraken.verdicts import VerdictLog  # noqa: E402


async def _with_page(body: Callable[[Any], Any], dpr: int = 1) -> Any:
    async with async_api.async_playwright() as p:
        browser, failures = None, []
        for kwargs in [{}] + [{"executable_path": exe} for exe in compat._installed_chromiums()]:
            try:
                browser = await p.chromium.launch(headless=True, args=compat.LAUNCH_ARGS, **kwargs)
                break
            except Exception as exc:
                failures.append(str(exc).splitlines()[0])
        if browser is None:
            pytest.skip("no launchable Chromium on this box; tried " + "; ".join(failures))
        try:
            context = await browser.new_context(viewport={"width": 1280, "height": 720}, device_scale_factor=dpr)
            return await body(await context.new_page())
        finally:
            await browser.close()


def _drive(sync_body: Callable[[Any], Any], dpr: int = 1) -> Any:
    """Run a body written against a sync page on the worker, the way AsyncPageSolver runs the solve."""
    async def body(page: Any) -> Any:
        return await _on_worker(sync_body, page)
    return asyncio.run(_with_page(body, dpr))


def test_every_member_the_driver_duck_types_works_through_the_bridge() -> None:
    _drive(compat.test_a_real_page_provides_every_member_the_driver_duck_types)


@pytest.mark.parametrize("dpr", [1, 2])
def test_the_capture_through_the_bridge_is_the_element_screenshot(dpr: int, tmp_path: Path) -> None:
    import numpy as np
    from PIL import Image

    def body(real: Any) -> None:
        real.set_content(compat.CAPTURE_FIXTURE)
        real.locator("#framed").element_handle().content_frame().wait_for_selector("div")
        solver = PageSolver()
        solver._page = real
        for selector in ("#board", "#framed", "#below"):
            handle = real.locator(selector).element_handle()
            path = tmp_path / f"{selector[1:]}.png"
            solver._screenshot(handle, str(path))
            ours = np.array(Image.open(path))
            theirs = np.array(Image.open(io.BytesIO(handle.screenshot(animations="disabled"))))
            assert ours.shape == theirs.shape and (ours == theirs).all(), f"{selector} at dpr {dpr}"

    _drive(body, dpr)


def test_a_response_listener_reads_bodies_and_comes_off_again() -> None:
    """The driver reads response bodies from inside `page.on`; through the bridge that callback blocks on the loop
    that called it, which must not deadlock, and `remove_listener` must find the handler `on` registered."""
    def body(page: Any) -> None:
        page.route("**/ping*", lambda route: route.fulfill(status=200, body="pong"))
        bodies: List[bytes] = []

        def on_response(response: Any) -> None:
            if "ping" in response.url:
                bodies.append(response.body())

        page.goto("data:text/html,<body>listening</body>")
        page.on("response", on_response)
        log = VerdictLog(page)
        assert log._attached
        page.evaluate("() => fetch('https://example.test/ping?1')")
        page.wait_for_timeout(300)
        assert bodies == [b"pong"], "the body read inside the listener never came back"
        assert log.exchanges >= 1, "the verdict log heard nothing"
        page.remove_listener("response", on_response)
        log.close()
        page.evaluate("() => fetch('https://example.test/ping?2')")
        page.wait_for_timeout(300)
        assert bodies == [b"pong"], "remove_listener left the listener on"

    _drive(body)


def test_the_loop_keeps_running_while_the_driver_waits() -> None:
    async def body(page: Any) -> None:
        ticks: List[float] = []

        async def ticker() -> None:
            while True:
                ticks.append(time.monotonic())
                await asyncio.sleep(0.02)

        tick = asyncio.create_task(ticker())
        try:
            await _on_worker(lambda p: (time.sleep(0.3), p.wait_for_timeout(300)), page)
        finally:
            tick.cancel()
        assert len(ticks) >= 15, f"the loop ran {len(ticks)} times in 0.6 s; the driver blocked it"

    asyncio.run(_with_page(body))


def test_a_cancelled_solve_stops_touching_the_page() -> None:
    async def body(page: Any) -> None:
        calls: List[int] = []
        ended: List[BaseException] = []

        def solve(p: Any) -> None:
            try:
                while True:
                    p.evaluate("() => 1")
                    calls.append(1)
            except BaseException as exc:
                ended.append(exc)
                raise

        task = asyncio.create_task(_on_worker(solve, page))
        await asyncio.sleep(0.3)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        settled = len(calls)
        await asyncio.sleep(0.2)
        assert settled > 0 and len(calls) == settled, "the worker kept calling the page after the cancel"
        assert ended and isinstance(ended[0], SolveCancelled)

    asyncio.run(_with_page(body))


def test_the_public_methods_answer_on_a_page_with_no_captcha() -> None:
    async def body(page: Any) -> None:
        await page.set_content("<body><p>nothing to solve here</p></body>")
        solver = AsyncPageSolver()
        assert not await solver.detect_captcha(page)
        assert not await solver.has_interactive_widget_in_dom(page)
        assert await solver.vendors_on_the_wire(page) is not None

    asyncio.run(_with_page(body))


def test_the_async_watcher_solves_a_captcha_that_appears_later() -> None:
    async def body(page: Any) -> None:
        await page.set_content("<body></body>")
        solved: List[Any] = []

        class Solver:
            def detect_captcha(self, p: Any) -> Any:
                return p.locator("#late-captcha").count() > 0

            def solve(self, p: Any) -> Any:
                p.locator("#late-captcha").evaluate("el => el.remove()")
                return {"is_solved": True}

        async def on_solved(result: Any) -> None:
            solved.append(result)

        solver = AsyncPageSolver()
        solver._solver = Solver()
        watcher = solver.watch(page, interval_ms=25, on_solved=on_solved)
        await page.evaluate("() => setTimeout(() => {"
                            " const el = document.createElement('div'); el.id = 'late-captcha';"
                            " document.body.appendChild(el); }, 100)")
        assert await watcher.run(timeout_ms=1500) == 1
        assert solved == [{"is_solved": True}], "the coroutine on_solved was not awaited on the caller's loop"

    asyncio.run(_with_page(body))


def test_a_sync_page_is_sent_to_page_solver() -> None:
    class SyncPage:
        def evaluate(self, *_a: Any) -> None:
            raise AssertionError("driven")

    with pytest.raises(TypeError, match="PageSolver"):
        asyncio.run(AsyncPageSolver().solve(SyncPage()))
