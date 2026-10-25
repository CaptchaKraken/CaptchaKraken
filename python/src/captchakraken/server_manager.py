import json
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

import requests

from . import config
from .clipvideo import media_io_kwargs

STATE_DIR = config.state_dir()
LOCK_FILE = STATE_DIR / "vllm.lock"
PID_FILE = STATE_DIR / "vllm.pid"
LOG_FILE = STATE_DIR / "vllm.log"

STARTUP_TIMEOUT_S = int(os.getenv("CAPTCHA_KRAKEN_STARTUP_TIMEOUT", "600"))


def _log(msg: str) -> None:
    if os.getenv("CAPTCHA_DEBUG", "0") == "1":
        print(f"[server] {msg}", file=sys.stderr)


def _server_root(base_url: str) -> str:
    p = urlparse(base_url)
    return f"{p.scheme}://{p.netloc}"


def is_local(base_url: str) -> bool:
    host = (urlparse(base_url).hostname or "").lower()
    return host in {"localhost", "127.0.0.1", "0.0.0.0", "::1", ""}


def is_healthy(base_url: str, timeout: float = 2.0) -> bool:
    try:
        r = requests.get(_server_root(base_url) + "/health", timeout=timeout)
        return r.ok
    except requests.RequestException:
        return False


def _vllm_bin() -> "str | None":
    """Next to the current interpreter first: the JS driver invokes the venv python without its bin on PATH."""
    sibling = os.path.join(os.path.dirname(sys.executable), "vllm")
    if os.path.exists(sibling) and os.access(sibling, os.X_OK):
        return sibling
    return shutil.which("vllm")


def _vllm_available() -> bool:
    return _vllm_bin() is not None


def _read_pid() -> "int | None":
    try:
        pid = int(PID_FILE.read_text().strip())
    except (OSError, ValueError):
        return None
    try:
        os.kill(pid, 0)
        return pid
    except OSError:
        return None


def build_serve_command() -> "list[str]":
    return [
        _vllm_bin() or "vllm", "serve", config.base_model(),
        "--reasoning-parser", "qwen3",
        # REQUIRED: without it vLLM silently drops the vision-tower half of the LoRA and grid accuracy collapses.
        "--enable-lora", "--enable-tower-connector-lora",
        "--max-lora-rank", str(config.max_lora_rank()),
        "--max-model-len", str(config.max_model_len()),
        "--gpu-memory-utilization", str(config.gpu_memory_utilization()),
        "--trust-remote-code",
        "--port", str(config.port()),
        "--lora-modules", f"{config.lora_name()}={config.lora_adapter()}",
        # A video-generation model watches an animation as one JPEG frame sequence; without these vLLM refuses the
        # video or resamples it to its own frame count, and the time the model answers with names the wrong moment.
        "--limit-mm-per-prompt", json.dumps({"image": 8, "video": 1}),
        "--media-io-kwargs", json.dumps(media_io_kwargs()),
        *config.extra_serve_args(),
    ]


def _serve_env() -> dict:
    env = dict(os.environ)
    key = config.api_key()
    # Only forward a real key; api_key() falls back to "EMPTY", which would lock vLLM to a placeholder.
    if key and key != "EMPTY":
        env["VLLM_API_KEY"] = key
    return env


def _spawn() -> subprocess.Popen:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    if not _vllm_available():
        raise RuntimeError(
            "vLLM is not installed, so a local server can't be started. Run the "
            "setup script (./setup.sh) or `pip install \"captchakraken[serve]\"`, "
            "or point VLLM_BASE_URL at a server you already run."
        )
    cmd = build_serve_command()
    _log("starting: " + " ".join(cmd))
    logf = open(LOG_FILE, "ab", buffering=0)
    logf.write(f"\n=== captchakraken starting vLLM at {time.strftime('%Y-%m-%dT%H:%M:%S')} ===\n"
               .encode())
    proc = subprocess.Popen(
        cmd,
        stdout=logf,
        stderr=logf,
        stdin=subprocess.DEVNULL,
        env=_serve_env(),
        start_new_session=True,
    )
    PID_FILE.write_text(str(proc.pid))
    return proc


def _wait_healthy(base_url: str, timeout: float) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if is_healthy(base_url, timeout=2.0):
            return True
        pid = _read_pid()
        if pid is None:
            return False
        time.sleep(2.0)
    return False


def ensure_server(base_url: "str | None" = None) -> None:
    base_url = base_url or config.base_url()

    # Remote first: /health against a hosted gateway that serves none costs up to 2s, once per ActionPlanner.
    if not is_local(base_url):
        return
    if is_healthy(base_url):
        return
    if not config.autostart_enabled():
        return

    STATE_DIR.mkdir(parents=True, exist_ok=True)
    # Two solves racing on first use must not both spawn a server; re-check under the lock.
    lock = _FileLock(LOCK_FILE)
    with lock:
        if is_healthy(base_url):
            return
        if _read_pid() is None:
            _spawn()
        if not _wait_healthy(base_url, STARTUP_TIMEOUT_S):
            raise RuntimeError(
                f"vLLM did not become healthy at {base_url} within "
                f"{STARTUP_TIMEOUT_S}s. See {LOG_FILE} for details."
            )


def start(background: bool = True) -> dict:
    base_url = config.base_url()
    if is_healthy(base_url):
        return {"status": "already-running", "base_url": base_url, "pid": _read_pid()}
    if not background:
        run_foreground()
    _spawn()
    ok = _wait_healthy(base_url, STARTUP_TIMEOUT_S)
    return {
        "status": "running" if ok else "timeout",
        "base_url": base_url,
        "pid": _read_pid(),
        "log": str(LOG_FILE),
    }


def run_foreground() -> None:
    if not _vllm_available():
        raise RuntimeError(
            "vLLM is not installed. Run ./setup.sh or "
            "`pip install \"captchakraken[serve]\"`."
        )
    cmd = build_serve_command()
    os.execvpe(cmd[0], cmd, _serve_env())


def stop() -> dict:
    pid = _read_pid()
    if pid is None:
        return {"status": "not-running"}
    try:
        os.killpg(os.getpgid(pid), signal.SIGTERM)
    except OSError:
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass
    for _ in range(20):
        if _read_pid() is None:
            break
        time.sleep(0.5)
    try:
        PID_FILE.unlink()
    except OSError:
        pass
    return {"status": "stopped", "pid": pid}


def status(base_url: "str | None" = None) -> dict:
    base_url = base_url or config.base_url()
    return {
        "base_url": base_url,
        "healthy": is_healthy(base_url),
        "local": is_local(base_url),
        "pid": _read_pid(),
        "autostart": config.autostart_enabled(),
        "base_model": config.base_model(),
        "lora_adapter": config.lora_adapter(),
        "lora_name": config.lora_name(),
    }


class _FileLock:

    def __init__(self, path: Path):
        self.path = path
        self._fh = None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = open(self.path, "w")
        try:
            import fcntl

            fcntl.flock(self._fh, fcntl.LOCK_EX)
        except (ImportError, OSError):
            pass
        return self

    def __exit__(self, *exc):
        if self._fh is not None:
            try:
                import fcntl

                fcntl.flock(self._fh, fcntl.LOCK_UN)
            except (ImportError, OSError):
                pass
            self._fh.close()
            self._fh = None
