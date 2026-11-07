"""A pin once read base and lora_name off `latest`, downloaded a 9B base for a 27B adapter and failed inside vLLM as a shape mismatch. An unregistered pin still falls back to `latest`; the endpoint is pinned here because base_url() falls through to the credentials file."""

import pytest

from captchakraken import config, prompts

PINS = [
    ("CaptchaKraken/Abyss-27B", "Qwen/Qwen3.8-27B", "abyss-27b"),
    ("CaptchaKraken/Abyss-grid", "Qwen/Qwen3.5-9B", "abyss-grid"),
    ("CaptchaKraken/Abyss-text", "Qwen/Qwen3.5-9B", "abyss-text"),
    ("CaptchaKraken/CaptchaKrakenV1_Lora",
     "RedHatAI/Qwen3.5-9B-FP8-dynamic", "captcha"),
]


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    for var in ("CAPTCHA_LORA_ADAPTER", "CAPTCHA_LORA_NAME", "CAPTCHA_BASE_MODEL",
                "CAPTCHA_LORA_REVISION"):
        monkeypatch.delenv(var, raising=False)
    prompts.clear_cache()


@pytest.mark.parametrize("pin, base, name", PINS)
def test_a_pinned_adapter_brings_its_own_base_and_served_name(monkeypatch, pin, base, name):
    monkeypatch.setenv("VLLM_BASE_URL", "http://127.0.0.1:8000/v1")
    monkeypatch.setenv("CAPTCHA_LORA_ADAPTER", pin)
    assert config.lora_adapter() == pin
    assert config.base_model() == base
    assert config.lora_name() == name


def test_pinning_the_served_name_alone_resolves_the_same_entry():
    import os
    os.environ["CAPTCHA_LORA_NAME"] = "abyss-grid"
    try:
        assert config.base_model() == "Qwen/Qwen3.5-9B"
        assert config.lora_name() == "abyss-grid"
    finally:
        del os.environ["CAPTCHA_LORA_NAME"]


def test_an_unpinned_client_still_resolves_latest(monkeypatch):
    monkeypatch.setenv("VLLM_BASE_URL", "http://127.0.0.1:8000/v1")
    latest = prompts.latest_model()
    entry = prompts.registered_models()[latest]
    assert config.lora_adapter() == latest
    assert config.base_model() == entry["base_model"]
    assert config.lora_name() == entry["lora_name"]


def test_our_own_endpoint_gets_the_hosted_model_instead(monkeypatch):
    monkeypatch.delenv("CAPTCHA_LORA_NAME", raising=False)
    monkeypatch.setenv("VLLM_BASE_URL", "https://api.captchakraken.com/v1")
    registry = prompts.registered_models()
    served = config.lora_name()
    assert served == registry[prompts.latest_model()]["lora_name"], (
        "v2 serves the same public pointer model from the hosted API and self-hosting")
    assert config.is_hosted_endpoint()


def test_an_unregistered_pin_still_falls_back_to_latest(monkeypatch):
    monkeypatch.setenv("CAPTCHA_LORA_ADAPTER", "some-stranger/their-own-lora")
    entry = prompts.registered_models()[prompts.latest_model()]
    assert config.lora_adapter() == "some-stranger/their-own-lora"
    assert config.base_model() == entry["base_model"]


def test_an_explicit_env_override_still_wins(monkeypatch):
    monkeypatch.setenv("CAPTCHA_LORA_ADAPTER", "CaptchaKraken/Abyss-27B")
    monkeypatch.setenv("CAPTCHA_BASE_MODEL", "Qwen/Qwen3.5-9B")
    assert config.base_model() == "Qwen/Qwen3.5-9B"
