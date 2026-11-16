import http.client
import json
import sys
import subprocess
import threading
import time
import types
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from captchakraken import server_manager
from captchakraken.pointer import service as Svc
from captchakraken.pointer.server import make_handler


def test_the_pointer_engine_never_uses_prefix_caching(monkeypatch):
    captured = {}

    class FakeLLM:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    class FakeTokenizer:
        @staticmethod
        def convert_tokens_to_ids(token):
            return 0

    class FakeProcessor:
        tokenizer = FakeTokenizer()

    class FakeAutoProcessor:
        @staticmethod
        def from_pretrained(path):
            return FakeProcessor()

    fake_vllm = types.ModuleType("vllm")
    fake_vllm.LLM = FakeLLM
    fake_transformers = types.ModuleType("transformers")
    fake_transformers.AutoProcessor = FakeAutoProcessor
    monkeypatch.setitem(sys.modules, "vllm", fake_vllm)
    monkeypatch.setitem(sys.modules, "transformers", fake_transformers)
    monkeypatch.setattr(Svc.vllm_plugin, "register", lambda: None)

    Svc.PointerService("/model")
    assert captured["enable_prefix_caching"] is False
    with pytest.raises(ValueError):
        Svc.PointerService("/model", enable_prefix_caching=True)


def test_the_default_server_runs_the_q4_pointer():
    cmd = server_manager.build_serve_command()
    assert cmd[1:4] == ["-m", "captchakraken.pointer.server", "--model"]
    assert cmd[4] == "CaptchaKraken/MidnightV2-4B-q4"
    assert "--detector" not in cmd


def test_health_is_open_and_the_api_uses_the_server_key(monkeypatch):
    monkeypatch.setenv("VLLM_API_KEY", "test-key")
    monkeypatch.setenv("CAPTCHA_LORA_NAME", "captcha-pointer")
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(None))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        conn = http.client.HTTPConnection(*server.server_address)
        conn.request("GET", "/health")
        response = conn.getresponse()
        assert response.status == 200
        response.read()

        conn.request("GET", "/v1/models")
        response = conn.getresponse()
        assert response.status == 401
        response.read()

        conn.request("GET", "/v1/models", headers={"Authorization": "Bearer test-key"})
        response = conn.getresponse()
        assert response.status == 200
        body = json.loads(response.read())
        assert body["data"][0]["id"] == "captcha-pointer"
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_a_server_that_crashed_while_loading_is_not_still_running(tmp_path, monkeypatch):
    """A crashed child stays a zombie until reaped; `start` used to wait out its whole timeout on one."""
    child = subprocess.Popen([sys.executable, "-c", "raise SystemExit(1)"])
    pid_file = tmp_path / "vllm.pid"
    pid_file.write_text(str(child.pid))
    monkeypatch.setattr(server_manager, "PID_FILE", pid_file)

    deadline = time.time() + 30
    while server_manager._read_pid() is not None:
        assert time.time() < deadline, "a dead child still reads as running"
    child.wait()  # already reaped: Popen tolerates that


def test_vllms_startup_batches_are_not_mistaken_for_prompts():
    torch = pytest.importorskip("torch", exc_type=ImportError)
    from captchakraken.pointer.vllm_plugin import is_startup_run

    assert is_startup_run(torch.zeros(2048, dtype=torch.long), 49), "the memory profile's all-zero run"
    assert is_startup_run(torch.arange(2), 49), "0.29's kernel warmup"
    assert not is_startup_run(torch.arange(1, 800), 49), "a real prompt without markers must still fail"


def test_a_machine_proxy_does_not_carry_calls_to_the_local_server(monkeypatch):
    """Through a proxy, /health on 127.0.0.1 never answers: `start` then waited out its whole timeout."""
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:9")
    monkeypatch.setenv("http_proxy", "http://127.0.0.1:9")
    monkeypatch.delenv("NO_PROXY", raising=False)
    monkeypatch.delenv("no_proxy", raising=False)
    server = ThreadingHTTPServer(("127.0.0.1", 0), type("Ok", (BaseHTTPRequestHandler,), {
        "do_GET": lambda self: (self.send_response(200), self.end_headers()),
        "log_message": lambda self, *a: None,
    }))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        assert server_manager.is_healthy(f"http://127.0.0.1:{server.server_port}/v1")
    finally:
        server.shutdown()


def test_a_cold_server_loads_before_the_solve_clock_starts(monkeypatch):
    """A model load is as long as the 45s budget: a warm start used to time out its first solve."""
    from captchakraken import config, page_solver

    calls = []
    monkeypatch.setattr(config, "selfhost_active", lambda: {"port": 1})
    monkeypatch.setattr(page_solver, "ensure_server", lambda url: calls.append(url) or (_ for _ in ()).throw(KeyError("stop here")))
    monkeypatch.setattr(page_solver, "_now", lambda: pytest.fail("the clock started before the server was up"))
    with pytest.raises(KeyError):
        page_solver.PageSolver().solve(object())
    assert calls
