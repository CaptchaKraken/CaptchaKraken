"""`fetch`'s menu, what it writes, and the client and server finding everything from that one file."""

import json
import subprocess
import sys
import types

import pytest

from captchakraken import config, prompts, selfhost, server_manager


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("CAPTCHA_KRAKEN_STATE_DIR", str(tmp_path))
    for name in ("VLLM_BASE_URL", "CAPTCHA_KRAKEN_API_KEY", "VLLM_API_KEY", "CAPTCHA_BASE_MODEL", "CAPTCHA_LORA_ADAPTER",
                 "CAPTCHA_LORA_NAME", "CAPTCHA_POINTER_DETECTOR", "VLLM_PORT", "VLLM_GPU_MEMORY_UTILIZATION",
                 "VLLM_MAX_CUDAGRAPH_CAPTURE_SIZE", "CUDA_VISIBLE_DEVICES"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(server_manager, "STOPPED_FILE", tmp_path / "server.stopped")
    monkeypatch.setattr(server_manager, "PID_FILE", tmp_path / "vllm.pid")
    return tmp_path


SMALL = selfhost.Gpu(1, "RTX 5060", 8151, 7900)
LARGE = selfhost.Gpu(0, "RTX 5090", 32607, 2400)


def _write(**over):
    choice = selfhost.Choice(selfhost.MODELS[0], SMALL, selfhost.FIRST_SOLVE)
    values = selfhost.settings(choice, "/weights/m", "/weights/d.pt", {"port": 8123})
    values.update(over)
    selfhost.write_settings(values)
    return values


def test_every_offered_model_is_registered_and_is_a_pointer_model():
    for model in selfhost.MODELS:
        assert model.repo in prompts.registered_models(), model.repo
        assert prompts.resolve(model.repo).pointer, model.repo


def test_the_default_offer_is_the_current_default_model():
    assert selfhost.MODELS[0].repo == prompts.latest_model()


def test_a_model_whose_heads_do_not_load_is_not_offered():
    assert not [m for m in selfhost.MODELS if "Sunlight" in m.repo]


def test_nvidia_smi_is_read_and_its_absence_is_no_gpus():
    def smi(*a, **k):
        return types.SimpleNamespace(returncode=0, stdout="0, NVIDIA GeForce RTX 5090, 32607, 2400\n"
                                                          "1, NVIDIA GeForce RTX 5060, 8151, 7900\n")
    assert [g.index for g in selfhost.detect_gpus(smi)] == [0, 1]
    assert selfhost.detect_gpus(smi)[1].total_mib == 8151

    def missing(*a, **k):
        raise FileNotFoundError
    assert selfhost.detect_gpus(missing) == []


def test_an_eight_gigabyte_card_fits_what_is_sold_for_eight():
    midnight_q4, _, midnight = selfhost.MODELS
    assert selfhost._fits(midnight_q4, SMALL)
    assert not selfhost._fits(midnight, SMALL)
    assert selfhost._fits(midnight, LARGE)


def test_a_card_too_full_to_start_says_so():
    assert selfhost._busy_note(selfhost.MODELS[0], LARGE)
    assert not selfhost._busy_note(selfhost.MODELS[0], SMALL)


def test_a_small_card_gets_the_settings_that_let_it_start(home):
    choice = selfhost.Choice(selfhost.MODELS[0], SMALL, selfhost.ALWAYS_ON)
    small = selfhost.settings(choice, "m", "d", {"port": 1})
    assert (small["gpu_memory_utilization"], small["max_cudagraph_capture_size"]) == (0.72, 16)
    large = selfhost.settings(choice._replace(gpu=LARGE), "m", "d", {"port": 1})
    assert (large["gpu_memory_utilization"], large["max_cudagraph_capture_size"]) == (0.80, None)
    twilight = next(m for m in selfhost.MODELS if m.repo.endswith("TwilightV2-2B"))
    # Measured on a 5060: at 0.72 its weights and activations left 0.01 GiB of the 0.11 GiB KV cache one request needs.
    assert selfhost.settings(choice._replace(model=twilight), "m", "d", {"port": 1})["gpu_memory_utilization"] == 0.80


def test_a_rerun_keeps_the_key_and_the_port(home):
    first = _write()
    choice = selfhost.Choice(selfhost.MODELS[1], SMALL, selfhost.ALWAYS_ON)
    second = selfhost.settings(choice, "m", "d", first)
    assert (second["key"], second["port"]) == (first["key"], first["port"])


def test_only_its_owner_can_read_the_file_holding_the_key(home):
    _write()
    assert (config.selfhost_path().stat().st_mode & 0o777) == 0o600


def test_with_no_env_at_all_the_client_finds_the_server_and_key(home):
    values = _write()
    assert config.base_url() == "http://127.0.0.1:8123/v1"
    assert config.api_key() == values["key"]
    assert config.lora_adapter() == selfhost.MODELS[0].repo
    assert config.lora_name() == "captcha-pointer"
    assert config.port() == 8123


def test_it_beats_a_hosted_credentials_file_and_a_stale_key(home, monkeypatch):
    values = _write()
    (home / "credentials").write_text("CAPTCHA_KRAKEN_API_KEY=ck_live_x\nVLLM_BASE_URL=https://api.captchakraken.com/v1\n")
    monkeypatch.setenv("CAPTCHA_KRAKEN_API_KEY", "ck_live_stale")
    assert config.base_url() == "http://127.0.0.1:8123/v1"
    assert config.api_key() == values["key"]


def test_an_endpoint_named_in_the_environment_owns_every_setting(home, monkeypatch):
    _write()
    monkeypatch.setenv("VLLM_BASE_URL", "https://api.captchakraken.com/v1")
    monkeypatch.setenv("CAPTCHA_KRAKEN_API_KEY", "ck_live_x")
    assert config.api_key() == "ck_live_x"
    assert config.selfhost_active() == {}
    assert config.pointer_detector() is None


def test_the_server_runs_from_the_runtime_on_the_chosen_gpu(home, monkeypatch):
    values = _write()
    cmd = server_manager.build_serve_command()
    assert cmd[0] == str(home / "runtime" / "bin" / "python")
    assert cmd[cmd.index("--model") + 1] == "/weights/m"
    assert cmd[cmd.index("--detector") + 1] == "/weights/d.pt"
    assert cmd[cmd.index("--gpu-memory-utilization") + 1] == "0.72"
    assert cmd[cmd.index("--max-cudagraph-capture-size") + 1] == "16"
    env = server_manager._serve_env()
    assert env["CUDA_VISIBLE_DEVICES"] == "1" and env["CUDA_DEVICE_ORDER"] == "PCI_BUS_ID"
    assert env["VLLM_API_KEY"] == values["key"]


def test_a_stopped_server_says_so_instead_of_starting(home, monkeypatch):
    _write()
    monkeypatch.setattr(server_manager, "is_healthy", lambda *a, **k: False)
    server_manager.STOPPED_FILE.touch()
    with pytest.raises(RuntimeError, match="captchakraken start"):
        server_manager.ensure_server()


def test_a_cold_server_is_started_by_a_pointer_solve(home, monkeypatch):
    from captchakraken import planner as planner_module

    _write()
    started = []
    monkeypatch.setattr(planner_module, "ensure_server", lambda url: started.append(url))

    class Reply:
        ok = True

        @staticmethod
        def json():
            return {"answer": {"action": "click", "points": [[1, 1]]}, "actions": []}

    planner = planner_module.ActionPlanner()
    monkeypatch.setattr(planner, "_http", types.SimpleNamespace(post=lambda *a, **k: Reply()))
    planner._ask_pointer({})
    planner._ask_pointer({})
    assert started == ["http://127.0.0.1:8123/v1"], "once per planner, before the first request"


def test_the_terminal_menu_is_not_entered_without_a_terminal(home, monkeypatch, capsys):
    monkeypatch.setattr(selfhost, "detect_gpus", lambda: [SMALL])
    monkeypatch.setattr(sys, "platform", "linux")
    assert selfhost.fetch() == 2
    assert "--yes" in capsys.readouterr().err


def test_no_gpu_points_at_the_hosted_api(home, monkeypatch, capsys):
    monkeypatch.setattr(selfhost, "detect_gpus", lambda: [])
    monkeypatch.setattr(sys, "platform", "linux")
    assert selfhost.fetch(yes=True) == 1
    assert "hosted" in capsys.readouterr().err.lower()


def test_flags_choose_and_an_unknown_model_is_named(home):
    choice = selfhost._from_flags([LARGE, SMALL], {}, "TwilightV2-2B", 1, "always")
    assert (choice.model.title, choice.gpu.index, choice.startup) == ("Twilight V2 2B", 1, "always")
    with pytest.raises(RuntimeError, match="MidnightV2-4B-q4"):
        selfhost._from_flags([SMALL], {}, "nope", None, None)


def test_the_unit_reads_the_same_file_as_everyone_else(home):
    _write(startup="always")
    unit = server_manager._unit_text()
    assert f"CAPTCHA_KRAKEN_STATE_DIR={home}" in unit
    assert "captchakraken.cli server run" in unit
    assert json.loads(config.selfhost_path().read_text())["key"] not in unit
