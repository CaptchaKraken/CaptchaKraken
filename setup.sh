#!/usr/bin/env bash
#
# setup.sh — one command to set up the self-hosted CaptchaKraken solver.
#
# It does everything the inference server needs, in one place:
#   1. Detects your accelerator memory and picks a base-model quantization that
#      actually fits (or refuses, with clear options).
#   2. Creates a venv under python/.venv and installs `captchakraken[serve]`
#      — this PULLS vLLM + the serving stack + the CLI.
#   3. Downloads the base model + the captcha LoRA from HuggingFace.
#   4. Writes a sourceable `captchakraken.env` with the (model-agnostic) config
#      the solver + server read automatically.
#   5. Optionally starts the vLLM server now (otherwise it AUTO-STARTS on your
#      first solve — you never have to babysit it).
#
# Usage:
#   ./setup.sh                  # auto-detect, install, download, write env
#   ./setup.sh --start          # ...and start the server now
#   ./setup.sh --quant fp8|awq|bf16
#   ./setup.sh --download-only  # just fetch weights (skip the hardware gate)
#   ./setup.sh --update         # pull latest weights + upgrade vLLM (already set up)
#   ./setup.sh --yes            # non-interactive (accept the recommended path)
#
# After setup, everything is hands-off:
#   source captchakraken.env
#   captchakraken path/to/captcha.png     # server auto-starts on first call
# Point VLLM_BASE_URL at a server you already run to skip local management.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY_DIR="$HERE/python"
VENV_DIR="$PY_DIR/.venv"

# ── Model registry (all overridable via the env file we write) ──────────────
BASE_BF16="Qwen/Qwen3.5-9B"                     # full precision, ~18 GB, matches training
BASE_FP8="RedHatAI/Qwen3.5-9B-FP8-dynamic"      # 8-bit, ~14 GB, best accuracy/size trade
BASE_AWQ="cyankiwi/Qwen3.5-9B-AWQ-4bit"         # 4-bit, ~6 GB, lighter / lower accuracy
# These two MUST match the `latest` entry in python/src/captchakraken/models.json:
# the env file we write overrides the client's own defaults, and an adapter that
# is not registered there resolves to generation-1 prompts against whatever
# generation the weights were trained on — silently, on every puzzle.
# tests/test_setup_sh_model_ids.py pins the match.
LORA_ADAPTER="CaptchaKraken/CaptchaKraken-Lora-v1.2"   # the unified captcha adapter
LORA_NAME="captcha-v12"                         # served name the client requests as `model`
PORT="${VLLM_PORT:-8000}"
REPO_URL="https://github.com/CaptchaKraken/CaptchaKraken"

FP8_MIN=22   # GB — comfortable FP8 serve (weights + KV + bf16 ViT + LoRA)
AWQ_MIN=11   # GB — comfortable AWQ serve
HARD_FLOOR=$AWQ_MIN

QUANT=""; DOWNLOAD_ONLY=0; ASSUME_YES=0; START_SERVER=0; UPDATE=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --quant) QUANT="${2:-}"; shift 2 ;;
    --quant=*) QUANT="${1#*=}"; shift ;;
    --download-only) DOWNLOAD_ONLY=1; shift ;;
    --update) UPDATE=1; shift ;;
    --start) START_SERVER=1; shift ;;
    --yes|-y) ASSUME_YES=1; shift ;;
    -h|--help) sed -n '2,29p' "$0"; exit 0 ;;
    *) echo "Unknown option: $1" >&2; exit 2 ;;
  esac
done

c() { printf '\033[%sm%s\033[0m' "$1" "$2"; }
info() { echo "$(c '1;36' '➜') $*"; }
ok()   { echo "$(c '1;32' '✓') $*"; }
warn() { echo "$(c '1;33' '!') $*"; }
err()  { echo "$(c '1;31' '✗') $*" >&2; }

# ── Hardware detection ──────────────────────────────────────────────────────
detect_hardware() {
  DETECT_MEM_GB=0; DETECT_KIND="cpu"
  if command -v nvidia-smi >/dev/null 2>&1; then
    local mib
    mib=$(nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits 2>/dev/null | sort -rn | head -1 || echo 0)
    if [[ -n "$mib" && "$mib" -gt 0 ]]; then DETECT_MEM_GB=$(( mib / 1024 )); DETECT_KIND="nvidia"; return; fi
  fi
  if [[ "$(uname -s)" == "Darwin" && "$(uname -m)" == "arm64" ]]; then
    local bytes; bytes=$(sysctl -n hw.memsize 2>/dev/null || echo 0)
    if [[ "$bytes" -gt 0 ]]; then DETECT_MEM_GB=$(( bytes / 1024 / 1024 / 1024 )); DETECT_KIND="apple"; return; fi
  fi
  if [[ -r /proc/meminfo ]]; then
    local kb; kb=$(awk '/MemTotal/ {print $2}' /proc/meminfo); DETECT_MEM_GB=$(( kb / 1024 / 1024 ))
  fi
}

pick_quant() {
  if [[ -n "$QUANT" ]]; then info "Quantization forced to: $QUANT"; return; fi
  if (( DETECT_MEM_GB >= FP8_MIN )); then
    QUANT="fp8"; ok "~${DETECT_MEM_GB} GB ${DETECT_KIND} → 8-bit FP8 (best accuracy)."
  elif (( DETECT_MEM_GB >= AWQ_MIN )); then
    QUANT="awq"; ok "~${DETECT_MEM_GB} GB ${DETECT_KIND} → 4-bit AWQ (lighter)."
  else
    err "Detected ~${DETECT_MEM_GB} GB ${DETECT_KIND} — below the ${HARD_FLOOR} GB floor to serve even the 4-bit model."
    echo "  1) Download weights anyway (stage for a bigger box):  ./setup.sh --download-only"
    echo "  2) Use the hosted API instead — no GPU needed:  https://captchakraken.com/signin"
    if [[ "$ASSUME_YES" == "1" ]]; then exit 1; fi
    read -r -p "Download-only now? [y/N]: " a
    case "${a:-N}" in y|Y) QUANT="awq"; DOWNLOAD_ONLY=1 ;; *) exit 0 ;; esac
  fi
}

# ── venv + serving stack (pulls vLLM) ───────────────────────────────────────
ensure_venv() {
  local sys_py="${CAPTCHA_KRAKEN_PYTHON:-python3}"
  if [[ ! -x "$VENV_DIR/bin/python" ]]; then
    info "Creating venv at $VENV_DIR"
    "$sys_py" -m venv "$VENV_DIR"
  fi
  PY="$VENV_DIR/bin/python"
  "$PY" -m pip install --upgrade pip wheel >/dev/null
}

install_serve_stack() {
  # Prefer the PUBLISHED package from PyPI (pinned to this checkout's version so
  # the engine matches the repo), falling back to the local source tree only if
  # PyPI can't satisfy it — offline, or a dev build not yet released.
  local ver
  ver="$(grep -m1 '^version' "$PY_DIR/pyproject.toml" | sed 's/.*"\(.*\)".*/\1/')"
  info "Installing captchakraken[serve]==${ver} from PyPI (pulls vLLM + serving stack)…"
  if "$PY" -m pip install "captchakraken[serve]==${ver}"; then
    ok "Serving stack installed from PyPI (vLLM + CLI in $VENV_DIR)."
  else
    warn "PyPI install failed; falling back to the local source tree."
    "$PY" -m pip install "$PY_DIR[serve]"
    ok "Serving stack installed from source (vLLM + CLI in $VENV_DIR)."
  fi
}

install_weights_only_deps() {
  # download-only path still needs the HF CLI.
  "$PY" -m pip install --upgrade "huggingface_hub[cli]" >/dev/null
}

# ── Weights ─────────────────────────────────────────────────────────────────
download_weights() {
  local base="$1"
  local hf="$VENV_DIR/bin/hf"
  [[ -x "$hf" ]] || hf="$VENV_DIR/bin/huggingface-cli"
  info "Downloading base model: $base"
  "$hf" download "$base" >/dev/null
  info "Downloading captcha LoRA: $LORA_ADAPTER"
  "$hf" download "$LORA_ADAPTER" >/dev/null
  ok "Weights cached under ${HF_HOME:-$HOME/.cache/huggingface}."
}

# ── Env file ────────────────────────────────────────────────────────────────
write_env() {
  local base="$1" key
  key="$(head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n' 2>/dev/null || echo changeme)"
  cat > "$HERE/captchakraken.env" <<EOF
# captchakraken.env — generated by setup.sh ($(date -u +%Y-%m-%dT%H:%M:%SZ))
# Source before solving:  source captchakraken.env
#
# The two most people ever touch:
export VLLM_BASE_URL="http://localhost:${PORT}/v1"
export CAPTCHA_KRAKEN_API_KEY="${key}"
#
# Which model gets served (model-agnostic — change these to serve anything):
export CAPTCHA_BASE_MODEL="${base}"
export CAPTCHA_LORA_ADAPTER="${LORA_ADAPTER}"
export CAPTCHA_LORA_NAME="${LORA_NAME}"
export VLLM_PORT="${PORT}"
EOF
  ok "Wrote captchakraken.env"
}

# ── Main ────────────────────────────────────────────────────────────────────
echo "$(c '1;35' '╔══ CaptchaKraken setup ══╗')"

# --update: an already-set-up box just wants the latest weights + engine. Skip
# the whole hardware-gate/install/env-write flow and hand off to the unified
# fetch command (pulls latest LoRA+base from HF, upgrades vLLM, restarts server).
if [[ "$UPDATE" == "1" ]]; then
  if [[ ! -x "$VENV_DIR/bin/captchakraken" ]]; then
    err "No venv found at $VENV_DIR — run ./setup.sh first, then ./setup.sh --update."
    exit 1
  fi
  info "Updating: pulling latest weights from HuggingFace + upgrading vLLM…"
  [[ -f "$HERE/captchakraken.env" ]] && { set -a; source "$HERE/captchakraken.env"; set +a; }
  "$VENV_DIR/bin/captchakraken" fetch
  ok "Update complete."
  exit 0
fi

detect_hardware
info "Detected: ${DETECT_KIND}, ~${DETECT_MEM_GB} GB memory."

if [[ "$DOWNLOAD_ONLY" == "1" && -z "$QUANT" ]]; then QUANT="awq"; warn "--download-only: defaulting to AWQ 4-bit."; else pick_quant; fi
case "$QUANT" in
  fp8)  BASE="$BASE_FP8" ;;
  awq)  BASE="$BASE_AWQ" ;;
  bf16) BASE="$BASE_BF16" ;;
  *) err "Invalid --quant '$QUANT' (use fp8|awq|bf16)"; exit 2 ;;
esac

ensure_venv
if [[ "$DOWNLOAD_ONLY" == "1" ]]; then install_weights_only_deps; else install_serve_stack; fi
download_weights "$BASE"
write_env "$BASE"

if [[ "$DOWNLOAD_ONLY" == "1" ]]; then
  ok "Download-only complete. Copy the HF cache + captchakraken.env to your server."
  exit 0
fi

if [[ "$START_SERVER" == "1" ]]; then
  info "Starting the vLLM server…"
  ( set -a; source "$HERE/captchakraken.env"; set +a; export VLLM_API_KEY="$CAPTCHA_KRAKEN_API_KEY"; "$VENV_DIR/bin/captchakraken" server start )
  ok "Server started. Check: source captchakraken.env && captchakraken server status"
else
  echo
  ok "Done. The server AUTO-STARTS on your first solve — nothing else to run:"
  echo "    source captchakraken.env"
  echo "    captchakraken path/to/captcha.png"
  echo "  Or start it explicitly now:  captchakraken server start"
fi
echo
info "No GPU on another box? The hosted API needs none: https://captchakraken.com/signin"
