"""A page just navigated has often not drawn its widget, and "no captcha" is only believed after a bounded wait.

Measured on a vendor's public demo: `solve()` straight after `goto(..., wait_until="domcontentloaded")` raised "no
interactive captcha widget detected ... the vendor's markup no longer matches anything in SELECTORS" 3 times out
of 3, while the same code solved 2 of 3 once the page had settled. It was a race, and the message blamed the table.
"""

import sys
from pathlib import Path
from typing import Any, List

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from captchakraken import page_solver  # noqa: E402
from captchakraken.kinds import Vendor  # noqa: E402
from captchakraken.page_solver import NoCaptchaFoundError, PageSolver, PageSolverConfig  # noqa: E402


class Clock:
    """Virtual time: every delay advances it, so a 15s wait costs nothing."""

    def __init__(self) -> None:
        self.ms = 0.0

    def now(self) -> float:
        return self.ms

    def delay(self, ms: float) -> None:
        self.ms += max(ms, 0.0)


@pytest.fixture
def clock(monkeypatch):
    c = Clock()
    monkeypatch.setattr(page_solver, "_now", c.now)
    monkeypatch.setattr(page_solver, "_delay", c.delay)
    return c


def _solver(clock: Clock, appears_after_ms: float, timeout_ms: int = 15_000) -> PageSolver:
    solver = PageSolver(config=PageSolverConfig(detection_timeout_ms=timeout_ms, max_solve_loops=1,
                                                overall_solve_timeout_ms=1_000, post_solve_outcome_timeout_ms=1))
    solver._reset_animated_state()
    solver.rounds_at: List[float] = []
    solver.detect_captcha = lambda _page: object() if clock.ms >= appears_after_ms else None
    solver.is_captcha_solved = lambda _page: len(solver.rounds_at) > 0

    def solve_single(_page, _widget, _retry):
        solver.rounds_at.append(clock.ms)
        return True, []

    solver._solve_single = solve_single
    return solver


def test_a_widget_that_draws_late_is_found_and_solved(clock):
    solver = _solver(clock, appears_after_ms=3_000)
    result = solver._solve_impl(object(), 0.0, [])
    assert result.is_solved
    assert 3_000 <= solver.rounds_at[0] < 3_000 + 2 * page_solver._DETECTION_POLL_MS


def test_the_wait_is_not_charged_to_the_solve_budget(clock):
    """A 1s budget, a widget that took 10s to draw, and a board that needs a second round: the second round runs."""
    solver = _solver(clock, appears_after_ms=10_000)
    solver.config.max_solve_loops = 2
    solver.is_captcha_solved = lambda _page: len(solver.rounds_at) >= 2
    solver._deadline_ms = 1_000.0
    assert solver._solve_impl(object(), 0.0, []).is_solved
    assert len(solver.rounds_at) == 2


def test_a_widget_that_never_draws_is_given_up_on_at_the_timeout(clock):
    solver = _solver(clock, appears_after_ms=float("inf"), timeout_ms=15_000)
    solver.vendors_on_the_wire = lambda _page: []
    with pytest.raises(NoCaptchaFoundError, match="within 15000ms") as caught:
        solver._solve_impl(object(), 0.0, [])
    assert 15_000 <= clock.ms < 15_000 + 2 * page_solver._DETECTION_POLL_MS
    assert "no vendor captcha code loaded" in str(caught.value)


def _message(clock: Clock, *, loaded: List[Vendor], unmatched: List[Vendor]) -> str:
    solver = _solver(clock, appears_after_ms=float("inf"), timeout_ms=500)
    solver.vendors_on_the_wire = lambda _page: loaded
    solver._unmatched_vendor_frames = lambda _page: unmatched
    with pytest.raises(NoCaptchaFoundError) as caught:
        solver._solve_impl(object(), 0.0, [])
    return str(caught.value)


def test_loaded_code_with_no_frame_does_not_blame_the_selectors(clock):
    message = _message(clock, loaded=[Vendor.HCAPTCHA], unmatched=[])
    assert "matches nothing in SELECTORS" not in message and "re-measuring" not in message
    assert "code is loaded but drew no widget" in message


def test_a_frame_nothing_matches_is_reported_as_changed_markup(clock):
    message = _message(clock, loaded=[Vendor.HCAPTCHA], unmatched=[Vendor.HCAPTCHA])
    assert "hcaptcha is showing a frame that matches nothing in SELECTORS" in message


class _Frame:
    def __init__(self, src: str) -> None:
        self.src = src

    def is_visible(self) -> bool:
        return True


class _Scope:
    """Answers `iframe[src*="..."]` from a list of frame URLs, which is all the unmatched-frame check asks."""

    def __init__(self, srcs: List[str]) -> None:
        self.srcs = srcs

    def locator(self, selector: str) -> Any:
        from fake_dom import FakeLocator

        needle = selector.split('src*="', 1)[1].split('"', 1)[0] if 'src*="' in selector else None
        return FakeLocator(lambda: [_Frame(s) for s in self.srcs if needle and needle in s])


def test_an_invisible_badge_is_not_an_unmatched_frame():
    solver = PageSolver(config=PageSolverConfig())
    badge = _Scope(["https://www.google.com/recaptcha/api2/anchor?k=SITE-KEY&size=invisible"])
    assert solver._unmatched_vendor_frames(badge) == []
    drawn = _Scope(["https://newassets.hcaptcha.com/captcha/v1/static/hcaptcha.html#frame=checkbox-renamed"])
    assert solver._unmatched_vendor_frames(drawn) == [Vendor.HCAPTCHA]
