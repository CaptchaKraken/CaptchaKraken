# 🖥️ Self-hosting

Run the model on your own GPU or Apple-silicon machine. Nothing leaves your
computer.

> 💡 **No GPU?** Use the [hosted API](./hosted-api.md) instead. It needs no
> weights, no vLLM, and no card.

## Pick a model

There are three ways to self-host, and they install different things.

| | **Merged model** | **GGUF** | **LoRA adapter** (what `setup.sh` installs) |
|---|---|---|---|
| Downloads | One file set | One file + a projector | Base model + adapter |
| Runtimes | vLLM, and any runtime that loads standard safetensors | Ollama, llama.cpp, LM Studio | vLLM only |
| Needs a GPU | Yes | No — CPU works, slowly | Yes |
| Setup | `vllm serve <id>` | `ollama run <id>` | `./setup.sh` |

All three are published under the Source-Available License, and the current
builds of all three are **prompt generation 2**. Pick GGUF if you use Ollama or
have no GPU, the merged model for the simplest vLLM serve, and the adapter for
the most accurate open weights.

### The merged models

The adapter already merged into the base and quantised, so there is nothing to
wire up.

| | Release | Precision | Size | Min VRAM | Hub |
|---|---|---|---|---|---|
| 🟦 **Sunlight v1.2** | current | 4-bit (AWQ) | 11 GB | ~14 GB | [`Sunlight-v1.2-AWQ-4bit`](https://huggingface.co/CaptchaKraken/Sunlight-v1.2-AWQ-4bit) |
| 🟦 **Twilight v1.2** | current | 8-bit (FP8) | 13 GB | ~22 GB | [`Twilight-v1.2-FP8`](https://huggingface.co/CaptchaKraken/Twilight-v1.2-FP8) |
| ⬜ Sunlight v1.1 | previous | 4-bit (AWQ) | ~9.1 GB | ~11 GB | [`Sunlight-AWQ-4bit`](https://huggingface.co/CaptchaKraken/Sunlight-AWQ-4bit) |
| ⬜ Twilight v1.1 | previous | 8-bit (FP8) | ~14 GB | ~22 GB | [`Twilight-FP8`](https://huggingface.co/CaptchaKraken/Twilight-FP8) |

**Take v1.2 unless you have a reason not to.** v1.1 was trained on image-grid
puzzles alone and will not attempt sliders, the other vendors v1.2 added,
animated challenges or typed text — see [The models](../README.md#the-models).

Serve either one directly — no `--enable-lora`, no adapter flags:

```bash
vllm serve CaptchaKraken/Twilight-v1.2-FP8 \
  --max-model-len 8192 --gpu-memory-utilization 0.85 \
  --trust-remote-code --port 8000
```

Then point the client at it, and tell it which name to ask for:

```bash
export VLLM_BASE_URL=http://localhost:8000/v1
export CAPTCHA_KRAKEN_API_KEY=EMPTY
export CAPTCHA_LORA_NAME=CaptchaKraken/Twilight-v1.2-FP8
```

> ⚠️ **`CAPTCHA_LORA_NAME` must match the name your server serves.** It is the
> `model` field the client sends. If you served the model under a different
> name with `--served-model-name`, use that name here instead. It is also how
> the client finds the right prompts.

Both repos ship a `prompts.json` carrying the exact prompts they were trained
on, so the client resolves prompts from the Hub even for a model it has never
seen. Two things to know if you write your own client against them: send
`chat_template_kwargs: {"enable_thinking": false}`, and coordinates come back
normalized 0–1000, not in pixels.

**The v1.1 rows are a generation behind.** They are merges of the
generation-1 adapter. The v1.2 builds, and the adapter `setup.sh` installs, are
generation 2. If you want the best open weights and you run vLLM, use the
adapter.

### GGUF, for Ollama, LM Studio and llama.cpp

The same v1.2 merge converted to GGUF, so it runs without vLLM and without a
GPU. One repo holds every quantisation:

| File | Precision | Size | Comparable to |
|---|---|---|---|
| `CaptchaKraken-v1.2-Q4_K_M.gguf` | 4-bit | 5.6 GB | Sunlight |
| `CaptchaKraken-v1.2-Q8_0.gguf` | 8-bit | 9.5 GB | Twilight |
| `CaptchaKraken-v1.2-F16.gguf` | full | 17.9 GB | the unquantised merge |
| `mmproj-F16.gguf` | full | 918 MB | **required by all three** |

[`CaptchaKraken-v1.2-GGUF`](https://huggingface.co/CaptchaKraken/CaptchaKraken-v1.2-GGUF)

> ⚠️ **The projector is not optional.** `mmproj-F16.gguf` is the vision half of
> the model — the part that reads the puzzle. A runtime given the weights
> without it loads a text-only model that does not error, it just answers
> without ever having seen the image. Ollama picks it up automatically when it
> is in the same repo or named in the same `Modelfile`.

It stays full precision in every build, on purpose: quantising the half that
reads a small picture costs far more accuracy than the space it saves.

### The adapter

The default. `setup.sh` installs
[`CaptchaKraken/CaptchaKraken-Lora-v1.2`](https://huggingface.co/CaptchaKraken/CaptchaKraken-Lora-v1.2)
plus a base model sized for your card, and vLLM applies the adapter at serve
time.

**Abyss** — trained against the failures of the open weights — is hosted-only
and never published, so there is nothing here to self-host. Licence holders name
it on a request to the hosted API; by default that API answers with **Twilight
v1.2**, the merge of the same adapter this page installs. See
[Hosted API](./hosted-api.md).

## One-command install

```bash
./setup.sh
```

This checks your memory, picks a base-model size that fits, downloads it plus
the adapter, and writes a `captchakraken.env` config file.

| Your memory | Base it picks |
|---|---|
| **≥ 22 GB** | `RedHatAI/Qwen3.5-9B-FP8-dynamic` (8-bit, ~14 GB) — best accuracy |
| **11–22 GB** | `cyankiwi/Qwen3.5-9B-AWQ-4bit` (4-bit, ~6 GB) — lighter |
| **< 11 GB** | Too small to serve — the installer stops and explains your options |

If your hardware is too small you can still `./setup.sh --download-only` (to
copy the weights to a bigger server later). Force a size with
`./setup.sh --quant fp8|awq|bf16`.

> ⏳ Wondering whether your card is fast enough? See
> [Performance → throughput by device](./performance.md), which lists estimated
> tokens/sec per GPU/SoC. `setup.sh` estimates the same from your device's
> bandwidth and flags cards that will feel sluggish.

## Start the server (you usually don't have to)

The server is **hands-off**: after `setup.sh`, it **auto-starts on your first
solve** and stays up. You never run `vllm serve` yourself. To manage it
explicitly:

```bash
source captchakraken.env
captchakraken server start     # background, waits until healthy
captchakraken server status    # endpoint + which model is served
captchakraken server stop
```

Under the hood that runs the equivalent of the following, assembled from your
env, so it tracks whatever model you configured. Keep
`--enable-tower-connector-lora` or the vision half of the adapter is dropped and
accuracy collapses:

```bash
vllm serve "$CAPTCHA_BASE_MODEL" \
  --reasoning-parser qwen3 \
  --enable-lora --enable-tower-connector-lora \
  --max-lora-rank 64 --max-model-len 65536 \
  --gpu-memory-utilization 0.80 --trust-remote-code \
  --port 8000 \
  --lora-modules "$CAPTCHA_LORA_NAME=$CAPTCHA_LORA_ADAPTER"
```

## Run it with Ollama

`setup.sh` does not manage Ollama — you run it, and point the client at it.

```bash
OLLAMA_CONTEXT_LENGTH=16384 ollama serve
ollama run hf.co/CaptchaKraken/CaptchaKraken-v1.2-GGUF:Q4_K_M
```

> ⚠️ **Raise the context length.** Ollama defaults to **4k tokens on cards
> under 24 GB**, and an animated challenge arrives as several stills in one
> request — which does not fit. The symptom is that still puzzles work and
> animated ones fail. 16k is enough; the weights themselves go far higher.

Then point the client at it. Ollama names a model after whatever you pulled it
as, so the two names differ and both matter:

```bash
export VLLM_BASE_URL=http://localhost:11434/v1
export CAPTCHA_KRAKEN_API_KEY=ollama
export CAPTCHA_LORA_NAME=hf.co/CaptchaKraken/CaptchaKraken-v1.2-GGUF:Q4_K_M
export CAPTCHA_LORA_ADAPTER=CaptchaKraken/CaptchaKraken-v1.2-GGUF
```

`CAPTCHA_LORA_NAME` is what goes on the wire, so it must be exactly what
`ollama list` shows. `CAPTCHA_LORA_ADAPTER` is what the client looks up to
decide **which prompts to send and what resolution to send the image at** —
both are properties of these weights, and neither can be read off an Ollama
model name. Set it, or the client falls back to whichever model is current.

To run a quantisation other than Q4, swap the tag (`:Q8_0`, `:F16`). Importing
the files by hand works too, and needs the projector named alongside them:

```dockerfile
FROM ./CaptchaKraken-v1.2-Q8_0.gguf
FROM ./mmproj-F16.gguf
```

```bash
ollama create captchakraken -f Modelfile
```

`ollama show <name>` lists `vision` under Capabilities when the projector was
picked up. If it does not, the model cannot see the puzzle.

## Run it with LM Studio

Search `CaptchaKraken-v1.2-GGUF` in the **Discover** tab and download a quant.
LM Studio pairs `mmproj-F16.gguf` automatically — the model should show
**Vision** among its capabilities.

Two settings before you load it:

- **Context Length → 16384.** Same reason as Ollama: an animated challenge
  arrives as several stills in one request and will not fit the default.
- **Runtime.** It needs one new enough for Qwen3.5 vision. If the model refuses
  to load, update it under **Runtime**.

Start the server from the **Developer** tab, then point the client at it:

```bash
export VLLM_BASE_URL=http://localhost:1234/v1
export CAPTCHA_KRAKEN_API_KEY=lm-studio
export CAPTCHA_LORA_NAME=captchakraken-v1.2-gguf     # whatever the server lists
export CAPTCHA_LORA_ADAPTER=CaptchaKraken/CaptchaKraken-v1.2-GGUF
```

> 💡 **You do not need to disable thinking.** These GGUF builds emit the
> no-think prefix unconditionally, so a plain request answers correctly in
> LM Studio, Ollama and llama.cpp alike.

## Configuration

The solver only needs **two** environment variables to talk to a server (both
written by `setup.sh` into `captchakraken.env`):

| Variable | Meaning | Default |
|---|---|---|
| `VLLM_BASE_URL` | Inference endpoint — your local vLLM server, or the hosted API. | `~/.captchakraken/credentials`, else `http://localhost:8000/v1` |
| `CAPTCHA_KRAKEN_API_KEY` | Bearer token — your server's key, or your hosted account key. | `~/.captchakraken/credentials`, else `EMPTY` |

Both fall back to the credentials file that the
[MCP server](./hosted-api.md#sign-in-without-touching-a-key) writes. Setting
either variable overrides that file.

Advanced overrides — only needed to change **which** model is served (the client
itself is model-agnostic):

| Variable | Meaning | Default |
|---|---|---|
| `CAPTCHA_BASE_MODEL` | Base weights vLLM loads (HF id or local path) | `RedHatAI/Qwen3.5-9B-FP8-dynamic` |
| `CAPTCHA_LORA_ADAPTER` | Captcha adapter served on top (HF id or local path) | `CaptchaKraken/CaptchaKraken-Lora-v1.2` |
| `CAPTCHA_LORA_REVISION` | Adapter git revision to serve | `main` |
| `CAPTCHA_LORA_NAME` | Served model name the client requests as `model` | `captcha-v12` |
| `VLLM_PORT` | Port the local server binds | `8000` |
| `VLLM_GPU_MEMORY_UTILIZATION` | Fraction of VRAM vLLM may use | `0.80` |
| `VLLM_MAX_MODEL_LEN` | Context length | `65536` |
| `VLLM_MAX_LORA_RANK` | Max adapter rank | `64` |
| `VLLM_EXTRA_ARGS` | Extra flags appended to `vllm serve` | empty |
| `CAPTCHA_KRAKEN_AUTOSTART` | `0` disables auto-starting a local server on first use | `1` |
| `CAPTCHA_KRAKEN_STATE_DIR` | Where the pidfile, log, and credentials live | `~/.captchakraken` |

The model defaults come from `python/src/captchakraken/models.json`, which also
records which **prompt generation** each model was trained on. That mapping is
why you should change models through these variables rather than by hardcoding
a name: a model sent the wrong generation's prompt does not error, it just
answers worse on every puzzle.

Point `VLLM_BASE_URL` at a server you already run to skip local management
entirely — a remote endpoint is never auto-started for you.

## Updating

Get new **model revisions** and **engine fixes** with one command — no full
reinstall:

```bash
captchakraken fetch
```

`fetch` does three things in order:

1. **Pulls the latest weights** — re-downloads the configured captcha adapter +
   base model from the HuggingFace org
   [huggingface.co/CaptchaKraken](https://huggingface.co/CaptchaKraken). A no-op
   if you're already on the latest revision; pulls the new commit otherwise.
2. **Upgrades the serving stack** — `pip install -U vllm huggingface_hub` in the
   current environment.
3. **Restarts a running local server** so the freshly pulled weights + engine
   actually take effect. Remote endpoints you manage are left untouched.

Flags:

| Flag | Effect |
|---|---|
| `--weights-only` | Just re-pull the weights (skip the vLLM upgrade). |
| `--engine-only` | Just upgrade vLLM (skip the weight download). |
| `--no-restart` | Don't bounce a running local server. |
| `--dry-run` | Print the plan as JSON and do nothing (no network, no pip). |

On an already-set-up box, the shell equivalent is:

```bash
./setup.sh --update
```

which sources your `captchakraken.env` and hands off to `captchakraken fetch`.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `Connection refused` on port 8000 | Nothing is serving, and autostart is off or failed | `captchakraken server start`, then check `~/.captchakraken/vllm.log` |
| A local server starts when you didn't want one | Your endpoint is localhost | Set `VLLM_BASE_URL` to your server, or `CAPTCHA_KRAKEN_AUTOSTART=0` |
| `401` from your own server | The key isn't reaching the CLI | `source captchakraken.env` first |
| Model answers, but badly, on every puzzle | Wrong prompt generation for these weights | Check `CAPTCHA_LORA_NAME` matches the served name |
| 4×4 grids always wrong, 3×3 mostly fine | Custom client, no cell-number overlay | See [Performance → grids must be numbered](./performance.md#grids-must-be-sent-with-the-cell-numbers-drawn-on) |
| Out of memory at startup | Base too big for the card | `./setup.sh --quant awq`, or lower `VLLM_GPU_MEMORY_UTILIZATION` |
| Answers describe nothing that is in the image | GGUF loaded without its projector | `ollama show <name>` should list `vision`; re-create with `mmproj-F16.gguf` |
| Still puzzles solve, animated ones fail | Context too small for a multi-still request | `OLLAMA_CONTEXT_LENGTH=16384`, or `--ctx-size` on llama.cpp |
| Every answer is empty, and the reply carries a `reasoning` field | Thinking is on, so the answer never reaches `content` | Our GGUF builds have it off unconditionally; on a GGUF you converted yourself send `reasoning_effort: "none"` (Ollama) or `chat_template_kwargs: {"enable_thinking": false}` |

Set `CAPTCHA_DEBUG=1` to print solver diagnostics to stderr.

---

← Back to [docs index](./README.md)
