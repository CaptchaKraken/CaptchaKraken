#!/usr/bin/env bash
# One-command CaptchaKraken v2 self-hosting. The default is Midnight V2 4B Q4.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY_DIR="$HERE/python"
VENV_DIR="$PY_DIR/.venv"

BASE_BF16="CaptchaKraken/MidnightV2-4B"
BASE_AWQ="CaptchaKraken/MidnightV2-4B-q4"
LORA_ADAPTER="CaptchaKraken/MidnightV2-4B-q4"
LORA_NAME="captcha-pointer"
DETECTOR_REPO="CaptchaKraken/CaptchaKrakenV2-CNN-large"
PORT="${VLLM_PORT:-8000}"
QUANT="awq"
DOWNLOAD_ONLY=0
START_SERVER=0
UPDATE=0
ASSUME_YES=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --quant) QUANT="${2:-}"; shift 2 ;;
    --quant=*) QUANT="${1#*=}"; shift ;;
    --download-only) DOWNLOAD_ONLY=1; shift ;;
    --update) UPDATE=1; shift ;;
    --start) START_SERVER=1; shift ;;
    --yes|-y) ASSUME_YES=1; shift ;;
    -h|--help)
      echo "Usage: ./setup.sh [--quant q4|bf16] [--download-only] [--start] [--yes]"
      echo "Default: install and download Midnight V2 4B Q4 for vLLM."
      exit 0 ;;
    *) echo "Unknown option: $1" >&2; exit 2 ;;
  esac
done

info() { printf '\033[1;36m➜\033[0m %s\n' "$*"; }
ok()   { printf '\033[1;32m✓\033[0m %s\n' "$*"; }
err()  { printf '\033[1;31m✗\033[0m %s\n' "$*" >&2; }

case "$QUANT" in
  q4|awq) BASE="$BASE_AWQ"; QUANT="q4" ;;
  bf16) BASE="$BASE_BF16" ;;
  *) err "Invalid --quant '$QUANT' (use q4|bf16)"; exit 2 ;;
esac

if [[ "$UPDATE" == "1" ]]; then
  [[ -x "$VENV_DIR/bin/captchakraken" ]] || { err "Run ./setup.sh first."; exit 1; }
  [[ -f "$HERE/captchakraken.env" ]] && { set -a; source "$HERE/captchakraken.env"; set +a; }
  exec "$VENV_DIR/bin/captchakraken" fetch --engine-only
fi

SYS_PY="${CAPTCHA_KRAKEN_PYTHON:-python3}"
[[ -x "$VENV_DIR/bin/python" ]] || "$SYS_PY" -m venv "$VENV_DIR"
PY="$VENV_DIR/bin/python"
"$PY" -m pip install --upgrade pip wheel >/dev/null

if [[ "$DOWNLOAD_ONLY" == "1" ]]; then
  "$PY" -m pip install "huggingface_hub[cli]==1.30.0"
else
  VER="$(grep -m1 '^version' "$PY_DIR/pyproject.toml" | sed 's/.*"\(.*\)".*/\1/')"
  info "Installing CaptchaKraken $VER with its vLLM serving stack"
  if ! "$PY" -m pip install "captchakraken[serve]==${VER}"; then
    "$PY" -m pip install "$PY_DIR[serve]"
  fi
fi

HF="$VENV_DIR/bin/hf"
[[ -x "$HF" ]] || HF="$VENV_DIR/bin/huggingface-cli"
info "Downloading $BASE ($QUANT)"
"$HF" download "$BASE" >/dev/null
DETECTOR="$("$HF" download "$DETECTOR_REPO" detector_r18.pt)"
ok "Weights cached under ${HF_HOME:-$HOME/.cache/huggingface}"

KEY="$(head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n')"
cat > "$HERE/captchakraken.env" <<EOF
# Source this file before solving: source captchakraken.env
export VLLM_BASE_URL="http://127.0.0.1:${PORT}/v1"
export CAPTCHA_KRAKEN_API_KEY="${KEY}"
export CAPTCHA_BASE_MODEL="${BASE}"
export CAPTCHA_LORA_ADAPTER="${LORA_ADAPTER}"
export CAPTCHA_LORA_NAME="${LORA_NAME}"
export CAPTCHA_POINTER_DETECTOR="${DETECTOR}"
export VLLM_PORT="${PORT}"
export VLLM_ENABLE_V1_MULTIPROCESSING=0
EOF
chmod 600 "$HERE/captchakraken.env"
ok "Wrote captchakraken.env"

if [[ "$DOWNLOAD_ONLY" == "1" ]]; then
  ok "Download complete."
  exit 0
fi
if [[ "$START_SERVER" == "1" ]]; then
  ( set -a; source "$HERE/captchakraken.env"; set +a
    export VLLM_API_KEY="$CAPTCHA_KRAKEN_API_KEY"
    "$VENV_DIR/bin/captchakraken" server start )
  ok "Server started."
else
  ok "Ready. The server starts on your first solve."
  echo "  source captchakraken.env"
  echo "  captchakraken path/to/captcha.png"
fi
