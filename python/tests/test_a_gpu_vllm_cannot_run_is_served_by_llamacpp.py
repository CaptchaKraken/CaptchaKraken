"""A GTX 1070 (compute capability 6.1) self-hosts: the vLLM build has no kernels for it, so llama.cpp runs a GGUF build."""

import json
import re
import subprocess
import sys
import types
from pathlib import Path

import pytest

from captchakraken import selfhost, server_manager
from captchakraken.pointer import layout as L
from captchakraken.pointer.llamacpp_engine import MARKER, LlamaCppPointerService

GTX_1070 = selfhost.Gpu(0, "NVIDIA GeForce GTX 1070", 8192, 8000, 6.1, "0000:01:00.0")
V100 = selfhost.Gpu(1, "Tesla V100-SXM2-16GB", 16384, 16000, 7.0, "0000:02:00.0")
T4 = selfhost.Gpu(2, "Tesla T4", 15360, 15000, 7.5, "0000:03:00.0")
BY_NAME = {m.repo.split("/")[-1]: m for m in selfhost.MODELS}


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("CAPTCHA_KRAKEN_STATE_DIR", str(tmp_path))
    for name in ("VLLM_BASE_URL", "CAPTCHA_KRAKEN_API_KEY", "CAPTCHA_LORA_ADAPTER", "CAPTCHA_POINTER_ENGINE",
                 "CAPTCHA_POINTER_STATES"):
        monkeypatch.delenv(name, raising=False)
    return tmp_path


def test_the_engine_follows_the_compute_capability():
    assert (GTX_1070.engine, V100.engine, T4.engine) == ("llamacpp", "llamacpp", "vllm")


def test_nvidia_smi_reports_the_compute_capability_and_the_pci_address_vulkan_uses():
    def smi(*a, **k):
        return types.SimpleNamespace(returncode=0, stdout="0, NVIDIA GeForce GTX 1070, 8192, 8000, 6.1, 00000000:01:00.0\n",
                                     stderr="")
    assert selfhost.detect_gpus(smi) == [GTX_1070]


def test_a_driver_that_cannot_report_it_is_named_not_mistaken_for_no_gpu():
    def smi(*a, **k):
        return types.SimpleNamespace(returncode=2, stdout="", stderr='Field "compute_cap" is not a valid field to query.')
    with pytest.raises(RuntimeError, match="driver"):
        selfhost.detect_gpus(smi)


def test_the_q4_models_run_from_their_gguf_and_models_without_one_are_refused():
    assert selfhost._fits(BY_NAME["MidnightV2-4B-q4"], GTX_1070)
    assert selfhost._fits(BY_NAME["TwilightV2-2B"], GTX_1070)
    assert selfhost._fits(BY_NAME["MidnightV2-4B"], V100)
    assert "no llama.cpp build" in selfhost._unfit(BY_NAME["AbyssV2-q4"], GTX_1070)
    assert selfhost._fits(BY_NAME["AbyssV2-q4"], T4)


def test_with_no_flags_the_default_is_the_default_model():
    assert selfhost._from_flags([GTX_1070], {}, None, None, None).model == selfhost.MODELS[0]


def test_asking_for_a_model_without_a_gguf_names_the_ones_that_run():
    with pytest.raises(RuntimeError, match="These run here: --model MidnightV2-4B-q4, TwilightV2-2B"):
        selfhost._from_flags([GTX_1070], {}, "abyss", 0, None)


def test_the_server_is_started_on_llamacpp_on_the_chosen_card(home):
    choice = selfhost.Choice(BY_NAME["MidnightV2-4B-q4"], GTX_1070, selfhost.FIRST_SOLVE)
    selfhost.write_settings({**selfhost.settings(choice, "/weights/midnight-gguf", {"port": 8123}),
                             "pointer_states": "/bin/pointer_states", "quant": "Q4_K_M",
                             "processor_path": "/weights/midnight"})
    cmd = server_manager.build_serve_command()
    flags = dict(zip(cmd[cmd.index("--engine"):][::2], cmd[cmd.index("--engine") + 1:][::2]))
    assert flags == {"--engine": "llamacpp", "--processor": "/weights/midnight", "--pointer-states": "/bin/pointer_states",
                     "--quant": "Q4_K_M", "--device": "0000:01:00.0"}
    assert "--gpu-memory-utilization" not in cmd, "a vLLM setting"


def test_cpu_torch_is_installed_before_the_client(monkeypatch):
    runs = []
    monkeypatch.setattr(subprocess, "run", lambda cmd, **k: runs.append(cmd) or types.SimpleNamespace(returncode=0))
    selfhost.install_client(Path("/env/bin/python"), "[serve-llamacpp]")
    torch = next(i for i, c in enumerate(runs) if selfhost.TORCH_CPU[0] in c)
    client = next(i for i, c in enumerate(runs) if any("captchakraken[serve-llamacpp]" in a for a in c))
    assert torch < client and selfhost.TORCH_CPU_INDEX in runs[torch]


def test_cpu_torch_is_the_extras_pins():
    pyproject = (Path(__file__).parents[1] / "pyproject.toml").read_text()
    extra = re.search(r"^serve-llamacpp = \[(.*?)\]", pyproject, re.S | re.M).group(1)
    assert all(f'"{pin}"' in extra for pin in selfhost.TORCH_CPU)


def test_only_one_gguf_is_downloaded():
    assert selfhost.gguf_patterns(BY_NAME["MidnightV2-4B"]) == ("*-BF16.gguf", "mmproj-*.gguf", "pointer_heads.safetensors")


def test_a_binary_that_is_not_the_pinned_one_is_refused(home, monkeypatch):
    monkeypatch.setattr(selfhost, "POINTER_STATES_SHA256", "0" * 64)
    http = types.SimpleNamespace(get=lambda *a, **k: types.SimpleNamespace(content=b"evil", raise_for_status=lambda: None))
    with pytest.raises(RuntimeError, match="Nothing was installed"):
        selfhost.fetch_pointer_states(http)
    assert not selfhost.pointer_states_path().exists()


def _listing(gpus, returncode=0, stderr=""):
    line = json.dumps({"gpus": gpus})
    return lambda *a, **k: types.SimpleNamespace(returncode=returncode, stdout=line + "\n", stderr=stderr)


def test_vulkan_must_see_the_chosen_card_before_anything_downloads():
    selfhost.check_vulkan(Path("/b"), GTX_1070, _listing([{"name": "NVIDIA GeForce GTX 1070", "pci": "0000:01:00.0"}]))
    with pytest.raises(RuntimeError, match="libnvidia-gl"):
        selfhost.check_vulkan(Path("/b"), GTX_1070, _listing([{"name": "llvmpipe", "pci": ""}]))
    missing = "pointer_states: error while loading shared libraries: libvulkan.so.1: cannot open shared object file"
    with pytest.raises(RuntimeError, match="apt install libvulkan1"):
        selfhost.check_vulkan(Path("/b"), GTX_1070, _listing([], 127, missing))


class _Tokenizer:
    """Ids 0-9 are text tokens, decoded as `t<id>`; the rest are the vision specials."""
    special = {"<|vision_start|>": 100, "<|vision_end|>": 101, L.IMAGE_PAD: 102, L.VIDEO_PAD: 103}

    def decode(self, ids, skip_special_tokens=False):
        return "".join(f"t{i}" for i in ids)


def _engine():
    svc = LlamaCppPointerService.__new__(LlamaCppPointerService)
    svc.processor = types.SimpleNamespace(tokenizer=_Tokenizer())
    svc.token_ids = {L.IMAGE_PAD: 102, L.VIDEO_PAD: 103}
    svc._special = {k: _Tokenizer.special[k] for k in ("<|vision_start|>", "<|vision_end|>")}
    return svc


def test_each_image_span_is_one_media_marker():
    ids = [1, 2, 100, 102, 102, 102, 101, 3, 100, 102, 101, 4]
    assert _engine()._prompt(ids, 2) == f"t1t2{MARKER}t3{MARKER}t4"


def test_each_video_span_is_a_frame_pair_so_two_markers():
    ids = [1, 5, 100, 103, 103, 101, 6, 100, 103, 103, 101, 2]
    assert _engine()._prompt(ids, 4) == f"t1t5{MARKER * 2}t6{MARKER * 2}t2"


def test_a_prompt_with_the_wrong_number_of_pictures_is_refused():
    with pytest.raises(ValueError, match="vision slots"):
        _engine()._prompt([1, 100, 102, 101], 2)


def test_the_documented_manual_install_is_the_one_fetch_runs():
    docs = (Path(__file__).parents[2] / "docs" / "self-hosting.md").read_text()
    assert f"pip install {' '.join(selfhost.TORCH_CPU)} --index-url {selfhost.TORCH_CPU_INDEX}" in docs
    assert '"captchakraken[serve-llamacpp]"' in docs
    assert selfhost.POINTER_STATES_URL in docs
    assert "python -m captchakraken.pointer.server --engine llamacpp" in docs


def test_the_binary_fetch_downloads_is_built_from_the_pinned_llama_cpp():
    build = (Path(__file__).parents[2] / "native" / "pointer_states" / "build.sh").read_text()
    assert f"LLAMA_CPP_TAG={selfhost.POINTER_STATES_RELEASE}\n" in build


_FAKE = '''
import json, sys
from pathlib import Path
starts = Path(sys.argv[1])
n = int(starts.read_text() or 0) + 1 if starts.exists() else 1
starts.write_text(str(n))
print(json.dumps({"ready": True, "n_embd": 4, "marker": "<__media__>"}), flush=True)
for line in sys.stdin:
    if n == 1:
        print(json.dumps({"ok": False, "error": "vk::Queue::submit: ErrorDeviceLost"}), flush=True)
        sys.exit(134)
    print(json.dumps({"ok": True, "n_embd": 4, "chunks": []}), flush=True)
'''


def _fake_engine(tmp_path):
    script = tmp_path / "pointer_states.py"
    script.write_text(_FAKE)
    svc = LlamaCppPointerService.__new__(LlamaCppPointerService)
    svc.lm_weight = types.SimpleNamespace(shape=(10, 4))
    svc._cmd = [sys.executable, str(script), str(tmp_path / "starts")]
    svc._start()
    return svc


def test_a_gpu_reset_restarts_the_binary_and_the_board_is_answered(tmp_path):
    svc = _fake_engine(tmp_path)
    assert svc._ask({"prompt": "x"})["ok"]
    assert (tmp_path / "starts").read_text() == "2"
    assert svc._ask({"prompt": "y"})["ok"], "the restarted process keeps serving"
