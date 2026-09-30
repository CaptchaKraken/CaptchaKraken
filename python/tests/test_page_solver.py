"""Driver semantics pinned by incidents: an invisible reCAPTCHA anchor is not "still loading"; `unsupported` after an interaction is a round transition; the Verify finder is scoped to the widget so a host form's own Submit is unreachable; camoufox reports viewport None and clamping to an exact edge deadlocks its juggler (upstream #225); the budget is checked mid-attempt after a session ran ten minutes past a 120s timeout; a slide's release is its submit."""

from __future__ import annotations

import struct
import time
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fake_dom import FakeLocator
from captchakraken.humanize import MobileHumanizer, MouseHumanizer
from captchakraken.kinds import FrameRole, Vendor
from captchakraken.page_solver import (
    Widget,
    AnimatedChallengeError,
    CaptchaSolveError,
    NoCaptchaFoundError,
    PageSolver,
    PageSolverConfig,
    UnsupportedChallengeError,
    _aggregate,
    _as_dict,
    _read_png_dimensions,
)
from captchakraken.selectors import submit_by_text
from captchakraken.solver import UnsupportedCaptchaError
from captchakraken.humanize import trajectory as generate_trajectory


class FakeElement:
    def __init__(
        self,
        src: str = "",
        visible: bool = True,
        box: Optional[Dict[str, float]] = None,
        frame: Optional["FakeFrame"] = None,
        text: str = "",
    ) -> None:
        self._src = src
        self._visible = visible
        self._box = box or {"x": 100.0, "y": 100.0, "width": 400.0, "height": 400.0}
        self._frame = frame
        self._text = text
        self.screenshots = 0

    def get_attribute(self, name: str) -> Optional[str]:
        return {"src": self._src, "value": None}.get(name)

    def is_visible(self) -> bool:
        return self._visible

    def bounding_box(self) -> Dict[str, float]:
        return self._box

    def content_frame(self) -> Optional["FakeFrame"]:
        return self._frame

    def text_content(self) -> str:
        return self._text

    def input_value(self) -> str:
        return ""

    def scroll_into_view_if_needed(self) -> None:
        pass

    def screenshot(self, path: str, **_: Any) -> None:
        self.screenshots += 1
        _write_png(path, 400, 400)


class FakeFrame:
    def __init__(self, elements: Optional[Dict[str, FakeElement]] = None) -> None:
        self._elements = elements or {}

    def locator(self, selector: str) -> FakeLocator:
        return FakeLocator(lambda: [el for key, el in self._elements.items() if key in selector or selector in key])

    def wait_for_selector(self, *_: Any, **__: Any) -> None:
        pass

    def wait_for_function(self, *_: Any, **__: Any) -> None:
        pass


class FakeMouse:
    def __init__(self) -> None:
        self.moves: List[tuple] = []
        self.clicks = 0
        self.presses = 0

    def move(self, x: float, y: float) -> None:
        self.moves.append((x, y))

    def down(self) -> None:
        self.presses += 1

    def up(self) -> None:
        self.clicks += 1


class FakePage:
    def __init__(self, elements: Optional[Dict[str, FakeElement]] = None) -> None:
        self._elements = elements or {}
        self.mouse = FakeMouse()
        self.viewport_size = {"width": 1280, "height": 800}

    def locator(self, selector: str) -> FakeLocator:
        # Honours one pseudo-class, `:not([src*=...])`, so the invisible-reCAPTCHA selector can be exercised.
        base, _, negated = selector.partition(':not([src*="')
        element = self._elements.get(base)
        excluded = bool(element and negated and negated.rstrip('"])') in (element.get_attribute("src") or ""))
        return FakeLocator(lambda: [element] if element and not excluded else [])

    inner_size: Optional[Dict[str, float]] = None

    def evaluate(self, *_: Any, **__: Any) -> Optional[Dict[str, float]]:
        return self.inner_size


def _write_png(path: str, width: int, height: int) -> None:
    ihdr = struct.pack(">II", width, height) + b"\x08\x02\x00\x00\x00"
    with open(path, "wb") as handle:
        handle.write(b"\x89PNG\r\n\x1a\n")
        handle.write(struct.pack(">I", 13) + b"IHDR" + ihdr + b"\x00\x00\x00\x00")


RECAPTCHA_BFRAME = 'iframe[src*="recaptcha/api2/bframe"]'
RECAPTCHA_ANCHOR = 'iframe[src*="recaptcha/api2/anchor"]'
HCAPTCHA_CHALLENGE = 'iframe[src*="hcaptcha"][src*="frame=challenge"]'
HCAPTCHA_CHECKBOX = 'iframe[src*="hcaptcha"][src*="frame=checkbox"]'


_NO_MODEL = object()


def _widget(element: FakeElement, vendor: Vendor = Vendor.UNKNOWN, role: FrameRole = FrameRole.UNKNOWN,
            at: Optional[Any] = None) -> Widget:
    return Widget(element, at if at is not None else _Scope({}), vendor, role)


def _solver(**overrides: Any) -> PageSolver:
    # No detection wait and no pause between rounds unless a test asks: both are real time.
    config = PageSolverConfig(**{"detection_timeout_ms": 0, "stale_element_backoff_ms": 0, **overrides})
    solver = PageSolver(config=config, solver=_NO_MODEL)
    solver._solver = None
    # These fakes photograph themselves; the viewport capture has its own tests.
    solver._screenshot = lambda element, path, **_: element.screenshot(path=path)
    if hasattr(solver._human, "_cursor_seeded"):
        solver._human._cursor_seeded = True
    return solver


class TestDetection:
    def test_prefers_the_open_challenge_over_the_checkbox(self):
        challenge = FakeElement(src="https://google.com/recaptcha/api2/bframe?k=x")
        anchor = FakeElement(src="https://google.com/recaptcha/api2/anchor?k=x")
        page = FakePage({RECAPTCHA_BFRAME: challenge, RECAPTCHA_ANCHOR: anchor})
        assert _solver().detect_captcha(page).element is challenge

    def test_ignores_an_already_checked_recaptcha_anchor(self):
        frame = FakeFrame({".recaptcha-checkbox-checked": FakeElement()})
        anchor = FakeElement(src="recaptcha/api2/anchor", frame=frame)
        page = FakePage({RECAPTCHA_ANCHOR: anchor})
        assert _solver().detect_captcha(page) is None

    def test_hcaptcha_checkbox_solved_via_aria_checked_without_a_token(self):
        frame = FakeFrame({'#checkbox[aria-checked="true"]': FakeElement()})
        checkbox = FakeElement(src="https://hcaptcha.com/?frame=checkbox", frame=frame)
        page = FakePage({HCAPTCHA_CHECKBOX: checkbox})
        assert _solver().detect_captcha(page) is None
        assert _solver().is_captcha_solved(page) is True

    def test_invisible_recaptcha_is_not_an_interactive_widget(self):
        anchor = FakeElement(src="https://google.com/recaptcha/api2/anchor?k=x&size=invisible")
        page = FakePage({RECAPTCHA_ANCHOR: anchor})
        assert _solver().has_interactive_widget_in_dom(page) is False

    def test_visible_v2_anchor_is_an_interactive_widget(self):
        anchor = FakeElement(src="https://google.com/recaptcha/api2/anchor?k=x")
        page = FakePage({RECAPTCHA_ANCHOR: anchor})
        assert _solver().has_interactive_widget_in_dom(page) is True


class TestSolveLoop:
    def test_no_widget_at_all_fails_fast(self):
        with pytest.raises(NoCaptchaFoundError):
            _solver().solve(FakePage())

    def test_nothing_left_after_interacting_is_success(self):
        solver = _solver()
        page = FakePage()
        solver._has_interacted_probe = True
        challenge = FakeElement(src="recaptcha/api2/bframe")
        pages = [_widget(challenge), None]

        def fake_detect(_page):
            return pages.pop(0) if pages else None

        solver.detect_captcha = fake_detect
        solver._solve_single = lambda *_: (True, [])
        solver.is_captcha_solved = lambda _page: False
        solver._is_challenge_freshly_rendered = lambda _page: False
        solver._has_recaptcha_underselect_error = lambda _page: False

        result = solver.solve(page)
        assert result.is_solved is True

    def test_no_interaction_with_captcha_still_present_gives_up_when_the_loops_are_spent(self):
        solver = _solver(post_solve_delay_ms=1)
        solver.detect_captcha = lambda _page: _widget(FakeElement(src="recaptcha/api2/bframe"))
        solver._solve_single = lambda *_: (False, [])
        solver.is_captcha_solved = lambda _page: False
        solver._has_recaptcha_underselect_error = lambda _page: False
        with pytest.raises(CaptchaSolveError, match="no interactions"):
            solver.solve(FakePage())

    def test_an_unsupported_board_every_round_ends_unsupported_once_the_loops_are_spent(self):
        solver = _solver()
        solver.detect_captcha = lambda _page: _widget(FakeElement(src="https://hcaptcha.com/?frame=challenge"))
        calls = {"n": 0}

        def raise_unsupported(*_):
            calls["n"] += 1
            raise UnsupportedCaptchaError("nope")

        solver._solve_single = raise_unsupported
        with pytest.raises(UnsupportedChallengeError, match="after 6 solve loops"):
            solver.solve(FakePage())
        assert calls["n"] == 6, "an unusable answer ended the solve before its loops were spent"

    def test_unsupported_mid_solve_retries_instead_of_aborting(self):
        solver = _solver(max_unsupported_resolves=2)
        solver.detect_captcha = lambda _page: _widget(FakeElement(src="https://hcaptcha.com/?frame=challenge"))
        solver._wait_for_element_settled = lambda _el: "settled"
        solver.is_captcha_solved = lambda _page: False
        solver._is_challenge_freshly_rendered = lambda _page: False
        solver._has_recaptcha_underselect_error = lambda _page: False

        calls = {"n": 0}

        def flaky(*_):
            calls["n"] += 1
            if calls["n"] == 1:
                return True, []
            raise UnsupportedCaptchaError("transitional blank frame")

        solver._solve_single = flaky
        with pytest.raises(UnsupportedChallengeError):
            solver.solve(FakePage())
        assert calls["n"] >= 3

    def test_stale_handle_after_submit_is_retried_not_fatal(self):
        solver = _solver()
        solver.detect_captcha = lambda _page: _widget(FakeElement(src="https://hcaptcha.com/?frame=challenge"))
        solver.is_captcha_solved = lambda _page: False
        solver._is_challenge_freshly_rendered = lambda _page: False
        solver._has_recaptcha_underselect_error = lambda _page: False

        calls = {"n": 0}

        def flaky(*_):
            calls["n"] += 1
            if calls["n"] == 1:
                return True, []
            raise RuntimeError("Element is not attached to the DOM")

        solver._solve_single = flaky
        with pytest.raises(CaptchaSolveError, match="after 6 solve loops"):
            solver.solve(FakePage())
        assert calls["n"] == 6, "a stale handle ended the solve before its loops were spent"

    def test_a_stale_handle_before_any_interaction_counts_a_loop(self):
        solver = _solver()
        solver.detect_captcha = lambda _page: _widget(FakeElement(src="https://hcaptcha.com/?frame=challenge"))
        calls = {"n": 0}

        def raise_detached(*_):
            calls["n"] += 1
            raise RuntimeError("Element is not attached to the DOM")

        solver._solve_single = raise_detached
        with pytest.raises(CaptchaSolveError, match="went stale"):
            solver.solve(FakePage())
        assert calls["n"] == 6

    def test_underselect_error_asks_for_the_missed_tiles_until_the_loops_are_spent(self):
        solver = _solver(post_solve_outcome_timeout_ms=1)
        solver.detect_captcha = lambda _page: _widget(FakeElement(src="recaptcha/api2/bframe"))
        solver.is_captcha_solved = lambda _page: False
        solver._is_challenge_freshly_rendered = lambda _page: False
        solver._banner_kind = lambda _page: "select-more"

        seen_retry_modes: List[Optional[str]] = []

        def record(_page, _el, retry_mode):
            seen_retry_modes.append(retry_mode)
            return True, []

        solver._solve_single = record
        with pytest.raises(CaptchaSolveError, match="after 6 solve loops"):
            solver.solve(FakePage())
        assert seen_retry_modes[0] is None
        assert seen_retry_modes[1:] == ["missed-tiles"] * 5

    def test_solved_signal_short_circuits_the_loop(self):
        solver = _solver()
        solver.detect_captcha = lambda _page: _widget(FakeElement(src="recaptcha/api2/bframe"))
        solver._solve_single = lambda *_: (True, [])
        solver.is_captcha_solved = lambda _page: True
        assert solver.solve(FakePage()).is_solved is True


class TestHumanizationMode:

    def _driven(self, mode, backend=None):
        cfg: Dict[str, Any] = {"humanization": mode}
        if backend is not None:
            cfg = {"humanizer": MobileHumanizer(backend=backend)}
        solver = _solver(**cfg)
        element = FakeElement(src="recaptcha/api2/bframe")
        page = FakePage({RECAPTCHA_BFRAME: element})
        solver.detect_captcha = lambda _page: _widget(element)
        solver._solve_single = lambda *_: (
            solver._execute_click(
                page,
                {"target_bounding_box": [0.1, 0.1, 0.3, 0.3]},
                element.bounding_box(),
            ),
            [],
        ) and (True, [])
        solver.is_captcha_solved = lambda _page: True
        solver.solve(page)
        return page

    def test_mobile_never_reaches_for_the_mouse(self):
        backend = _RecordingTouch()
        page = self._driven("mobile", backend=backend)
        assert page.mouse.moves == [] and page.mouse.presses == 0
        assert backend.kinds == ["down", "move", "up"]

    _TARGET = (148.0, 212.0)

    def _lands_on_target(self, at) -> bool:
        lo, hi = self._TARGET
        return lo <= at[0] <= hi and lo <= at[1] <= hi

    def test_none_spends_one_move_per_gesture(self):
        page = self._driven("none")
        assert len(page.mouse.moves) == 1
        assert self._lands_on_target(page.mouse.moves[0])

    def test_mouse_is_still_a_full_trajectory(self):
        page = self._driven("mouse")
        assert len(page.mouse.moves) > 5
        assert self._lands_on_target(page.mouse.moves[-1])


class _RecordingTouch:

    name = "recording"

    def __init__(self) -> None:
        self.kinds: List[str] = []

    def down(self, x: float, y: float) -> None:
        self.kinds.append("down")

    def move(self, path) -> None:
        self.kinds.append("move")

    def up(self, x: float, y: float) -> None:
        self.kinds.append("up")


class TestFreshnessGuard:
    def test_reuses_the_answer_when_the_frame_held_still(self):
        solver = _solver()
        solver._frame_changed_since = lambda *_: False
        calls = {"n": 0}

        def query(_path):
            calls["n"] += 1
            return [{"action": "done"}], [{"total_tokens": 5}]

        actions, usage = solver._solve_frame_freshness_guarded(FakeElement(), "/tmp/x.png", query)
        assert calls["n"] == 1
        assert actions == [{"action": "done"}]
        assert usage == [{"total_tokens": 5}]

    def test_resolves_and_merges_usage_when_the_frame_moved(self):
        solver = _solver(max_stale_frame_resolves=1)
        solver._frame_changed_since = lambda *_: True
        solver._screenshot = lambda *a, **k: _write_png(a[1] if len(a) > 1 else k["path"], 4, 4)
        calls = {"n": 0}

        def query(_path):
            calls["n"] += 1
            return [{"action": f"round{calls['n']}"}], [{"total_tokens": calls["n"]}]

        actions, usage = solver._solve_frame_freshness_guarded(FakeElement(), "/tmp/x.png", query)
        assert calls["n"] == 2
        assert actions == [{"action": "round2"}]
        assert usage == [{"total_tokens": 1}, {"total_tokens": 2}]

    def test_disabled_guard_never_requeries(self):
        solver = _solver(stale_frame_resolve_enabled=False)
        solver._frame_changed_since = lambda *_: True
        calls = {"n": 0}

        def query(_path):
            calls["n"] += 1
            return [{"action": "done"}], []

        solver._solve_frame_freshness_guarded(FakeElement(), "/tmp/x.png", query)
        assert calls["n"] == 1


class TestGridGeometry:
    GRID = [
        [0, 0, 100, 100], [100, 0, 200, 100], [200, 0, 300, 100],
        [0, 100, 100, 200], [100, 100, 200, 200], [200, 100, 300, 200],
        [0, 200, 100, 300], [100, 200, 200, 300], [200, 200, 300, 300],
    ]

    def test_bbox_maps_to_a_row_major_one_indexed_cell(self):
        solver = _solver()
        assert solver._bbox_to_cell([0.4, 0.4, 0.6, 0.6], self.GRID, 300, 300) == 5
        assert solver._bbox_to_cell([0.0, 0.0, 0.2, 0.2], self.GRID, 300, 300) == 1
        assert solver._bbox_to_cell([0.85, 0.85, 1.0, 1.0], self.GRID, 300, 300) == 9

    def test_bbox_outside_every_cell_is_none(self):
        sparse = [[0, 0, 10, 10]]
        assert _solver()._bbox_to_cell([0.9, 0.9, 0.95, 0.95], sparse, 300, 300) is None

    def test_clicked_cells_are_watched_first(self):
        assert _solver()._order_by_priority([3, 7, 1], [7, 1]) == [7, 1, 3]

    def test_priority_cells_not_loading_are_dropped(self):
        assert _solver()._order_by_priority([3], [7, 1]) == [3]


class TestHelpers:
    def test_png_dimensions_from_ihdr(self, tmp_path):
        path = str(tmp_path / "a.png")
        _write_png(path, 321, 654)
        assert _read_png_dimensions(path) == (321, 654)

    def test_png_dimensions_rejects_non_png(self, tmp_path):
        path = str(tmp_path / "a.png")
        Path(path).write_bytes(b"not a png at all......")
        assert _read_png_dimensions(path) is None

    def test_aggregate_sums_rounds(self):
        assert _aggregate([
            {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12},
            {"prompt_tokens": 5, "completion_tokens": 1, "total_tokens": 6},
        ]) == [{"rounds": 2, "prompt_tokens": 15, "completion_tokens": 3, "total_tokens": 18}]

    def test_aggregate_of_nothing_is_empty(self):
        assert _aggregate([]) == []

    def test_as_dict_accepts_pydantic_actions(self):
        from captchakraken.action_types import WaitAction

        assert _as_dict(WaitAction(action="wait", duration_ms=50))["duration_ms"] == 50

    def test_as_dict_passes_plain_dicts_through(self):
        assert _as_dict({"action": "done"}) == {"action": "done"}


class TestTrajectory:
    def test_lands_exactly_on_target(self):
        points, _ = generate_trajectory((0, 0), (640, 480))
        assert points[-1] == (640, 480)

    def test_timings_are_cumulative_and_monotonic(self):
        _, timings = generate_trajectory((0, 0), (800, 600))
        assert timings[0] == 0
        assert all(b >= a for a, b in zip(timings, timings[1:]))

    def test_path_is_not_a_straight_line(self):
        points, _ = generate_trajectory((0, 0), (600, 0))
        assert any(abs(y) > 1.0 for _, y in points[:-1])

    def test_zero_length_move_is_a_single_sample(self):
        points, timings = generate_trajectory((10, 10), (10, 10))
        assert points == [(10, 10)] and timings == [0.0]

    def test_longer_moves_take_longer(self):
        _, short = generate_trajectory((0, 0), (40, 0))
        _, long = generate_trajectory((0, 0), (1200, 0))
        assert long[-1] > short[-1]


class TestAlreadySolved:
    def test_an_already_satisfied_captcha_returns_solved_not_an_error(self):
        solver = _solver()
        solver.detect_captcha = lambda _page: None
        solver.is_captcha_solved = lambda _page: True
        solver.has_interactive_widget_in_dom = lambda _page: True
        assert solver.solve(FakePage()).is_solved is True

    def test_an_unrendered_widget_still_waits_then_fails(self):
        solver = _solver()
        solver.detect_captcha = lambda _page: None
        solver.is_captcha_solved = lambda _page: False
        solver.has_interactive_widget_in_dom = lambda _page: True
        with pytest.raises(NoCaptchaFoundError):
            solver.solve(FakePage())


class TestDeadline:
    def test_a_slow_single_attempt_cannot_overrun_the_budget(self):
        solver = _solver(overall_solve_timeout_ms=50)

        def slow_single(_page, _el, _retry):
            time.sleep(0.2)
            solver._check_deadline("test")
            return True, []

        solver.detect_captcha = lambda _page: _widget(FakeElement(src="recaptcha/api2/bframe"))
        solver._solve_single = slow_single
        solver.is_captcha_solved = lambda _page: False
        with pytest.raises(CaptchaSolveError, match="exceeded overall_solve_timeout_ms"):
            solver.solve(FakePage())

    def test_the_deadline_is_cleared_between_solves(self):
        solver = _solver(overall_solve_timeout_ms=50)
        solver.detect_captcha = lambda _page: None
        solver.is_captcha_solved = lambda _page: True
        solver.solve(FakePage())
        assert solver._deadline_ms is None
        solver._check_deadline("outside a solve")


class TestTracePathClamping:

    def _points(self, page, pts):
        human = MouseHumanizer()
        human._trace(page, pts, [0.0] * len(pts))
        return page.mouse.moves

    def test_falls_back_to_the_page_when_viewport_size_is_none(self):
        page = FakePage()
        page.viewport_size = None
        page.inner_size = {"width": 800.0, "height": 600.0}
        assert self._points(page, [(5000.0, 4000.0)]) == [(799.0, 599.0)]

    def test_no_clamping_when_the_viewport_is_genuinely_unknowable(self):
        page = FakePage()
        page.viewport_size = None
        assert self._points(page, [(5000.0, 4000.0)]) == [(5000.0, 4000.0)]

    def test_clamping_insets_off_the_exact_edge(self):
        page = FakePage()
        page.viewport_size = {"width": 800, "height": 600}
        moves = self._points(page, [(-50.0, -50.0), (5000.0, 5000.0)])
        assert moves == [(1.0, 1.0), (799.0, 599.0)]

    def test_in_range_points_are_untouched(self):
        page = FakePage()
        page.viewport_size = {"width": 800, "height": 600}
        assert self._points(page, [(400.0, 300.0)]) == [(400.0, 300.0)]


class _Scope:

    def __init__(self, mapping: Dict[str, "FakeElement"]) -> None:
        self._mapping = mapping
        self.asked: List[str] = []

    def locator(self, selector: str) -> FakeLocator:
        self.asked.append(selector)
        return FakeLocator(lambda: [self._mapping[selector]] if selector in self._mapping else [])


class _Keyboard:
    def __init__(self) -> None:
        self.typed: List[str] = []
        self.pressed: List[str] = []

    def type(self, text: str) -> None:
        self.typed.append(text)

    def press(self, key: str) -> None:
        self.pressed.append(key)


class _Mouse(FakeMouse):

    def __init__(self) -> None:
        super().__init__()
        self.log: List[tuple] = []

    def move(self, x: float, y: float) -> None:
        super().move(x, y)
        self.log.append(("move", x, y))

    def down(self) -> None:
        self.log.append(("down", self.moves[-1][0] if self.moves else None, None))

    def up(self) -> None:
        super().up()
        self.log.append(("up", self.moves[-1][0] if self.moves else None, None))


def _typing_page() -> "FakePage":
    page = FakePage()
    page.mouse = _Mouse()
    page.keyboard = _Keyboard()
    return page


class TestTextCaptchas:
    def test_the_vendor_box_wins_over_the_generic_one(self):
        from captchakraken.selectors import TEXT_INPUT_SELECTORS

        vendor = FakeElement(box={"x": 10.0, "y": 10.0, "width": 100.0, "height": 20.0})
        generic = FakeElement(box={"x": 10.0, "y": 60.0, "width": 100.0, "height": 20.0})
        scope = _Scope({"input.mtcap-inputtext": vendor, "input[type=text]": generic})
        assert _solver()._find_control(scope, TEXT_INPUT_SELECTORS) is vendor

    def test_the_generic_fallback_still_finds_an_unnamed_box(self):
        from captchakraken.selectors import TEXT_INPUT_SELECTORS

        box = FakeElement()
        scope = _Scope({"input[type=text]": box})
        assert _solver()._find_control(scope, TEXT_INPUT_SELECTORS) is box

    def test_an_invisible_box_is_not_the_box(self):
        from captchakraken.selectors import TEXT_INPUT_SELECTORS

        hidden = FakeElement(visible=False)
        real = FakeElement()
        scope = _Scope({"input#captchaCode": hidden, "input[type=text]": real})
        assert _solver()._find_control(scope, TEXT_INPUT_SELECTORS) is real

    def test_the_code_is_typed_character_by_character(self):
        page = _typing_page()
        scope = _Scope({"input[type=text]": FakeElement()})
        assert _solver()._execute_type(page, scope, {"text": "aB3d"}) is True
        assert page.keyboard.typed == ["a", "B", "3", "d"]

    def test_the_mouse_travels_to_the_box_before_typing(self):
        page = _typing_page()
        field = FakeElement(box={"x": 200.0, "y": 300.0, "width": 120.0, "height": 24.0})
        _solver()._execute_type(page, _Scope({"input[type=text]": field}), {"text": "x"})
        pressed_at = next(x for kind, x, _ in page.mouse.log if kind == "down")
        assert 200.0 <= pressed_at <= 320.0

    def test_a_retry_clears_the_previous_attempt(self):
        page = _typing_page()
        _solver()._execute_type(page, _Scope({"input[type=text]": FakeElement()}), {"text": "ok"})
        assert page.keyboard.pressed and page.keyboard.pressed[0] == "Control+A"

    def test_no_box_means_nothing_was_done(self):
        page = _typing_page()
        assert _solver()._execute_type(page, _Scope({}), {"text": "abc"}) is False
        assert page.keyboard.typed == []

    def test_an_empty_answer_is_not_typed(self):
        page = _typing_page()
        assert _solver()._execute_type(page, _Scope({"input[type=text]": FakeElement()}),
                                       {"text": ""}) is False


class TestSlideGeometry:

    def test_two_readings_recover_both_unknowns(self):
        piece_w, ratio = PageSolver._solve_slide_geometry([(24.0, 64.0), (64.0, 104.0)], 400.0)
        assert (round(piece_w, 6), round(ratio, 6)) == (40.0, 1.0)

    def test_a_geared_slider_is_measured_not_assumed(self):
        piece_w, ratio = PageSolver._solve_slide_geometry([(20.0, 70.0), (60.0, 150.0)], 400.0)
        assert (round(piece_w, 6), round(ratio, 6)) == (30.0, 2.0)

    def test_one_reading_falls_back_to_a_stated_one_to_one(self):
        piece_w, ratio = PageSolver._solve_slide_geometry([(24.0, 64.0)], 400.0)
        assert (piece_w, ratio) == (40.0, 1.0)

    def test_an_absurd_ratio_is_rejected_rather_than_steered_by(self):
        _, ratio = PageSolver._solve_slide_geometry([(24.0, 64.0), (64.0, 65.0)], 400.0)
        assert ratio == 1.0

    def test_a_piece_wider_than_the_widget_is_not_a_piece(self):
        piece_w, _ = PageSolver._solve_slide_geometry([(24.0, 390.0), (64.0, 430.0)], 400.0)
        assert piece_w is None

    def test_no_measurements_at_all_is_reported_as_such(self):
        assert PageSolver._solve_slide_geometry([], 400.0) == (None, 1.0)

    def test_two_readings_taken_close_together_do_not_set_the_ratio(self):
        piece_w, ratio = PageSolver._solve_slide_geometry(
            [(110.0, 150.0), (112.0, 151.0)], 400.0)
        assert ratio == 1.0
        assert round(piece_w, 6) == 39.0

    def test_the_widest_pair_is_used_not_the_two_that_arrived_last(self):
        piece_w, ratio = PageSolver._solve_slide_geometry(
            [(110.0, 150.0), (30.0, 70.0), (112.0, 151.0)], 400.0)
        assert round(ratio, 2) == 0.99
        assert round(piece_w, 1) == 40.4


class TestSlideDriver:

    PIECE_LEFT, PIECE_W = 10.0, 40.0

    def _rig(self, target_px: float, widget_w: float = 400.0, dpr: float = 1.0):
        solver = _solver()
        page = _typing_page()
        handle = FakeElement(box={"x": 120.0, "y": 420.0, "width": 40.0, "height": 30.0})
        element = FakeElement(box={"x": 100.0, "y": 100.0, "width": widget_w, "height": 400.0})
        element.screenshot = lambda path, **_: _write_png(
            path, int(round(widget_w * dpr)), int(round(400.0 * dpr)))
        scope = _Scope({".geetest_slider_button": handle})
        start_x = handle._box["x"] + handle._box["width"] / 2
        page.excludes = []

        def fake_track(_element, _before, _after, exclude, travel=0.0):
            page.excludes.append(list(exclude))
            offset = page.mouse.moves[-1][0] - start_x
            right = self.PIECE_LEFT + self.PIECE_W + offset
            return {"bbox": [int(self.PIECE_LEFT * dpr), 0,
                             int(round(right * dpr)), int(20 * dpr)],
                    "piece": None}

        solver._track_piece = fake_track
        frac = target_px / widget_w
        action = {"target_bounding_box": [frac, 0.4, frac, 0.6]}
        return solver, page, element, scope, action, start_x

    def test_the_handle_is_pressed_not_the_gap(self):
        solver, page, element, scope, action, _ = self._rig(target_px=150.0)
        solver._execute_slide(page, element, scope, action, element._box)
        pressed_at = next(x for kind, x, _ in page.mouse.log if kind == "down")
        assert 120.0 <= pressed_at <= 160.0

    def test_the_piece_is_steered_onto_the_slot(self):
        solver, page, element, scope, action, start_x = self._rig(target_px=150.0)
        solver._execute_slide(page, element, scope, action, element._box)
        released_at = next(x for kind, x, _ in reversed(page.mouse.log) if kind == "move")
        assert abs((released_at - start_x) - 120.0) <= solver.config.slide_tolerance_px

    def test_the_button_is_not_released_before_the_piece_arrives(self):
        solver, page, element, scope, action, _ = self._rig(target_px=150.0)
        solver._execute_slide(page, element, scope, action, element._box)
        kinds = [k for k, _, _ in page.mouse.log]
        assert kinds.count("down") == 1 and kinds.count("up") == 1
        assert kinds.index("up") == len(kinds) - 1

    def test_a_geared_widget_still_lands(self):
        solver, page, element, scope, action, start_x = self._rig(target_px=200.0)

        def geared(_element, _before, _after, _exclude, travel=0.0):
            offset = page.mouse.moves[-1][0] - start_x
            return {"bbox": [int(self.PIECE_LEFT), 0,
                             int(round(self.PIECE_LEFT + self.PIECE_W + 2.0 * offset)), 20],
                    "piece": None}

        solver._track_piece = geared
        solver._execute_slide(page, element, scope, action, element._box)
        released_at = next(x for kind, x, _ in reversed(page.mouse.log) if kind == "move")
        assert abs((released_at - start_x) - 85.0) <= solver.config.slide_tolerance_px

    def test_a_hidpi_screen_still_lands_the_piece(self):
        solver, page, element, scope, action, start_x = self._rig(target_px=150.0, dpr=2.625)
        solver._execute_slide(page, element, scope, action, element._box)
        released_at = next(x for kind, x, _ in reversed(page.mouse.log) if kind == "move")
        assert abs((released_at - start_x) - 120.0) <= solver.config.slide_tolerance_px

    def test_the_handle_mask_is_in_the_shot_s_pixel_space(self):
        solver, page, element, scope, action, _ = self._rig(target_px=150.0, dpr=2.625)
        solver._execute_slide(page, element, scope, action, element._box)
        x1, y1, x2, y2 = page.excludes[0]
        assert y1 <= 320.0 * 2.625 and y2 >= 350.0 * 2.625
        assert x1 == 0.0 and x2 == pytest.approx(400.0 * 2.625, abs=1.0)

    def test_the_mask_reaches_the_bottom_of_the_widget(self):
        solver, page, element, scope, action, _ = self._rig(target_px=150.0, dpr=1.0)
        solver._execute_slide(page, element, scope, action, element._box)
        x1, y1, x2, y2 = page.excludes[0]
        assert (x1, round(y1), x2) == (0.0, 310, 400.0)
        assert y2 == pytest.approx(400.0), (
            "the mask stops at the handle instead of the bottom of the widget — "
            "a rail that runs lower than its handle is left in the diff")

    def test_a_sliderless_widget_drags_the_piece_itself(self):
        solver = _solver()
        page = _typing_page()
        piece = FakeElement(box={"x": 140.0, "y": 220.0, "width": 40.0, "height": 40.0})
        element = FakeElement(box={"x": 100.0, "y": 100.0, "width": 400.0, "height": 400.0})
        scope = _Scope({".lemin-cropped-puzzle-piece": piece})
        action = {"target_bounding_box": [0.5, 0.3, 0.5, 0.4]}
        assert solver._execute_slide(page, element, scope, action, element._box) is True
        released_at = next(x for kind, x, _ in reversed(page.mouse.log) if kind == "move")
        assert abs(released_at - (100.0 + 200.0)) < 1.0

    def test_nothing_draggable_at_all_reports_no_action(self):
        solver = _solver()
        page = _typing_page()
        element = FakeElement()
        action = {"target_bounding_box": [0.5, 0.3, 0.5, 0.4]}
        assert solver._execute_slide(page, element, _Scope({}), action, element._box) is False
        assert [k for k, _, _ in page.mouse.log if k == "down"] == []

    def test_an_invisible_piece_never_stops_the_drag_hanging(self):
        solver, page, element, scope, action, _ = self._rig(target_px=150.0)
        solver._track_piece = lambda *_a, **_k: None
        solver._execute_slide(page, element, scope, action, element._box)
        assert [k for k, _, _ in page.mouse.log][-1] == "up"


class TestPieceTracking:

    def _frame(self, path, piece_x, handle_x):
        import numpy as np
        try:
            import cv2
        except ImportError:
            pytest.skip("cv2 not available")
        img = np.zeros((120, 400, 3), dtype=np.uint8)
        img[20:60, piece_x:piece_x + 40] = 255
        img[90:110, handle_x:handle_x + 30] = 200
        cv2.imwrite(str(path), img)

    def test_the_union_spans_the_vacated_ground_to_the_new_edge(self, tmp_path):
        from captchakraken.tool_calls.track_piece import changed_bbox

        a, b = tmp_path / "a.png", tmp_path / "b.png"
        self._frame(a, piece_x=10, handle_x=10)
        self._frame(b, piece_x=70, handle_x=70)
        bbox = changed_bbox(str(a), str(b), exclude=[0, 85, 400, 115])
        assert bbox is not None
        assert bbox[0] == 10 and bbox[2] == 110
        assert bbox[2] - bbox[0] == 40 + 60

    def test_the_handle_is_masked_out_of_the_measurement(self, tmp_path):
        from captchakraken.tool_calls.track_piece import changed_bbox

        a, b = tmp_path / "a.png", tmp_path / "b.png"
        self._frame(a, piece_x=10, handle_x=10)
        self._frame(b, piece_x=30, handle_x=300)
        masked = changed_bbox(str(a), str(b), exclude=[0, 85, 400, 115])
        unmasked = changed_bbox(str(a), str(b))
        assert masked is not None and masked[2] == 70
        assert unmasked is not None and unmasked[2] == 330

    def test_a_still_frame_reports_nothing_moved(self, tmp_path):
        from captchakraken.tool_calls.track_piece import changed_bbox

        a, b = tmp_path / "a.png", tmp_path / "b.png"
        self._frame(a, piece_x=10, handle_x=10)
        self._frame(b, piece_x=10, handle_x=10)
        assert changed_bbox(str(a), str(b), exclude=[0, 85, 400, 115]) is None


class TestLocatingThePiece:

    MASK = [0, 85, 400, 115]

    def _frame(self, path, pieces, handle_x=10):
        import numpy as np
        try:
            import cv2
        except ImportError:
            pytest.skip("cv2 not available")
        img = np.zeros((120, 400, 3), dtype=np.uint8)
        for x, w in pieces:
            img[20:60, x:x + w] = 255
        img[90:110, handle_x:handle_x + 30] = 200
        cv2.imwrite(str(path), img)

    def _read(self, tmp_path, before, after, travel):
        from captchakraken.tool_calls.track_piece import locate_piece

        a, b = tmp_path / "a.png", tmp_path / "b.png"
        self._frame(a, before)
        self._frame(b, after)
        return locate_piece(str(a), str(b), travel, exclude=self.MASK)

    def test_a_piece_clear_of_its_ghost_is_measured_not_inferred(self, tmp_path):
        got = self._read(tmp_path, [(10, 40)], [(200, 40)], travel=190)
        assert got == {"centre": 220.0, "width": 40.0}

    def test_the_reading_survives_a_travel_the_caller_only_believes(self, tmp_path):
        got = self._read(tmp_path, [(10, 40)], [(170, 40)], travel=190)
        assert got == {"centre": 190.0, "width": 40.0}

    def test_a_piece_that_only_partly_left_its_ghost_is_not_two_pieces(self, tmp_path):
        got = self._read(tmp_path, [(10, 40)], [(30, 40)], travel=20)
        assert got == {"centre": 50.0, "width": 40.0}

    def test_a_piece_driven_off_the_board_is_reported_where_it_went(self, tmp_path):
        got = self._read(tmp_path, [(10, 40)], [], travel=300)
        assert got == {"centre": 330.0, "width": 40.0}

    def test_a_piece_whose_vacated_ground_does_not_register_is_read_where_it_is(self, tmp_path):
        got = self._read(tmp_path, [(105, 33)], [(312, 33)], travel=207)
        assert got == {"centre": 328.5, "width": 33.0}

    def test_the_two_lone_marks_are_told_apart_by_where_the_piece_began(self, tmp_path):
        got = self._read(tmp_path, [(10, 40)], [], travel=300)
        assert got == {"centre": 330.0, "width": 40.0}

    def test_something_else_moving_in_frame_is_not_mistaken_for_the_piece(self, tmp_path):
        got = self._read(tmp_path, [(10, 40)], [(200, 40), (330, 8)], travel=190)
        assert got == {"centre": 220.0, "width": 40.0}

    def test_a_still_frame_locates_nothing(self, tmp_path):
        assert self._read(tmp_path, [(10, 40)], [(10, 40)], travel=0) is None


class TestSlideSubmitPolicy:

    def _run(self, actions):
        solver = _solver()
        page = _typing_page()
        handle = FakeElement(box={"x": 120.0, "y": 420.0, "width": 40.0, "height": 30.0})
        verify = FakeElement(box={"x": 300.0, "y": 500.0, "width": 80.0, "height": 30.0})
        scope = _Scope({".geetest_slider_button": handle, ".button-submit": verify})
        element = FakeElement(box={"x": 100.0, "y": 100.0, "width": 400.0, "height": 400.0})
        element._frame = scope

        solver._settle_or_animated = lambda _e: False
        solver._solve_frame_freshness_guarded = (
            lambda _el, shot, fn: fn(shot))
        solver._get_solution = lambda *_a, **_k: (actions, [])
        solver._track_piece = (
            lambda *_a, **_k: {"bbox": [10, 0, 200, 20], "piece": None})

        performed, _ = solver._solve_single(page, _widget(element, Vendor.GEETEST), None)
        return performed, [k for k, _, _ in page.mouse.log]

    def test_a_slide_is_not_followed_by_a_verify_click(self):
        from captchakraken.action_types import DragAction

        slide = DragAction(action="drag", source_bounding_box=None,
                           target_bounding_box=[0.35, 0.4, 0.4, 0.6])
        performed, kinds = self._run([slide])
        assert performed is True
        assert kinds.count("down") == 1, "the only press should be the slider handle"
        assert kinds.count("up") == 1

    def test_the_gate_does_not_suppress_an_ordinary_submit(self):
        from captchakraken.action_types import DoneAction

        performed, kinds = self._run([DoneAction(action="done")])
        assert kinds.count("down") == 1, "the Verify click"
        assert performed is True

    def test_a_slide_action_constructs_at_all(self):
        from captchakraken.action_types import DragAction

        action = DragAction(action="drag", source_bounding_box=None,
                            target_bounding_box=[0.1, 0.2, 0.3, 0.4])
        assert action.source_bounding_box is None


class TestSlideLooksAgain:

    def test_a_look_that_resolves_nothing_is_taken_again(self):
        solver = _solver()
        page = _typing_page()
        handle = FakeElement(box={"x": 120.0, "y": 420.0, "width": 40.0, "height": 30.0})
        element = FakeElement(box={"x": 100.0, "y": 100.0, "width": 400.0, "height": 400.0})
        scope = _Scope({".geetest_slider_button": handle})
        start_x = 140.0

        calls = {"n": 0}

        def flaky(_element, _before, _after, _exclude, travel=0.0):
            calls["n"] += 1
            if calls["n"] == 1:
                return None
            offset = page.mouse.moves[-1][0] - start_x
            return {"bbox": [10, 0, int(round(10 + 40 + offset)), 20], "piece": None}

        solver._track_piece = flaky
        target_px = 150.0
        frac = target_px / 400.0
        solver._execute_slide(page, element, scope,
                              {"target_bounding_box": [frac, 0.4, frac, 0.6]}, element._box)

        released_at = next(x for kind, x, _ in reversed(page.mouse.log) if kind == "move")
        assert abs((released_at - start_x) - 120.0) <= solver.config.slide_tolerance_px
        assert calls["n"] >= 2, "the loop gave up on the first unreadable frame"


class TestSlideAimsBeforeItCorrects:

    START_X, PIECE_REST, PIECE_W = 140.0, 30.0, 40.0

    def _drive(self, piece_in_dom: bool, target_px: float = 150.0):
        solver = _solver()
        page = _typing_page()
        handle = FakeElement(box={"x": 120.0, "y": 420.0, "width": 40.0, "height": 30.0})
        element = FakeElement(box={"x": 100.0, "y": 100.0, "width": 400.0, "height": 400.0})
        state = {"offset": 0.0}
        sweeps: list = []
        rest, width = self.PIECE_REST, self.PIECE_W

        class _Piece:

            def is_visible(self):
                return True

            def bounding_box(self):
                centre = element._box["x"] + rest + state["offset"]
                return {"x": centre - width / 2, "y": 200.0,
                        "width": width, "height": width}

        scope = _Scope(dict({".geetest_slider_button": handle},
                            **({".geetest_slice": _Piece()} if piece_in_dom else {})))

        def smooth(_page, x, _y):
            if not any(kind == "down" for kind, _, _ in page.mouse.log):
                return
            state["offset"] = x - self.START_X
            sweeps.append(state["offset"])

        solver._smooth_move = smooth
        solver._track_piece = lambda *_a, **_k: {
            "bbox": [int(rest - width / 2), 0,
                     int(round(rest + width / 2 + state["offset"])), 20],
            "piece": None}
        frac = target_px / 400.0
        solver._execute_slide(page, element, scope,
                              {"target_bounding_box": [frac, 0.4, frac, 0.6]}, element._box)
        return sweeps

    def test_the_first_move_goes_most_of_the_way_to_the_slot(self):
        sweeps = self._drive(piece_in_dom=False)
        assert sweeps[0] > 100.0, f"opened with a {sweeps[0]:.0f}px nudge, not a sweep"

    def test_the_piece_the_page_names_is_where_the_sweep_is_aimed(self):
        sweeps = self._drive(piece_in_dom=True)
        assert sweeps == [120.0], f"expected one exact sweep, got {sweeps}"

    def test_a_sweep_that_lands_short_is_corrected_from_the_screen(self):
        sweeps = self._drive(piece_in_dom=False)
        assert len(sweeps) > 1, "no correction after an estimate that was off"
        assert abs(sweeps[-1] - 120.0) <= _solver().config.slide_tolerance_px


class TestASweepThatOvershootsTheBoard:

    WIDGET, PIECE_REST, PIECE_W, START_X = 360.0, 136.0, 42.0, 42.0

    def _drive(self, target_px=288.4):
        solver = _solver()
        page = _typing_page()
        handle = FakeElement(box={"x": 15.0, "y": 297.0, "width": 54.0, "height": 28.0})
        element = FakeElement(box={"x": 0.0, "y": 0.0,
                                   "width": self.WIDGET, "height": self.WIDGET})
        element.screenshot = lambda path, **_: _write_png(
            path, int(self.WIDGET), int(self.WIDGET))
        scope = _Scope({".tencent-captcha-dy__slider-block": handle})
        state = {"offset": 0.0}
        sweeps: list = []

        def smooth(_page, x, _y):
            if not any(kind == "down" for kind, _, _ in page.mouse.log):
                return
            state["offset"] = x - self.START_X
            sweeps.append(state["offset"])

        def track(_element, _before, _after, _exclude, travel=0.0):
            rest_left = self.PIECE_REST - self.PIECE_W / 2
            centre = self.PIECE_REST + state["offset"]
            right = centre + self.PIECE_W / 2
            span = [int(rest_left), 0, int(min(right, self.WIDGET)), 20]
            if right > self.WIDGET:
                span = [int(rest_left), 0, int(rest_left + self.PIECE_W), 20]
                piece = {"centre": self.PIECE_REST + travel, "width": self.PIECE_W}
            else:
                piece = {"centre": centre, "width": self.PIECE_W}
            return {"bbox": span, "piece": piece}

        solver._smooth_move = smooth
        solver._track_piece = track
        frac = target_px / self.WIDGET
        solver._execute_slide(page, element, scope,
                              {"target_bounding_box": [frac, 0.4, frac, 0.6]}, element._box)
        return sweeps, self.PIECE_REST + state["offset"]

    def test_the_opening_sweep_does_overshoot_here(self):
        sweeps, _ = self._drive()
        assert sweeps[0] > self.WIDGET - self.PIECE_REST, (
            f"first sweep {sweeps[0]:.0f}px does not put the piece off the board; "
            f"this test is no longer about anything")

    def test_the_piece_is_brought_back_onto_the_slot(self):
        sweeps, final = self._drive()
        assert len(sweeps) > 1, "released at the overshoot without correcting"
        assert abs(final - 288.4) <= _solver().config.slide_tolerance_px, (
            f"piece released at {final:.1f}px, wanted 288.4")


class TestTypedAnswerIsSubmitted:

    def _run(self, actions):
        solver = _solver()
        page = _typing_page()
        field = FakeElement(box={"x": 120.0, "y": 300.0, "width": 200.0, "height": 30.0})
        verify = FakeElement(box={"x": 300.0, "y": 500.0, "width": 80.0, "height": 30.0})
        scope = _Scope({"input[type=text]": field, ".button-submit": verify})
        element = FakeElement(box={"x": 100.0, "y": 100.0, "width": 400.0, "height": 400.0})
        element._frame = scope

        solver._settle_or_animated = lambda _e: False
        solver._solve_frame_freshness_guarded = (
            lambda _el, shot, fn: fn(shot))
        solver._get_solution = lambda *_a, **_k: (actions, [])

        performed, _ = solver._solve_single(page, _widget(element), None)
        return performed, [k for k, _, _ in page.mouse.log], page

    def test_typing_is_followed_by_a_verify_click(self):
        from captchakraken.action_types import TypeAction

        performed, kinds, _ = self._run([TypeAction(action="type", text="5T63")])
        assert performed is True
        assert kinds.count("down") == 2, (
            "the typed code was never submitted — only the field was clicked"
        )

    def test_a_click_answer_is_submitted_too(self):
        from captchakraken.action_types import ClickAction

        performed, kinds, _ = self._run(
            [ClickAction(action="click", target_bounding_boxes=[[0.4, 0.4, 0.5, 0.5]])])
        assert performed is True
        assert kinds.count("down") == 2, "the selection was never submitted"

    def test_button_discovery_never_escapes_the_widget(self):
        from captchakraken.action_types import ClickAction

        solver = _solver()
        page = _typing_page()
        page._elements["button"] = FakeElement(
            box={"x": 600.0, "y": 700.0, "width": 80.0, "height": 30.0}, text="Submit")
        element = FakeElement(box={"x": 100.0, "y": 100.0, "width": 400.0, "height": 400.0})
        element._frame = None

        solver._settle_or_animated = lambda _e: False
        solver._solve_frame_freshness_guarded = (
            lambda _el, shot, fn: fn(shot))
        solver._get_solution = lambda *_a, **_k: (
            [ClickAction(action="click", target_bounding_boxes=[[0.4, 0.4, 0.5, 0.5]])], [])

        solver._solve_single(page, _widget(element), None)
        kinds = [k for k, _, _ in page.mouse.log]
        assert kinds.count("down") == 1, (
            "pressed a Submit that belongs to the page, not to the captcha"
        )

    def test_a_widget_that_is_not_an_iframe_still_gets_its_verify_pressed(self):
        from captchakraken.action_types import TypeAction

        solver = _solver()
        page = _typing_page()
        field = FakeElement(box={"x": 120.0, "y": 300.0, "width": 200.0, "height": 30.0})
        verify = FakeElement(box={"x": 300.0, "y": 500.0, "width": 80.0, "height": 30.0},
                             text="Verify")
        element = FakeElement(box={"x": 100.0, "y": 100.0, "width": 400.0, "height": 400.0})
        element._frame = None
        at = _Scope({"input[type=text]": field, submit_by_text("verify"): verify})

        solver._settle_or_animated = lambda _e: False
        solver._solve_frame_freshness_guarded = (
            lambda _el, shot, fn: fn(shot))
        solver._get_solution = lambda *_a, **_k: (
            [TypeAction(action="type", text="5T63")], [])

        performed, _ = solver._solve_single(page, _widget(element, at=at), None)
        kinds = [k for k, _, _ in page.mouse.log]
        assert performed is True
        assert kinds.count("down") == 2, (
            "no Verify press on a non-iframe widget — the typed code was never sent"
        )


class TestSliderlessFreeDrag:

    def _run(self, target_bbox):
        piece = FakeElement(box={"x": 130.0, "y": 620.0, "width": 60.0, "height": 60.0})
        scope = _Scope({".lemin-cropped-puzzle-piece": piece})
        element = FakeElement(box={"x": 100.0, "y": 100.0, "width": 400.0, "height": 600.0})
        element._frame = scope

        solver = _solver()
        page = _typing_page()
        ok = solver._execute_slide(
            page, element, scope,
            {"target_bounding_box": target_bbox, "source_bounding_box": None},
            element.bounding_box())
        return ok, page.mouse.log

    def test_the_piece_is_carried_to_the_slot_not_along_the_tray(self):
        ok, log = self._run([0.375, 0.283, 0.425, 0.317])
        assert ok is True
        release_y = [y for kind, _, y in log if kind == "move"][-1]
        assert abs(release_y - 280.0) < 2.0, (
            f"released at y={release_y}: the piece was dragged along the tray "
            f"(y≈650) instead of up to the slot (y≈280)"
        )


class TestInlineWidgetSubmit:

    def _run(self, actions, *, verify_named="Verify"):
        verify = FakeElement(box={"x": 300.0, "y": 500.0, "width": 80.0, "height": 30.0},
                             text=verify_named)
        element = FakeElement(box={"x": 100.0, "y": 100.0, "width": 400.0, "height": 400.0})
        element._frame = None
        at = _Scope({submit_by_text(verify_named.lower()): verify})

        solver = _solver()
        page = _typing_page()
        solver._settle_or_animated = lambda _e: False
        solver._solve_frame_freshness_guarded = (
            lambda _el, shot, fn: fn(shot))
        solver._get_solution = lambda *_a, **_k: (actions, [])

        performed, _ = solver._solve_single(page, _widget(element, at=at), None)
        return performed, [k for k, _, _ in page.mouse.log]

    def test_done_on_an_inline_widget_presses_verify(self):
        from captchakraken.action_types import DoneAction

        performed, kinds = self._run([DoneAction(action="done")])
        assert kinds.count("down") == 1, (
            "the tiles were selected and the widget was never submitted"
        )
        assert performed is True

    def test_a_placed_piece_is_submitted(self):
        from captchakraken.action_types import DragAction

        performed, kinds = self._run([DragAction(
            action="drag",
            source_bounding_box=[0.20, 0.83, 0.23, 0.86],
            target_bounding_box=[0.70, 0.64, 0.73, 0.67])])
        assert performed is True
        assert kinds.count("down") == 2, "the piece was placed and never submitted"

    def test_a_click_round_is_submitted_without_waiting_for_done(self):
        from captchakraken.action_types import ClickAction

        performed, kinds = self._run(
            [ClickAction(action="click", target_bounding_boxes=[[0.4, 0.4, 0.5, 0.5]])])
        assert performed is True
        assert kinds.count("down") == 2, "the selection waited for a `done` round"
