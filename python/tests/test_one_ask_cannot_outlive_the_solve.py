# A request in flight cannot be cancelled, so the timeout it was SENT with is the only thing bounding it.
#
# `_check_deadline` is read between steps. A single ask that hangs is therefore unbounded by anything the
# solve loop does, and the planner used to send every one of them with a hardcoded 120s — 2.7x the whole
# 45s solve budget. Measured against the hosted endpoint on 2026-09-17: one ask hung, gave up after ~124s
# with "the write operation timed out", and the attempt ran 143.3s of which 123.9s was that single call.
#
# The caller owns the number now: whatever is left of the solve, floored so a nearly-spent budget still
# buys a real attempt rather than a certain timeout.
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

from captchakraken import planner
from captchakraken.page_solver import PageSolver, PageSolverConfig, _now


class _Planner:
    """Only what the solver touches."""

    def __init__(self):
        self.request_timeout_s = planner.DEFAULT_REQUEST_TIMEOUT_S


def _solver_with_budget_left(ms: float) -> PageSolver:
    solver = PageSolver(config=PageSolverConfig())
    solver._solver.planner = _Planner()
    solver._deadline_ms = _now() + ms
    return solver


def test_an_ask_gets_what_is_left_of_the_solve():
    solver = _solver_with_budget_left(20_000)
    solver._bound_ask_to_the_budget()
    assert 19.0 <= solver._solver.planner.request_timeout_s <= 20.0, (
        "the ask may outlive the budget it sits inside"
    )


def test_a_nearly_spent_budget_still_buys_a_real_attempt():
    solver = _solver_with_budget_left(1_000)
    solver._bound_ask_to_the_budget()
    assert solver._solver.planner.request_timeout_s == planner.MIN_REQUEST_TIMEOUT_S


def test_a_long_budget_does_not_raise_the_ceiling():
    solver = _solver_with_budget_left(600_000)
    solver._bound_ask_to_the_budget()
    assert solver._solver.planner.request_timeout_s == planner.DEFAULT_REQUEST_TIMEOUT_S


def test_the_planner_sends_the_number_it_was_given():
    """The attribute is worth nothing if the request ignores it."""
    sent = {}

    class _Response:
        ok = True
        status_code = 200

        @staticmethod
        def json():
            return {"choices": [{"message": {"content": "[]"}}], "usage": {}}

    class _Session:
        def post(self, url, headers=None, json=None, timeout=None):
            sent["timeout"] = timeout
            return _Response()

    live = planner.ActionPlanner(model="captcha-v12", base_url="http://127.0.0.1:1", api_key="x")
    live._http = _Session()
    live._server_ensured = True
    live.request_timeout_s = 17.5
    live._chat_with_image("prompt", str(Path(__file__)), max_tokens=16)
    assert sent["timeout"] == 17.5, f"the ask ignored its budget: {sent}"


def test_the_default_is_still_there_for_a_caller_with_no_deadline():
    live = planner.ActionPlanner(model="captcha-v12", base_url="http://127.0.0.1:1", api_key="x")
    assert live.request_timeout_s == planner.DEFAULT_REQUEST_TIMEOUT_S
