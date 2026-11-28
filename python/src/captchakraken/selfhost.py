"""`captchakraken fetch`: ask which model, GPU and startup mode, then install, download and start it.

A licensed model (Abyss) downloads from a gated Hub repo as the licence holder's own Hugging Face account,
so `fetch` checks that account can read it before the 8 GB serving stack installs, and says what to do if not.

Everything lands under the state directory and the choices live in `selfhost.json`, so a solve, the
server and `captchakraken start` read one file and nobody exports anything or edits their PATH.
The serving stack gets its own environment because the one running this command may be a throwaway:
npx and pipx both evict theirs, and a server must not break when they do.
"""

import getpass
import json
import os
import secrets
import shutil
import socket
import subprocess
import sys
import venv
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, NamedTuple, Optional, Sequence, Tuple

import requests

from . import __version__, config, prompts, server_manager
from .updater import PLANS_URL

ALWAYS_ON = "always"
FIRST_SOLVE = "first-solve"

# The serving stack on disk, measured: torch and vLLM with their CUDA libraries.
RUNTIME_GB = 8.0
# vLLM's default reservation and graph set run an 8 GB card out of memory while it starts.
SMALL_CARD_MIB = 12_000
SMALL_CARD_CAPTURE_SIZE = 16

VLLM = "vllm"
LLAMACPP = "llamacpp"
# The serving stack's torch is built for compute capability 7.5 and up (RTX 20 series, GTX 16 series, T4).
VLLM_MIN_COMPUTE = 7.5
# Older cards run a GGUF build on llama.cpp's Vulkan backend, which the NVIDIA driver serves on any card
# since Kepler. Torch there only prepares the board and runs the small heads, so it is the CPU build: the
# same versions as the `serve-llamacpp` extra (a test checks), from PyTorch's index, without CUDA.
TORCH_CPU = ("torch==2.13.0", "torchvision==0.28.0")
TORCH_CPU_INDEX = "https://download.pytorch.org/whl/cpu"
# pointer_states (native/pointer_states): llama.cpp's language model and vision encoder returning every
# token's hidden state, one static binary built per llama.cpp release.
POINTER_STATES_RELEASE = "b12819"
POINTER_STATES_URL = ("https://github.com/CaptchaKraken/CaptchaKraken/releases/download/"
                      f"pointer-states-{POINTER_STATES_RELEASE}/pointer_states-linux-x86_64")
POINTER_STATES_SHA256 = "70fd71385e92f567daadaaf1827beb30e2f08419c5b454acfb68bbf55e5133b9"
# The files of a full-precision repo the GGUF builds leave out: what turns a board into token ids.
PROCESSOR_FILES = ("tokenizer.json", "tokenizer_config.json", "processor_config.json", "chat_template.jinja",
                   "config.json", "preprocessor_config.json", "video_preprocessor_config.json")


@dataclass(frozen=True)
class Model:
    repo: str
    title: str
    blurb: str
    download_gb: float
    # The smallest card it was seen to load on, as a card's advertised size.
    min_vram_gb: int
    # Its share of a small card. Twilight's full-precision weights leave no KV cache at the default (measured, 8 GB).
    small_card_utilization: float = 0.72
    # Other names `fetch <name>` and `--model` accept, besides the repo and its last part.
    aliases: Tuple[str, ...] = ()
    # False keeps it out of the interactive menu: a single-purpose model is reached by name, never offered to everyone.
    listed: bool = True
    # How an account without access gets it; empty means the Abyss Licence.
    access: str = ""
    # The folder of the repo that is served, when the repo holds several builds; empty means the whole repo.
    subfolder: str = ""
    # Its llama.cpp build, for a card older than VLLM_MIN_COMPUTE: a GGUF repo and which of its files to load.
    # The tokenizer and processor files come from `processor_repo`, or `repo` when that is empty.
    gguf: str = ""
    gguf_quant: str = "Q4_K_M"
    processor_repo: str = ""

    @property
    def licensed(self) -> bool:
        """Read from the registry, the one place that says which weights are gated."""
        return prompts.is_licensed(self.repo)

    def named(self, wanted: str) -> bool:
        return wanted.lower() in {n.lower() for n in (self.repo, self.repo.split("/")[-1], *self.aliases)}


# Sunlight is absent on purpose: its published heads predate this client's layout and refuse to load.
MODELS = (
    Model("CaptchaKraken/MidnightV2-4B-q4", "Midnight V2 4B Q4", "the default: best balance of speed and accuracy",
          3.8, 8, gguf="CaptchaKraken/MidnightV2-4B-GGUF"),
    Model("CaptchaKraken/TwilightV2-2B", "Twilight V2 2B", "smaller model, full precision", 4.5, 8, 0.80,
          gguf="CaptchaKraken/TwilightV2-2B-GGUF"),
    Model("CaptchaKraken/MidnightV2-4B", "Midnight V2 4B", "the same model at full precision", 9.1, 16,
          gguf="CaptchaKraken/MidnightV2-4B-GGUF", gguf_quant="BF16"),
    Model("CaptchaKraken/AbyssV2-q4", "Abyss V2 Q4", "our most accurate model, needs an Abyss Licence",
          3.8, 8, aliases=("abyss",)),
    Model("CaptchaKraken/AbyssV2", "Abyss V2", "Abyss at full precision, needs an Abyss Licence", 9.1, 16),
    Model("CaptchaKraken/CaptchaKraken-Custom-Yidun-Commision", "CaptchaKraken Custom Yidun", "Abyss tuned for Yidun icon click-in-order boards",
          3.8, 8, aliases=("custom-yidun",), listed=False, subfolder="q4",
          access="  Use the access token the CaptchaKraken team sent you once your purchase was confirmed:\n"
                 "  HF_TOKEN=hf_... captchakraken fetch custom-yidun"),
)


def listed_models() -> Tuple[Model, ...]:
    return tuple(m for m in MODELS if m.listed)


class Gpu(NamedTuple):
    index: int
    name: str
    total_mib: int
    free_mib: int
    compute: float
    # As Vulkan writes it, 0000:01:00.0: the only number nvidia-smi and llama.cpp agree on.
    pci: str = ""

    @property
    def label(self) -> str:
        return f"{self.name} ({self.total_mib / 1024:.0f} GB, {self.free_mib / 1024:.1f} GB free)"

    @property
    def engine(self) -> str:
        return VLLM if self.compute >= VLLM_MIN_COMPUTE else LLAMACPP


class Choice(NamedTuple):
    model: Model
    gpu: Gpu
    startup: str
    # "" is the card's own default: vLLM where it has kernels, else llama.cpp.
    engine: str = ""

    @property
    def runs_on(self) -> str:
        return self.engine or self.gpu.engine


ENGINES = (VLLM, LLAMACPP)


class Cancelled(Exception):
    pass


def _unfit(model: Model, gpu: Gpu, engine: str = "") -> str:
    """Why `model` cannot run on `gpu` with `engine` (the card's default when empty), or "" when it can."""
    engine = engine or gpu.engine
    if engine == VLLM and gpu.compute < VLLM_MIN_COMPUTE:
        return f"vLLM runs on compute capability {VLLM_MIN_COMPUTE}+ and the {gpu.name} has {gpu.compute}"
    if engine == LLAMACPP and not model.gguf:
        return "it has no llama.cpp build yet" + (
            f", which the {gpu.name} needs: vLLM runs on compute capability {VLLM_MIN_COMPUTE}+ and it has "
            f"{gpu.compute}" if gpu.engine == LLAMACPP else "")
    # Cards are sold in GB and report a little under it: an "8 GB" 5060 reports 8151 MiB, a 7.96.
    if gpu.total_mib < model.min_vram_gb * 1024 * 0.95:
        return f"needs {model.min_vram_gb} GB of VRAM, the {gpu.name} has {gpu.total_mib / 1024:.0f} GB"
    return ""


def _fits(model: Model, gpu: Gpu, engine: str = "") -> bool:
    return not _unfit(model, gpu, engine)


def _engines(model: Model, gpu: Gpu) -> List[str]:
    """The engines that run `model` on `gpu`, the default first."""
    return [e for e in ENGINES if _fits(model, gpu, e)]


def _busy_note(model: Model, gpu: Gpu) -> str:
    # The server holds about 70% of a card sold at the model's minimum.
    return "" if gpu.free_mib >= model.min_vram_gb * 1024 * 0.7 else "too full right now unless you free it up"


def _pci(bus_id: str) -> str:
    """nvidia-smi's 00000000:01:00.0 as Vulkan writes it, 0000:01:00.0."""
    domain, _, rest = bus_id.strip().lower().partition(":")
    try:
        return f"{int(domain, 16):04x}:{rest}" if rest else ""
    except ValueError:
        return ""


def detect_gpus(run: Callable = subprocess.run) -> List[Gpu]:
    """Numbered as nvidia-smi numbers them, which is PCI order, so the server is pinned with that same order."""
    try:
        out = run(["nvidia-smi", "--query-gpu=index,name,memory.total,memory.free,compute_cap,pci.bus_id",
                   "--format=csv,noheader,nounits"],
                  capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return []
    if out.returncode != 0:
        # A driver too old to report compute_cap is also too old for any CUDA 12 build.
        if "compute_cap" in (out.stderr or "") + (out.stdout or ""):
            raise RuntimeError("This NVIDIA driver is too old to self-host: update it (any driver from 2022 on "
                               "reports compute capability), or use the hosted API.")
        return []
    gpus = []
    for line in out.stdout.splitlines():
        fields = [f.strip() for f in line.split(",")]
        if len(fields) == 6 and fields[0].isdigit() and fields[2].isdigit() and fields[3].isdigit():
            gpus.append(Gpu(int(fields[0]), fields[1], int(fields[2]), int(fields[3]), float(fields[4]),
                            _pci(fields[5])))
    return gpus


# ── the terminal menu ────────────────────────────────────────────────────────

class Option(NamedTuple):
    label: str
    detail: str = ""
    disabled: str = ""


ENGINE_OPTIONS = {
    VLLM: Option("vLLM", "the default: serves several solves at once; about 8 GB of serving stack, "
                         f"NVIDIA compute capability {VLLM_MIN_COMPUTE}+"),
    LLAMACPP: Option("llama.cpp", "about 1 GB of serving stack, through Vulkan; one solve at a time"),
}


def _read_key() -> str:
    ch = os.read(sys.stdin.fileno(), 1).decode(errors="ignore")
    if ch != "\x1b":
        return ch
    import select
    if not select.select([sys.stdin], [], [], 0.05)[0]:
        return "esc"
    tail = os.read(sys.stdin.fileno(), 2).decode(errors="ignore")
    return {"[A": "up", "[B": "down"}.get(tail, "")


def _render(title: str, options: Sequence[Option], at: int) -> List[str]:
    lines = [f"\033[1m{title}\033[0m"]
    for i, o in enumerate(options):
        if o.disabled:
            lines.append(f"    \033[2m{i + 1}. {o.label}  ({o.disabled})\033[0m")
            continue
        here = i == at
        mark = "\033[1;36m❯\033[0m" if here else " "
        name = f"\033[1;36m{o.label}\033[0m" if here else o.label
        lines.append(f"  {mark} {i + 1}. {name}" + (f"  \033[2m{o.detail}\033[0m" if o.detail else ""))
    lines.append("  \033[2m↑/↓ or a number, Enter to choose, q to quit\033[0m")
    return lines


def choose(title: str, options: Sequence[Option], default: int = 0) -> int:
    """The index picked with the arrow keys. A disabled option can be seen and not landed on."""
    import termios
    import tty

    usable = [i for i, o in enumerate(options) if not o.disabled]
    at = default if default in usable else usable[0]
    fd = sys.stdin.fileno()
    saved = termios.tcgetattr(fd)
    drawn = 0
    try:
        tty.setcbreak(fd)
        sys.stdout.write("\033[?25l")
        while True:
            lines = _render(title, options, at)
            sys.stdout.write((f"\033[{drawn}F" if drawn else "") + "".join(f"\033[2K{li}\n" for li in lines))
            sys.stdout.flush()
            drawn = len(lines)
            key = _read_key()
            if key in ("q", "esc", "\x03"):
                raise Cancelled()
            if key in ("\n", "\r"):
                return at
            if key in ("up", "k"):
                at = usable[(usable.index(at) - 1) % len(usable)]
            elif key in ("down", "j"):
                at = usable[(usable.index(at) + 1) % len(usable)]
            elif key.isdigit() and int(key) - 1 in usable:
                at = int(key) - 1
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, saved)
        sys.stdout.write("\033[?25h\n")
        sys.stdout.flush()


def ask(gpus: Sequence[Gpu], saved: dict) -> Choice:
    """Model, then GPU, then startup. A previous choice is where the cursor starts."""
    menu = listed_models()
    runnable = [any(_fits(m, g) for g in gpus) for m in menu]
    if not any(runnable):
        raise RuntimeError(_no_model_fits(gpus))
    default_model = next((i for i, m in enumerate(menu) if m.repo == saved.get("model") and runnable[i]),
                         runnable.index(True))
    picked = menu[choose("Which model do you want to run?", [
        Option(m.title, f"{m.blurb}, {m.download_gb:.1f} GB download, needs {m.min_vram_gb} GB of VRAM",
               "" if ok else _unfit(m, max(gpus, key=lambda g: g.total_mib)))
        for m, ok in zip(menu, runnable)], default_model)]

    fitting = [g for g in gpus if _fits(picked, g)]
    default_gpu = next((i for i, g in enumerate(gpus) if g.index == saved.get("gpu")), None)
    if default_gpu is None or gpus[default_gpu] not in fitting:
        default_gpu = gpus.index(max(fitting, key=lambda g: g.free_mib))
    gpu = gpus[choose("Which GPU should the server run on?", [
        Option(f"GPU {g.index}: {g.label}", _busy_note(picked, g), _unfit(picked, g))
        for g in gpus], default_gpu)]

    # Asked only where there is a choice: a card vLLM has no kernels for, or a model with no GGUF, has one engine.
    engines = _engines(picked, gpu)
    engine = engines[0]
    if len(engines) > 1:
        engine = engines[choose("Which engine should serve it?", [ENGINE_OPTIONS[e] for e in engines],
                                engines.index(saved["engine"]) if saved.get("engine") in engines else 0)]

    modes = [ALWAYS_ON, FIRST_SOLVE]
    startup = modes[choose("When should the server run?", [
        Option("Always on", "starts with this machine and restarts if it crashes"),
        Option("Warm start", "starts now and after a reboot on the first solve, then stays loaded"),
    ], modes.index(saved["startup"]) if saved.get("startup") in modes else 0)]
    return Choice(picked, gpu, startup, engine)


# ── a licensed model's Hugging Face access ───────────────────────────────────

HUB = "https://huggingface.co"
HOSTED_API = "https://api.captchakraken.com"
# Replaced in tests; the signature is requests.request's.
_HUB_REQUEST: Callable = requests.request


def _hub_token_path() -> Path:
    """Where huggingface_hub keeps the login `hf auth login` writes, so the download finds what was saved here."""
    if os.getenv("HF_TOKEN_PATH"):
        return Path(os.environ["HF_TOKEN_PATH"])
    home = os.getenv("HF_HOME") or os.path.join(os.getenv("XDG_CACHE_HOME") or Path.home() / ".cache", "huggingface")
    return Path(home) / "token"


def hub_token() -> Optional[str]:
    token = os.getenv("HF_TOKEN") or os.getenv("HUGGING_FACE_HUB_TOKEN")
    if token:
        return token.strip()
    try:
        return _hub_token_path().read_text().strip() or None
    except OSError:
        return None


def _save_hub_token(token: str) -> None:
    path = _hub_token_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(token)
        os.chmod(path, 0o600)
    except OSError as e:
        raise RuntimeError(f"Could not save the Hugging Face token to {path}: {e}") from e


def _hub(http: Callable, method: str, url: str, token: str):
    try:
        return http(method, url, headers={"Authorization": f"Bearer {token}"}, timeout=20, allow_redirects=False)
    except requests.RequestException as e:
        raise RuntimeError(f"Could not reach Hugging Face to check the licence: {e}") from e


def _licence_steps() -> str:
    return (f"  An Abyss Licence comes with access: buy one at {PLANS_URL} and add your Hugging Face username there.\n"
            f"  Or use the hosted API ({HOSTED_API}), which serves Abyss to every account and needs no weights.")


def ensure_access(repo: str, *, interactive: bool, http: Optional[Callable] = None,
                  read_secret: Callable[[str], str] = getpass.getpass, access: str = "", subfolder: str = "") -> str:
    """The Hugging Face account that will download `repo`, once it is known to be allowed to. A token typed here is saved where huggingface_hub looks, so the download and later updates use it."""
    http = http or _HUB_REQUEST
    token, typed = hub_token(), False
    if not token:
        if not interactive:
            raise RuntimeError(f"{repo} downloads as your Hugging Face account, and none is signed in here.\n"
                               "  Set HF_TOKEN, or run `hf auth login`, then run this again.\n" + (access or _licence_steps()))
        print(f"{repo} downloads as your Hugging Face account. Paste a token from "
              f"{HUB}/settings/tokens (read access is enough).")
        token, typed = read_secret("Hugging Face token: ").strip(), True
        if not token:
            raise Cancelled()

    who = _hub(http, "GET", f"{HUB}/api/whoami-v2", token)
    if who.status_code == 401:
        raise RuntimeError("Hugging Face did not accept that token. Make a new one at "
                           f"{HUB}/settings/tokens and run this again.")
    if who.status_code != 200:
        raise RuntimeError(f"Hugging Face answered {who.status_code} when asked who the token belongs to. Try again shortly.")
    user = who.json().get("name") or "this account"

    probe = _hub(http, "HEAD", f"{HUB}/{repo}/resolve/main/{subfolder + '/' if subfolder else ''}config.json", token)
    if probe.status_code in (401, 403, 404):
        if access:
            raise RuntimeError(f"Hugging Face account {user} cannot download {repo} yet.\n" + access)
        raise RuntimeError(f"Hugging Face account {user} cannot download {repo} yet.\n"
                           f"  If you have an Abyss Licence, set your Hugging Face username to {user} at {PLANS_URL};\n"
                           "  access follows within a couple of minutes. Then run this again.\n" + _licence_steps())
    if not 200 <= probe.status_code < 400:
        raise RuntimeError(f"Hugging Face answered {probe.status_code} for {repo}. Try again shortly.")

    if typed:
        _save_hub_token(token)
    _ok(f"Hugging Face account {user} has access to {repo}")
    return user


# ── installing ───────────────────────────────────────────────────────────────

def _step(message: str) -> None:
    print(f"\033[1;36m➜\033[0m {message}", flush=True)


def _ok(message: str) -> None:
    print(f"\033[1;32m✓\033[0m {message}", flush=True)


def _source_tree() -> Optional[Path]:
    """The installable source beside this package, which npm ships and a checkout has."""
    # A checkout runs from src/, and npm keeps its environment at python/.venv beside the source it ships.
    for root in (Path(__file__).resolve().parents[2], Path(sys.prefix).resolve().parent):
        if (root / "pyproject.toml").is_file():
            return root
    return None


def make_venv(where: Path) -> Path:
    python = where / "bin" / "python"
    if not python.exists():
        try:
            venv.create(where, with_pip=True)
        except (OSError, subprocess.CalledProcessError) as e:
            shutil.rmtree(where, ignore_errors=True)
            raise RuntimeError(f"Could not create a Python environment at {where}: {e}. "
                               "On Debian or Ubuntu, install it with: sudo apt install python3-venv") from e
    return python


def install_client(python: Path, extra: str = "") -> None:
    """This same version from PyPI, or from the source beside this file when that version is not on PyPI."""
    subprocess.run([str(python), "-m", "pip", "install", "--quiet", "--upgrade", "pip"], check=True)
    if extra == "[serve-llamacpp]":
        # Before the client, so its torch pins are met by the CPU build and pip skips the 3 GB of CUDA libraries.
        subprocess.run([str(python), "-m", "pip", "install", "--quiet", *TORCH_CPU, "--index-url", TORCH_CPU_INDEX],
                       check=True)
    wanted = f"captchakraken{extra}=={__version__}"
    if subprocess.run([str(python), "-m", "pip", "install", "--quiet", wanted]).returncode == 0:
        return
    source = _source_tree()
    if source is None:
        raise RuntimeError(f"Could not install {wanted}. The pip output above says why.")
    subprocess.run([str(python), "-m", "pip", "install", "--quiet", f"{source}{extra}"], check=True)


_DOWNLOAD = """
import os, sys
from huggingface_hub import snapshot_download
repo, sub, patterns = sys.argv[1], sys.argv[2], sys.argv[3:]
path = snapshot_download(repo, allow_patterns=patterns or ([sub + "/*"] if sub else None))
print(os.path.join(path, sub) if sub else path)
"""


def download(python: Path, repo: str, subfolder: str = "", patterns: Sequence[str] = ()) -> str:
    """The model directory. Stored as a path so a server never asks the Hub again. Only `subfolder`, or the
    files matching `patterns`, are fetched when given."""
    out = subprocess.run([str(python), "-c", _DOWNLOAD, repo, subfolder, *patterns], stdout=subprocess.PIPE,
                         text=True, check=True)
    return out.stdout.strip().splitlines()[-1]


def gguf_patterns(model: Model) -> Tuple[str, ...]:
    """One language model of the GGUF repo, its vision encoder and the pointer heads."""
    return (f"*-{model.gguf_quant}.gguf", "mmproj-*.gguf", "pointer_heads.safetensors")


def pointer_states_path() -> Path:
    return config.state_dir() / "bin" / f"pointer_states-{POINTER_STATES_RELEASE}"


def fetch_pointer_states(http=requests) -> Path:
    """The release binary, checked against its pinned digest. CAPTCHA_POINTER_STATES names a local build instead."""
    import hashlib
    local = os.getenv("CAPTCHA_POINTER_STATES")
    if local:
        return Path(local)
    path = pointer_states_path()
    if path.is_file():
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    response = http.get(POINTER_STATES_URL, timeout=600)
    response.raise_for_status()
    digest = hashlib.sha256(response.content).hexdigest()
    if digest != POINTER_STATES_SHA256:
        raise RuntimeError(f"{POINTER_STATES_URL} has sha256 {digest}, not the {POINTER_STATES_SHA256} this "
                           "release pins. Nothing was installed.")
    temporary = path.with_suffix(".tmp")
    temporary.write_bytes(response.content)
    temporary.chmod(0o755)
    os.replace(temporary, path)
    return path


NO_VULKAN = ("llama.cpp runs the {gpu} through Vulkan, and this machine has no Vulkan loader. "
             "On Debian or Ubuntu: sudo apt install libvulkan1")
NO_VULKAN_GPU = ("Vulkan does not see the {gpu} (PCI {pci}); it sees {seen}. The NVIDIA driver's Vulkan part "
                 "may be missing: on Ubuntu it is in libnvidia-gl-<driver version>, and `vulkaninfo --summary` "
                 "(apt install vulkan-tools) lists what Vulkan sees.")


def check_vulkan(binary: Path, gpu: Gpu, run: Callable = subprocess.run) -> None:
    """That llama.cpp can reach `gpu`, before gigabytes of weights download for it."""
    out = run([str(binary), "--list-devices"], capture_output=True, text=True, timeout=60)
    if out.returncode != 0:
        if "libvulkan" in (out.stderr or ""):
            raise RuntimeError(NO_VULKAN.format(gpu=gpu.name))
        raise RuntimeError(f"{binary} --list-devices failed: {(out.stderr or '').strip()[-500:]}")
    lines = [line for line in out.stdout.splitlines() if line.startswith("{")]
    seen = json.loads(lines[-1])["gpus"] if lines else []
    if not any(d.get("pci", "").lower() == gpu.pci for d in seen):
        raise RuntimeError(NO_VULKAN_GPU.format(gpu=gpu.name, pci=gpu.pci,
                                                seen=", ".join(d["name"] for d in seen) or "no GPU"))


def free_port(start: int = 8000) -> int:
    for port in range(start, start + 100):
        with socket.socket() as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise RuntimeError(f"No free port between {start} and {start + 99}.")


def settings(choice: Choice, model_path: str, saved: dict) -> dict:
    small = choice.gpu.total_mib < SMALL_CARD_MIB
    return {
        "model": choice.model.repo,
        "title": choice.model.title,
        "model_path": model_path,
        "gpu": choice.gpu.index,
        "gpu_name": choice.gpu.name,
        "engine": choice.runs_on,
        "gpu_pci": choice.gpu.pci,
        "startup": choice.startup,
        "port": saved.get("port") or free_port(),
        # The client and the server both read it from this file, which only its owner can open.
        "key": saved.get("key") or secrets.token_hex(32),
        "gpu_memory_utilization": choice.model.small_card_utilization if small else 0.80,
        "max_cudagraph_capture_size": SMALL_CARD_CAPTURE_SIZE if small else None,
    }


def write_settings(values: dict) -> None:
    path = config.selfhost_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(values, f, indent=2)
    os.replace(temporary, path)


def link_command() -> Optional[Path]:
    """`captchakraken` on the PATH where the system already looks, so no shell file gets edited."""
    bin_dir = Path.home() / ".local" / "bin"
    link = bin_dir / "captchakraken"
    target = config.runtime_dir() / "bin" / "captchakraken"
    try:
        bin_dir.mkdir(parents=True, exist_ok=True)
        if link.is_symlink() or not link.exists():
            link.unlink(missing_ok=True)
            link.symlink_to(target)
    except OSError:
        return None
    return link if link.resolve() == target.resolve() else None


def _on_path(command: Path) -> bool:
    found = shutil.which(command.name)
    return bool(found) and Path(found).resolve() == command.resolve()


def _disk_check(model: Model) -> None:
    where = config.state_dir()
    where.mkdir(parents=True, exist_ok=True)
    free_gb = shutil.disk_usage(where).free / 1e9
    needed = model.download_gb + RUNTIME_GB
    if free_gb < needed:
        raise RuntimeError(f"This needs about {needed:.0f} GB of disk and {where} has {free_gb:.0f} GB free.")


def install(choice: Choice, saved: dict) -> dict:
    _disk_check(choice.model)
    server_manager.stop()

    engine = choice.runs_on
    llama: dict = {}
    if engine == LLAMACPP:
        _step(f"Checking that llama.cpp can reach the {choice.gpu.name}"
              + (" (vLLM has no kernels for it)" if choice.gpu.engine == LLAMACPP else ""))
        binary = fetch_pointer_states()
        check_vulkan(binary, choice.gpu)
        llama = {"pointer_states": str(binary), "quant": choice.model.gguf_quant}
    # The two engines need different torch builds of one version, and pip calls either one installed already.
    if (saved.get("engine") or VLLM) != engine:
        shutil.rmtree(config.runtime_dir(), ignore_errors=True)
    _step("Installing the serving stack (torch and vLLM)" if engine == VLLM
          else "Installing the serving stack (llama.cpp's helpers, on CPU torch)")
    python = make_venv(config.runtime_dir())
    install_client(python, "[serve]" if engine == VLLM else "[serve-llamacpp]")

    _step(f"Downloading {choice.model.title}")
    if engine == LLAMACPP:
        model_path = download(python, choice.model.gguf, patterns=gguf_patterns(choice.model))
        llama["processor_path"] = download(python, choice.model.processor_repo or choice.model.repo,
                                           choice.model.subfolder, PROCESSOR_FILES)
    else:
        model_path = download(python, choice.model.repo, choice.model.subfolder)

    values = {**settings(choice, model_path, saved), **llama}
    write_settings(values)
    config.selfhost.cache_clear()

    _step("Preparing the browser for the demo")
    try:
        from . import demo
        demo.prepare()
    except (RuntimeError, subprocess.SubprocessError, OSError) as e:
        print(f"  The demo browser did not install ({e}); `captchakraken demo` will try again.", flush=True)

    _step(f"Starting the server on GPU {choice.gpu.index} ({choice.gpu.name})")
    started = server_manager.start(background=True)
    if started["status"] not in ("running", "already-running"):
        raise RuntimeError(f"The server did not come up. Last lines of {server_manager.LOG_FILE}:\n"
                           + server_manager.log_tail())
    return values


def _summary(values: dict) -> None:
    command = link_command()
    bare = bool(command) and _on_path(command)
    name = "captchakraken" if bare else str(command or config.runtime_dir() / "bin" / "captchakraken")
    engine = ENGINE_OPTIONS.get(values.get("engine") or VLLM, ENGINE_OPTIONS[VLLM]).label
    _ok(f"{values['title']} is running on GPU {values['gpu']} with {engine} at http://127.0.0.1:{values['port']}")
    print(f"\nTry it:\n  {name} demo\n")
    print(f"Start and stop the server:\n  {name} start\n  {name} stop\n")
    if command and not bare:
        print(f"Open a new terminal for the short name `captchakraken`, once {command.parent} is on your PATH.\n")
    if os.getenv("VLLM_BASE_URL"):
        print(f"VLLM_BASE_URL is set in this shell, and it wins over this install: {os.environ['VLLM_BASE_URL']}\n")


def _no_model_fits(gpus: Sequence[Gpu]) -> str:
    return ("No model runs on " + ", ".join(g.name for g in gpus) + ": "
            + "; ".join(sorted({_unfit(m, g) for m in listed_models() for g in gpus})) + ".\n"
            "The hosted API needs no GPU: https://github.com/CaptchaKraken/CaptchaKraken/blob/main/docs/hosted-api.md")


def _from_flags(gpus: Sequence[Gpu], saved: dict, model: Optional[str], gpu: Optional[int],
                startup: Optional[str], engine: Optional[str] = None) -> Choice:
    wanted = model or saved.get("model") or next((m.repo for m in listed_models() if any(_fits(m, g) for g in gpus)),
                                                 MODELS[0].repo)
    found = next((m for m in MODELS if m.named(wanted)), None)
    if found is None:
        raise RuntimeError(f"Unknown model {wanted!r}. Choose from: abyss, "
                           + ", ".join(m.repo.split("/")[-1] for m in listed_models()))
    if engine and engine not in ENGINES:
        raise RuntimeError(f"Unknown engine {engine!r}. Choose from: {', '.join(ENGINES)}")
    asked = engine or ""
    index = gpu if gpu is not None else saved.get("gpu")
    if index is None:
        fitting = [g for g in gpus if _fits(found, g, asked)]
        if not fitting:
            biggest = max(gpus, key=lambda g: g.total_mib)
            raise RuntimeError(f"{found.title} cannot run here: {_unfit(found, biggest, asked)}."
                               + _runs_here_hint(gpus))
        chosen = max(fitting, key=lambda g: g.free_mib)
    else:
        chosen = next((g for g in gpus if g.index == index), None)
        if chosen is None:
            raise RuntimeError(f"There is no GPU {index}. Found: {[g.index for g in gpus]}")
        if _unfit(found, chosen, asked):
            raise RuntimeError(f"{found.title} cannot run on GPU {index}: {_unfit(found, chosen, asked)}."
                               + _runs_here_hint(gpus))
    if not engine:
        # The last engine, while it still runs this model on this card; else the card's default.
        engines = _engines(found, chosen)
        engine = saved.get("engine") if saved.get("engine") in engines else engines[0]
    return Choice(found, chosen, startup or saved.get("startup") or ALWAYS_ON, engine)


def _runs_here_hint(gpus: Sequence[Gpu]) -> str:
    here = [m.repo.split("/")[-1] for m in listed_models() if any(_fits(m, g) for g in gpus)]
    return f" These run here: --model {', '.join(here)}" if here else ""


NO_GPU = ("No NVIDIA GPU was found, and self-hosting needs one on Linux.\n"
          "The hosted API needs no GPU: https://github.com/CaptchaKraken/CaptchaKraken/blob/main/docs/hosted-api.md")


def fetch(*, yes: bool = False, model: Optional[str] = None, gpu: Optional[int] = None,
          startup: Optional[str] = None, engine: Optional[str] = None) -> int:
    if sys.platform != "linux":
        print(NO_GPU, file=sys.stderr)
        return 1
    try:
        gpus = detect_gpus()
    except RuntimeError as e:
        print(f"\033[1;31m✗\033[0m {e}", file=sys.stderr)
        return 1
    if not gpus:
        print(NO_GPU, file=sys.stderr)
        return 1
    saved = config.selfhost()
    interactive = sys.stdin.isatty() and sys.stdout.isatty()
    if not yes and not interactive:
        print("`captchakraken fetch` asks its questions in a terminal. Without one, pass --yes, "
              "plus --model, --gpu, --engine and --startup to choose other than the defaults.", file=sys.stderr)
        return 2
    try:
        if yes:
            choice = _from_flags(gpus, saved, model, gpu, startup, engine)
        else:
            print("\n\033[1mCaptchaKraken self-hosted setup\033[0m\n")
            choice = ask(gpus, saved)
        if choice.model.licensed:
            # A sign-in, not a choice: asked for whenever there is a terminal, --yes or not.
            ensure_access(choice.model.repo, interactive=interactive, access=choice.model.access,
                          subfolder=choice.model.subfolder)
        values = install(choice, saved)
    except Cancelled:
        print("Cancelled. Nothing was changed.")
        return 130
    except (RuntimeError, subprocess.CalledProcessError) as e:
        print(f"\033[1;31m✗\033[0m {e}", file=sys.stderr)
        return 1
    _summary(values)
    return 0
