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

Then it installs the tested serving stack, downloads the weights, fetches a
browser for the demo, starts the server and waits until it
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

### Older GPUs

The serving stack is vLLM, built for compute capability 7.5 and up: RTX 20
series and newer, GTX 16 series, T4. On an older card (GTX 10 series, Tesla
P40 or P100, V100), `fetch` runs the model's GGUF build on llama.cpp instead,
through the NVIDIA driver's Vulkan support, and says so. It is one download: a
prebuilt `pointer_states` binary, about 1 GB of Python helpers instead of
vLLM's 8 GB, and the weights. Nothing compiles.

It needs the Vulkan loader, which a desktop install usually has already:

```bash
sudo apt install libvulkan1
```

Midnight V2 4B Q4 and Twilight V2 2B run on an 8 GB card, Midnight V2 4B at
full precision on 16 GB. Abyss has no GGUF build yet, so `fetch` does not offer
it on such a card.

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
captchakraken fetch abyss                     # Abyss V2 Q4, with an Abyss Licence
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

`captchakraken fetch` downloads only the model; the client runs no detector
model of its own.
The client and all CaptchaKraken models are LGPL-3.0-only.

## Updating parts separately

`captchakraken fetch` above is the normal path. A server you manage yourself on
a card older than compute capability 7.5 runs the same endpoint on llama.cpp.
`--device` is the card's PCI address, as `nvidia-smi --query-gpu=pci.bus_id
--format=csv` prints it, with the domain cut to four digits; `pointer_states
--list-devices` prints what Vulkan sees.

```bash
pip install torch==2.13.0 torchvision==0.28.0 --index-url https://download.pytorch.org/whl/cpu
pip install "captchakraken[serve-llamacpp]"
curl -fL -o pointer_states https://github.com/CaptchaKraken/CaptchaKraken/releases/download/pointer-states-b12819/pointer_states-linux-x86_64
chmod +x pointer_states
hf download CaptchaKraken/TwilightV2-2B-GGUF --include "*-Q4_K_M.gguf" "mmproj-*.gguf" pointer_heads.safetensors --local-dir TwilightV2-2B-GGUF
hf download CaptchaKraken/TwilightV2-2B tokenizer.json tokenizer_config.json processor_config.json chat_template.jinja config.json --local-dir TwilightV2-2B
python -m captchakraken.pointer.server --engine llamacpp --model TwilightV2-2B-GGUF --processor TwilightV2-2B \
  --pointer-states ./pointer_states --device 0000:01:00.0 --port 8000
```

To build `pointer_states` yourself (another CPU architecture, or a newer
llama.cpp), see [`native/pointer_states`](../native/pointer_states).

For a vLLM server you manage yourself,
`captchakraken fetch --engine-only` upgrades the serving stack, and
`captchakraken fetch --weights-only --no-restart` pulls weight revisions; restart
the server afterward to load them.

## Abyss (licensed)

Abyss is served through the hosted API to every account. With an Abyss Licence
you can also run it yourself:

1. Buy the licence at <https://captchakraken.com/plans> and add your Hugging
   Face username on that page. Access to the gated `CaptchaKraken/AbyssV2`
   repos follows within a couple of minutes.
2. Run:

```bash
npx captchakraken fetch abyss      # or: pipx run captchakraken fetch abyss
```

It asks for a Hugging Face token (read access is enough) unless you are
already signed in with `hf auth login` or `HF_TOKEN`, checks that the account
can download Abyss, and only then installs the serving stack, downloads
Abyss V2 Q4, and starts the server on your roomiest GPU. A typed token is saved
where `hf auth login` keeps it, so later updates use it too. For the
full-precision checkpoint (16 GB of VRAM), use `--model AbyssV2`. Both are also
in the `captchakraken fetch` menu.

If the account cannot download it, `fetch` names the account and points at the
plans page before anything installs.

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
- **"no kernel image is available for execution on the device", or "Minimum
  capability: 70":** the server was installed by a `captchakraken` that did not
  yet read the card's compute capability. Run `npx captchakraken@latest fetch`
  (or `pipx run captchakraken fetch`) again.
- **"Vulkan does not see the GTX 1070":** the NVIDIA driver's Vulkan part is
  missing. On Ubuntu it is in `libnvidia-gl-<driver version>`; `vulkaninfo
  --summary` (from `vulkan-tools`) lists what Vulkan sees.
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
