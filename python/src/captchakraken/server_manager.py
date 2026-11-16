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
# `captchakraken stop` means off: a solve must not quietly start the server again.
STOPPED_FILE = STATE_DIR / "server.stopped"
UNIT = "captchakraken-local.service"

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
        # Empty, not absent: a machine's HTTP_PROXY must not carry a call to this machine's own server.
        direct = {"http": "", "https": ""} if is_local(base_url) else None
        r = requests.get(_server_root(base_url) + "/health", timeout=timeout, proxies=direct)
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
    return Path(_serve_python()).exists() if config.selfhost_active() else _vllm_bin() is not None


def _serve_python() -> str:
    """The stack `fetch` installed, whichever environment this command itself is running from."""
    return str(config.runtime_dir() / "bin" / "python") if config.selfhost_active() else sys.executable


def _read_pid() -> "int | None":
    try:
        pid = int(PID_FILE.read_text().strip())
    except (OSError, ValueError):
        return None
    try:
        # A server we spawned that crashed stays a zombie until we reap it, and kill(0) calls a zombie alive.
        if os.waitpid(pid, os.WNOHANG)[0] == pid:
            return None
    except OSError:
        pass  # not our child: someone else's start, or a pid from an earlier run
    try:
        os.kill(pid, 0)
        return pid
    except OSError:
        return None


def build_serve_command() -> "list[str]":
    from . import prompts

    if prompts.resolve(config.lora_adapter()).pointer:
        capture = config.max_cudagraph_capture_size()
        return [
            _serve_python(), "-m", "captchakraken.pointer.server",
            "--model", config.serve_model(),
            "--host", os.getenv("CAPTCHA_POINTER_HOST", "127.0.0.1"),
            "--port", str(config.port()),
            "--gpu-memory-utilization", str(config.gpu_memory_utilization()),
            *(["--max-cudagraph-capture-size", str(capture)] if capture else []),
        ]
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
    active = config.selfhost_active()
    if active:
        env["VLLM_ENABLE_V1_MULTIPROCESSING"] = "0"
        # nvidia-smi numbers GPUs in PCI order and CUDA does not unless told to.
        if "CUDA_VISIBLE_DEVICES" not in os.environ:
            env["CUDA_DEVICE_ORDER"] = "PCI_BUS_ID"
            env["CUDA_VISIBLE_DEVICES"] = str(active.get("gpu", 0))
    return env


def _spawn() -> subprocess.Popen:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    if not _vllm_available():
        raise RuntimeError(
            "vLLM is not installed, so a local server can't be started. Run "
            "`captchakraken fetch`, or point VLLM_BASE_URL at a server you already run."
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


def _wait_healthy(base_url: str, timeout: float, alive=None) -> bool:
    deadline = time.time() + timeout
    alive = alive or (lambda: _read_pid() is not None)
    while time.time() < deadline:
        if is_healthy(base_url, timeout=2.0):
            return True
        if not alive():
            return False
        time.sleep(2.0)
    return False


def log_tail(lines: int = 15) -> str:
    try:
        return "\n".join(LOG_FILE.read_text(errors="replace").splitlines()[-lines:])
    except OSError:
        return "(no log)"


def _always_on() -> bool:
    return config.selfhost_active().get("startup") == "always" and _systemd_available()


def _systemd_available() -> bool:
    return shutil.which("systemctl") is not None and subprocess.run(
        ["systemctl", "--user", "show-environment"], capture_output=True).returncode == 0


def _unit_path() -> Path:
    return Path.home() / ".config" / "systemd" / "user" / UNIT


def _unit_text() -> str:
    return (
        "[Unit]\nDescription=CaptchaKraken pointer server\nAfter=network.target\n\n"
        "[Service]\n"
        f"Environment=CAPTCHA_KRAKEN_STATE_DIR={config.state_dir()}\n"
        f"ExecStart={_serve_python()} -m captchakraken.cli server run\n"
        f"StandardOutput=append:{LOG_FILE}\nStandardError=append:{LOG_FILE}\n"
        "Restart=on-failure\nRestartSec=10\n\n"
        "[Install]\nWantedBy=default.target\n"
    )


def _unit_running() -> bool:
    return subprocess.run(["systemctl", "--user", "is-active", "--quiet", UNIT]).returncode == 0


def _unit_alive() -> bool:
    # Between a crash and its restart the unit reads "activating", which is still worth waiting on.
    state = subprocess.run(["systemctl", "--user", "is-failed", UNIT], capture_output=True, text=True).stdout.strip()
    return state != "failed" and state != "inactive"


def _start_unit(base_url: str) -> dict:
    path = _unit_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_unit_text(), encoding="utf-8")
    subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
    subprocess.run(["systemctl", "--user", "enable", "--now", UNIT], check=True, capture_output=True)
    # Without linger a user's services wait for them to log in. Refused on some systems; it still runs from login.
    subprocess.run(["loginctl", "enable-linger"], capture_output=True)
    restarts = _unit_restarts()
    # A server that dies while loading is restarted by systemd for ever; one restart is the answer.
    ok = _wait_healthy(base_url, STARTUP_TIMEOUT_S, alive=lambda: _unit_alive() and _unit_restarts() == restarts)
    crashed = not ok and _unit_restarts() != restarts
    if crashed:
        subprocess.run(["systemctl", "--user", "disable", "--now", UNIT], capture_output=True)
    return {"status": "running" if ok else "crashed" if crashed else "timeout", "base_url": base_url, "unit": UNIT,
            "log": str(LOG_FILE)}


def _unit_restarts() -> int:
    out = subprocess.run(["systemctl", "--user", "show", "-p", "NRestarts", "--value", UNIT],
                         capture_output=True, text=True).stdout.strip()
    return int(out) if out.isdigit() else 0


def _unit_installed() -> bool:
    return _unit_path().exists() and shutil.which("systemctl") is not None


def ensure_server(base_url: "str | None" = None) -> None:
    base_url = base_url or config.base_url()

    # Remote first: /health against a hosted gateway that serves none costs up to 2s, once per ActionPlanner.
    if not is_local(base_url):
        return
    if is_healthy(base_url):
        return
    if not config.autostart_enabled():
        return
    if config.selfhost_active() and STOPPED_FILE.exists():
        raise RuntimeError("The CaptchaKraken server is stopped. Start it with: captchakraken start")

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
    STOPPED_FILE.unlink(missing_ok=True)
    if is_healthy(base_url):
        return {"status": "already-running", "base_url": base_url, "pid": _read_pid()}
    if not background:
        run_foreground()
    if _always_on():
        return _start_unit(base_url)
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
            "vLLM is not installed. Run `captchakraken fetch`."
        )
    cmd = build_serve_command()
    os.execvpe(cmd[0], cmd, _serve_env())


def stop() -> dict:
    was_on = False
    if config.selfhost():
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        STOPPED_FILE.touch()
    if _unit_installed():
        was_on = _unit_running()
        subprocess.run(["systemctl", "--user", "disable", "--now", UNIT], capture_output=True)
    pid = _read_pid()
    if pid is None:
        return {"status": "stopped" if was_on else "not-running"}
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
        "gpu": config.selfhost_active().get("gpu"),
        "startup": config.selfhost_active().get("startup"),
        "stopped": STOPPED_FILE.exists(),
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
