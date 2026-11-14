<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="./docs/assets/logo-dark.svg">
    <img src="./docs/assets/logo-light.svg" alt="CaptchaKraken" width="140" height="140">
  </picture>
</p>

<h1 align="center">CaptchaKraken</h1>

<p align="center">
  <b>A captcha solver for browser automation.</b><br>
  Give it a page — it finds the captcha, reads the puzzle with the v2 pointer
  model, and clicks through to a token.<br>
  Run the model on <b>your own hardware</b>, or call the <b>hosted API</b> and
  run nothing at all.
</p>

<p align="center">
  <a href="https://www.npmjs.com/package/captchakraken"><img src="https://img.shields.io/npm/v/captchakraken?logo=npm&label=npm" alt="npm"></a>
  <a href="https://pypi.org/project/captchakraken/"><img src="https://img.shields.io/pypi/v/captchakraken?logo=pypi&logoColor=white&label=PyPI" alt="PyPI"></a>
  <a href="./LICENSE"><img src="https://img.shields.io/badge/license-LGPL--3.0-blue" alt="License: LGPL-3.0-only"></a>
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
**captcha-v12**, the legacy adapter used for these historical measurements.

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
| You need | Nothing | 8 GB+ of free CUDA VRAM |
| Takes | ~1 minute | One command plus the model download |
| Runs | **Midnight V2 4B Q4** on our fleet | The same weights, on your card |
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

Pick a model, a GPU and how the server should start, and it does the rest:

```bash
npx captchakraken fetch          # or: pipx run captchakraken fetch
captchakraken demo
```

There is nothing to export. `captchakraken start` and `captchakraken stop` turn the
server on and off. It needs an NVIDIA GPU on Linux, and **Midnight V2 4B Q4**, the
default, runs on an 8 GB card. Hardware notes and the rest of the commands:
**[docs/self-hosting.md](./docs/self-hosting.md)**.

> v2 uses a merged pointer model and `/v1/pointer`, not the older chat LoRA
> protocol. GGUF weights are published for advanced llama.cpp integrations;
> stock Ollama cannot evaluate v2's external pointer heads. See
> [The models](#the-models).

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

**Your own captcha?** Every URL pattern and selector the solver uses is in
[`captchakraken.config.json`](./captchakraken.config.json). Write a file with a
`custom` entry for a captcha it does not know, and pass it in:

```typescript
new CaptchaKrakenSolver({ selectors: './my-captchas.json' })
```

```python
PageSolver(config=PageSolverConfig(selectors="my-captchas.json"))
```

It is laid over the defaults, so it holds only what it changes. Details in
[docs/usage.md § Selectors and URL patterns](./docs/usage.md#selectors-and-url-patterns-captchakrakenconfigjson).

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
`captcha-v12`, the legacy adapter used for these historical measurements.

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

> **Grids are sent with the cell numbers drawn on** (v1 chat models). `solver.py`
> reads the cell boxes from the reCAPTCHA challenge frame's tiles, renders `get_numbered_grid_overlay` (red labels, top-right, all
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

### v2 — current

The v2 architecture is a vision-language pointer model that reads the bare
board. The server owns the fixed prompt and exposes `POST /v1/pointer`; clients
send a board and receive points, paths, text, or a no-answer decision.

The client runs no detector model of its own. Measured on real boards, the
pointer models score higher on bare boards than on boards with numbered marks
drawn on (TwilightV2-2B 72.6% plain vs 68.2% marked; MidnightV2-4B q4 75.1% vs
70.8%), and leaving the detector out keeps the client light.

| Family | Parameters | Formats |
|---|---|---|
| **Sunlight V2** | 0.8B | bf16, Q4, LoRA, GGUF |
| **Twilight V2** | 2B | bf16, LoRA, GGUF |
| **Midnight V2** | 4B | bf16, Q4, LoRA, GGUF |

Every repository is in the [CaptchaKraken v2 collection](https://huggingface.co/collections/CaptchaKraken/captchakraken-v2).
The default for both self-hosting and the hosted API is **Midnight V2 4B Q4**.

The published Sunlight V2 pointer heads predate this release's head layout and fail a
strict load, so use Twilight V2 or Midnight V2 until they are republished.

`captchakraken fetch` installs a merged model and its pointer heads.
The LoRA repositories are for further training. GGUF repositories include the
vision projector and pointer heads for custom llama.cpp integrations; stock
Ollama and `llama-server` alone cannot evaluate those heads and are not a
supported CaptchaKraken server.

Earlier chat-completion releases remain registered for existing pinned clients.
They use a different prompt protocol and cannot serve a v2 client.

| If | Use |
|---|---|
| You have no GPU | the [hosted API](./docs/hosted-api.md) |
| You want the supported one-command setup | **Midnight V2 4B Q4** — `npx captchakraken fetch` |
| You want full precision | Midnight V2 4B, from the same menu |
| You are building a custom llama.cpp runtime | a **v2 GGUF** repository |

Serving details: **[docs/self-hosting.md](./docs/self-hosting.md)**.

---

## Solves

### What a solve actually looks like

One inference round sends a board to `POST /v1/pointer`. The server owns the
prompt, runs the model and its pointer heads on the bare board, and returns an
action plan:

```json
{"action": "click", "points": [[375, 262], [625, 262]]}
```

The response also includes the detected elements and the board dimensions.
Grids and interactive elements carry numbers drawn on the image so the client
can connect each point to the element it belongs to.

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
| 📦 [Self-hosting](./docs/self-hosting.md) | `captchakraken fetch`, model sizes, server management, config, **updating** |
| 🚀 [Usage](./docs/usage.md) | Install, the 4 browser frameworks, **mouse / mobile / no humanization**, the Python CLI, migrating from v1 |
| ⚙️ [How it works](./docs/how-it-works.md) | The solve pipeline, grid cells from the DOM, the freshness guard, dedup |
| 📊 [Benchmarks](./docs/benchmarks.md) | The canonical numbers: real captchas in a browser, and per-puzzle model accuracy |
| ⚡ [Performance](./docs/performance.md) | Speed-by-device tables, IP-reputation & rate limits |
| 🗺️ [Roadmap](./docs/roadmap.md) | What shipped, what's in progress, and what's planned |
| 📜 [Licensing](./docs/licensing.md) | Plain-English: what you can and can't build |

---

## Roadmap

- 🟢 **Shipped** — the **hosted API** (`api.captchakraken.com`, self-serve
  signup), a mid-inference **freshness guard** (never act on a stale frame),
  and a one-command **`captchakraken fetch`** updater.
- 🟢 **Shipped** — **v2**: the pointer architecture (the CNN detector is no
  longer part of the client), one-command vLLM hosting, and public Sunlight 0.8B, Twilight 2B, and Midnight
  4B weights in the [v2 collection](https://huggingface.co/collections/CaptchaKraken/captchakraken-v2).
- 🟢 **Shipped** — **Midnight V2 4B Q4** as the default for both self-hosting
  and the hosted API.
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

CaptchaKraken and all its models are **LGPL-3.0-only** — see
**[LICENSE](./LICENSE)**, **[COPYING](./COPYING)**, and the plain-English
**[licensing guide](./docs/licensing.md)**. Commercial use, modification, and
redistribution are permitted under LGPLv3, including use in browsers, automation
products, and hosted APIs. Distributed modifications to CaptchaKraken itself must
remain available under LGPLv3.

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
