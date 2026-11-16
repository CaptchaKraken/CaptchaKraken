"""`captchakraken fetch`: ask which model, GPU and startup mode, then install, download and start it.

Everything lands under the state directory and the choices live in `selfhost.json`, so a solve, the
server and `captchakraken start` read one file and nobody exports anything or edits their PATH.
The serving stack gets its own environment because the one running this command may be a throwaway:
npx and pipx both evict theirs, and a server must not break when they do.
"""

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
from typing import Callable, List, NamedTuple, Optional, Sequence

from . import __version__, config, server_manager

ALWAYS_ON = "always"
FIRST_SOLVE = "first-solve"

# The serving stack on disk, measured: torch and vLLM with their CUDA libraries.
RUNTIME_GB = 8.0
# vLLM's default reservation and graph set run an 8 GB card out of memory while it starts.
SMALL_CARD_MIB = 12_000
SMALL_CARD_CAPTURE_SIZE = 16


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


# Sunlight is absent on purpose: its published heads predate this client's layout and refuse to load.
MODELS = (
    Model("CaptchaKraken/MidnightV2-4B-q4", "Midnight V2 4B Q4", "the default: best balance of speed and accuracy",
          3.8, 8),
    Model("CaptchaKraken/TwilightV2-2B", "Twilight V2 2B", "smaller model, full precision", 4.5, 8, 0.80),
    Model("CaptchaKraken/MidnightV2-4B", "Midnight V2 4B", "the same model at full precision", 9.1, 16),
)


class Gpu(NamedTuple):
    index: int
    name: str
    total_mib: int
    free_mib: int

    @property
    def label(self) -> str:
        return f"{self.name} ({self.total_mib / 1024:.0f} GB, {self.free_mib / 1024:.1f} GB free)"


class Choice(NamedTuple):
    model: Model
    gpu: Gpu
    startup: str


class Cancelled(Exception):
    pass


def _fits(model: Model, gpu: Gpu) -> bool:
    # Cards are sold in GB and report a little under it: an "8 GB" 5060 reports 8151 MiB, a 7.96.
    return gpu.total_mib >= model.min_vram_gb * 1024 * 0.95


def _busy_note(model: Model, gpu: Gpu) -> str:
    # The server holds about 70% of a card sold at the model's minimum.
    return "" if gpu.free_mib >= model.min_vram_gb * 1024 * 0.7 else "too full right now unless you free it up"


def detect_gpus(run: Callable = subprocess.run) -> List[Gpu]:
    """Numbered as nvidia-smi numbers them, which is PCI order, so the server is pinned with that same order."""
    try:
        out = run(["nvidia-smi", "--query-gpu=index,name,memory.total,memory.free", "--format=csv,noheader,nounits"],
                  capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return []
    if out.returncode != 0:
        return []
    gpus = []
    for line in out.stdout.splitlines():
        fields = [f.strip() for f in line.split(",")]
        if len(fields) == 4 and fields[0].isdigit() and fields[2].isdigit() and fields[3].isdigit():
            gpus.append(Gpu(int(fields[0]), fields[1], int(fields[2]), int(fields[3])))
    return gpus


# ── the terminal menu ────────────────────────────────────────────────────────

class Option(NamedTuple):
    label: str
    detail: str = ""
    disabled: str = ""


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
    biggest = max(gpus, key=lambda g: g.total_mib)
    default_model = next((i for i, m in enumerate(MODELS) if m.repo == saved.get("model")), 0)
    picked = MODELS[choose("Which model do you want to run?", [
        Option(m.title, f"{m.blurb}, {m.download_gb:.1f} GB download, needs {m.min_vram_gb} GB of VRAM",
               "" if _fits(m, biggest) else f"needs {m.min_vram_gb} GB of VRAM, your largest has "
                                            f"{biggest.total_mib / 1024:.0f} GB")
        for m in MODELS], default_model)]

    fitting = [g for g in gpus if _fits(picked, g)]
    default_gpu = next((i for i, g in enumerate(gpus) if g.index == saved.get("gpu")), None)
    if default_gpu is None or gpus[default_gpu] not in fitting:
        default_gpu = gpus.index(max(fitting, key=lambda g: g.free_mib))
    gpu = gpus[choose("Which GPU should the server run on?", [
        Option(f"GPU {g.index}: {g.label}", _busy_note(picked, g), "" if g in fitting else f"too small for {picked.title}")
        for g in gpus], default_gpu)]

    modes = [ALWAYS_ON, FIRST_SOLVE]
    startup = modes[choose("When should the server run?", [
        Option("Always on", "starts with this machine and restarts if it crashes"),
        Option("Warm start", "starts now and after a reboot on the first solve, then stays loaded"),
    ], modes.index(saved["startup"]) if saved.get("startup") in modes else 0)]
    return Choice(picked, gpu, startup)


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
    wanted = f"captchakraken{extra}=={__version__}"
    if subprocess.run([str(python), "-m", "pip", "install", "--quiet", wanted]).returncode == 0:
        return
    source = _source_tree()
    if source is None:
        raise RuntimeError(f"Could not install {wanted}. The pip output above says why.")
    subprocess.run([str(python), "-m", "pip", "install", "--quiet", f"{source}{extra}"], check=True)


_DOWNLOAD = """
import sys
from huggingface_hub import snapshot_download
print(snapshot_download(sys.argv[1]))
"""


def download(python: Path, repo: str) -> str:
    """The model directory. Stored as a path so a server never asks the Hub again."""
    out = subprocess.run([str(python), "-c", _DOWNLOAD, repo], stdout=subprocess.PIPE, text=True, check=True)
    return out.stdout.strip().splitlines()[-1]


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

    _step("Installing the serving stack (torch and vLLM)")
    python = make_venv(config.runtime_dir())
    install_client(python, "[serve]")

    _step(f"Downloading {choice.model.title}")
    model_path = download(python, choice.model.repo)

    values = settings(choice, model_path, saved)
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
    _ok(f"{values['title']} is running on GPU {values['gpu']} at http://127.0.0.1:{values['port']}")
    print(f"\nTry it:\n  {name} demo\n")
    print(f"Start and stop the server:\n  {name} start\n  {name} stop\n")
    if command and not bare:
        print(f"Open a new terminal for the short name `captchakraken`, once {command.parent} is on your PATH.\n")
    if os.getenv("VLLM_BASE_URL"):
        print(f"VLLM_BASE_URL is set in this shell, and it wins over this install: {os.environ['VLLM_BASE_URL']}\n")


def _from_flags(gpus: Sequence[Gpu], saved: dict, model: Optional[str], gpu: Optional[int],
                startup: Optional[str]) -> Choice:
    wanted = model or saved.get("model") or MODELS[0].repo
    found = next((m for m in MODELS if wanted in (m.repo, m.repo.split("/")[-1])), None)
    if found is None:
        raise RuntimeError(f"Unknown model {wanted!r}. Choose from: "
                           + ", ".join(m.repo.split("/")[-1] for m in MODELS))
    index = gpu if gpu is not None else saved.get("gpu")
    if index is None:
        fitting = [g for g in gpus if _fits(found, g)]
        if not fitting:
            raise RuntimeError(f"{found.title} needs {found.min_vram_gb} GB of VRAM.")
        chosen = max(fitting, key=lambda g: g.free_mib)
    else:
        chosen = next((g for g in gpus if g.index == index), None)
        if chosen is None:
            raise RuntimeError(f"There is no GPU {index}. Found: {[g.index for g in gpus]}")
    return Choice(found, chosen, startup or saved.get("startup") or ALWAYS_ON)


NO_GPU = ("No NVIDIA GPU was found, and self-hosting needs one on Linux.\n"
          "The hosted API needs no GPU: https://github.com/CaptchaKraken/CaptchaKraken/blob/main/docs/hosted-api.md")


def fetch(*, yes: bool = False, model: Optional[str] = None, gpu: Optional[int] = None,
          startup: Optional[str] = None) -> int:
    if sys.platform != "linux":
        print(NO_GPU, file=sys.stderr)
        return 1
    gpus = detect_gpus()
    if not gpus:
        print(NO_GPU, file=sys.stderr)
        return 1
    saved = config.selfhost()
    interactive = sys.stdin.isatty() and sys.stdout.isatty()
    if not yes and not interactive:
        print("`captchakraken fetch` asks its questions in a terminal. Without one, pass --yes, "
              "plus --model, --gpu and --startup to choose other than the defaults.", file=sys.stderr)
        return 2
    try:
        if yes:
            choice = _from_flags(gpus, saved, model, gpu, startup)
        else:
            print("\n\033[1mCaptchaKraken self-hosted setup\033[0m\n")
            choice = ask(gpus, saved)
        values = install(choice, saved)
    except Cancelled:
        print("Cancelled. Nothing was changed.")
        return 130
    except (RuntimeError, subprocess.CalledProcessError) as e:
        print(f"\033[1;31m✗\033[0m {e}", file=sys.stderr)
        return 1
    _summary(values)
    return 0
