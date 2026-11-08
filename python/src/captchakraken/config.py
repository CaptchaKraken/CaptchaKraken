import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Optional

_PINNED_MODEL_PATH = Path(__file__).with_name("pinned_model.json")


@lru_cache(maxsize=1)
def pinned() -> Dict[str, Any]:
    with _PINNED_MODEL_PATH.open(encoding="utf-8") as f:
        return json.load(f)


def selfhost_path() -> Path:
    return state_dir() / "selfhost.json"


def runtime_dir() -> Path:
    """The serving stack `captchakraken fetch` installs."""
    return state_dir() / "runtime"


@lru_cache(maxsize=1)
def _selfhost_cached(path: str, mtime_ns: int) -> Dict[str, Any]:
    try:
        with open(path, encoding="utf-8") as f:
            values = json.load(f)
    except (OSError, ValueError):
        return {}
    return values if isinstance(values, dict) else {}


def selfhost() -> Dict[str, Any]:
    """What `captchakraken fetch` chose, or nothing. Read through the file's mtime: every config call lands here."""
    path = selfhost_path()
    try:
        return _selfhost_cached(str(path), path.stat().st_mtime_ns)
    except OSError:
        return {}


selfhost.cache_clear = _selfhost_cached.cache_clear  # type: ignore[attr-defined]


def _selfhost_url(values: Dict[str, Any]) -> str:
    return f"http://127.0.0.1:{values.get('port')}/v1"


def selfhost_active() -> Dict[str, Any]:
    """`selfhost()` unless the caller pointed this process at another endpoint, which then owns every other setting."""
    values = selfhost()
    if not values:
        return {}
    explicit = os.getenv("VLLM_BASE_URL")
    return values if not explicit or explicit.rstrip("/") == _selfhost_url(values) else {}


def base_url() -> str:
    """Env, then what `fetch` set up, then the credentials file, then localhost: a camoufox user who signed up through the MCP had a valid key and no endpoint, so every solve dialled a local port."""
    active = selfhost_active()
    return (
        os.getenv("VLLM_BASE_URL")
        or (_selfhost_url(active) if active else "")
        or _base_url_from_credentials_file()
        or f"http://localhost:{port()}/v1"
    )


# An exact host list, not "is it remote": a self-hoster's vLLM across the network is remote too, and asking
# it for the hosted-only model 404s every request.
_HOSTED_HOSTS = ("api.captchakraken.com",)


def hosted_hosts() -> tuple:
    extra = os.getenv("CAPTCHA_HOSTED_HOSTS", "")
    return _HOSTED_HOSTS + tuple(
        h.strip().lower() for h in extra.split(",") if h.strip())


def is_hosted_endpoint(url: Optional[str] = None) -> bool:
    from urllib.parse import urlparse

    try:
        host = (urlparse(url or base_url()).hostname or "").lower()
    except Exception:
        return False
    return host in hosted_hosts()


def state_dir() -> Path:
    return Path(os.getenv("CAPTCHA_KRAKEN_STATE_DIR", str(Path.home() / ".captchakraken")))


def credentials_path() -> Path:
    return state_dir() / "credentials"


_KEY_NAMES = ("CAPTCHA_KRAKEN_API_KEY", "VLLM_API_KEY")
_BASE_URL_NAMES = ("CAPTCHA_KRAKEN_BASE_URL", "VLLM_BASE_URL")


def _read_credentials_file() -> Dict[str, str]:
    """Two spellings per key because the file doubles as something a user can `source`; the bare-token form stays because dropping it would silently break every existing file."""
    try:
        text = credentials_path().read_text(encoding="utf-8")
    except OSError:
        return {}

    found: Dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            name, _, value = line.partition("=")
            name = name.strip()
            if name not in _KEY_NAMES and name not in _BASE_URL_NAMES:
                continue
            found.setdefault(name, value.strip().strip("'\""))
        elif "" not in found:
            found[""] = line.strip("'\"")

    return found


def _first_present(values: Dict[str, str], names) -> str:
    for name in names:
        value = values.get(name, "").strip()
        if value:
            return value
    return ""


def _key_from_credentials_file() -> str:
    values = _read_credentials_file()
    return _first_present(values, _KEY_NAMES) or values.get("", "").strip()


# A bare token yields no endpoint on purpose: it would silently redirect a self-hoster who hand-wrote a local key here.


def _base_url_from_credentials_file() -> str:
    return _first_present(_read_credentials_file(), _BASE_URL_NAMES)


def api_key() -> str:
    # The local server's key first: a hosted key left in the environment could only earn a 401 from it.
    return (
        selfhost_active().get("key")
        or os.getenv("CAPTCHA_KRAKEN_API_KEY")
        or os.getenv("VLLM_API_KEY")
        or _key_from_credentials_file()
        or "EMPTY"
    )


def _registry_default(field: str) -> Optional[str]:
    """The pin decides the registry entry, not just the adapter: reading base/lora_name off `latest` once downloaded a 9B base for a pinned 27B adapter and failed deep in vLLM as a shape mismatch. An unregistered pin still falls back to `latest` for self-hosters."""
    try:
        from . import prompts

        models = prompts.registered_models()
        entry = None
        pin = os.getenv("CAPTCHA_LORA_ADAPTER") or os.getenv("CAPTCHA_LORA_NAME") or selfhost_active().get("model")
        if pin:
            entry = models.get(prompts.canonical_model_id(pin) or "")
        if entry is None:
            entry = models.get(prompts.latest_model() or "")
        value = (entry or {}).get(field)
        return value if isinstance(value, str) else None
    except Exception:
        return None


def base_model() -> str:
    return os.getenv("CAPTCHA_BASE_MODEL") or selfhost_active().get("model") or _registry_default("base_model") \
        or pinned()["base_model"]


def lora_adapter() -> str:
    from . import prompts

    return (os.getenv("CAPTCHA_LORA_ADAPTER") or selfhost_active().get("model") or prompts.latest_model()
            or pinned()["lora_adapter"])


def lora_revision() -> str:
    return os.getenv("CAPTCHA_LORA_REVISION") or _registry_default("lora_revision") \
        or pinned()["lora_revision"]


def lora_name() -> str:
    # Pin, then the hosted default, then the registry: `latest` leads pinned_model.json so download and prompt advance together.
    pin = os.getenv("CAPTCHA_LORA_NAME")
    if pin:
        return pin
    if selfhost_active():
        return _registry_default("lora_name") or pinned()["lora_name"]
    if is_hosted_endpoint():
        hosted = _hosted_default_name()
        if hosted:
            return hosted
    return _registry_default("lora_name") or pinned()["lora_name"]


def _hosted_default_name() -> Optional[str]:
    """Send the routing alias, not an arm: `abyss-general` is a lone expert with no `experts` of its own, and naming it would pin every family to the generalist and silently lose the routing."""
    try:
        from . import prompts

        repo = prompts.hosted_default_model()
        if not repo:
            return None
        aliases = [a for a, target in prompts.served_aliases().items()
                   if target == repo and not a.startswith("_")]
        for alias in aliases:
            if prompts.experts(alias):
                return alias
        if aliases:
            return aliases[0]
        entry = prompts.registered_models().get(repo) or {}
        value = entry.get("lora_name")
        return value if isinstance(value, str) else None
    except Exception:
        return None


def port() -> int:
    return int(os.getenv("VLLM_PORT") or selfhost().get("port") or 8000)


def gpu_memory_utilization() -> float:
    return float(os.getenv("VLLM_GPU_MEMORY_UTILIZATION") or selfhost_active().get("gpu_memory_utilization") or 0.80)


def max_cudagraph_capture_size() -> Optional[int]:
    """vLLM reserves memory for a compiled graph per batch size up to this; unset leaves vLLM's own default."""
    value = os.getenv("VLLM_MAX_CUDAGRAPH_CAPTURE_SIZE", "").strip() or selfhost_active().get("max_cudagraph_capture_size")
    return int(value) if value else None


def serve_model() -> str:
    """What the server loads: `fetch`'s download directory, which needs no Hub, or the repo id."""
    return os.getenv("CAPTCHA_BASE_MODEL") or selfhost_active().get("model_path") or base_model()


def pointer_detector() -> Optional[str]:
    return os.getenv("CAPTCHA_POINTER_DETECTOR") or selfhost_active().get("detector")


def max_model_len() -> int:
    return int(os.getenv("VLLM_MAX_MODEL_LEN", "65536"))


def max_lora_rank() -> int:
    return int(os.getenv("VLLM_MAX_LORA_RANK", "64"))


def autostart_enabled() -> bool:
    return os.getenv("CAPTCHA_KRAKEN_AUTOSTART", "1") != "0"


def extra_serve_args() -> list:
    raw = os.getenv("VLLM_EXTRA_ARGS", "").strip()
    return raw.split() if raw else []
