"""How the driver moves: one pluggable object per input device. Mirrors js/src/humanize.ts.

Humanisation is an interface, not a dial: composing ours with camoufox's own juggler measured
82.1s against 13.4s on one GeeTest v4 slider, and a mousemove at a touch widget is the wrong
event type, not weak mimicry. The pointer position lives here, not in the solver, because a
touch mode that dispatches no motion between taps still has to say where the next gesture starts.
"""

from __future__ import annotations

import os
import random
import time
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from cursory import generate_trajectory

from .kinds import HumanizationMode, PauseKind

Point = Tuple[float, float]

# Each device supplies its own table. An unknown kind yields no wait rather than raising, so adding
# a pause site cannot break a custom humanizer written against an older release.
PAUSE_KINDS = tuple(PauseKind)
# How often a held press looks at the widget, in ms: a frame hash per look, so not every frame.
HOLD_POLL_MS = (180.0, 320.0)


def _delay(ms: float) -> None:
    if ms > 0:
        time.sleep(ms / 1000.0)


def _log(message: str) -> None:
    print(f"[captchakraken] {message}", flush=True)


def _same_point(a: Point, b: Point) -> bool:
    """`click` travels then clicks at the landing point; without this every click dispatched one redundant move."""
    return abs(float(a[0]) - float(b[0])) < 1e-6 and abs(float(a[1]) - float(b[1])) < 1e-6


def trajectory(start: Point, end: Point, frequency: int = 60) -> Tuple[List[Point], List[float]]:
    """A recorded human movement morphed onto the endpoints; timings are cumulative ms."""
    points, timings = generate_trajectory(start, end, frequency=frequency)
    return [(float(x), float(y)) for x, y in points], [float(t) for t in timings]


class Humanizer:
    """The gesture vocabulary the driver speaks. Subclass or duck-type."""

    name = "custom"
    hovers = False
    PAUSES: Dict[PauseKind, Tuple[float, float]] = {}

    def __init__(self, start: Point = (0.0, 0.0)) -> None:
        self.at: Point = (float(start[0]), float(start[1]))

    def reset(self, page: Any) -> None:
        pass

    def move(self, page: Any, to: Point) -> None:
        raise NotImplementedError

    def drift(self, page: Any, to: Point) -> None:
        """A held hand's pixel of wander. `move` is a reach, and a reach overshoots: on a 1px move it wandered up to
        34px, off a thin bar, which the widget takes for a release."""
        self.move(page, to)

    def press(self, page: Any) -> None:
        raise NotImplementedError

    def release(self, page: Any) -> None:
        raise NotImplementedError

    def type_text(self, page: Any, field: Any, text: str) -> bool:
        raise NotImplementedError

    def _pause_ms(self, kind: PauseKind) -> float:
        lo, hi = self.PAUSES.get(kind, (0.0, 0.0))
        return random.uniform(lo, hi)

    def pause(self, kind: PauseKind) -> None:
        _delay(self._pause_ms(kind))

    def click(self, page: Any, to: Point) -> None:
        self.move(page, to)
        self.press(page)
        self.pause(PauseKind.TAP)
        self.release(page)

    def drag(self, page: Any, src: Point, dst: Point) -> None:
        self.move(page, src)
        self.press(page)
        self.pause(PauseKind.GRAB)
        self.move(page, dst)
        self.pause(PauseKind.DROP)
        self.release(page)


def hold(human: "Humanizer", page: Any, to: Point, done: Callable[[], bool], max_ms: float) -> bool:
    """Press at `to` until `done()` says the widget completed, or `max_ms` passes; True when it completed.

    Built on move/press/release so any humanizer can hold. The hand drifts a pixel or so meanwhile, because a
    press that does not move for seconds is a synthetic one, and the button is released whatever `done` raises.
    """
    human.move(page, to)
    anchor = human.at
    human.press(page)
    t0 = time.monotonic()
    try:
        while True:
            _delay(random.uniform(*HOLD_POLL_MS))
            try:
                getattr(human, "drift", human.move)(page, (anchor[0] + random.gauss(0.0, 0.8),
                                                         anchor[1] + random.gauss(0.0, 0.8)))
            except Exception:
                pass
            if done():
                return True
            if (time.monotonic() - t0) * 1000.0 >= max_ms:
                return False
    finally:
        human.release(page)


class MouseHumanizer(Humanizer):
    name = HumanizationMode.MOUSE
    hovers = True
    PAUSES = {PauseKind.TAP: (20.0, 50.0), PauseKind.BETWEEN: (80.0, 160.0), PauseKind.GRAB: (50.0, 100.0),
              PauseKind.DROP: (50.0, 100.0), PauseKind.PROBE: (40.0, 80.0), PauseKind.SETTLE: (90.0, 210.0),
              PauseKind.KEY: (45.0, 135.0)}

    def __init__(self, start: Point = (0.0, 0.0), frequency: int = 60) -> None:
        super().__init__(start)
        self._frequency = frequency
        self._viewport_cache: Optional[Dict[str, float]] = None
        self._down = False
        self._cursor_seeded = False

    def reset(self, page: Any) -> None:
        self._viewport_cache = None
        self._cursor_seeded = False
        self._down = False

    def _viewport(self, page: Any) -> Optional[Dict[str, float]]:
        """The window to keep the cursor inside; None under camoufox, which reports no viewport."""
        if self._viewport_cache is None:
            for read in (lambda: page.viewport_size() if callable(page.viewport_size) else page.viewport_size,
                         lambda: page.evaluate("() => ({width: window.innerWidth, height: window.innerHeight})")):
                try:
                    vp = read()
                    if vp and vp.get("width") and vp.get("height"):
                        self._viewport_cache = {"width": float(vp["width"]), "height": float(vp["height"])}
                        break
                except Exception:
                    continue
        return self._viewport_cache

    def _seed_cursor(self, page: Any) -> None:
        """One plain move off the (0, 0) origin per solve: a trajectory from the corner wedges camoufox."""
        if self._cursor_seeded:
            return
        self._cursor_seeded = True
        if self.at != (0.0, 0.0):
            cx, cy = self.at
        else:
            vp = self._viewport(page)
            cx, cy = (vp["width"] / 2, vp["height"] / 2) if vp else (200.0, 200.0)
        try:
            page.mouse.move(cx, cy)
            self.at = (cx, cy)
        except Exception:
            pass

    def move(self, page: Any, to: Point) -> None:
        self._seed_cursor(page)
        if _same_point(self.at, to):
            return
        points, timings = trajectory(self.at, to, self._frequency)
        self._trace(page, points, timings)

    def drift(self, page: Any, to: Point) -> None:
        self._trace(page, [to], [0.0])

    def _trace(self, page: Any, points: Sequence[Point], timings: Sequence[float]) -> None:
        # Clamp only when the viewport is known: a guessed edge coordinate deadlocks camoufox's juggler.
        viewport = self._viewport(page)
        start = time.monotonic() * 1000.0
        for (x, y), t in zip(points, timings):
            x, y = float(x), float(y)
            if viewport is not None:
                x = max(1.0, min(x, viewport["width"] - 1.0))
                y = max(1.0, min(y, viewport["height"] - 1.0))
            try:
                page.mouse.move(x, y)
            except Exception as exc:
                if "Target closed" in str(exc) or "Session closed" in str(exc):
                    _log("could not move mouse; page or session closed")
                    return
                continue
            self.at = (x, y)
            _delay(start + t - time.monotonic() * 1000.0)

    def press(self, page: Any) -> None:
        page.mouse.down()
        self._down = True

    def release(self, page: Any) -> None:
        page.mouse.up()
        self._down = False

    def type_text(self, page: Any, field: Any, text: str) -> bool:
        # Clear first: a retry round arrives with the previous attempt still in the box, and typing would append.
        try:
            page.keyboard.press("Control+A")
        except Exception:
            pass
        # Per character, not `type(text, delay=…)`: a constant inter-key delay is itself a signal these vendors score.
        for ch in text:
            try:
                page.keyboard.type(ch)
            except Exception as exc:
                _log(f"could not type into the captcha field: {exc}")
                return False
            self.pause(PauseKind.KEY)
        return True


class TouchBackend:
    """Where touch events go. `move` takes a whole leg of `(x, y, dt_ms)` samples."""

    name = "touch"

    def down(self, x: float, y: float) -> None:
        raise NotImplementedError

    def move(self, path: Sequence[Tuple[float, float, float]]) -> None:
        raise NotImplementedError

    def up(self, x: float, y: float) -> None:
        raise NotImplementedError


class CdpTouchBackend(TouchBackend):
    """`Input.dispatchTouchEvent` over CDP; Chromium-family pages launched with has_touch=True.

    Checked at construction, not per gesture: WebKit and Firefox expose no touch dispatch, and emitting mouse
    events at a touch widget instead is worse than not running (the report reads as a model that cannot solve mobile).
    """

    name = "cdp"

    def __init__(self, page: Any) -> None:
        try:
            context = page.context() if callable(page.context) else page.context
            self._session = context.new_cdp_session(page)
        except Exception as exc:
            raise RuntimeError(
                f"mobile humanisation needs touch dispatch, and this page offers none ({exc}). Use a "
                "Chromium-family Playwright browser launched with has_touch=True, or pass an Appium "
                "driver as PageSolverConfig.touch_driver.") from exc

    def _send(self, kind: str, points: Sequence[Tuple[float, float]]) -> None:
        # radius and force are what a real digitizer reports; a synthetic tap reports zero.
        self._session.send("Input.dispatchTouchEvent", {"type": kind, "touchPoints": [
            {"x": float(x), "y": float(y), "radiusX": random.uniform(8.0, 14.0),
             "radiusY": random.uniform(8.0, 14.0), "force": random.uniform(0.35, 0.75), "id": 1}
            for x, y in points]})

    def down(self, x: float, y: float) -> None:
        self._send("touchStart", [(x, y)])

    def move(self, path: Sequence[Tuple[float, float, float]]) -> None:
        for x, y, dt_ms in path:
            _delay(dt_ms)
            self._send("touchMove", [(x, y)])

    def up(self, x: float, y: float) -> None:
        self._send("touchEnd", [])


class AppiumTouchBackend(TouchBackend):
    """W3C touch pointer actions for Appium and Selenium, paced by the device from one chain per leg.

    Press and release are separate `perform` calls on purpose: W3C input state is per session, which is what
    lets the slider press, screenshot, steer, screenshot and only then release. Raw protocol payload, so no client import.
    """

    name = "appium"

    def __init__(self, driver: Any, scale: Optional[float] = None, origin: Optional[Point] = None,
                 page: Any = None) -> None:
        self._driver = driver
        self._scale_given = scale is not None
        self._scale = 1.0 if scale is None else float(scale)
        self._origin = (0.0, 0.0) if origin is None else (float(origin[0]), float(origin[1]))
        self._page = page
        self._checked = False

    def _check_scale(self) -> None:
        """Refuse an unset scale on a device whose pixel ratio is not 1: the finger would land elsewhere, silently.

        Read once, not per gesture (a solve makes hundreds); an unreadable ratio is absent evidence, so identity.
        """
        self._checked = True
        if self._scale_given or self._page is None or not hasattr(self._page, "evaluate"):
            return
        try:
            dpr = float(self._page.evaluate("() => window.devicePixelRatio"))
        except Exception:
            return
        if abs(dpr - 1.0) < 1e-6:
            return
        raise RuntimeError(
            f"the touch driver maps CSS pixels onto a device reporting devicePixelRatio {dpr:g}, and no "
            f"scale was given. Fix: touch_transform={{'scale': {dpr:g}, 'origin': (x, y)}}, where origin "
            "is the webview's top-left in SCREEN coordinates, or pass scale=1 to assert the coordinates "
            "are already mapped.")

    def _map(self, x: float, y: float) -> Tuple[int, int]:
        # Unset scale and an explicit 1.0 are different facts; only the first is checked.
        if not self._checked:
            self._check_scale()
        return int(round(self._origin[0] + x * self._scale)), int(round(self._origin[1] + y * self._scale))

    def _perform(self, actions: Sequence[Dict[str, Any]]) -> None:
        chain = [{"type": "pointer", "id": "ck-finger", "parameters": {"pointerType": "touch"},
                  "actions": list(actions)}]
        if callable(getattr(self._driver, "execute_actions", None)):
            self._driver.execute_actions(chain)
        elif callable(getattr(self._driver, "execute", None)):
            self._driver.execute("actions", {"actions": chain})
        else:
            raise RuntimeError("the touch driver speaks neither execute_actions() nor execute('actions', …); "
                               "pass a WebDriver-compatible driver or a custom TouchBackend.")

    def down(self, x: float, y: float) -> None:
        mx, my = self._map(x, y)
        self._perform([{"type": "pointerMove", "duration": 0, "origin": "viewport", "x": mx, "y": my},
                       {"type": "pointerDown", "button": 0}])

    def move(self, path: Sequence[Tuple[float, float, float]]) -> None:
        # The per-sample gap becomes the move's duration, so the device interpolates like a real finger.
        actions = []
        for x, y, dt_ms in path:
            mx, my = self._map(x, y)
            actions.append({"type": "pointerMove", "duration": max(0, int(round(dt_ms))),
                            "origin": "viewport", "x": mx, "y": my})
        if actions:
            self._perform(actions)

    def up(self, x: float, y: float) -> None:
        if not self._checked:
            self._check_scale()
        self._perform([{"type": "pointerUp", "button": 0}])


class TouchscreenTouchBackend(TouchBackend):
    """Playwright's tap-only touchscreen, for browsers with touch but no CDP. A drag cannot be expressed."""

    name = "touchscreen"

    def __init__(self, page: Any) -> None:
        self._page = page
        self._pending: Optional[Point] = None

    def down(self, x: float, y: float) -> None:
        self._pending = (x, y)

    def move(self, path: Sequence[Tuple[float, float, float]]) -> None:
        raise RuntimeError("this browser exposes taps but not touch travel, so a drag/slide puzzle cannot be "
                           "driven on it. Use a Chromium-family browser (CDP touch dispatch) or an Appium driver.")

    def up(self, x: float, y: float) -> None:
        at = self._pending or (x, y)
        self._pending = None
        self._page.touchscreen.tap(float(at[0]), float(at[1]))


def touch_backend_for(page: Any, driver: Any = None, **kwargs: Any) -> TouchBackend:
    if driver is not None:
        return driver if isinstance(driver, TouchBackend) else AppiumTouchBackend(driver, page=page, **kwargs)
    try:
        return CdpTouchBackend(page)
    except RuntimeError:
        if hasattr(page, "touchscreen"):
            _log("no CDP session; falling back to tap-only touch dispatch")
            return TouchscreenTouchBackend(page)
        raise


class MobileHumanizer(Humanizer):
    """A finger on glass: no hover, touch events only, slower and more variable pauses."""

    name = HumanizationMode.MOBILE
    hovers = False
    # Tap: measured human touch dwell clusters at 60-120ms. Key: a soft keyboard is ~3x slower than a physical one.
    PAUSES = {PauseKind.TAP: (55.0, 130.0), PauseKind.BETWEEN: (140.0, 320.0), PauseKind.GRAB: (90.0, 190.0),
              PauseKind.DROP: (80.0, 170.0), PauseKind.PROBE: (70.0, 140.0), PauseKind.SETTLE: (140.0, 300.0),
              PauseKind.KEY: (110.0, 320.0)}

    def __init__(self, start: Point = (0.0, 0.0), backend: Any = None, driver: Any = None,
                 frequency: int = 90, **backend_kwargs: Any) -> None:
        super().__init__(start)
        self._backend: Optional[TouchBackend] = backend
        self._driver = driver
        self._backend_kwargs = backend_kwargs
        self._frequency = frequency
        self._down = False

    def reset(self, page: Any) -> None:
        # A solve that timed out mid-gesture leaves a pointer down in the session's input state; lift it.
        if self._down:
            try:
                self._touch(page).up(*self.at)
            except Exception:
                pass
            self._down = False

    def _touch(self, page: Any) -> TouchBackend:
        if self._backend is None:
            self._backend = touch_backend_for(page, self._driver, **self._backend_kwargs)
        return self._backend

    def move(self, page: Any, to: Point) -> None:
        to = (float(to[0]), float(to[1]))
        if self._down:
            points, timings = trajectory(self.at, to, self._frequency)
            self._touch(page).move([(x, y, timings[i] - (timings[i - 1] if i else 0.0))
                                    for i, (x, y) in enumerate(points)])
        self.at = to

    def drift(self, page: Any, to: Point) -> None:
        to = (float(to[0]), float(to[1]))
        if self._down:
            self._touch(page).move([(to[0], to[1], 0.0)])
        self.at = to

    def press(self, page: Any) -> None:
        self._touch(page).down(*self.at)
        self._down = True

    def release(self, page: Any) -> None:
        self._touch(page).up(*self.at)
        self._down = False

    def click(self, page: Any, to: Point) -> None:
        """A tap whose contact patch wobbles a pixel while held; a motionless tap is a synthetic one."""
        self.move(page, to)
        self.press(page)
        held = self._pause_ms(PauseKind.TAP)
        _delay(held * 0.5)
        try:
            self._touch(page).move([(self.at[0] + random.gauss(0.0, 0.9), self.at[1] + random.gauss(0.0, 0.9), 0.0)])
        except Exception:
            pass
        _delay(held * 0.5)
        self.release(page)

    def type_text(self, page: Any, field: Any, text: str) -> bool:
        # Cleared through the element: there is no Control key on a phone, and no `page.keyboard` on Appium.
        for clear, arg in (("clear", ()), ("fill", ("",))):
            fn = getattr(field, clear, None)
            if fn is not None:
                try:
                    fn(*arg)
                    break
                except Exception:
                    continue
        send = getattr(field, "send_keys", None)
        for ch in text:
            try:
                send(ch) if send is not None else page.keyboard.type(ch)
            except Exception as exc:
                _log(f"could not type into the captcha field: {exc}")
                return False
            self.pause(PauseKind.KEY)
        return True


class NullHumanizer(Humanizer):
    """No humanisation: one move per gesture and a single fill. Fast, and detectable.

    Still moves and presses: a click dispatched with no preceding move fails on vendors that need a hover state first.
    """

    name = HumanizationMode.NONE
    hovers = False

    def move(self, page: Any, to: Point) -> None:
        if _same_point(self.at, to):
            return
        self.at = (float(to[0]), float(to[1]))
        try:
            page.mouse.move(*self.at)
        except Exception as exc:
            if "Target closed" in str(exc) or "Session closed" in str(exc):
                _log("could not move mouse; page or session closed")

    def press(self, page: Any) -> None:
        page.mouse.down()

    def release(self, page: Any) -> None:
        page.mouse.up()

    def type_text(self, page: Any, field: Any, text: str) -> bool:
        try:
            field.fill(text)
            return True
        except Exception:
            pass
        try:
            page.keyboard.press("Control+A")
        except Exception:
            pass
        try:
            page.keyboard.type(text)
            return True
        except Exception as exc:
            _log(f"could not type into the captcha field: {exc}")
            return False


MODES = {HumanizationMode.MOUSE: MouseHumanizer, HumanizationMode.MOBILE: MobileHumanizer,
         HumanizationMode.NONE: NullHumanizer}


def resolve(config: Any) -> Humanizer:
    """`config.humanizer`, else `config.humanization`, else CAPTCHA_HUMANIZATION, else mouse.

    The env var loses to code, the opposite of the model-identity settings, because the right mode is a
    property of the page: an env var flipping a desktop solve to touch dispatch would break every one silently.
    """
    custom = getattr(config, "humanizer", None)
    if custom is not None:
        return custom
    raw = str(getattr(config, "humanization", None) or os.getenv("CAPTCHA_HUMANIZATION") or "mouse").strip().lower()
    try:
        mode = HumanizationMode(raw)
    except ValueError:
        raise ValueError(f"unknown humanization mode {raw!r}; expected one of {', '.join(sorted(MODES))}, "
                         "or pass your own object as PageSolverConfig.humanizer") from None
    start = getattr(config, "starting_mouse_position", None) or (0.0, 0.0)
    if mode is HumanizationMode.MOBILE:
        return MobileHumanizer(start, driver=getattr(config, "touch_driver", None),
                               **(getattr(config, "touch_transform", None) or {}))
    return MODES[mode](start)
