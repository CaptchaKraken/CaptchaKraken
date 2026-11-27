"""`captchakraken fetch abyss`: a licence holder sets up Abyss in one command, and anyone the Hub will refuse learns why before torch and vLLM download."""

import os
import stat
import sys
import types
from pathlib import Path

import pytest
import requests

from captchakraken import cli, prompts, selfhost, updater

ABYSS_Q4 = "CaptchaKraken/AbyssV2-q4"
ABYSS = "CaptchaKraken/AbyssV2"
GPU = selfhost.Gpu(0, "RTX 5090", 32607, 30000, 12.0)


@pytest.fixture
def hub_home(tmp_path, monkeypatch):
    monkeypatch.setenv("HF_HOME", str(tmp_path / "hf"))
    for name in ("HF_TOKEN", "HUGGING_FACE_HUB_TOKEN", "HF_TOKEN_PATH"):
        monkeypatch.delenv(name, raising=False)
    return tmp_path / "hf"


def _hub(user="licensee", readable=True, status=None):
    """A fake huggingface.co: whoami answers for one token, the gated file answers by `readable`."""
    calls = []

    def request(method, url, headers=None, **kw):
        calls.append((method, url, (headers or {}).get("Authorization")))
        if status is not None:
            return types.SimpleNamespace(status_code=status, json=lambda: {})
        if url.endswith("/api/whoami-v2"):
            ok = headers.get("Authorization") == "Bearer hf_good"
            return types.SimpleNamespace(status_code=200 if ok else 401, json=lambda: {"name": user})
        return types.SimpleNamespace(status_code=200 if readable else 403, json=lambda: {})

    request.calls = calls
    return request


def test_abyss_is_offered_and_licensed():
    offered = {m.repo: m for m in selfhost.MODELS}
    for repo in (ABYSS_Q4, ABYSS):
        assert repo in offered
        assert offered[repo].licensed
        assert prompts.resolve(repo).pointer
    assert not [m for m in selfhost.MODELS if m.licensed and m.repo == prompts.latest_model()]


def test_abyss_by_its_short_name_is_the_q4():
    choice = selfhost._from_flags([GPU], {}, "abyss", None, None)
    assert choice.model.repo == ABYSS_Q4
    assert selfhost._from_flags([GPU], {}, "AbyssV2", None, None).model.repo == ABYSS


def test_the_cli_takes_the_model_as_a_word(monkeypatch):
    seen = {}
    monkeypatch.setattr(selfhost, "fetch", lambda **kw: seen.update(kw) or 0)
    monkeypatch.setattr(sys, "argv", ["captchakraken", "fetch", "abyss"])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 0
    assert seen["model"] == "abyss" and seen["yes"] is True


def test_no_token_without_a_terminal_says_how_to_sign_in(hub_home):
    with pytest.raises(RuntimeError) as exc:
        selfhost.ensure_access(ABYSS_Q4, interactive=False, http=_hub())
    message = str(exc.value)
    assert "HF_TOKEN" in message and "hf auth login" in message
    assert updater.PLANS_URL in message


def test_a_pasted_token_is_checked_then_saved_for_the_download(hub_home):
    hub = _hub()
    user = selfhost.ensure_access(ABYSS_Q4, interactive=True, http=hub, read_secret=lambda prompt: " hf_good\n")
    assert user == "licensee"
    saved = hub_home / "token"
    assert saved.read_text() == "hf_good"
    assert stat.S_IMODE(os.stat(saved).st_mode) == 0o600
    assert any(url.endswith(f"/{ABYSS_Q4}/resolve/main/config.json") for _, url, _ in hub.calls)


def test_a_saved_login_is_used_without_asking(hub_home):
    hub_home.mkdir(parents=True)
    (hub_home / "token").write_text("hf_good\n")

    def never(prompt):
        raise AssertionError("asked for a token it already had")

    assert selfhost.ensure_access(ABYSS_Q4, interactive=True, http=_hub(), read_secret=never) == "licensee"


def test_an_account_without_access_is_named_and_sent_to_the_plans_page(hub_home, monkeypatch):
    monkeypatch.setenv("HF_TOKEN", "hf_good")
    with pytest.raises(RuntimeError) as exc:
        selfhost.ensure_access(ABYSS_Q4, interactive=False, http=_hub(user="someone", readable=False))
    message = str(exc.value)
    assert "someone" in message
    assert updater.PLANS_URL in message
    assert not (hub_home / "token").exists()


def test_a_rejected_token_is_not_saved(hub_home):
    with pytest.raises(RuntimeError) as exc:
        selfhost.ensure_access(ABYSS_Q4, interactive=True, http=_hub(), read_secret=lambda prompt: "hf_typo")
    assert "did not accept" in str(exc.value)
    assert not (hub_home / "token").exists()


def test_a_hub_outage_is_not_blamed_on_the_licence(hub_home, monkeypatch):
    monkeypatch.setenv("HF_TOKEN", "hf_good")
    with pytest.raises(RuntimeError) as exc:
        selfhost.ensure_access(ABYSS_Q4, interactive=False, http=_hub(status=503))
    assert "503" in str(exc.value)
    assert updater.PLANS_URL not in str(exc.value)


def test_an_unreachable_hub_is_a_plain_error(hub_home, monkeypatch):
    monkeypatch.setenv("HF_TOKEN", "hf_good")

    def offline(*a, **k):
        raise requests.ConnectionError("no route")

    with pytest.raises(RuntimeError) as exc:
        selfhost.ensure_access(ABYSS_Q4, interactive=False, http=offline)
    assert "reach Hugging Face" in str(exc.value)


def test_a_refused_licence_installs_nothing(hub_home, monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(selfhost, "detect_gpus", lambda: [GPU])
    monkeypatch.setattr(selfhost.config, "selfhost", lambda: {})
    monkeypatch.setattr(selfhost, "_HUB_REQUEST", _hub(readable=False))
    monkeypatch.setenv("HF_TOKEN", "hf_good")
    monkeypatch.setattr(selfhost, "install", lambda *a: pytest.fail("installed without access"))
    assert selfhost.fetch(yes=True, model="abyss") == 1


def test_a_free_model_never_asks_the_hub(hub_home, monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(selfhost, "detect_gpus", lambda: [GPU])
    monkeypatch.setattr(selfhost.config, "selfhost", lambda: {})
    monkeypatch.setattr(selfhost, "_HUB_REQUEST", lambda *a, **k: pytest.fail("asked the Hub"))
    monkeypatch.setattr(selfhost, "install", lambda choice, saved: {"model": choice.model.repo})
    monkeypatch.setattr(selfhost, "_summary", lambda values: None)
    assert selfhost.fetch(yes=True, model="MidnightV2-4B-q4") == 0


YIDUN = "CaptchaKraken/CaptchaKraken-Custom-Yidun-Commision"


def test_the_yidun_model_is_fetched_by_name_and_never_offered_in_the_menu():
    assert selfhost._from_flags([GPU], {}, "custom-yidun", None, None).model.repo == YIDUN
    assert prompts.resolve(YIDUN).pointer and prompts.is_licensed(YIDUN)
    assert YIDUN not in {m.repo for m in selfhost.listed_models()}
    with pytest.raises(RuntimeError) as exc:
        selfhost._from_flags([GPU], {}, "nonsense", None, None)
    assert "Yidun" not in str(exc.value)


def test_the_yidun_model_sends_a_refused_account_to_the_team_not_the_plans_page(hub_home, monkeypatch):
    monkeypatch.setenv("HF_TOKEN", "hf_good")
    model = next(m for m in selfhost.MODELS if m.repo == YIDUN)
    with pytest.raises(RuntimeError) as exc:
        selfhost.ensure_access(YIDUN, interactive=False, http=_hub(user="someone", readable=False), access=model.access)
    message = str(exc.value)
    assert "someone" in message and "access token the CaptchaKraken team sent" in message
    assert updater.PLANS_URL not in message


def test_a_refused_yidun_account_installs_nothing(hub_home, monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(selfhost, "detect_gpus", lambda: [GPU])
    monkeypatch.setattr(selfhost.config, "selfhost", lambda: {})
    monkeypatch.setattr(selfhost, "_HUB_REQUEST", _hub(readable=False))
    monkeypatch.setenv("HF_TOKEN", "hf_good")
    monkeypatch.setattr(selfhost, "install", lambda *a: pytest.fail("installed without access"))
    assert selfhost.fetch(yes=True, model="custom-yidun") == 1


def test_the_yidun_repo_is_probed_and_downloaded_from_its_q4_folder_only(hub_home, monkeypatch, tmp_path):
    """The repo also holds bf16/ and lora/: a fetch that took the whole repo would pull 13 GB, and a probe of the root config would read as no access."""
    monkeypatch.setenv("HF_TOKEN", "hf_good")
    model = next(m for m in selfhost.MODELS if m.repo == YIDUN)
    assert model.subfolder == "q4"
    hub = _hub()
    selfhost.ensure_access(YIDUN, interactive=False, http=hub, access=model.access, subfolder=model.subfolder)
    assert any(url.endswith(f"/{YIDUN}/resolve/main/q4/config.json") for _, url, _ in hub.calls)

    fake = tmp_path / "huggingface_hub"
    fake.mkdir()
    (fake / "__init__.py").write_text(
        "def snapshot_download(repo, allow_patterns=None):\n"
        "    print('patterns', allow_patterns)\n"
        "    return '/snap/' + repo\n")
    monkeypatch.setenv("PYTHONPATH", str(tmp_path))
    assert selfhost.download(Path(sys.executable), YIDUN, "q4") == f"/snap/{YIDUN}/q4"
    assert selfhost.download(Path(sys.executable), "CaptchaKraken/AbyssV2-q4") == "/snap/CaptchaKraken/AbyssV2-q4"
