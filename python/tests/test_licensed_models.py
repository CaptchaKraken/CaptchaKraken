"""A licensed model downloads from its gated Hub repo with the holder's own token; a refusal from the Hub says where the licence is sold, not "you are not logged in"."""

import sys

import httpx
import pytest
from huggingface_hub.errors import GatedRepoError, HfHubHTTPError, LocalEntryNotFoundError, RepositoryNotFoundError

from captchakraken import cli, prompts, updater

LICENSED_REPO = "CaptchaKraken/Abyss"
LICENSED_SERVED = "abyss"
PUBLIC_REPO = "CaptchaKraken/CaptchaKraken-Lora-v1.2"


def test_the_licensed_model_is_registered_as_licensed():
    assert prompts.availability(LICENSED_REPO) == prompts.LICENSED
    assert prompts.is_licensed(LICENSED_REPO)


def test_a_published_model_is_public():
    assert prompts.availability(PUBLIC_REPO) == prompts.PUBLIC
    assert not prompts.is_licensed(PUBLIC_REPO)


def test_an_unregistered_model_is_public():
    assert not prompts.is_licensed("some-stranger/their-own-lora")


def test_an_unrecognised_availability_reads_as_licensed(monkeypatch):
    monkeypatch.setattr(prompts, "_REGISTRY", {
        "models": {"org/m": {"availability": "licenced"}}})
    assert prompts.is_licensed("org/m")


def test_the_served_name_resolves_to_the_licensed_entry():
    assert prompts.canonical_model_id(LICENSED_SERVED) == LICENSED_REPO


def test_the_served_name_carries_its_own_prompt_generation():
    assert prompts.resolve(LICENSED_SERVED) == prompts.resolve(LICENSED_REPO)
    assert prompts.resolve(LICENSED_SERVED).source == f"registry:{LICENSED_REPO}"


def test_the_served_name_is_licensed_too():
    assert prompts.is_licensed(LICENSED_SERVED)


def _refusal(error_class, status):
    response = httpx.Response(status, request=httpx.Request("GET", f"https://huggingface.co/api/models/{LICENSED_REPO}"))
    return error_class(f"{status} refused", response=response)


def _fetch_licensed(monkeypatch, download):
    monkeypatch.setattr("huggingface_hub.snapshot_download", download)
    monkeypatch.setattr(updater, "_run", lambda cmd: None)
    return updater.fetch(weights=True, engine=False, restart=False, base=PUBLIC_REPO, lora=LICENSED_REPO)


def test_the_dry_run_lists_a_licensed_model_as_needing_a_token():
    plan = updater.fetch(dry_run=True, engine=False, restart=False, base=PUBLIC_REPO, lora=LICENSED_REPO)
    assert plan["needs_auth"] == [LICENSED_REPO]
    assert any(cmd[-1] == LICENSED_REPO for cmd in plan["downloads"])


def test_the_served_name_plans_the_repo_it_names():
    plan = updater.plan(engine=False, base=PUBLIC_REPO, lora=LICENSED_SERVED)
    assert plan["lora_adapter"] == LICENSED_REPO
    assert plan["needs_auth"] == [LICENSED_REPO]


def test_a_licence_holder_downloads_the_weights(monkeypatch):
    pulled = []
    out = _fetch_licensed(monkeypatch, lambda repo_id, **kw: pulled.append(repo_id) or "/cache")
    assert pulled == [LICENSED_REPO]
    assert out["fetched_weights"] is True


@pytest.mark.parametrize("refusal", [
    _refusal(GatedRepoError, 401),
    _refusal(GatedRepoError, 403),
    _refusal(RepositoryNotFoundError, 401),
    _refusal(HfHubHTTPError, 403),
], ids=["gated-no-token", "gated-not-approved", "not-found", "forbidden"])
def test_a_hub_refusal_points_at_the_licence(monkeypatch, refusal):
    def refuse(repo_id, **kw):
        raise refusal

    with pytest.raises(updater.LicensedModelError) as exc:
        _fetch_licensed(monkeypatch, refuse)
    message = str(exc.value)
    assert "https://captchakraken.com/plans" in message
    assert "Abyss Licence" in message
    assert "api.captchakraken.com" in message
    assert exc.value.__cause__ is refusal


def test_a_refusal_wrapped_by_snapshot_download_still_points_at_the_licence(monkeypatch):
    def refuse(repo_id, **kw):
        raise LocalEntryNotFoundError("no cached snapshot") from _refusal(HfHubHTTPError, 403)

    with pytest.raises(updater.LicensedModelError):
        _fetch_licensed(monkeypatch, refuse)


def test_a_hub_outage_is_not_blamed_on_the_licence(monkeypatch):
    outage = _refusal(HfHubHTTPError, 503)

    def fail(repo_id, **kw):
        raise outage

    with pytest.raises(HfHubHTTPError) as exc:
        _fetch_licensed(monkeypatch, fail)
    assert exc.value is outage


def test_a_public_model_still_downloads_through_the_cli(monkeypatch):
    ran = []
    monkeypatch.setattr(updater, "_run", ran.append)
    updater.fetch(weights=True, engine=False, restart=False, base=PUBLIC_REPO, lora=PUBLIC_REPO)
    assert [cmd[-1] for cmd in ran] == [PUBLIC_REPO, PUBLIC_REPO]


def test_skipping_the_weights_downloads_nothing():
    assert updater.plan(weights=False, lora=LICENSED_REPO)["downloads"] == []


def test_the_documented_command_fetches_the_licensed_repo_and_its_base(monkeypatch, capsys):
    pulled, ran = [], []
    monkeypatch.setenv("CAPTCHA_LORA_ADAPTER", LICENSED_REPO)
    monkeypatch.delenv("CAPTCHA_BASE_MODEL", raising=False)
    monkeypatch.setattr("huggingface_hub.snapshot_download", lambda repo_id, **kw: pulled.append(repo_id))
    monkeypatch.setattr(updater, "_run", ran.append)
    monkeypatch.setattr(sys, "argv", ["captchakraken", "fetch", "--weights-only", "--no-restart"])
    cli.main()
    assert pulled == [LICENSED_REPO]
    assert [cmd[-1] for cmd in ran] == [prompts.registered_models()[LICENSED_REPO]["base_model"]]
