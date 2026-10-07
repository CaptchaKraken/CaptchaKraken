"""A hosted request that names a model the endpoint no longer routes is answered by an older model, so the client says so.

Once per process, because a solve asks many times. A driver that has already said it (the JS port, which starts this
engine once per round) sets CAPTCHA_KRAKEN_MODEL_WARNING=0. Both ports print the same words; the Python tests run without node, so
the JS text is read from its source.
"""
import re
from pathlib import Path

import pytest

from captchakraken import planner, prompts

HOSTED = "https://api.captchakraken.com/v1"
JS_SOURCE = Path(__file__).resolve().parents[2] / "js" / "src" / "model-name.ts"


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    monkeypatch.setattr(planner, "_legacy_model_warned", False)
    for name in ("CAPTCHA_KRAKEN_MODEL_WARNING", "CAPTCHA_LORA_NAME", "CAPTCHA_HOSTED_HOSTS"):
        monkeypatch.delenv(name, raising=False)


def test_the_routed_names_are_each_routing_alias_and_its_arms():
    routed = prompts.routed_names()
    for alias in routed:
        assert prompts.experts(alias) or any(alias in prompts.experts(a).values() for a in routed)
    assert not prompts.is_legacy_hosted_name(next(iter(routed)))


def test_a_name_with_no_route_is_warned_about_once(capsys):
    planner.ActionPlanner(model="captcha", base_url=HOSTED, api_key="SYNTHETIC")
    planner.ActionPlanner(model="captcha", base_url=HOSTED, api_key="SYNTHETIC")
    err = capsys.readouterr().err
    assert err.count("answers the model name 'captcha' with an older model") == 1


def test_a_routed_name_or_a_self_hosted_endpoint_hears_nothing(capsys):
    routed = sorted(prompts.routed_names())[0]
    planner.ActionPlanner(model=routed, base_url=HOSTED, api_key="SYNTHETIC")
    planner.ActionPlanner(model="captcha", base_url="http://127.0.0.1:8000/v1", api_key="SYNTHETIC")
    assert "older model" not in capsys.readouterr().err


def test_a_driver_that_already_warned_keeps_the_engine_quiet(monkeypatch, capsys):
    monkeypatch.setenv("CAPTCHA_KRAKEN_MODEL_WARNING", "0")
    planner.ActionPlanner(model="captcha", base_url=HOSTED, api_key="SYNTHETIC")
    assert "older model" not in capsys.readouterr().err


def test_both_ports_print_the_same_words():
    source = JS_SOURCE.read_text()
    block = re.search(r"export const LEGACY_MODEL_WARNING =(.*?);", source, re.S)
    assert block, "model-name.ts no longer exports LEGACY_MODEL_WARNING"
    js_text = "".join(m.group(2) for m in re.finditer(r"(['\"])(.*?)\1", block.group(1)))
    assert js_text == prompts.LEGACY_MODEL_WARNING
