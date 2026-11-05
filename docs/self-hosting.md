# Self-hosting CaptchaKraken v2

Run the model on your own GPU. Screenshots never leave your machine.

## One command

```bash
git clone https://github.com/CaptchaKraken/CaptchaKraken
cd CaptchaKraken
./setup.sh
```

The installer defaults to **Midnight V2 4B Q4** (GPTQ W4A16, about 3.6 GB of
weights), downloads the element detector, installs the tested vLLM stack into
`python/.venv`, and writes `captchakraken.env`. Use a CUDA GPU with at least
8 GB of free VRAM.

```bash
source captchakraken.env
captchakraken path/to/captcha.png
```

The server starts automatically on the first solve and stays running. To manage
it yourself:

```bash
captchakraken server start
captchakraken server status
captchakraken server stop
```

`./setup.sh --start` starts it during installation. `./setup.sh --quant bf16`
selects the full-precision Midnight V2 4B checkpoint instead. Q4 is the default
on every GPU; the installer no longer changes precision based on memory.

## The endpoint

The server listens on `http://127.0.0.1:8000` and provides:

- `POST /v1/pointer` — the v2 board-to-answer inference endpoint
- `GET /v1/models` — the served model name
- `GET /health` — the unauthenticated load-balancer health check

`captchakraken.env` contains a random bearer key. The client and server read it
from the same file, so no further configuration is needed. Remote vLLM endpoints
are never auto-started:

```bash
export VLLM_BASE_URL=http://your-server:8000/v1
export CAPTCHA_KRAKEN_API_KEY=your-server-key
export CAPTCHA_LORA_NAME=captcha-pointer
export CAPTCHA_LORA_ADAPTER=CaptchaKraken/MidnightV2-4B-q4
```

Generation 4 uses the pointer route, not `/v1/chat/completions`. Do not point a
v2 client at an older generation-2 or generation-3 server.

## Models and runtimes

The [CaptchaKraken v2 collection](https://huggingface.co/collections/CaptchaKraken/captchakraken-v2)
contains three model sizes. Midnight V2 4B Q4 is the default; the other merged
checkpoints can be selected by editing `CAPTCHA_BASE_MODEL` and
`CAPTCHA_LORA_ADAPTER` together in `captchakraken.env`.

- **Merged Q4 checkpoints** are the supported one-command vLLM path. The LoRA is
  already merged and the pointer heads ship beside it.
- **LoRA repositories** contain the unmerged adapter and pointer heads for
  further training. They are not interchangeable with the old 9B chat LoRA
  server.
- **GGUF repositories** contain Q4_K_M and BF16 weights, the required F16 vision
  projector, pointer heads, and a llama.cpp state-extraction tool. They are for
  advanced llama.cpp integrations: stock Ollama or `llama-server` alone cannot
  evaluate the external pointer heads and therefore is not a supported
  one-command CaptchaKraken server.

The CNN detector is downloaded from
[`CaptchaKraken/CaptchaKrakenV2-CNN-large`](https://huggingface.co/CaptchaKraken/CaptchaKrakenV2-CNN-large).
The client and all CaptchaKraken models are LGPL-3.0-only.

## Updating

```bash
./setup.sh --update
```

Or run `captchakraken fetch --engine-only`. Weight revisions can be pulled with
`captchakraken fetch --weights-only --no-restart`; restart the server afterward
to load them.

## Legacy generation-3 chat servers

These flags apply only to the old chat-completion models, not the v2 pointer
server. They remain documented for an existing pinned deployment:

```bash
vllm serve "$CAPTCHA_BASE_MODEL" \
  --reasoning-parser qwen3 \
  --enable-lora --enable-tower-connector-lora \
  --max-lora-rank 64 --max-model-len 65536 \
  --gpu-memory-utilization 0.80 --trust-remote-code \
  --port 8000 \
  --lora-modules "$CAPTCHA_LORA_NAME=$CAPTCHA_LORA_ADAPTER" \
  --limit-mm-per-prompt '{"image": 8, "video": 1}' \
  --media-io-kwargs '{"video": {"num_frames": -1, "fps": 5.0}}'
```

## Troubleshooting

- **401 from your own server:** run `source captchakraken.env` first.
- **Connection refused:** run `captchakraken server start` and inspect
  `~/.captchakraken/vllm.log`.
- **Unsupported pointer architecture:** use the environment created by
  `setup.sh`; it installs the tested vLLM and torch versions together.
- **404 on `/v1/chat/completions`:** this is the v2 pointer server; use the
  shipped client or `POST /v1/pointer`.
- **Out of memory:** stop other GPU jobs or lower
  `VLLM_GPU_MEMORY_UTILIZATION` in `captchakraken.env`.

Set `CAPTCHA_DEBUG=1` for solver diagnostics.

---

← Back to [docs index](./README.md)
