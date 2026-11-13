"""Both `private` and `licensed` weights sit behind a Hub token; only `licensed` turns a refusal into a pointer to the licence. The served alias must resolve its own prompts."""

from captchakraken import prompts, updater

PRIVATE_REPO = "CaptchaKraken/Abyss-text"
PRIVATE_SERVED = "abyss-text"
LICENSED_REPO = "CaptchaKraken/Abyss"
PUBLIC_REPO = "CaptchaKraken/CaptchaKraken-Lora-v1.2"


def test_the_private_model_is_registered_private():
    assert prompts.availability(PRIVATE_REPO) == prompts.PRIVATE


def test_private_and_licensed_both_need_a_token():
    assert not prompts.is_licensed(PRIVATE_REPO)
    assert prompts.requires_auth(PRIVATE_REPO)

    assert prompts.is_licensed(LICENSED_REPO)
    assert prompts.requires_auth(LICENSED_REPO)

    assert not prompts.is_licensed(PUBLIC_REPO)
    assert not prompts.requires_auth(PUBLIC_REPO)


def test_an_unrecognised_availability_still_fails_closed(monkeypatch):
    monkeypatch.setattr(prompts, "_REGISTRY", {
        "models": {"org/m": {"availability": "privte"}}})
    assert prompts.is_licensed("org/m")


def test_fetch_plans_a_download_for_a_private_model():
    plan = updater.plan(weights=True, engine=False, restart=False,
                        base=PUBLIC_REPO, lora=PRIVATE_REPO)
    assert any(PRIVATE_REPO in " ".join(cmd) for cmd in plan["downloads"])


def test_the_plan_says_which_repos_need_a_token():
    plan = updater.plan(weights=True, engine=False, restart=False,
                        base=PUBLIC_REPO, lora=PRIVATE_REPO)
    assert plan["needs_auth"] == [PRIVATE_REPO]


def test_a_licensed_model_is_planned_like_a_private_one():
    plan = updater.plan(weights=True, engine=False, restart=False,
                        base=PUBLIC_REPO, lora=LICENSED_REPO)
    assert plan["needs_auth"] == [LICENSED_REPO]


def test_a_public_only_plan_needs_no_token():
    plan = updater.plan(weights=True, engine=False, restart=False,
                        base=PUBLIC_REPO, lora=PUBLIC_REPO)
    assert plan["needs_auth"] == []


def test_the_expert_name_resolves_to_its_own_entry():
    assert prompts.canonical_model_id(PRIVATE_SERVED) == PRIVATE_REPO
    assert prompts.availability(PRIVATE_SERVED) == prompts.PRIVATE
