"""The async driver: `PageSolver` for an `async_playwright` (or async Camoufox / patchright) page.

    async with async_playwright() as p:
        page = await (await p.chromium.launch()).new_page()
        await page.goto(url)
        result = await AsyncPageSolver().solve(page)

WHY IT IS A BRIDGE AND NOT A SECOND DRIVER
    The solve is ~3,000 lines of timing-sensitive decisions, and the two Python copies would drift the way the two
    ports did where only one had a guard. So there is one driver. It runs on a worker thread, and the page it drives
    is a proxy that hands every Playwright call back to the caller's event loop and blocks the worker, never the loop,
    until the call returns. The caller's other tasks keep running for the whole solve, waits included: a wait is a
    sleep on the worker thread, not on the loop.

    Every call goes through the loop, sync-shaped ones too (`page.locator`, `page.on`), so the async objects are only
    ever touched from the thread that owns them. Event callbacks run the other way: the loop gets an async handler
    that runs the driver's sync callback on a worker thread, so a callback that reads a response body can block on
    the loop without deadlocking it.

WHAT CANCELLATION DOES
    Cancelling the awaiting task stops the solve at its next page call, which raises `SolveCancelled` on the worker.
    Nothing is left running against the page once that call returns.
"""

from __future__ import annotations

import asyncio
import inspect
import threading
from typing import Any, Callable, Dict, Optional

from .page_solver import PageSolver, SolveResult
from .watcher import CaptchaWatcher

__all__ = ["AsyncPageSolver", "AsyncCaptchaWatcher", "solve_captcha_on_page_async"]

# Members that are coroutine functions on an async Playwright object, one or more per class the driver reaches.
_ASYNC_PROBES = ("evaluate", "click", "move", "press", "bounding_box", "screenshot", "body", "cookies", "new_page")
_PASSTHROUGH = (str, bytes, bytearray, int, float, bool, type(None), dict)


class SolveCancelled(RuntimeError):
    """Raised on the worker thread when the task awaiting the solve was cancelled."""


def is_async_page(page: Any) -> bool:
    return inspect.iscoroutinefunction(getattr(page, "evaluate", None))


def _is_async_handle(value: Any) -> bool:
    if isinstance(value, _PASSTHROUGH) or isinstance(value, _Proxy):
        return False
    if "async_api" in type(value).__module__:
        return True
    return any(inspect.iscoroutinefunction(getattr(type(value), name, None)) for name in _ASYNC_PROBES)


def _positional_arity(fn: Callable[..., Any]) -> Optional[int]:
    """How many positional arguments `fn` takes; None when it takes any number, or cannot be inspected."""
    try:
        params = inspect.signature(fn).parameters.values()
    except (TypeError, ValueError):
        return None
    if any(p.kind is p.VAR_POSITIONAL for p in params):
        return None
    return sum(p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD) for p in params)


class _Bridge:
    """Carries calls from the worker thread to the loop that owns the page."""

    def __init__(self, loop: asyncio.AbstractEventLoop) -> None:
        self.loop = loop
        # Built on the loop's own thread, by _on_worker.
        self.loop_thread = threading.current_thread()
        self.cancelled = threading.Event()
        self._handlers: Dict[Any, Callable[..., Any]] = {}

    def call(self, fn: Callable[..., Any], args: tuple, kwargs: dict) -> Any:
        if self.cancelled.is_set():
            raise SolveCancelled("the solve was cancelled")
        if threading.current_thread() is self.loop_thread:
            raise RuntimeError("a bridged page was called from its own event loop; that would deadlock")
        args = tuple(self.unwrap(a, register=fn) for a in args)
        kwargs = {k: self.unwrap(v, register=fn) for k, v in kwargs.items()}

        async def on_loop() -> Any:
            result = fn(*args, **kwargs)
            if inspect.isawaitable(result):
                result = await result
            return result

        future = asyncio.run_coroutine_threadsafe(on_loop(), self.loop)
        while True:
            try:
                return self.wrap(future.result(timeout=0.25))
            except TimeoutError:
                if self.cancelled.is_set():
                    future.cancel()
                    raise SolveCancelled("the solve was cancelled") from None

    def wrap(self, value: Any) -> Any:
        if isinstance(value, list):
            return [self.wrap(v) for v in value]
        if isinstance(value, tuple):
            return tuple(self.wrap(v) for v in value)
        return _Proxy(value, self) if _is_async_handle(value) else value

    def unwrap(self, value: Any, register: Any = None) -> Any:
        if isinstance(value, _Proxy):
            return object.__getattribute__(value, "_target")
        if isinstance(value, list):
            return [self.unwrap(v) for v in value]
        if callable(value) and not isinstance(value, type):
            return self._handler_for(value)
        return value

    def _handler_for(self, callback: Callable[..., Any]) -> Callable[..., Any]:
        """The loop-side twin of a sync callback; the same callback always maps to the same handler, so that
        `remove_listener` finds the one `on` registered."""
        try:
            return self._handlers[callback]
        except (KeyError, TypeError):
            pass

        # Playwright passes a handler as many arguments as its signature takes (a route handler gets the request
        # too when it asks), so the twin forwards only what the callback accepts.
        accepts = _positional_arity(callback)

        async def handler(*args: Any) -> Any:
            if self.cancelled.is_set():
                return None
            wrapped = [self.wrap(a) for a in (args if accepts is None else args[:accepts])]
            return await self.loop.run_in_executor(None, lambda: callback(*wrapped))

        try:
            self._handlers[callback] = handler
        except TypeError:
            pass
        return handler


class _Proxy:
    """A sync-looking stand-in for one async Playwright object."""

    __slots__ = ("_target", "_bridge")

    def __init__(self, target: Any, bridge: _Bridge) -> None:
        object.__setattr__(self, "_target", target)
        object.__setattr__(self, "_bridge", bridge)

    def __getattr__(self, name: str) -> Any:
        target = object.__getattribute__(self, "_target")
        bridge = object.__getattribute__(self, "_bridge")
        value = getattr(target, name)
        if inspect.ismethod(value) or inspect.isfunction(value) or inspect.iscoroutinefunction(value):
            return lambda *args, **kwargs: bridge.call(value, args, kwargs)
        return bridge.wrap(value)

    def __setattr__(self, name: str, value: Any) -> None:
        setattr(object.__getattribute__(self, "_target"), name, value)

    def __eq__(self, other: Any) -> bool:
        mine = object.__getattribute__(self, "_target")
        theirs = object.__getattribute__(other, "_target") if isinstance(other, _Proxy) else other
        return mine == theirs

    def __hash__(self) -> int:
        return hash(object.__getattribute__(self, "_target"))

    def __repr__(self) -> str:
        return f"<sync view of {object.__getattribute__(self, '_target')!r}>"


async def _on_worker(fn: Callable[..., Any], page: Any, *args: Any, **kwargs: Any) -> Any:
    if not is_async_page(page):
        raise TypeError(
            "AsyncPageSolver drives an async page and was given a synchronous one; use PageSolver for "
            "playwright.sync_api pages."
        )
    loop = asyncio.get_running_loop()
    bridge = _Bridge(loop)
    task = loop.run_in_executor(None, lambda: fn(bridge.wrap(page), *args, **kwargs))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        bridge.cancelled.set()
        try:
            await task
        except BaseException:
            pass
        raise


class AsyncPageSolver:
    """`PageSolver`, awaited. Takes the same arguments; each method takes an async page."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self._solver = PageSolver(*args, **kwargs)
        # One solve at a time per solver, as with PageSolver: its per-solve state lives on the instance.
        self._lock = asyncio.Lock()

    @property
    def config(self) -> Any:
        return self._solver.config

    async def _run(self, method: str, page: Any, *args: Any, **kwargs: Any) -> Any:
        async with self._lock:
            return await _on_worker(getattr(self._solver, method), page, *args, **kwargs)

    async def solve(self, page: Any) -> SolveResult:
        return await self._run("solve", page)

    async def capture(self, page: Any, *args: Any, **kwargs: Any) -> Any:
        return await self._run("capture", page, *args, **kwargs)

    async def detect_captcha(self, page: Any) -> Any:
        return await self._run("detect_captcha", page)

    async def is_captcha_solved(self, page: Any, *args: Any, **kwargs: Any) -> bool:
        return await self._run("is_captcha_solved", page, *args, **kwargs)

    async def has_interactive_widget_in_dom(self, page: Any) -> bool:
        return await self._run("has_interactive_widget_in_dom", page)

    async def vendors_on_the_wire(self, page: Any) -> Any:
        return await self._run("vendors_on_the_wire", page)

    def watch(self, page: Any, **options: Any) -> "AsyncCaptchaWatcher":
        """A watcher over `page`; `await .run()` polls until stopped, `await .poll_once()` checks once."""
        return AsyncCaptchaWatcher(self, page, **options)


class AsyncCaptchaWatcher:
    """`CaptchaWatcher` for an async page. `on_solved` / `on_error` may be plain functions or coroutine functions;
    either way they run on the caller's loop."""

    def __init__(self, solver: AsyncPageSolver, page: Any, on_solved: Optional[Callable[[Any], Any]] = None,
                 on_error: Optional[Callable[[BaseException], Any]] = None, **options: Any) -> None:
        self._solver = solver
        self._page = page
        self._options = options
        self._on_solved = on_solved
        self._on_error = on_error
        self._watcher: Optional[CaptchaWatcher] = None
        self._stopped = False
        self._solves = 0

    @property
    def solves(self) -> int:
        return self._watcher.solves if self._watcher is not None else self._solves

    def stop(self) -> None:
        self._stopped = True
        if self._watcher is not None:
            self._watcher.stop()

    def _report_on_loop(self, loop: asyncio.AbstractEventLoop, callback: Optional[Callable[[Any], Any]]):
        if callback is None:
            return None

        def report(value: Any) -> None:
            async def on_loop() -> None:
                out = callback(value)
                if inspect.isawaitable(out):
                    await out

            asyncio.run_coroutine_threadsafe(on_loop(), loop).result()

        return report

    async def _drive(self, method: str, *args: Any) -> Any:
        loop = asyncio.get_running_loop()

        def on_worker(page: Any) -> Any:
            if self._watcher is None:
                self._watcher = CaptchaWatcher(
                    solver=self._solver._solver, page=page, on_solved=self._report_on_loop(loop, self._on_solved),
                    on_error=self._report_on_loop(loop, self._on_error), **self._options)
            else:
                self._watcher.page = page
            if self._stopped:
                self._watcher.stop()
            return getattr(self._watcher, method)(*args)

        async with self._solver._lock:
            return await _on_worker(on_worker, self._page)

    async def run(self, timeout_ms: Optional[int] = None) -> int:
        return await self._drive("run", timeout_ms)

    async def poll_once(self) -> Optional[Any]:
        return await self._drive("poll_once")


async def solve_captcha_on_page_async(page: Any, **kwargs: Any) -> SolveResult:
    return await AsyncPageSolver(**kwargs).solve(page)
