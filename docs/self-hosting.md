# Self-hosting CaptchaKraken v2

Run the model on your own GPU. Screenshots never leave your machine.

## One command

```bash
npx captchakraken fetch
```

Or from Python, with no Node involved:

```bash
pipx run captchakraken fetch     # or: uvx captchakraken fetch
```

It detects your NVIDIA GPUs and asks three things:

1. **Which model.** Midnight V2 4B Q4 is the default.
2. **Which GPU.** Each detected card is listed with its free memory, and a card
   too small for the model cannot be picked.
3. **When the server runs.**
   - **Always on** starts with the machine and restarts if it crashes.
   - **Warm start** starts now, and after a reboot on the first solve, then
     stays loaded.

Then it installs the tested serving stack, downloads the weights and the element
detector, fetches a browser for the demo, starts the server and waits until it
answers. There is nothing to export and no PATH to edit. Try it:

```bash
captchakraken demo
```

Use it from your own code with no configuration: every client on this machine
finds the server through `~/.captchakraken/selfhost.json`.

| Model | Download | GPU |
|---|---|---|
| Midnight V2 4B Q4 (default) | 3.8 GB | 8 GB card (measured on an RTX 5060: 5.3 GB in use) |
| Twilight V2 2B | 4.5 GB | 8 GB card (measured on an RTX 5060: 6.0 GB in use) |
| Midnight V2 4B (full precision) | 9.1 GB | 16 GB card (estimated from its size, not measured on a 16 GB card) |

Allow about 8 GB of disk for the serving stack as well. Self-hosting needs Linux
and an NVIDIA GPU; on anything else use the [hosted API](./hosted-api.md).

### Starting and stopping

```bash
captchakraken stop      # off, and stays off across reboots and solves
captchakraken start     # back on; waits until it answers
captchakraken status    # endpoint, model, GPU and startup mode
```

`stop` is respected: a solve against a stopped server fails with a message
telling you to run `captchakraken start`, instead of quietly starting it again.
It does not fall back to the hosted API.

### Changing your mind, and updating

Run `npx captchakraken fetch` again. Your previous answers are where the cursor
starts, and your key and port are kept. A newer `captchakraken` installs the
matching serving stack as part of the same run.

### Without a terminal

```bash
captchakraken fetch --yes                     # previous answers, then the defaults
captchakraken fetch --model MidnightV2-4B-q4 --gpu 0 --startup always
captchakraken fetch --model TwilightV2-2B --startup first-solve
```

### What it leaves on your machine

Everything is under `~/.captchakraken`, apart from the weights in the Hugging
Face cache, a `~/.local/bin/captchakraken` link, and with **Always on** a systemd
user unit, `captchakraken-local.service`. To go back to the hosted API, run
`captchakraken stop` and delete `~/.captchakraken/selfhost.json`. Setting
`VLLM_BASE_URL` also overrides this install for that process.

## The endpoint

The server listens on `127.0.0.1`, on the first free port from 8000 up (`captchakraken status` says which), and provides:

- `POST /v1/pointer` — the v2 board-to-answer inference endpoint
- `GET /v1/models` — the served model name
- `GET /health` — the unauthenticated load-balancer health check

A pointer response carries three complete plans, best first:

```json
{"actions": [{"action": "click", "points": [[x, y]], "checks": {}},
             {"action": "click", "points": [[x, y]], "checks": {}},
             {"action": "drag", "drags": [{"from": [x, y], "to": [x, y]}], "checks": {}}],
 "answer": {"action": "click", "points": [[x, y]], "checks": {}},
 "size": [W, H],
 "elements": [{"id": 1, "class": "tile", "box": [x, y, w, h], "score": 0.9}]}
```

Perform the first action. The second and third are the next likeliest distinct
plans, for a retry after the widget refuses it. `answer` repeats the first for
callers written before `actions`. The shipped Python and JavaScript drivers try
all three in that order, then refresh the board.

`~/.captchakraken/selfhost.json` holds a random bearer key that only its owner can
read. The client and server take it from that file, so no further configuration
is needed. Remote vLLM endpoints are never auto-started:

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
contains three model sizes. `captchakraken fetch` offers the ones this client can
load; the Sunlight V2 0.8B heads predate the current output layout and are not
offered until they are republished.

- **Merged checkpoints** are the supported one-command vLLM path. The LoRA is
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

## Updating parts separately

`captchakraken fetch` above is the normal path. For a server you manage yourself,
`captchakraken fetch --engine-only` upgrades the serving stack, and
`captchakraken fetch --weights-only --no-restart` pulls weight revisions; restart
the server afterward to load them.

## Licensed weights

Abyss is served through the hosted API to every account. Its weights are in a
gated Hugging Face repo, `CaptchaKraken/Abyss`, open to Abyss Licence holders:
buy a licence at <https://captchakraken.com/plans>, add your Hugging Face
username on that page, then sign in as that account and fetch:

```bash
hf auth login
CAPTCHA_LORA_ADAPTER=CaptchaKraken/Abyss captchakraken fetch --weights-only --no-restart
```

`--dry-run` lists the repo under `needs_auth`. If the Hub refuses the download
(no token, or an account without access), `fetch` stops and says where to get a
licence.

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

- **"The CaptchaKraken server is stopped":** run `captchakraken start`.
- **The server did not come up:** the command prints the end of
  `~/.captchakraken/vllm.log`, which holds the whole story.
- **Out of memory while starting:** another job holds the card. Stop it, or run
  `captchakraken fetch` and pick a different GPU. Cards under 12 GB already get a
  smaller memory reservation and graph set automatically.
- **401 from your own server:** `CAPTCHA_KRAKEN_API_KEY` is ignored for this install
  unless `VLLM_BASE_URL` also points elsewhere, so check for a `VLLM_BASE_URL` naming
  another server. `captchakraken fetch` warns when one is set.
- **Always on does not survive a reboot:** your system refused `loginctl
  enable-linger`, so the unit only starts when you log in.
- **404 on `/v1/chat/completions`:** this is the v2 pointer server; use the
  shipped client or `POST /v1/pointer`.

Set `CAPTCHA_DEBUG=1` for solver diagnostics.

---

← Back to [docs index](./README.md)
