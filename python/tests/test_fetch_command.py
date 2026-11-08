import json
import sys

import pytest

from captchakraken import cli, config, updater


def test_plan_targets_hf_org_and_configured_repos():
    p = updater.plan()
    assert p["hf_org"] == "https://huggingface.co/CaptchaKraken"
    assert p["lora_adapter"] == config.lora_adapter()
    assert p["base_model"] == config.base_model()
    assert p["downloads"][0][-1] == p["lora_adapter"]
    assert p["downloads"][1][-1] == p["base_model"]
    assert p["engine_upgrade"][:4] == [sys.executable, "-m", "pip", "install"]
    assert "vllm" in p["engine_upgrade"]


def test_plan_scoping_flags():
    assert updater.plan(weights=False)["downloads"] == []
    assert updater.plan(engine=False)["engine_upgrade"] is None


def test_plan_respects_overrides():
    p = updater.plan(base="acme/base", lora="acme/lora")
    assert p["base_model"] == "acme/base"
    assert p["lora_adapter"] == "acme/lora"
    assert [d[-1] for d in p["downloads"]] == ["acme/lora", "acme/base"]


def test_fetch_dry_run_is_side_effect_free(monkeypatch):
    calls = []
    monkeypatch.setattr(updater.subprocess, "run", lambda *a, **k: calls.append(a))
    out = updater.fetch(dry_run=True)
    assert out["dry_run"] is True
    assert calls == []


def test_cli_fetch_dry_run(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["captchakraken", "fetch", "--dry-run"])
    cli.main()
    out = json.loads(capsys.readouterr().out)
    assert out["dry_run"] is True


def test_cli_update_alias(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["captchakraken", "update", "--dry-run"])
    cli.main()
    assert json.loads(capsys.readouterr().out)["dry_run"] is True


def test_cli_fetch_flag_mapping(monkeypatch):
    seen = {}
    monkeypatch.setattr(updater, "fetch", lambda **kw: seen.update(kw) or {})
    monkeypatch.setattr(
        sys, "argv",
        ["captchakraken", "fetch", "--engine-only", "--no-restart", "--dry-run"],
    )
    cli.main()
    assert seen == {"weights": False, "engine": True, "restart": False, "dry_run": True}


def test_cli_fetch_rejects_unknown_flag(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["captchakraken", "fetch", "--bogus"])
    with pytest.raises(SystemExit) as ei:
        cli.main()
    assert ei.value.code == 2


def test_cli_fetch_rejects_conflicting_flags(monkeypatch):
    monkeypatch.setattr(
        sys, "argv", ["captchakraken", "fetch", "--weights-only", "--engine-only"],
    )
    with pytest.raises(SystemExit) as ei:
        cli.main()
    assert ei.value.code == 2


@pytest.mark.parametrize("command", ["start", "stop", "status", "demo", "server"])
def test_a_command_help_prints_and_never_acts(command, monkeypatch, capsys, tmp_path):
    # `stop --help` once stopped the server and `demo --help` built a venv.
    monkeypatch.setenv("CAPTCHA_KRAKEN_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setattr(sys, "argv", ["captchakraken", command, "--help"])
    for name in ("run", "Popen"):
        monkeypatch.setattr(cli.subprocess, name, lambda *a, **k: pytest.fail("help ran a command"))
    try:
        cli.main()
    except SystemExit as e:
        assert e.code in (0, None)
    assert command in capsys.readouterr().out
    assert not (tmp_path / "state").exists()


def test_bare_captchakraken_lists_the_commands(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["captchakraken"])
    with pytest.raises(SystemExit) as ei:
        cli.main()
    assert ei.value.code == 0
    out = capsys.readouterr().out
    for name in ("fetch", "start", "stop", "status", "demo"):
        assert name in out
