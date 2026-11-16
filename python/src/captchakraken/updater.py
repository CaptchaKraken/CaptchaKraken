import os
import shutil
import subprocess
import sys

from . import config


ENGINE_PACKAGES = ["vllm", "huggingface_hub"]


def _hf_bin() -> "str | None":
    """Next to the current interpreter first: the JS driver invokes the venv python without its bin on PATH."""
    here = os.path.dirname(sys.executable)
    for name in ("hf", "huggingface-cli"):
        sibling = os.path.join(here, name)
        if os.path.exists(sibling) and os.access(sibling, os.X_OK):
            return sibling
    return shutil.which("hf") or shutil.which("huggingface-cli")


def _download_cmd(repo_id: str) -> "list[str]":
    hf = _hf_bin()
    if hf:
        return [hf, "download", repo_id]
    return [
        sys.executable, "-c",
        "import sys; from huggingface_hub import snapshot_download; "
        "snapshot_download(sys.argv[1])",
        repo_id,
    ]


def _pip_upgrade_cmd() -> "list[str]":
    return [sys.executable, "-m", "pip", "install", "--upgrade", *ENGINE_PACKAGES]


PLANS_URL = "https://captchakraken.com/plans"


class LicensedModelError(RuntimeError):
    pass


def _licence_message(repo_id: str) -> str:
    return (
        f"{repo_id} needs an Abyss Licence: its weights are in a gated Hugging Face repo, "
        "and the Hub refused this download.\n"
        f"  Buy a licence at {PLANS_URL}, add your Hugging Face username on that page,\n"
        "  then sign in as that account (`hf auth login`, or HF_TOKEN) and run fetch again.\n"
        "  Or use the hosted API (https://api.captchakraken.com), which needs no weights at all."
    )


def _hub_refused(error: "BaseException | None") -> bool:
    """snapshot_download wraps some refusals (a 403 on the repo lookup) in LocalEntryNotFoundError, so walk the causes."""
    from huggingface_hub.errors import HfHubHTTPError, RepositoryNotFoundError

    while error is not None:
        # GatedRepoError is a RepositoryNotFoundError, which is also how the Hub answers a token it will not show the repo to.
        if isinstance(error, RepositoryNotFoundError):
            return True
        if isinstance(error, HfHubHTTPError) and error.response is not None \
                and error.response.status_code in (401, 403):
            return True
        error = error.__cause__
    return False


def _download_licensed(repo_id: str) -> None:
    """In-process, not through `hf download`, so a refusal arrives as an exception that names the licence."""
    try:
        from huggingface_hub import snapshot_download
    except ImportError as e:
        raise RuntimeError(f'Fetching {repo_id} needs huggingface_hub: pip install "captchakraken[serve]"') from e

    _log(f"$ snapshot_download({repo_id!r})")
    try:
        snapshot_download(repo_id)
    except Exception as e:
        if _hub_refused(e):
            raise LicensedModelError(_licence_message(repo_id)) from e
        raise


def _needs_auth(*repo_ids: "str | None") -> "list[str]":
    """Reported by `plan()` so `--dry-run` says "this needs a token" before the download, not after a 401."""
    from . import prompts

    return [r for r in repo_ids if r and prompts.requires_auth(r)]


def _hub_id(model: str) -> str:
    """A served name such as `abyss` is not a Hub id; download the repo it names."""
    from . import prompts

    return prompts.canonical_model_id(model) or model


def plan(
    *,
    weights: bool = True,
    engine: bool = True,
    restart: bool = True,
    base: "str | None" = None,
    lora: "str | None" = None,
) -> dict:
    base_model = _hub_id(base or config.base_model())
    lora_adapter = _hub_id(lora or config.lora_adapter())
    base_url = config.base_url()

    repos = [lora_adapter, base_model] if weights else []
    return {
        "weights": weights,
        "engine": engine,
        "restart": restart,
        "base_model": base_model,
        "lora_adapter": lora_adapter,
        "hf_org": "https://huggingface.co/CaptchaKraken",
        "downloads": [_download_cmd(r) for r in repos],
        "needs_auth": _needs_auth(*repos),
        "engine_upgrade": _pip_upgrade_cmd() if engine else None,
        "server": {"base_url": base_url, "local": _is_local(base_url)},
    }


def _is_local(base_url: str) -> bool:
    from .server_manager import is_local

    return is_local(base_url)


def _log(msg: str) -> None:
    print(f"[fetch] {msg}", file=sys.stderr)


def _run(cmd: "list[str]") -> None:
    _log("$ " + " ".join(cmd))
    subprocess.run(cmd, check=True)


def fetch(
    *,
    weights: bool = True,
    engine: bool = True,
    restart: bool = True,
    dry_run: bool = False,
    base: "str | None" = None,
    lora: "str | None" = None,
) -> dict:
    p = plan(weights=weights, engine=engine, restart=restart, base=base, lora=lora)
    if dry_run:
        return {**p, "dry_run": True}

    if weights:
        from . import prompts

        _log(f"Pulling latest weights from {p['hf_org']} (+ base) …")
        for repo in p["needs_auth"]:
            _log(f"{repo} needs a Hugging Face token authorised on it (`hf auth login`, or HF_TOKEN).")
        for repo, cmd in zip((p["lora_adapter"], p["base_model"]), p["downloads"]):
            if prompts.is_licensed(repo):
                _download_licensed(repo)
            else:
                _run(cmd)

    if engine:
        _log("Upgrading the vLLM serving stack …")
        _run(p["engine_upgrade"])

    server_result = None
    if restart and p["server"]["local"]:
        from . import server_manager

        if server_manager._read_pid() is not None:
            _log("Restarting the local vLLM server so new weights/engine load …")
            server_manager.stop()
            server_result = server_manager.start(background=True)
        else:
            _log("No local server running — it will pick up the update on next start.")
    elif restart:
        _log("Endpoint is remote — leaving the server you manage untouched.")

    return {
        "fetched_weights": bool(weights),
        "upgraded_engine": bool(engine),
        "server": server_result,
        "base_model": p["base_model"],
        "lora_adapter": p["lora_adapter"],
    }
