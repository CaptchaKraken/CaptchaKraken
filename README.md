<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="./docs/assets/logo-dark.svg">
    <img src="./docs/assets/logo-light.svg" alt="CaptchaKraken" width="140" height="140">
  </picture>
</p>

<h1 align="center">CaptchaKraken</h1>

<p align="center">
  <b>A captcha solver for browser automation.</b><br>
  Give it a page — it finds the captcha, reads the puzzle with a fine-tuned
  <b>Qwen3.5-9B</b> vision model, and clicks through to a token.<br>
  Run the model on <b>your own hardware</b>, or call the <b>hosted API</b> and
  run nothing at all.
</p>

<p align="center">
  <a href="https://www.npmjs.com/package/captchakraken"><img src="https://img.shields.io/npm/v/captchakraken?logo=npm&label=npm" alt="npm"></a>
  <a href="https://pypi.org/project/captchakraken/"><img src="https://img.shields.io/pypi/v/captchakraken?logo=pypi&logoColor=white&label=PyPI" alt="PyPI"></a>
  <a href="./LICENSE"><img src="https://img.shields.io/badge/license-Source--Available-blue" alt="License: Source-Available"></a>
  <a href="https://github.com/CaptchaKraken/CaptchaKraken/actions/workflows/ci.yml"><img src="https://github.com/CaptchaKraken/CaptchaKraken/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
</p>

> ⭐ **Enjoying CaptchaKraken?** [Star & watch the repo](https://github.com/CaptchaKraken/CaptchaKraken)
> for new puzzle types and new models. One repo, two
> published ports — the TypeScript browser driver (**npm:** `captchakraken`) and
> the Python engine (**PyPI:** `captchakraken`).

---

<!--
  The clips are served from captchakraken.com, NOT from this repo, and that is
  deliberate. raw.githubusercontent.com sends `.webm` as `audio/webm` and `.mp4`
  as `application/octet-stream` (both measured 2026-08-24), and a <video> given
  either of those does not reliably play. The site's own /art/demo route sends
  `video/webm`, which does. The animated WebP in the npm and PyPI READMEs is a
  different story — `image/webp` IS served correctly from raw, so those come
  from docs/assets/demo/ here.

  Each <video> carries a plain <a> fallback so the section degrades to links
  rather than to nothing if a renderer strips the tag.
-->

## Watch it work

Nine puzzle types, each driven on the vendor's own **public demo page**
through the hosted API, with every attempt scored. These clips also run on
[captchakraken.com](https://captchakraken.com) — recorded 2026-08-19 against
**captcha-v12**, the adapter the hosted API serves today.

Three things worth knowing before you read the numbers:

- **They are counts, not percentages.** Ten attempts is not a percentage, and
  the count is the thing you can actually reason about.
- **The clip runs shorter than the solve.** Stretches where the pointer is not
  moving are cut out, so the footage stays watchable. The median beside each
  clip is the measured whole-solve time, computed from the run and never from
  the footage — the clip illustrates, the median asserts.
- **It is the whole widget, not one puzzle.** A tab is named for the puzzle the
  vendor *opened* with, and the time covers every round after it. reCAPTCHA
  keeps going until it is satisfied, and a later round is often a different
  shape from the one that opened, so two attempts at one puzzle can differ in
  length several times over.

A round the vendor waved through without a puzzle is not in these counts, and
neither is one we could not classify — only rounds where a challenge was on
screen and had to be solved.

<details open>
<summary><b>reCAPTCHA</b> — 3 puzzle types</summary>

**4×4 tile grid** — 9/10 solved · 8.7s median

One image cut into sixteen, with the object spanning several of them. Another board normally follows.

<video src="https://captchakraken.com/art/demo/recaptcha_4x4.webm" width="408" controls muted loop playsinline preload="none">
  <a href="https://captchakraken.com/#demos">Watch the reCAPTCHA 4×4 tile grid solve</a>
</video>

**3×3 tile grid** — 11/11 solved · 9.3s median

Nine tiles of one photo. reCAPTCHA keeps asking until it is satisfied, so the clip usually runs past the board it opened on.

<video src="https://captchakraken.com/art/demo/recaptcha_3x3.webm" width="408" controls muted loop playsinline preload="none">
  <a href="https://captchakraken.com/#demos">Watch the reCAPTCHA 3×3 tile grid solve</a>
</video>

**3×3 dynamic** — 8/10 solved · 38.2s median

Each tile you clear fades and is replaced. It only ends when the board comes back clean.

<video src="https://captchakraken.com/art/demo/recaptcha_3x3_fade.webm" width="408" controls muted loop playsinline preload="none">
  <a href="https://captchakraken.com/#demos">Watch the reCAPTCHA 3×3 dynamic solve</a>
</video>

</details>

<details>
<summary><b>GeeTest</b> — 6 puzzle types</summary>

**Ordered icon click** — 10/10 solved · 9.0s median

Find small icons hidden in a photo and click them in the order given.

<video src="https://captchakraken.com/art/demo/geetest_icon.webm" width="348" controls muted loop playsinline preload="none">
  <a href="https://captchakraken.com/#demos">Watch the GeeTest ordered icon click solve</a>
</video>

**Icon crush** — 9/10 solved · 7.1s median

Match-3 on near-identical sprites: swap one pair to line up three.

<video src="https://captchakraken.com/art/demo/geetest_iconcrush.webm" width="348" controls muted loop playsinline preload="none">
  <a href="https://captchakraken.com/#demos">Watch the GeeTest icon crush solve</a>
</video>

**Gobang** — 10/10 solved · 6.8s median

A 5×5 board. Move one stone so five identical ones line up.

<video src="https://captchakraken.com/art/demo/geetest_gobang.webm" width="348" controls muted loop playsinline preload="none">
  <a href="https://captchakraken.com/#demos">Watch the GeeTest gobang solve</a>
</video>

**3×3 photo grid** — 10/10 solved · 7.8s median

The target is a thumbnail in the prompt bar, not a word. Nothing to read.

<video src="https://captchakraken.com/art/demo/geetest_nine.webm" width="348" controls muted loop playsinline preload="none">
  <a href="https://captchakraken.com/#demos">Watch the GeeTest 3×3 photo grid solve</a>
</video>

**Slide jigsaw** — 10/10 solved · 7.6s median

Drag the cut-out back into its notch. Off by six pixels is a failure.

<video src="https://captchakraken.com/art/demo/geetest_slide.webm" width="348" controls muted loop playsinline preload="none">
  <a href="https://captchakraken.com/#demos">Watch the GeeTest slide jigsaw solve</a>
</video>

**Cycling line art** — 9/10 solved · 39.5s median

The board cycles through fresh candidates. The answer is a frame and a point.

<video src="https://captchakraken.com/art/demo/geetest_svg.webm" width="348" controls muted loop playsinline preload="none">
  <a href="https://captchakraken.com/#demos">Watch the GeeTest cycling line art solve</a>
</video>

</details>
---

## Setup

Two ways to run the model. The client code is identical — only the endpoint
changes, so you can switch later by editing one variable.

| | ☁️ **Hosted API** | 🖥️ **Self-hosted** |
|---|---|---|
| You need | Nothing | 11 GB+ of VRAM or Apple unified memory |
| Takes | ~1 minute | ~20 minutes (model download) |
| Runs | **Twilight v1.2** on our fleet, served for you | The same weights, on your card |
| Cost | $0.30 per 1,000 image responses. Checkbox and Turnstile are free. | Your electricity |
| Screenshots | Sent to our gateway | Never leave your machine |

**Agents:** the same instructions in a shorter, machine-readable form are in
**[AGENTS.md](./AGENTS.md)**.

### Option 1 — Hosted API

No GPU, no download, no server.

The easiest path is the account MCP server. It signs you in and writes the key
to disk for you, so **you set no environment variables at all**:

```bash
claude mcp add captchakraken -- npx -y captchakraken-mcp
```

Then call `sign_in` (a human approves it in a browser with GitHub — new accounts
get free trial credits), and call `create_api_key`. The key and the endpoint are
written to `~/.captchakraken/credentials`, which the solver reads by itself. The
key is never printed into your terminal or your agent's transcript.

Prefer to do it by hand? Sign in at
**[captchakraken.com/signin](https://captchakraken.com/signin)**, copy your
`ck_live_…` key, and set two variables:

```bash
export VLLM_BASE_URL=https://api.captchakraken.com/v1
export CAPTCHA_KRAKEN_API_KEY=ck_live_your_key_here
```

You are billed per **model response**, not per captcha — one captcha usually
takes 1–2. A single solve attempt is capped at **5 billable responses**, so a
stubborn captcha cannot run up an unbounded bill.

### Option 2 — Self-host

One command. It checks your GPU or Apple memory, picks a model size that fits,
downloads it, and writes a config file:

```bash
git clone https://github.com/CaptchaKraken/CaptchaKraken
cd CaptchaKraken
./setup.sh
source captchakraken.env
```

| Your memory | What it installs |
|---|---|
| **22 GB+** | 8-bit base (~14 GB) — best accuracy |
| **11–22 GB** | 4-bit base (~6 GB) — lighter |
| **Under 11 GB** | Stops and explains your options |

**You never start a server.** vLLM starts by itself on your first solve and
stays up. Hardware notes, server commands, and updating:
**[docs/self-hosting.md](./docs/self-hosting.md)**.

> `setup.sh` installs a **LoRA adapter**, which needs vLLM. If you use another
> runtime — or just want one file and no adapter flags — serve the merged
> **Sunlight v1.2** (4-bit) or **Twilight v1.2** (8-bit) builds instead. On
> **Ollama**, or with no GPU at all, take the **GGUF** build. All are public.
> See [The models](#the-models).

**Already run your own vLLM server?** Point at it and skip all of the above. A
non-local URL is never auto-started or managed for you:

```bash
export VLLM_BASE_URL=https://your-server:8000/v1
export CAPTCHA_KRAKEN_API_KEY=your-server-key
```

### Then install the client and solve

Same for every option above. Python needs 3.11+; neither package installs a
browser, so bring your own.

```bash
npm install captchakraken        # TypeScript browser driver
pip install captchakraken        # Python engine + `captchakraken` CLI
```

In the browser — hand it any Playwright-compatible page:

```typescript
import { chromium } from 'playwright';
import { CaptchaKrakenSolver } from 'captchakraken';

const page = await (await (await chromium.launch()).newContext()).newPage();
await page.goto('https://www.google.com/recaptcha/api2/demo');

await new CaptchaKrakenSolver().solve(page);   // detect → solve → click → verify
```

In Python — synchronous Playwright:

```python
from playwright.sync_api import sync_playwright
from captchakraken import PageSolver

with sync_playwright() as p:
    page = p.chromium.launch().new_page()
    page.goto("https://www.google.com/recaptcha/api2/demo")
    print(PageSolver().solve(page).is_solved)
```

Or with no browser at all — a screenshot in, a JSON click plan out:

```bash
captchakraken path/to/captcha.png
```

Check your setup any time with `captchakraken server status`. Every browser
framework (Playwright, Patchright, camoufox, Puppeteer) and the background
watcher are in **[docs/usage.md](./docs/usage.md)**.

**On a phone?** How the solver *performs* the answer is a choice of input
device, not a realism dial:

```typescript
new CaptchaKrakenSolver({ humanization: 'mobile' })   // touch events, finger kinematics
new CaptchaKrakenSolver({ humanization: 'none' })     // straight to the DOM effect
new CaptchaKrakenSolver({ humanizer: myOwn })         // yours
```

`mobile` never touches `page.mouse` — a mousemove at a touch-only widget is the
wrong event, not a weaker one. It drives a Chromium page with `hasTouch: true`,
or a real handset over **Appium / WebdriverIO / Selenium** via `touchDriver`.
Full details in
[docs/usage.md § How it moves](./docs/usage.md#how-it-moves--mouse-mobile-none-or-yours).

**Stay current** — pull the latest model + engine in one step, no reinstall:

```bash
captchakraken fetch
```

---

## What it solves today

CaptchaKraken detects the captcha, solves it, clicks, and verifies — end to end.

| Captcha type | Status |
|---|---|
| ✅ Checkbox / "I'm not a robot" | Works end-to-end |
| ✅ **reCAPTCHA 3×3** (dynamic refresh) | Works end-to-end |
| ✅ **reCAPTCHA 4×4** (one-shot) | Works end-to-end |
| ✅ Cloudflare Turnstile | Works via the checkbox flow |
| ✅ **GeeTest** (v3 + v4) | Slide, icon, nine, svg. `gobang` and `iconcrush` are weak — see below |
| ✅ **NetEase Yidun** | Jigsaw, picture-click, icon-click |
| ✅ **Lemin, Prosopo, Tencent** | Cropped-image, grid, and slide flows |
| ✅ **Distorted text** | BotDetect, MTCaptcha, Yandex — read and typed, not clicked |
| ✅ **Animated / video challenges** | Recorded, cut into keyframes, solved as one multi-image prompt, then clicked once the widget returns to the chosen frame |

Beyond reCAPTCHA, the vendors in this table are driven end-to-end in CI against
generated fixtures in **both** ports. Per-vendor accuracy varies more than the
headline grids do, and the clips above are the per-type record: each one is that puzzle
driven on the vendor's own demo page, with every attempt scored. GeeTest's
gobang and icon-crush boards were long the two weakest — both drive to
completion now (10/10 and 9/10 above) but they are the least exercised of the
set, so they are the likeliest to move.

### Accuracy, measured

**The headline numbers are the clips at the top of this page.** Each one is
that puzzle driven on the vendor's own public demo page through the hosted API,
with every attempt scored — counts, not percentages, and a median solve time
computed from the run rather than from the footage. Recorded 2026-08-19 against
`captcha-v12`, the adapter the hosted API serves today.

That is deliberately the *end-to-end* number: detect, read, click, verify, and
the vendor accepting. It is the one you can hold us to, because it is the one
you experience.

An earlier revision of this section carried per-type **model** accuracy taken on
2026-07-27. Those figures were withdrawn — the eval split of the day let some
hand-labeled captures reach training, so they measured memorisation alongside
skill. The split was replaced (**every** real capture is held out; nothing
hand-labeled trains) and the model has been re-measured against it since. Those
re-measured rates are published on the benchmark page below, never on their own:
a bare model score tells you very little about whether a captcha clears, so it is
printed beside the browser counts rather than instead of them.

The method behind them, so you can reproduce the shape of it: exact set match —
every correct tile and no incorrect ones, no partial credit, because a
partially-correct grid answer is a rejected captcha — taken over the full
customer path (HTTPS → gateway → vLLM) rather than a local checkpoint, against
captures the adapter has never trained on.

> **Grids are sent with the cell numbers drawn on.** `solver.py` runs
> `find_grid`, renders `get_numbered_grid_overlay` (red labels, top-right, all
> cells 1..N — byte-identical to the overlay the training data was built with)
> and sends *that*. This is not cosmetic: measured on raw un-numbered
> screenshots the same model scores **0% on 4×4**, because it has to invent a
> numbering convention for sixteen cells of one continuous photograph and
> answers `1..k`. If you are building your own client, draw the overlay.

**Both tables, one page: [docs/benchmarks.md](./docs/benchmarks.md).** That is
the canonical benchmark page — the browser runs above in full, and beside them
the per-puzzle model accuracy over held-out real captures, scored the way a
widget scores. Two measurements, because they answer two different questions; a
figure quoted anywhere else in this repo is a copy of one of them.

Method, per-device speed tables, and why browser solve rates differ from model
accuracy: **[docs/performance.md](./docs/performance.md)**.

---

## The models

Two public releases. Within each, the same weights in several shapes: the
**LoRA adapter** (strongest, needs vLLM and two downloads), two **merged**
builds that are one self-contained file any safetensors runtime will serve,
and — for v1.2 — a **GGUF** build for Ollama, LM Studio and llama.cpp that
needs no vLLM
and no GPU.

### v1.2 — current

**Covers every vendor we solve**: 44 puzzle types across ten vendors, among
them reCAPTCHA, GeeTest, NetEase Yidun, BotDetect, MTCaptcha, Yandex, Tencent,
Lemin and Prosopo — and it is the first generation to handle **animated
challenges** and **typed text**. Prompt generation 2; needs `captchakraken >= 2.5.0`.

| | Precision | Size | Min VRAM | Weights |
|---|---|---|---|---|
| **LoRA adapter** | bf16 on a stock base | ~0.4 GB + base | depends on base | [`CaptchaKraken-Lora-v1.2`](https://huggingface.co/CaptchaKraken/CaptchaKraken-Lora-v1.2) |
| 🟦 **Twilight** | 8-bit (FP8) | 13 GB | ~22 GB | [`Twilight-v1.2-FP8`](https://huggingface.co/CaptchaKraken/Twilight-v1.2-FP8) |
| 🟦 **Sunlight** | 4-bit (AWQ) | 11 GB | ~14 GB | [`Sunlight-v1.2-AWQ-4bit`](https://huggingface.co/CaptchaKraken/Sunlight-v1.2-AWQ-4bit) |
| 🟩 **GGUF** | 4-bit / 8-bit / F16 | 5.6–17.9 GB | none — CPU works | [`CaptchaKraken-v1.2-GGUF`](https://huggingface.co/CaptchaKraken/CaptchaKraken-v1.2-GGUF) |

All of them are **Qwen3.5-9B** — the adapter, and the builds made from it.

The GGUF repo holds every quantisation plus `mmproj-F16.gguf`, the vision half
of the model. **It is required**: without it a runtime loads a text-only model
that answers without ever seeing the puzzle. See
[Self-hosting → GGUF](./docs/self-hosting.md#gguf-for-ollama-and-llamacpp).

`./setup.sh` installs the LoRA adapter. **Twilight v1.2 is what the hosted API
answers with** — the same LoRA on the same base, merged.

### v1.1 — previous

**Image-grid puzzles only.** Not "worse at" everything else — it was
never shown it, and will not attempt a GeeTest slider or a typed-text captcha
at all. Prompt generation 1. Still published and supported; take it if that is
all you face and you want the smaller stack.

| | Precision | Size | Min VRAM | Weights |
|---|---|---|---|---|
| **LoRA adapter** | bf16 on a stock base | ~0.4 GB + base | depends on base | [`CaptchaKrakenV1_Lora`](https://huggingface.co/CaptchaKraken/CaptchaKrakenV1_Lora) |
| 🟦 **Twilight** | 8-bit (FP8) | ~14 GB | ~22 GB | [`Twilight-FP8`](https://huggingface.co/CaptchaKraken/Twilight-FP8) |
| 🟦 **Sunlight** | 4-bit (AWQ) | ~9 GB | ~11 GB | [`Sunlight-AWQ-4bit`](https://huggingface.co/CaptchaKraken/Sunlight-AWQ-4bit) |

### ⬛ Abyss — what the hosted API serves, never downloadable

**Serving now, to every hosted account.** It shares the public models' base —
Qwen3.5-9B — but it is not a bigger quantisation of them and nothing about its
VRAM follows from theirs: it is a **routed mixture of specialist adapters**,
one each for grids, pixel-precision work, animation and text, chosen per
request by the shape of the puzzle. Trained against the failures of the open
weights, and **hosted-only**. Every puzzle the open model gets wrong on the held-out set is a
labelled example of a weakness, and Abyss is trained specifically to close
them, starting with the non-grid click and drag puzzles. Keeping it on our own fleet
is what lets it keep learning from production failures without shipping a
customer's puzzle set to everyone who runs `hf download`.

**It is what the hosted API answers with, and there is nothing to download.**
The current client names an Abyss expert on every request to our endpoint; an
older client, or a request that names no model, is answered by Twilight v1.2,
because its prompts belong to that generation — never a quiet substitution the
other way, so you always know which model answered. No weights are published for it, and no
accuracy figures are either: every number on this page is Twilight v1.2's. Open
an issue to ask about a licence.

Which one you want:

| If | Use |
|---|---|
| You have no GPU | the [hosted API](./docs/hosted-api.md) |
| You want the best open weights, and run vLLM | the **v1.2 LoRA adapter** — `./setup.sh` |
| You want one file and the simplest serve, 22 GB+ | **Twilight v1.2** |
| You want one file and the simplest serve, 14–22 GB | **Sunlight v1.2** |
| You only face image-grid captchas and want the older, smaller stack | **v1.1** |

Serving details for every option: **[docs/self-hosting.md](./docs/self-hosting.md)**.

---

## Solves

### What a solve actually looks like

One inference round. The screenshot goes up, cell numbers come back — that is
the whole protocol, and it is why anything that speaks the OpenAI
chat-completions API can drive this.

Every grid request carries the screenshot **with the cell numbers drawn on it**
by `get_numbered_grid_overlay` — see the note under Accuracy. The model reads
those labels; it does not infer a numbering.

**reCAPTCHA 3×3** — nine separate photographs, pick the matching ones:

```jsonc
// prompt (abbreviated) ────────────────────────────────────────────────
"Solve the captcha grid by choosing the cell numbers that match the
 description from the captcha image prompt.

 Grid: 3x3 (9 cells)
 Hint: Separate images. Select only clear matches.
 ...
 Return JSON Array: [list of cell numbers (1-9)]"

// response ────────────────────────────────────────────────────────────
[2, 8, 9]
// ground truth [2, 8, 9] ✓   1,796 ms   336 prompt / 10 completion tokens
```

**reCAPTCHA 4×4** — one large image cut into sixteen tiles, "select ALL parts":

```jsonc
[5, 9, 12, 16]
// ground truth [5, 9, 12, 16] ✓   1,385 ms   341 prompt / 15 completion tokens
```

The browser driver wraps this: it finds the grid, converts cell numbers into
click coordinates, clicks, waits for tiles to refresh, and re-solves until the
challenge clears. What the CLI hands back to it is bounding boxes rather than
cell indices:

```jsonc
{
  "actions": {
    "action": "click",
    "target_bounding_boxes": [
      [0.010, 0.206, 0.335, 0.418],
      [0.335, 0.206, 0.660, 0.418],
      [0.335, 0.631, 0.660, 0.843]
    ]
  },
  "token_usage": [{ "prompt_tokens": 348, "completion_tokens": 10 }]
}
```

### End-to-end, in a real browser

The run below drove **live reCAPTCHA challenges** at
`google.com/recaptcha/api2/demo` on 2026-07-27, headless, against the hosted
API. A "solve" means reCAPTCHA accepted and the widget cleared — not that the
model's first answer was right.

| Browser | Solved | Rounds billed | Median wall clock |
|---|---:|---:|---:|
| [Camoufox](https://camoufox.com) 0.4.11 | **3 / 3** | 21 | 96 s |

A solve took 5–8 model rounds, because reCAPTCHA replaces tiles after each
click and every replacement is a fresh puzzle. That is the whole reason the
hosted API meters per round rather than per solve.

**Solve rate in a browser is not model accuracy, and much of it is your IP.**
reCAPTCHA rejects correct answers from addresses it distrusts, and the run above
came from a datacenter address — which is the least favourable condition there
is. The figure is not a benchmark; it is proof the path works. See
[Rate limiting & IP reputation](./docs/performance.md#rate-limiting--ip-reputation).

Reproduce it yourself — the demos in this repo drive a real browser end to end:

```bash
cd js
npm install && npm i -D camoufox-js tsx   # example-only deps
npx camoufox-js fetch                     # one-time browser download
source ../captchakraken.env               # written by ./setup.sh

npx tsx examples/demoRecaptcha.ts                      # the demo page above
npx tsx examples/demoRecaptcha.ts https://your.site/   # or your own page
```

Add `--headed` to watch it happen in a visible window. The Python engine ships
the same demo — `cd python && python examples/demoRecaptcha.py` — and it takes
the same arguments.

---

## Documentation

Most of the detail lives in the docs hub — start at **[docs/](./docs/README.md)**.

| Guide | What's in it |
|---|---|
| ☁️ [Hosted API](./docs/hosted-api.md) | Sign in, keys, pricing, per-session billing, error codes |
| 📦 [Self-hosting](./docs/self-hosting.md) | `setup.sh`, model sizes, server management, config, **updating** |
| 🚀 [Usage](./docs/usage.md) | Install, the 4 browser frameworks, **mouse / mobile / no humanization**, the Python CLI, migrating from v1 |
| ⚙️ [How it works](./docs/how-it-works.md) | The solve pipeline, `find_grid`, the freshness guard, dedup |
| 📊 [Benchmarks](./docs/benchmarks.md) | The canonical numbers: real captchas in a browser, and per-puzzle model accuracy |
| ⚡ [Performance](./docs/performance.md) | Speed-by-device tables, IP-reputation & rate limits |
| 🗺️ [Roadmap](./docs/roadmap.md) | What shipped, what's in progress, and what's planned |
| 📜 [Licensing](./docs/licensing.md) | Plain-English: what you can and can't build |

---

## Roadmap

- 🟢 **Shipped** — the **hosted API** (`api.captchakraken.com`, self-serve
  signup), a mid-inference **freshness guard** (never act on a stale frame),
  and a one-command **`captchakraken fetch`** updater.
- 🟢 **Shipped** — **v1.2**: every vendor we solve (44 puzzle types across 10),
  animated challenges, typed text — as a LoRA and as **Sunlight** / **Twilight**
  merges, all public on [HuggingFace](https://huggingface.co/CaptchaKraken).
- 🟢 **Shipped** — **Abyss**, hosted-only: what the hosted API serves the current
  client, never downloadable. An older client, or a request that names no model,
  still gets **Twilight v1.2**.
- ⚪ **Planned** — 🎯 higher accuracy on the **freehand drag and path puzzles**
  (connect-the-path and the numbered-line / missing-piece drags), which are the
  families the model is least reliable on. Every family we ship is already
  routed and driven — this is about how often they land, not whether they are
  attempted.

The visual, always-current version is in **[docs/roadmap.md](./docs/roadmap.md)**.
📣 **[Watch the repo](https://github.com/CaptchaKraken/CaptchaKraken)** to hear about
these as they ship.

---

## License

Source-available under the **CaptchaKraken Source-Available License v1.1** — see
**[LICENSE](./LICENSE)** (plain-English: **[docs/licensing.md](./docs/licensing.md)**).

- ✅ **Build _with_ it** — scrapers, data pipelines, QA tooling: commercial use is
  fine when captcha solving is an internal, enabling component.
- ✅ **Use it with any browser you like** — Camoufox, Puppeteer, Playwright, any
  stealth browser. Running the solver against your own automation is unrestricted.
- ⛔ **Don't sell _the solve_** — no captcha-solving-as-a-service, no thin wrappers
  (browser extensions, hosted endpoints, CLIs) whose main purpose is solving, and
  no relaying the model's outputs through a paid solving API.
- ⛔ **Don't _ship_ the solve** — you may not bundle, preinstall, or advertise this
  as a built-in captcha feature of a stealth browser, antidetect/profile manager,
  or automation platform you distribute to other people. Using it with one is
  fine; shipping it as part of one needs a license.

For otherwise-prohibited uses, open an issue about a commercial license.

---

## Contributing

PRs welcome — see [CONTRIBUTING.md](CONTRIBUTING.md). CI runs a hermetic
no-regression suite (grid detection, the freshness check, and the fetch command)
plus a TypeScript build on every PR — no GPU or network. Release notes:
[CHANGELOG.md](CHANGELOG.md).

---

## Credits

**The mouse is not ours.** Every pointer path this driver performs comes from
**[cursory](https://github.com/Vinyzu/cursory)**, by
**[Vinyzu](https://github.com/Vinyzu)**. It does not model a hand: it searches a
database of thousands of trajectories recorded from real people for the closest
match to the requested movement, morphs that recording onto the endpoints, and
re-noises it — realism that is measured rather than asserted. It replaced the
hand-tuned curves we shipped before it; see
[docs/usage.md § How it moves](./docs/usage.md#how-it-moves--mouse-mobile-none-or-yours).

**[cursory-js](https://github.com/JWriter20/cursory-js)** is our TypeScript port
of it, published so the JS driver has the same mouse. It is a port rather than a
rewrite, so a seed gives the same trajectory in both ports.

Both are **LGPL-3.0-or-later**, and both are ordinary installed dependencies —
never vendored, inlined, or bundled — so you can swap in a modified build of
either by reinstalling the package. Full third-party notice: **[NOTICE](./NOTICE)**.

---

> ⚠️ Use responsibly and lawfully — respect the terms of service of any site you
> interact with. This project is for legitimate automation, research, and testing.
