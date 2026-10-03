# Examples (Python)

A runnable demo that drives a real stealth browser
([camoufox](https://github.com/JWriter20/camoufox)) to a live captcha demo site,
screenshots the challenge, runs the **engine** on it, and prints token speed /
total time / outcome:

| File | Site |
|---|---|
| `demoRecaptcha.py` | Google reCAPTCHA v2 demo |

> The Python port is the engine (detection + planner). This demo validates the
> engine + model + server on a real challenge frame. Full click-replay and
> multi-round verification in a live page are what the TypeScript port
> (`captchakraken`) does end-to-end.

## Setup

```bash
cd python
pip install -e ".[serve]"         # engine + serving stack (use ".[]" for a remote server)
pip install camoufox              # example-only dep
```

### The camoufox binary (from your fork)

Uses the **camoufox binary from the fork's releases**:
[JWriter20/camoufox → Releases](https://github.com/JWriter20/camoufox/releases).

1. Download the latest release asset for your OS/arch and extract it.
2. Point the demo at the extracted `camoufox` executable:

```bash
export CAMOUFOX_BINARY=/path/to/camoufox/camoufox      # your fork binary
```

If `CAMOUFOX_BINARY` is unset, camoufox falls back to its default binary
(`python -m camoufox fetch`).

### Point at a model

```bash
source ../captchakraken.env       # VLLM_BASE_URL + CAPTCHA_KRAKEN_API_KEY
```

Running the model locally on **Ollama** or **LM Studio** instead? Those load
GGUF, so they need the GGUF build rather than the AWQ/FP8 downloads — see
[Self-hosting → GGUF](../../docs/self-hosting.md#gguf-for-ollama-lm-studio-and-llamacpp),
then check the wiring with one image and no browser:

```bash
python examples/with_local_gguf.py path/to/captcha.png
python examples/with_local_gguf.py path/to/text-captcha.png --text
```

## Run

```bash
python examples/demoRecaptcha.py
HEADLESS=0 python examples/demoRecaptcha.py    # watch the browser
```

## Reading the report

```
  result        : ✓ engine produced a solution
  click plan: 4 tile(s)/target(s)
  total time    : 6.1s (solve: 3.4s)
  tokens        : 812 in / 34 out
  gen speed     : ~10.0 tok/s
  reason        : <only on failure — unsupported puzzle, unreachable server, …>
```

`gen speed` = model output tokens ÷ solve seconds. Failure reasons the harness
reports: unreachable vLLM server, a challenge type the solver does not handle,
the challenge iframe never appearing, or the model returning no matching tiles.

## Playwright, and the auto-solver

| File | What it shows |
|---|---|
| `with_playwright.py` | Vanilla Playwright — no adapter, 2 added lines |
| `watch_playwright.py` | The auto-solver: install once, solves as they appear |

```bash
pip install playwright && playwright install chromium

export VLLM_BASE_URL=https://api.captchakraken.com/v1
export CAPTCHA_KRAKEN_API_KEY=ck_live_...

python examples/with_playwright.py
python examples/watch_playwright.py https://your.site/page 60
```

Use `sync_playwright`, not `async_playwright`: `PageSolver` mirrors the
synchronous API, and a sync handle cannot be driven from inside an event loop.

## There is no Puppeteer path in Python

The TypeScript port ships `fromPuppeteer()` because Puppeteer is a first-class
Node library. Python has no equivalent worth pointing you at:

- **pyppeteer** last released 2.0.0 in **February 2024**, and pins
  `urllib3 <2.0.0` and `websockets <11.0` — which conflicts directly with
  CaptchaKraken's own `requests` dependency, so the two cannot co-install
  cleanly.
- It is **async-only**, and this driver is synchronous. Even resolving the
  dependency conflict, a sync `PageSolver` cannot be driven from asyncio.

Playwright *is* the Python answer, and `patchright` and `camoufox` are the
stealth-patched builds of it — all three duck-type identically, so the examples
above work unchanged with any of them.
