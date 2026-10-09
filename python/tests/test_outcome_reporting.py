"""The outcome report: a self-hosted 404 switches it off, a hosted failure is a fault and is said out loud every time.

A self-hosted vLLM has no /solve-outcome, so asking it once per solve forever is noise. The hosted API does have
one: a 404 there is a broken route, and switching reporting off for the process on it hid every later solve from
the ledger for as long as the process ran.
"""

import os
import sys
from pathlib import Path
from typing import Any, Dict, List

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from captchakraken.planner import ActionPlanner, routing_headers  # noqa: E402

HOSTED = "https://api.captchakraken.com/v1"
SELF_HOSTED = "http://localhost:8000/v1"


class Reply:
    def __init__(self, status: int) -> None:
        self.status_code = status


class Wire:
    def __init__(self, status: int) -> None:
        self.status = status
        self.posts: List[Dict[str, Any]] = []

    def post(self, url: str, **kwargs: Any) -> Reply:
        self.posts.append({"url": url, **kwargs})
        return Reply(self.status)


def _planner(base_url: str, status: int) -> ActionPlanner:
    planner = ActionPlanner.__new__(ActionPlanner)
    planner.base_url, planner.api_key, planner.outcome_supported = base_url, "SYNTHETIC-KEY", True
    planner._http = Wire(status)
    return planner


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for name in ("CAPTCHA_REPORT_OUTCOME", "CAPTCHA_KRAKEN_SESSION", "CAPTCHA_KRAKEN_VENDOR", "CAPTCHA_KRAKEN_SITE",
                 "CAPTCHA_KRAKEN_WIDGET_HOST", "CAPTCHA_KRAKEN_EXTRA_HEADERS", "CAPTCHA_HOSTED_HOSTS"):
        monkeypatch.delenv(name, raising=False)


def test_the_body_endpoint_and_timeout_are_the_contract():
    planner = _planner(HOSTED, 200)
    assert planner.report_outcome("SESSION-1", True) is True
    (post,) = planner._http.posts
    assert post["url"] == f"{HOSTED}/solve-outcome"
    assert post["json"] == {"session": "SESSION-1", "solved": True}
    assert post["timeout"] == 3.0


def test_a_hosted_404_is_warned_about_every_time_and_never_switches_reporting_off(capsys):
    planner = _planner(HOSTED, 404)
    assert planner.report_outcome("SESSION-1", True) is False
    assert planner.report_outcome("SESSION-2", False) is False
    assert len(planner._http.posts) == 2, "a hosted 404 switched reporting off"
    warnings = [line for line in capsys.readouterr().err.splitlines() if "warning" in line]
    assert len(warnings) == 2 and all("HTTP 404" in w for w in warnings)


def test_a_self_hosted_404_switches_reporting_off_quietly(capsys):
    planner = _planner(SELF_HOSTED, 404)
    assert planner.report_outcome("SESSION-1", True) is False
    assert planner.report_outcome("SESSION-2", True) is False
    assert len(planner._http.posts) == 1
    assert planner.outcome_supported is False
    assert "warning" not in capsys.readouterr().err


def test_the_opt_out_sends_nothing(monkeypatch):
    monkeypatch.setenv("CAPTCHA_REPORT_OUTCOME", "0")
    planner = _planner(HOSTED, 200)
    assert planner.report_outcome("SESSION-1", True) is False
    assert planner._http.posts == []


def test_a_hosted_report_says_which_vendor_and_site(monkeypatch):
    monkeypatch.setenv("CAPTCHA_KRAKEN_VENDOR", "geetest")
    monkeypatch.setenv("CAPTCHA_KRAKEN_SITE", "shop.example.com")
    planner = _planner(HOSTED, 200)
    planner.report_outcome("SESSION-1", True)
    headers = planner._http.posts[0]["headers"]
    assert headers["X-CK-Vendor"] == "geetest" and headers["X-CK-Site"] == "shop.example.com"


def test_vendor_and_site_go_to_the_hosted_api_only():
    env = {"CAPTCHA_KRAKEN_VENDOR": "recaptcha", "CAPTCHA_KRAKEN_SITE": "shop.example.com"}
    assert routing_headers(env=env) == {}
    assert routing_headers(env=env, hosted=True) == {"X-CK-Vendor": "recaptcha", "X-CK-Site": "shop.example.com"}


def test_extra_headers_cannot_rewrite_vendor_or_site():
    env = {"CAPTCHA_KRAKEN_VENDOR": "recaptcha", "CAPTCHA_KRAKEN_SITE": "shop.example.com",
           "CAPTCHA_KRAKEN_EXTRA_HEADERS": "X-CK-Vendor: forged, x-ck-site: forged.example"}
    assert routing_headers(env=env, hosted=True) == {"X-CK-Vendor": "recaptcha", "X-CK-Site": "shop.example.com"}


def test_the_widget_host_goes_to_the_hosted_api_only_and_cannot_be_rewritten():
    env = {"CAPTCHA_KRAKEN_WIDGET_HOST": "assets.vendor.example",
           "CAPTCHA_KRAKEN_EXTRA_HEADERS": "X-CK-Widget-Host: forged.example"}
    assert routing_headers(env=env) == {}
    assert routing_headers(env=env, hosted=True) == {"X-CK-Widget-Host": "assets.vendor.example"}


def test_the_widget_host_is_the_iframes_hostname_and_nothing_else(monkeypatch):
    from captchakraken.page_solver import _WIDGET_HOST_ENV, PageSolver, Widget
    from captchakraken.kinds import FrameRole, Vendor

    frame = type("F", (), {"url": "https://Assets.Vendor.Example/challenge?k=SYNTHETIC"})()
    element = type("E", (), {"content_frame": lambda self: frame})()
    solver = PageSolver.__new__(PageSolver)
    seen = {}

    def stop(*_a, **_k):
        seen["host"] = os.environ.get(_WIDGET_HOST_ENV)
        raise RuntimeError("stop after the env is set")

    monkeypatch.setattr(PageSolver, "_click_checkbox", stop, raising=False)
    with pytest.raises(RuntimeError):
        PageSolver._solve_single(solver, None, Widget(element, None, Vendor.RECAPTCHA, FrameRole.CHECKBOX), None)
    assert seen["host"] == "assets.vendor.example"


def test_the_site_header_is_the_hostname_and_nothing_else():
    from captchakraken.page_solver import _hostname

    page = type("P", (), {"url": "https://Shop.Example.com:8443/checkout/step-2?order=SYNTHETIC#pay"})()
    assert _hostname(page) == "shop.example.com"
    assert _hostname(type("P", (), {"url": "about:blank"})()) == ""


def test_the_cli_tells_the_js_driver_when_there_is_no_route(monkeypatch):
    """The JS port reports through this command and must learn the self-hosted 404 the way this process did."""
    from captchakraken import cli, planner

    class NoRoute:
        outcome_supported = True

        def report_outcome(self, _session: str, _solved: bool) -> bool:
            self.outcome_supported = False
            return False

    monkeypatch.setattr(planner, "ActionPlanner", NoRoute)
    assert cli._report_outcome(["SESSION-1", "failed"]) == {"reported": False, "supported": False}
