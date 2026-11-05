import http.client
import json
import threading
from http.server import ThreadingHTTPServer

from captchakraken import server_manager
from captchakraken.pointer.server import make_handler


def test_the_default_server_runs_the_q4_pointer(monkeypatch):
    monkeypatch.setenv("CAPTCHA_POINTER_DETECTOR", "/models/detector_r18.pt")
    cmd = server_manager.build_serve_command()
    assert cmd[1:4] == ["-m", "captchakraken.pointer.server", "--model"]
    assert cmd[4] == "CaptchaKraken/MidnightV2-4B-q4"
    assert cmd[cmd.index("--detector") + 1] == "/models/detector_r18.pt"


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
