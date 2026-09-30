"""The vendor's own answer-check response decides a round, and only a refusal to serve ends the solve early.

A DOM done-signal only says something changed on the page; the answer-check response says whether the round was
taken. The shapes in `fixtures/vendor_verdicts.json` were recorded on the vendors' public demo pages and then
stripped of every token; the JS port reads the same file.
"""

import json
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from captchakraken.kinds import Verdict, Vendor  # noqa: E402
from captchakraken.page_solver import (CaptchaSolveError, PageSolver, PageSolverConfig,  # noqa: E402
                                       VendorBlockedError, _now)
from captchakraken.verdicts import RoundVerdict, VerdictLog, read_verdict  # noqa: E402

CASES = json.loads((Path(__file__).parent / "fixtures" / "vendor_verdicts.json").read_text())["cases"]


@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
def test_each_recorded_response_reads_as_the_vendor_meant_it(case):
    got = read_verdict(case["url"], case["status"], case["body"])
    expected = None if case["verdict"] is None else RoundVerdict(Vendor(case["vendor"]), Verdict(case["verdict"]))
    assert got == expected


class FakeResponse:
    def __init__(self, url: str, status: int, body: str) -> None:
        self.url, self.status, self._body = url, status, body
        self.read = False

    def body(self) -> bytes:
        self.read = True
        return self._body.encode("utf-8") if isinstance(self._body, str) else self._body


class ListeningPage:
    """Just the event surface: the page emits a response by calling what was registered."""

    def __init__(self) -> None:
        self.listeners: List[Callable[[Any], None]] = []

    def on(self, event: str, listener: Callable[[Any], None]) -> None:
        assert event == "response"
        self.listeners.append(listener)

    def remove_listener(self, event: str, listener: Callable[[Any], None]) -> None:
        self.listeners.remove(listener)

    def emit(self, case: Dict[str, Any]) -> FakeResponse:
        response = FakeResponse(case["url"], case["status"], case["body"])
        for listener in list(self.listeners):
            listener(response)
        return response


def _case(name: str) -> Dict[str, Any]:
    return next(c for c in CASES if c["name"] == name)


def test_the_log_reads_only_the_bodies_it_can_judge_and_lets_go_of_the_page():
    page = ListeningPage()
    log = VerdictLog(page)
    unrelated = page.emit(_case("A page's own traffic is not read"))
    page.emit(_case("hCaptcha refuses the answer"))
    page.emit(_case("hCaptcha takes the answer"))
    assert not unrelated.read, "a body the driver cannot judge was read anyway"
    assert [v.verdict for v in log.fresh()] == [Verdict.REJECTED, Verdict.ACCEPTED]
    assert log.fresh() == [], "a verdict was handed out twice"
    assert log.decisive() == Verdict.ACCEPTED
    log.close()
    assert page.listeners == []


def test_a_body_that_is_not_text_still_yields_its_url_verdict():
    """Measured live: the encrypted deal response raised on a strict decode, so the Python port dropped a verdict the
    JS port recorded."""
    page = ListeningPage()
    log = VerdictLog(page)
    page.emit({**_case("hCaptcha deals a board, encrypted"), "body": b"\xff\xfe\x00SYNTHETIC"})
    assert [v.verdict for v in log.fresh()] == [Verdict.NEW_CHALLENGE]


def test_a_page_that_cannot_be_listened_to_records_nothing_and_raises_nothing():
    log = VerdictLog(object())
    assert log.fresh() == [] and log.decisive() is None
    log.close()


def _solver(page: ListeningPage, on_round: Callable[[int], None], *, solved: Callable[[], bool] = lambda: False,
            widget_present: Callable[[], bool] = lambda: True, loops: int = 6) -> PageSolver:
    """A solver whose every round interacts and then lets `on_round` put traffic on the page's wire."""
    solver = PageSolver(config=PageSolverConfig(max_solve_loops=loops, post_solve_outcome_timeout_ms=40,
                                                post_solve_outcome_poll_ms=5, stale_element_backoff_ms=0,
                                                detection_timeout_ms=0))
    solver._reset_animated_state()
    rounds = {"n": 0}

    def solve_single(_page, _widget, _retry):
        rounds["n"] += 1
        on_round(rounds["n"])
        return True, []

    solver.rounds = rounds
    solver._solve_single = solve_single
    solver.detect_captcha = lambda _page: object() if widget_present() else None
    solver.is_captcha_solved = lambda _page: solved()
    solver._is_challenge_freshly_rendered = lambda _page: False
    solver._banner_kind = lambda _page: None
    solver._is_blocked = lambda _page: False
    return solver


def test_an_accepted_verdict_ends_the_solve_as_solved():
    page = ListeningPage()
    solver = _solver(page, lambda n: page.emit(_case("hCaptcha takes the answer")))
    result = solver._solve_impl(page, _now(), [])
    assert result.is_solved and solver.rounds["n"] == 1
    assert result.verdicts == [RoundVerdict(Vendor.HCAPTCHA, Verdict.ACCEPTED)]


def test_a_rejected_verdict_counts_the_loop_and_the_next_one_can_still_win():
    page = ListeningPage()
    said = ["GeeTest refuses the answer", "GeeTest refuses the answer", "GeeTest takes the answer"]
    solver = _solver(page, lambda n: page.emit(_case(said[n - 1])))
    result = solver._solve_impl(page, _now(), [])
    assert result.is_solved and solver.rounds["n"] == 3
    assert [v.verdict for v in result.verdicts] == [Verdict.REJECTED, Verdict.REJECTED, Verdict.ACCEPTED]


def test_a_widget_that_vanishes_after_a_rejection_was_not_solved():
    """The DOM reads a closed widget as success; the vendor had just said no."""
    page = ListeningPage()
    state = {"gone": False}

    def reject_and_close(_n):
        page.emit(_case("hCaptcha refuses the answer"))
        state["gone"] = True

    solver = _solver(page, reject_and_close, widget_present=lambda: not state["gone"])
    with pytest.raises(CaptchaSolveError, match="rejected the last answer"):
        solver._solve_impl(page, _now(), [])


def test_every_rejected_round_is_spent_before_giving_up():
    page = ListeningPage()
    solver = _solver(page, lambda n: page.emit(_case("reCAPTCHA refuses the answer and deals the next board")))
    with pytest.raises(CaptchaSolveError, match="after 6 solve loops"):
        solver._solve_impl(page, _now(), [])
    assert solver.rounds["n"] == 6


def test_a_vendor_that_refuses_to_serve_ends_the_solve_at_once():
    page = ListeningPage()
    solver = _solver(page, lambda n: page.emit(_case("hCaptcha refuses to serve at all")))
    with pytest.raises(VendorBlockedError, match="429"):
        solver._solve_impl(page, _now(), [])
    assert solver.rounds["n"] == 1


def test_a_try_again_later_screen_ends_the_solve_at_once():
    page = ListeningPage()
    solver = _solver(page, lambda n: None)
    solver._is_blocked = lambda _page: True
    with pytest.raises(VendorBlockedError, match="try-again-later"):
        solver._solve_impl(page, _now(), [])
    assert solver.rounds["n"] == 1


class _Planner:
    def __init__(self) -> None:
        self.reports: List[bool] = []
        self.token_usage: List[Any] = []

    def report_outcome(self, _session: str, solved: bool) -> bool:
        self.reports.append(solved)
        return True


def test_the_reported_outcome_is_the_vendors_verdict_over_the_dom():
    """The DOM says solved (a token appeared); the vendor's last word was a refusal, so the ledger hears failed."""
    page = ListeningPage()
    planner = _Planner()
    state = {"round": 0}

    def reject(n):
        state["round"] = n
        page.emit(_case("hCaptcha refuses the answer"))

    solver = _solver(page, reject, solved=lambda: state["round"] >= 1)
    solver._solver = type("S", (), {"planner": planner})()
    solver._human.reset = lambda _page: None
    assert solver.solve(page).is_solved is True
    assert planner.reports == [False]


def test_without_a_readable_verdict_the_dom_decides_the_report():
    page = ListeningPage()
    planner = _Planner()
    solver = _solver(page, lambda n: None, solved=lambda: True)
    solver._solver = type("S", (), {"planner": planner})()
    solver._human.reset = lambda _page: None
    assert solver.solve(page).verdicts == []
    assert planner.reports == [True]
