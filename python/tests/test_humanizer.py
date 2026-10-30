"""Humanisation is a pluggable input device, not a realism dial: mobile must never touch `page.mouse`, the Appium
payload is the W3C one built by hand (no Selenium import), and the measured mouse mode did not change.
"""

from __future__ import annotations

import random
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from captchakraken import humanize
from captchakraken.humanize import (
    AppiumTouchBackend,
    MobileHumanizer,
    MouseHumanizer,
    NullHumanizer,
    PAUSE_KINDS,
    TouchBackend,
    resolve,
)
from captchakraken.page_solver import PageSolverConfig


@pytest.fixture(autouse=True)
def _no_sleeping(monkeypatch):
    monkeypatch.setattr(humanize, "_delay", lambda ms: None)


class RecordingMouse:
    def __init__(self) -> None:
        self.events: List[Any] = []

    def move(self, x: float, y: float) -> None:
        self.events.append(("move", x, y))

    def down(self) -> None:
        self.events.append(("down",))

    def up(self) -> None:
        self.events.append(("up",))


class RecordingPage:
    def __init__(self) -> None:
        self.mouse = RecordingMouse()
        self.viewport_size = {"width": 800, "height": 600}


class SlowMouse(RecordingMouse):
    """A browser that answers each move after `latency_s`, plus `path_s` when the move goes anywhere."""

    def __init__(self, latency_s: float, path_s: float) -> None:
        super().__init__()
        self.latency_s, self.path_s, self.last = latency_s, path_s, None

    def move(self, x: float, y: float) -> None:
        travels = self.last != (x, y)
        self.last = (x, y)
        time.sleep(self.latency_s + (self.path_s if travels else 0.0))
        super().move(x, y)


class RecordingTouch(TouchBackend):
    name = "recording"

    def __init__(self) -> None:
        self.events: List[Any] = []

    def down(self, x: float, y: float) -> None:
        self.events.append(("down", x, y))

    def move(self, path) -> None:
        self.events.append(("move", len(path)))

    def up(self, x: float, y: float) -> None:
        self.events.append(("up", x, y))

    @property
    def kinds(self) -> List[str]:
        return [e[0] for e in self.events]


class RatioPage(RecordingPage):

    def __init__(self, dpr: Optional[float] = 1.0) -> None:
        super().__init__()
        self._dpr = dpr

    def evaluate(self, expression: str) -> Any:
        assert "devicePixelRatio" in expression
        if self._dpr is None:
            raise RuntimeError("no execution context")
        return self._dpr


class RecordingDriver:

    def __init__(self) -> None:
        self.chains: List[Any] = []

    def execute(self, command: str, params: Dict[str, Any]) -> None:
        assert command == "actions"
        self.chains.append(params["actions"])


class TestResolve:
    def test_an_explicit_object_wins_over_everything(self, monkeypatch):
        monkeypatch.setenv("CAPTCHA_HUMANIZATION", "mobile")
        mine = NullHumanizer()
        cfg = PageSolverConfig(humanization="mouse", humanizer=mine)
        assert resolve(cfg) is mine

    def test_code_beats_the_environment(self, monkeypatch):
        """Deliberate, and the opposite of the model-identity vars: which mode is right is a property of the page."""
        monkeypatch.setenv("CAPTCHA_HUMANIZATION", "mobile")
        assert resolve(PageSolverConfig(humanization="none")).name == "none"

    def test_the_environment_is_read_when_the_code_says_nothing(self, monkeypatch):
        monkeypatch.setenv("CAPTCHA_HUMANIZATION", "mobile")
        assert resolve(PageSolverConfig()).name == "mobile"

    def test_the_default_is_the_historical_behaviour(self, monkeypatch):
        monkeypatch.delenv("CAPTCHA_HUMANIZATION", raising=False)
        assert resolve(PageSolverConfig()).name == "mouse"

    def test_a_typo_names_the_alternatives(self, monkeypatch):
        monkeypatch.delenv("CAPTCHA_HUMANIZATION", raising=False)
        with pytest.raises(ValueError) as exc:
            resolve(PageSolverConfig(humanization="touch"))
        assert "mobile" in str(exc.value) and "humanizer" in str(exc.value)

    def test_the_starting_position_is_honoured(self, monkeypatch):
        monkeypatch.delenv("CAPTCHA_HUMANIZATION", raising=False)
        assert resolve(PageSolverConfig(starting_mouse_position=(30.0, 40.0))).at == (30.0, 40.0)

    def test_every_mode_answers_the_whole_pause_vocabulary(self, monkeypatch):
        """An unknown kind yields no wait rather than raising, so a pause site added later cannot break an older custom humanizer."""
        for mode in (MouseHumanizer(), MobileHumanizer(), NullHumanizer()):
            for kind in PAUSE_KINDS + ("a-kind-added-next-year",):
                assert mode._pause_ms(kind) >= 0.0


class TestMouse:
    def test_a_click_is_a_trajectory_then_a_press(self):
        page, human = RecordingPage(), MouseHumanizer(start=(10.0, 10.0))
        human.click(page, (400.0, 300.0))
        kinds = [e[0] for e in page.mouse.events]
        assert kinds[-2:] == ["down", "up"]
        assert kinds.count("move") > 5
        assert human.at == (400.0, 300.0)

    def test_it_still_hovers(self):
        assert MouseHumanizer().hovers is True


class TestMobile:
    def _human(self):
        backend = RecordingTouch()
        return MobileHumanizer(backend=backend), backend

    def test_a_move_with_no_finger_down_dispatches_nothing(self):
        human, backend = self._human()
        human.move(RecordingPage(), (300.0, 200.0))
        assert backend.events == []
        assert human.at == (300.0, 200.0)

    def test_a_tap_wobbles_between_touchstart_and_touchend(self):
        human, backend = self._human()
        human.click(RecordingPage(), (120.0, 90.0))
        assert backend.kinds == ["down", "move", "up"]
        assert backend.events[0][1:] == (120.0, 90.0)

    def test_a_drag_travels_while_touching(self):
        human, backend = self._human()
        human.drag(RecordingPage(), (10.0, 10.0), (300.0, 140.0))
        assert backend.kinds == ["down", "move", "up"]
        assert backend.events[1][1] > 5
        assert human.at == (300.0, 140.0)

    def test_it_never_touches_the_mouse(self):
        page, (human, _) = RecordingPage(), self._human()
        human.click(page, (50.0, 50.0))
        human.drag(page, (50.0, 50.0), (200.0, 200.0))
        assert page.mouse.events == []

    def test_it_does_not_hover(self):
        assert MobileHumanizer().hovers is False

    def test_reset_lifts_a_finger_a_previous_solve_left_down(self):
        """W3C input state is per session: a solve that timed out inside the slider leaves the pointer down."""
        human, backend = self._human()
        human.press(RecordingPage())
        backend.events.clear()
        human.reset(RecordingPage())
        assert backend.kinds == ["up"]
        human.reset(RecordingPage())
        assert backend.kinds == ["up"]

    def test_typing_clears_through_the_element_not_control_a(self):
        class Field:
            def __init__(self) -> None:
                self.cleared = 0
                self.keys: List[str] = []

            def clear(self) -> None:
                self.cleared += 1

            def send_keys(self, ch: str) -> None:
                self.keys.append(ch)

        human, _ = self._human()
        field = Field()
        assert human.type_text(RecordingPage(), field, "ab7") is True
        assert field.cleared == 1 and field.keys == ["a", "b", "7"]


class TestNone:
    def test_one_move_per_gesture_and_no_dwell(self):
        page, human = RecordingPage(), NullHumanizer(start=(10.0, 10.0))
        human.click(page, (400.0, 300.0))
        assert page.mouse.events == [("move", 400.0, 300.0), ("down",), ("up",)]

    def test_typing_is_one_fill(self):
        class Field:
            def __init__(self) -> None:
                self.value: Optional[str] = None

            def fill(self, text: str) -> None:
                self.value = text

        field = Field()
        assert NullHumanizer().type_text(RecordingPage(), field, "xyz") is True
        assert field.value == "xyz"


class TestAppiumBackend:
    def test_the_chain_is_a_w3c_touch_pointer(self):
        driver = RecordingDriver()
        AppiumTouchBackend(driver).down(12.0, 34.0)
        (pointer,) = driver.chains[0]
        assert pointer["type"] == "pointer"
        assert pointer["parameters"] == {"pointerType": "touch"}
        assert [a["type"] for a in pointer["actions"]] == ["pointerMove", "pointerDown"]
        assert (pointer["actions"][0]["x"], pointer["actions"][0]["y"]) == (12, 34)
        assert pointer["actions"][0]["origin"] == "viewport"

    def test_a_leg_is_one_chain_with_per_sample_durations(self):
        driver = RecordingDriver()
        AppiumTouchBackend(driver).move([(1.0, 2.0, 11.0), (3.0, 4.0, 12.6)])
        assert len(driver.chains) == 1
        actions = driver.chains[0][0]["actions"]
        assert [a["duration"] for a in actions] == [11, 13]

    def test_press_and_release_are_separate_performs(self):
        """Per-session input state is what lets the slider press, screenshot, steer, screenshot and only then release."""
        driver = RecordingDriver()
        backend = AppiumTouchBackend(driver)
        backend.down(0.0, 0.0)
        backend.move([(5.0, 5.0, 8.0)])
        backend.up(5.0, 5.0)
        assert len(driver.chains) == 3
        assert driver.chains[-1][0]["actions"] == [{"type": "pointerUp", "button": 0}]

    def test_css_pixels_are_mapped_onto_the_device(self):
        driver = RecordingDriver()
        AppiumTouchBackend(driver, scale=3.0, origin=(0.0, 132.0)).down(10.0, 20.0)
        move = driver.chains[0][0]["actions"][0]
        assert (move["x"], move["y"]) == (30, 192)

    def test_a_driver_that_speaks_neither_call_says_so(self):
        with pytest.raises(RuntimeError) as exc:
            AppiumTouchBackend(object()).down(0.0, 0.0)
        assert "execute" in str(exc.value)


class TestAppiumScaleIsNotGuessed:
    """A wrong scale fails silently on both sides of the wire and looks exactly like a model that cannot read the puzzle."""

    def test_a_hidpi_session_with_no_transform_refuses(self):
        driver = RecordingDriver()
        backend = AppiumTouchBackend(driver, page=RatioPage(3.0))
        with pytest.raises(RuntimeError) as exc:
            backend.down(10.0, 20.0)
        message = str(exc.value)
        assert "devicePixelRatio 3" in message and "scale" in message
        assert "origin" in message
        assert not driver.chains

    def test_an_explicit_scale_is_taken_as_the_callers_word(self):
        driver = RecordingDriver()
        AppiumTouchBackend(driver, scale=1.0, page=RatioPage(3.0)).down(10.0, 20.0)
        move = driver.chains[0][0]["actions"][0]
        assert (move["x"], move["y"]) == (10, 20)

    def test_a_1x_session_needs_no_transform(self):
        driver = RecordingDriver()
        AppiumTouchBackend(driver, page=RatioPage(1.0)).down(10.0, 20.0)
        assert driver.chains

    def test_a_page_that_cannot_be_asked_is_not_refused(self):
        driver = RecordingDriver()
        AppiumTouchBackend(driver, page=RatioPage(None)).down(10.0, 20.0)
        assert driver.chains

    def test_no_page_at_all_is_not_refused(self):
        driver = RecordingDriver()
        AppiumTouchBackend(driver).down(10.0, 20.0)
        assert driver.chains

    def test_the_ratio_is_read_once_not_per_gesture(self):
        page = RatioPage(1.0)
        reads = []
        original = page.evaluate
        page.evaluate = lambda e: (reads.append(e), original(e))[1]
        backend = AppiumTouchBackend(RecordingDriver(), page=page)
        backend.down(1.0, 1.0)
        backend.move([(2.0, 2.0, 5.0)])
        backend.up(2.0, 2.0)
        assert len(reads) == 1

    def test_the_factory_hands_the_backend_its_page(self):
        backend = humanize.touch_backend_for(RatioPage(3.0), RecordingDriver())
        with pytest.raises(RuntimeError):
            backend.down(0.0, 0.0)


def test_a_browser_that_draws_its_own_path_gets_one_move_per_gesture():
    """camoufox's humanize re-draws every mouse.move(); our trajectory on top of it is drawn twice."""
    page, human = RecordingPage(), MouseHumanizer(start=(10.0, 10.0))
    page.mouse = SlowMouse(0.0, 0.15)
    human.click(page, (400.0, 300.0))
    human.drag(page, (400.0, 300.0), (150.0, 120.0))

    # the solve's seed, then sync, round trip and the timed step; then one move per destination
    kinds = [e[0] for e in page.mouse.events]
    assert kinds == ["move"] * 5 + ["down", "up", "down", "move", "up"]
    assert page.mouse.events[4][1:] == (400.0, 300.0)
    assert human.at == (150.0, 120.0)


def test_a_slow_round_trip_alone_is_not_taken_for_a_browser_that_draws_its_own_path():
    page, human = RecordingPage(), MouseHumanizer(start=(10.0, 10.0))
    page.mouse = SlowMouse(0.12, 0.0)
    human.move(page, (30.0, 22.0))
    assert len(page.mouse.events) > 6, f"{len(page.mouse.events)} moves; a remote browser lost its trajectory"
