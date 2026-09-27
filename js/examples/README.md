# Examples (TypeScript)

Runnable, end-to-end demos. `demoRecaptcha.ts` drives a real stealth browser
([camoufox](https://github.com/JWriter20/camoufox)) against Google's reCAPTCHA
demo page, runs the full solver, and prints token speed / total time / outcome:

| File | What it shows |
|---|---|
| `withPlaywright.ts` | Vanilla Playwright — no adapter, 2 added lines |
| `withPuppeteer.ts` | Puppeteer — `fromPuppeteer(page)`, 2 added lines |
| `watchPlaywright.ts` | The auto-solver: install once, solves as they appear |
| `demoRecaptcha.ts` | Google reCAPTCHA v2 demo, via camoufox |

The first three take an optional URL, so you can point them at your own page:

```bash
npm i -D playwright puppeteer tsx     # example-only; the package ships none
npx playwright install chromium

export VLLM_BASE_URL=https://api.captchakraken.com/v1
export CAPTCHA_KRAKEN_API_KEY=ck_live_...

npx tsx examples/withPlaywright.ts
npx tsx examples/withPuppeteer.ts https://your.site/page
npx tsx examples/watchPlaywright.ts https://your.site/page 60
```

Running them **from this repo** needs one extra step: they `import
{ ... } from 'captchakraken'`, exactly as your own code would, and that resolves
from npm for a normal user but from nothing inside the checkout. Link the
package to itself once:

```bash
cd js && ln -sfn "$(pwd)" node_modules/captchakraken && npm run build
```

`npm run build` matters too — the examples run the built `dist/`, and it also
recopies `python/`, which wipes the bundled engine's venv. Re-create it with
`node scripts/setup-python.js` if a solve dies on `No module named 'pydantic'`.

They use `async function main()` rather than top-level await: this package is
CommonJS, and tsx transpiles these to CJS, where top-level await is a syntax
error.

## Setup

```bash
cd js
npm install                       # builds + bundles the python engine
npm i -D camoufox-js tsx          # example-only deps (not shipped)
```

### The camoufox binary (from your fork)

These demos use the **camoufox binary from the fork's releases**:
[JWriter20/camoufox → Releases](https://github.com/JWriter20/camoufox/releases).

1. Download the latest release asset for your OS/arch and extract it.
2. Point the demo at the extracted `camoufox` executable:

```bash
export CAMOUFOX_BINARY=/path/to/camoufox/camoufox      # your fork binary
```

If `CAMOUFOX_BINARY` is unset, camoufox-js falls back to its default binary
(`npx camoufox-js fetch`) — fine for a quick try, but not the fork build.

> **Camoufox build note.** These demos are validated with the mainline
> `camoufox-js` (apify/camoufox-js) and a current camoufox build (Firefox 150 or
> 152). If `page.screenshot()`/`elementHandle.screenshot()` ever fails with
> `Protocol error (Page.screenshot): can't access property "document", win is
> undefined`, your camoufox **browser build** predates the FF152 screenshot fix —
> update the binary (it's a browser-side bug, not the JS bindings or playwright).
> The harness sets `viewport: null` so playwright ≥1.6 doesn't trip FF152's
> viewport schema.

### Point at a model

```bash
source ../captchakraken.env       # VLLM_BASE_URL + CAPTCHA_KRAKEN_API_KEY
# (produced by ../setup.sh; or export VLLM_BASE_URL yourself for a remote server)
```

Running the model locally on **Ollama** or **LM Studio**? Those load GGUF, so
they need the GGUF build rather than the AWQ/FP8 downloads — see
[Self-hosting → GGUF](../../docs/self-hosting.md#gguf-for-ollama-lm-studio-and-llamacpp).
The same four environment variables configure both ports, because this one
forwards `process.env` to the engine unchanged.

## Run

```bash
npx tsx examples/demoRecaptcha.ts
HEADLESS=0 npx tsx examples/demoRecaptcha.ts   # watch it solve
```

## Reading the report

```
  result        : ✓ SOLVED            # end-to-end: reached a captcha token
  total time    : 14.2s (solve: 12.9s)
  tokens        : 812 in / 34 out
  gen speed     : ~2.6 tok/s (end-to-end approx)
  reason        : <only shown on failure — e.g. IP flagging, unsupported puzzle>
```

`gen speed` is end-to-end (output tokens ÷ solve seconds), so it includes browser
+ subprocess overhead, not just raw model decode. Common failure reasons the
harness reports: unreachable vLLM server, a challenge the model could not
produce a usable action for, a timeout, or the provider rejecting a correct answer (usually IP
reputation / fingerprint flagging).
