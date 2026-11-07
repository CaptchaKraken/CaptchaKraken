"""The 2026-07-18 retrain shipped a prompt drift that failed every drag as "unsupported" with CI green; the hashes resolve through models.json, not module constants."""

import hashlib

from captchakraken import config, prompts

_PINNED = prompts.resolve(config.pinned()["lora_adapter"])

SERVING_PROMPTS = {
    "PIXEL_ACTION_PROMPT": _PINNED.action_prompt,
    "SELECT_GRID_PROMPT": _PINNED.grid_template,
}


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def test_manifest_has_every_field_config_reads():
    manifest = config.pinned()
    for key in ("base_model", "lora_adapter", "lora_revision", "lora_name", "prompt_sha256"):
        assert key in manifest, f"pinned_model.json is missing '{key}'"


def test_config_defaults_come_from_the_current_registry(monkeypatch):
    for var in (
        "CAPTCHA_BASE_MODEL",
        "CAPTCHA_LORA_ADAPTER",
        "CAPTCHA_LORA_REVISION",
        "CAPTCHA_LORA_NAME",
    ):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("VLLM_BASE_URL", "http://127.0.0.1:8000/v1")

    model = prompts.registry()["models"][prompts.latest_model()]
    assert config.base_model() == model["base_model"]
    assert config.lora_adapter() == prompts.latest_model()
    assert config.lora_revision() == model["lora_revision"]
    assert config.lora_name() == model["lora_name"]


def test_env_still_overrides_the_pin(monkeypatch):
    monkeypatch.setenv("CAPTCHA_LORA_ADAPTER", "someone-else/their-adapter")
    assert config.lora_adapter() == "someone-else/their-adapter"


def test_every_guarded_prompt_is_listed_in_the_manifest():
    pinned_names = set(config.pinned()["prompt_sha256"])
    assert pinned_names == set(SERVING_PROMPTS), (
        "pinned_model.json prompt_sha256 keys drifted from the prompts this test "
        "guards. A new serving prompt must be pinned too — an unpinned prompt is "
        "exactly the hole that let the 2026-07-18 drag regression ship."
    )


def test_serving_prompts_match_their_pinned_hashes():
    expected = config.pinned()["prompt_sha256"]
    drifted = {
        name: (expected[name], _sha256(text))
        for name, text in SERVING_PROMPTS.items()
        if _sha256(text) != expected[name]
    }
    assert not drifted, (
        "A serving prompt changed but pinned_model.json was not updated:\n"
        + "\n".join(f"  {n}: pinned {p[:12]}… now {a[:12]}…" for n, (p, a) in drifted.items())
        + "\n\nThe LoRA is trained to answer one exact prompt. If this change is "
        "intentional, confirm the pinned adapter still expects the new wording, "
        "run the Tier 2 static-image gate, then update prompt_sha256."
    )
