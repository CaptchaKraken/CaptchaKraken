""""Target closed" is terminal, not stale: retried as stale, a dead page was re-detected three times. Solved is checked before spending another round on a stale handle after submit."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from captchakraken.page_solver import (
    _CLOSED_TARGET_RE,
    _STALE_HANDLE_RE,
    PageClosedError,
)

CLOSED_MESSAGES = [
    "ElementHandle.screenshot: Target page, context or browser has been closed",
    "Page.query_selector: Target page, context or browser has been closed",
    "Target closed",
    "Session closed. Most likely the page has been closed.",
]

STALE_MESSAGES = [
    "element is not attached to the DOM",
    "element is not visible",
    "Timeout 5000ms exceeded",
    "elementHandle.screenshot: element is detached from document",
]


@pytest.mark.parametrize("message", CLOSED_MESSAGES)
def test_closed_target_is_not_classified_as_stale(message):
    assert _CLOSED_TARGET_RE.search(message), f"should read as closed: {message!r}"
    assert not _STALE_HANDLE_RE.search(message), (
        f"{message!r} must NOT be retried as a stale handle — it means the page is gone"
    )


@pytest.mark.parametrize("message", STALE_MESSAGES)
def test_real_staleness_still_retries(message):
    assert _STALE_HANDLE_RE.search(message), f"should read as stale: {message!r}"
    assert not _CLOSED_TARGET_RE.search(message)


def _solver(failure: str, *, solved_after_failure: bool):
    from captchakraken.page_solver import PageSolver, PageSolverConfig

    cfg = PageSolverConfig(
        post_solve_outcome_timeout_ms=1,
        stale_element_backoff_ms=1,
    )
    solver = PageSolver(config=cfg)
    solver._last_mouse = (10.0, 20.0)

    state = {"detects": 0, "interacts": 0, "accepted": False}

    def detect(page):
        state["detects"] += 1
        return object()

    def solve_single(page, element, retry_mode):
        state["interacts"] += 1
        if state["interacts"] == 1:
            return True, []
        state["accepted"] = True
        raise RuntimeError(failure)

    def is_solved(page):
        if not state["accepted"]:
            return False
        if not solved_after_failure:
            raise RuntimeError("Target page, context or browser has been closed")
        return True

    solver.detect_captcha = detect
    solver._solve_single = solve_single
    solver.is_captcha_solved = is_solved
    return solver, state


class FakePage:
    pass


def test_solved_is_checked_before_spending_another_round():
    solver, state = _solver("element is not attached to the DOM", solved_after_failure=True)

    result = solver.solve(FakePage())

    assert result.is_solved is True
    assert state["interacts"] == 2, (
        f"the challenge pipeline ran {state['interacts']}x — expected 2. A third means "
        "the driver re-solved a puzzle that had already been accepted."
    )


def test_closed_page_raises_a_named_error_not_a_raw_playwright_message():
    solver, state = _solver(
        "Page.query_selector: Target page, context or browser has been closed",
        solved_after_failure=False,
    )

    with pytest.raises(PageClosedError):
        solver.solve(FakePage())

    assert state["interacts"] == 2, (
        f"the challenge pipeline ran {state['interacts']}x — a closed target must not be "
        "retried, it can never answer"
    )
