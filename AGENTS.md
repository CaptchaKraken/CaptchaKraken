# AGENTS.md

**Using CaptchaKraken in your own project? This file is for you.**

**Changing CaptchaKraken itself? Stop here — the contributor rules, dev setup
and gates are in [CONTRIBUTING.md](./CONTRIBUTING.md).**

Setup instructions for AI agents and for humans in a hurry.

CaptchaKraken solves captchas in a browser you control. You give it a page, it
finds the captcha, reads it with a vision model, clicks, and verifies.

It is a library you drive, not a service you hand a URL to and not a browser:
you bring the page, and no browser is installed for you.

The model runs in one of two places. **Pick one before you install anything.**

---

## 1. Pick where the model runs

| Your machine | Use | Setup time |
|---|---|---|
| No suitable GPU | **Hosted API** | ~1 min |
| 8 GB+ free CUDA VRAM | **Self-host: Midnight V2 4B Q4** | One command plus download |
| You already run a v2 pointer server | **Point at it** | ~1 min |

Both options run the **same client code**. Only the endpoint changes. You can
switch later by changing one environment variable.

---

## 2A. Hosted API

You send screenshots to `https://api.captchakraken.com/v1`. No GPU, no
download, no server.

### Fastest way (no environment variables)

Add the account MCP server, then call two tools:

```bash
claude mcp add captchakraken -- npx -y captchakraken-mcp
```

1. Call `sign_in`. It prints a link and a code. A human opens the link and
   approves with GitHub. New accounts get free trial credits.
2. Call `create_api_key`.

`create_api_key` writes the key and the endpoint to
`~/.captchakraken/credentials` (file mode 0600). The solver reads that file by
itself, so **you do not need to set any environment variable.** The key is
never printed into the chat.

Check it worked:

```bash
test -f ~/.captchakraken/credentials && echo ok
```

### Manual way

Sign in at <https://captchakraken.com/signin>, copy the `ck_live_…` key, then:

```bash
export VLLM_BASE_URL=https://api.captchakraken.com/v1
export CAPTCHA_KRAKEN_API_KEY=ck_live_your_key_here
```

### Cost

| What | Price |
|---|---|
| reCAPTCHA checkbox, Cloudflare Turnstile | **Free** |
| Image response (grids, click, drag) | $0.30 per 1,000 |
| Video response | $1.00 per 1,000 |

Billing is **per model response**, not per captcha. One captcha usually takes
1–2 responses; reCAPTCHA 3×3 refreshes tiles and can take more. One solve
attempt is capped at **5 billable responses**, so a hard captcha cannot run up
an unbounded bill.

The cap works because the driver sends an `X-CK-Session` header that groups all
rounds of one solve. Both shipped drivers do this for you. If you write your own
HTTP client, set `CAPTCHA_KRAKEN_SESSION` to one value per captcha, or every
round is billed separately.

---

## 2B. Self-host

One command installs **Midnight V2 4B Q4**, its element detector, and the tested
vLLM stack. Use a CUDA GPU with at least 8 GB of free VRAM.

```bash
git clone https://github.com/CaptchaKraken/CaptchaKraken
cd CaptchaKraken
./setup.sh
source captchakraken.env
```

The server starts automatically on the first solve and stays up. To manage it:

```bash
captchakraken server start    # background, waits until healthy
captchakraken server status   # endpoint + which model is served
captchakraken server stop
```

Useful flags:

| Command | Effect |
|---|---|
| `./setup.sh --quant q4\|bf16` | Select Q4 (default) or full precision |
| `./setup.sh --download-only` | Only download weights |
| `./setup.sh --start` | Start the server during installation |
| `./setup.sh --update` | Upgrade the serving stack |
| `captchakraken fetch` | Update from the installed CLI |

The merged model serves `POST /v1/pointer`. GGUF builds are for advanced
llama.cpp integrations: stock Ollama cannot evaluate v2's external pointer heads.

### 2C. You already run a v2 pointer server

Point at it and skip everything local:

```bash
export VLLM_BASE_URL=https://your-server:8000/v1
export CAPTCHA_KRAKEN_API_KEY=your-server-key
```

A non-localhost URL is never auto-started or managed for you. Generation 4 uses
`/v1/pointer`, not an older server's `/v1/chat/completions`.

---

## 3. Install the client

Same step for every option above. Pick the language you are writing in.

```bash
npm install captchakraken     # TypeScript: browser driver
pip install captchakraken     # Python: engine + `captchakraken` CLI
```

Python needs 3.11 or newer. Neither package installs a browser — you bring your
own (Playwright, Patchright, camoufox, or Puppeteer).

---

## 4. Solve

**TypeScript** — hand it any Playwright-compatible page:

```typescript
import { chromium } from 'playwright';
import { CaptchaKrakenSolver } from 'captchakraken';

const page = await (await (await chromium.launch()).newContext()).newPage();
await page.goto('https://www.google.com/recaptcha/api2/demo');

await new CaptchaKrakenSolver().solve(page);   // detect → solve → click → verify
```

**Python** — synchronous Playwright only:

```python
from playwright.sync_api import sync_playwright
from captchakraken import PageSolver

with sync_playwright() as p:
    page = p.chromium.launch().new_page()
    page.goto("https://www.google.com/recaptcha/api2/demo")
    result = PageSolver().solve(page)
    print(result.is_solved)
```

**Puppeteer** — wrap the page once:

```typescript
import { CaptchaKrakenSolver, fromPuppeteer } from 'captchakraken';
await new CaptchaKrakenSolver().solve(fromPuppeteer(page));
```

**Do not know when the captcha appears?** Use the watcher instead of `solve()`:

```typescript
const watcher = solver.watch(page);   // handles captchas in the background
// ... your automation ...
await watcher.stop();
```

**On a phone, or driving a real device?** How the answer is PERFORMED is a
choice of input device:

```typescript
// Chromium mobile emulation — needs hasTouch on the context.
const context = await browser.newContext({ ...devices['Pixel 7'], hasTouch: true });
await new CaptchaKrakenSolver({ humanization: 'mobile' }).solve(await context.newPage());

// A real handset over Appium / WebdriverIO / Selenium.
new CaptchaKrakenSolver({
  humanization: 'mobile',
  touchDriver: driver,
  touchTransform: { scale: 3, origin: [0, 132] },   // CSS px -> screen px
});

new CaptchaKrakenSolver({ humanization: 'none' });  // no humanisation at all
new CaptchaKrakenSolver({ humanizer: myOwn });      // your own implementation
```

Same keys in Python, snake_cased: `PageSolverConfig(humanization="mobile",
touch_driver=driver, touch_transform={"scale": 3.0, "origin": (0, 132)})`.

`mobile` never touches `page.mouse` — a mousemove at a touch-only widget is the
wrong event, not a weaker one. `none` is much faster and detectable by anything
scoring pointer telemetry; use it for your own fixtures, or when your browser
already humanises (camoufox does). See
[docs/usage.md § How it moves](./docs/usage.md#how-it-moves--mouse-mobile-none-or-yours).

**No browser, just an image:**

```bash
captchakraken path/to/captcha.png    # prints a JSON click plan
```

---

## 5. Check the setup works

```bash
captchakraken server status
```

It prints the endpoint, whether it is local, and which model is configured. For
the hosted API it should show `api.captchakraken.com` and `local: false`.

---

## Account MCP tools

Installed by the one command in §2A. They manage the **account** — none of them
solves a captcha, and none of them applies to a self-hosted server, which has no
account. What each one is for:

| Tool | Reach for it to |
|---|---|
| `sign_in` | Connect a GitHub account, or resume a sign-in already in progress. Nothing else works until this has |
| `sign_out` | Disconnect this client. Keys already minted keep solving |
| `get_account` | Learn who is signed in and which base URL to point a solving client at |
| `get_balance` | Answer "am I out of credit?" before blaming a failed solve on the model |
| `get_usage` | See what has already been spent, per day, when a bill looks wrong |
| `get_pricing` | Estimate what a job will cost before you run it |
| `create_api_key` | Get a working key onto disk without it passing through this conversation |
| `list_api_keys` | Find the id of the key you want to revoke. Secrets are never listed, only minted |
| `revoke_api_key` | Kill a key that leaked, or one a finished job no longer needs |
| `get_topup_link` | Hand a human a link to add credits. It charges nothing by itself |
| `get_models` | Decide whether to pay per solve or self-host, by seeing which weights are downloadable |

---

## Environment variables

Most users set **none** (hosted, via MCP) or **two** (everything else).

| Variable | What it is | Default |
|---|---|---|
| `VLLM_BASE_URL` | Where inference requests go | credentials file, else `http://localhost:8000/v1` |
| `CAPTCHA_KRAKEN_API_KEY` | Bearer token | credentials file, else `EMPTY` |

Both fall back to `~/.captchakraken/credentials` when unset. Setting either one
overrides that file.

Advanced — only to change **which** model is served:

| Variable | What it is | Default |
|---|---|---|
| `CAPTCHA_BASE_MODEL` | Merged v2 weights vLLM loads | `CaptchaKraken/MidnightV2-4B-q4` |
| `CAPTCHA_LORA_ADAPTER` | Model repository used for downloads and metadata | `CaptchaKraken/MidnightV2-4B-q4` |
| `CAPTCHA_LORA_REVISION` | Model git revision | `main` |
| `CAPTCHA_LORA_NAME` | Name the client sends as `model` | `captcha-pointer` |
| `CAPTCHA_POINTER_DETECTOR` | v2 CNN element detector | path written by `setup.sh` |
| `VLLM_PORT` | Local server port | `8000` |
| `VLLM_GPU_MEMORY_UTILIZATION` | Fraction of VRAM vLLM may use | `0.80` |
| `VLLM_EXTRA_ARGS` | Extra flags for the local server | empty |
| `CAPTCHA_KRAKEN_AUTOSTART` | `0` never auto-starts a local server | `1` |
| `CAPTCHA_KRAKEN_STATE_DIR` | Where the pidfile, log, and credentials live | `~/.captchakraken` |
| `CAPTCHA_KRAKEN_DETECTOR` | A local element-detector `.onnx` to run instead of the released one | the released weights |
| `CAPTCHA_KRAKEN_DETECTOR_MODEL` | `auto`, `standard` or `lite`; overrides `detector` in `captchakraken.config.json` | the config's `detector` (`auto`: `lite` on two usable CPUs or fewer, else `standard` when one board times under 200 ms) |
| `HF_TOKEN` | A Hugging Face token, sent only when downloading the detector weights from a private copy of their repo | unset: the download sends no credential |
| `CAPTCHA_KRAKEN_SESSION` | Groups rounds of one solve for billing | set per solve by both drivers |
| `CAPTCHA_KRAKEN_VENDOR`, `CAPTCHA_KRAKEN_SITE` | Which captcha vendor and which site (hostname only) a hosted solve was for; sent to the hosted API only | set per solve by both drivers |
| `CAPTCHA_REPORT_OUTCOME` | `0` stops the driver telling the hosted API whether each solve was accepted | `1` |
| `CAPTCHA_DEBUG` | `1` prints solver diagnostics to stderr | `0` |
| `CAPTCHA_HUMANIZATION` | `mouse`, `mobile` or `none` — how gestures are performed. Loses to anything set in code, because the right mode is a property of the page | `mouse` |

The defaults for model identity come from `python/src/captchakraken/models.json`.
Do not hardcode a model name in your own code — read it from the config, or the
prompt generation and the weights can drift apart.

---

## Errors and what to do

**The two ports do not raise the same classes**, so a `catch` written for one
never matches in the other.

**Python.** `PageSolver.solve()` raises these, importable from
`captchakraken.page_solver`. `CaptchaSolveError` is the base class of the other
five, so catch it last or it swallows them:

| Error | Meaning | Do |
|---|---|---|
| `NoCaptchaFoundError` | No interactive widget appeared within `detection_timeout_ms` (15 s) — reCAPTCHA v3 / invisible, or one that only triggers on user action | Continue — this is not a failure |
| `VendorBlockedError` | The vendor refused to serve this client at all (rate-limited, or its try-again-later screen) | Stop; a retry from the same browser and network will be refused too |
| `UnsupportedChallengeError` | The model had no usable answer on every round until `max_solve_loops` ran out | Skip, or retry to get a different puzzle |
| `AnimatedChallengeError` | An animated challenge could not be **recorded** (the element refuses to screenshot, or the recording decodes to nothing) | Retry |
| `PageClosedError` | The page, context or browser went away mid-solve | Nothing to retry against — reopen the page |
| `CaptchaSolveError` | Everything else, including every loop spent without a solve, and the base of the five above | Read the message |

**TypeScript.** The driver exports exactly **one** error class,
`CaptchaKrakenAPIError`. Everything else — no widget on the page, a puzzle it
cannot drive, the round budget exhausted — arrives as a plain `Error` whose
message says which. Do not write `catch (e) { if (e instanceof
NoCaptchaFoundError) }` against this port: that class does not exist here and
the branch can never be taken. Read `result.isSolved`, and read the message.

**A solve gives up in two situations only**: the vendor refuses to serve the
client at all, or every one of `maxSolveLoops` / `max_solve_loops` (default 6)
has been spent without a solve. A round that fails for any other reason — a
refused answer, a board that would not screenshot, an answer the widget could
not use — counts one loop and the next round goes again. The time budget,
a closed page and a hosted API refusal still end a solve at once.

Where the vendor's own answer-check response can be read, each round's verdict
is on the result as `result.verdicts` (`accepted`, `rejected`, `new-challenge`,
`blocked`), and an accepted verdict is what ends the solve.

Hosted API refusals arrive as `CaptchaKrakenAPIError` in **both** ports.
**Branch on `e.code`, never on the message text** — wording changes, codes do
not.

| `code` | Meaning | Do |
|---|---|---|
| `insufficient_credits` | Balance is empty | Top up; MCP `get_topup_link` |
| `missing_api_key` / `invalid_api_key` | Key missing or rejected | Run MCP `create_api_key` |
| `rate_limited` | Too many requests | Back off; honour `retry_after_seconds` |
| `request_too_large` | Screenshot too big | Capture the captcha element, not the whole page |
| `account_suspended` | Solving disabled | Contact support |
| `upstream_unavailable` | Our fleet is down | Retry shortly |

Common setup problems:

| Symptom | Cause | Fix |
|---|---|---|
| `Connection refused` on port 8000 | Hosted key set, endpoint not set | Set `VLLM_BASE_URL`, or run MCP `create_api_key` |
| vLLM starts when you did not want it | Endpoint is localhost | Set `VLLM_BASE_URL`, or `CAPTCHA_KRAKEN_AUTOSTART=0` |
| 401 from a local server | Key not forwarded to the CLI | `source captchakraken.env` first |
| Solves are wrong on 4×4 grids | Custom client, no cell numbers drawn | See below |

---

## If you write your own client

Do not skip this. Grid screenshots must be sent with **cell numbers drawn on
them**. The solver runs `find_grid`, renders `get_numbered_grid_overlay` (red
labels, top-right, cells `1..N`), and sends that image. The model reads those
labels — it was never trained to invent a numbering.

Without the overlay, reCAPTCHA 4×4 scores **zero**. It does not error. It just
answers `1..k` and looks like a broken model.

Image resolution also matters. The model declares a `pixel_budget` in
`models.json` and the client clamps every image's area into it. Use the shipped
client unless you have a reason not to.

---

## Rules for agents

- **Never invent accuracy numbers.** Everything we publish is on one page,
  [docs/benchmarks.md](./docs/benchmarks.md): the end-to-end browser runs (each
  puzzle driven on the vendor's own demo page, quoted as counts rather than
  percentages, with the date and the model beside them) and the per-puzzle
  static-image rates over held-out real captures. Quote those or quote nothing.
  Do not convert a count into a percentage, and do not read a static-image rate
  as a promise about a browser — the page says why they differ.
- **Midnight V2 4B Q4 is the default self-hosted and hosted model.** The v2
  weights are downloadable under LGPL-3.0-only. Older clients keep using their
  registered chat-completion model because the protocols are not interchangeable.
- **Never print an API key** into a transcript, a log, or a commit. Use the MCP
  flow, which writes it to disk instead.
- **Do not commit `captchakraken.env`.** It holds a key and is gitignored.
- **Respect the license.** CaptchaKraken and all its models are LGPL-3.0-only;
  commercial use and integration are permitted under those terms. See
  [docs/licensing.md](./docs/licensing.md).

---

## More detail

| Topic | Guide |
|---|---|
| The npm package alone, as `npm i` installs it | [js/AGENTS.md](./js/AGENTS.md) |
| The PyPI package alone, as `pip install` installs it | [python/AGENTS.md](./python/AGENTS.md) |
| Hardware, server management, updating | [docs/self-hosting.md](./docs/self-hosting.md) |
| Every browser framework, the watcher, migrating from v1 | [docs/usage.md](./docs/usage.md) |
| The solve pipeline | [docs/how-it-works.md](./docs/how-it-works.md) |
| The published accuracy numbers | [docs/benchmarks.md](./docs/benchmarks.md) |
| Speed by device, IP reputation | [docs/performance.md](./docs/performance.md) |
| What you may build | [docs/licensing.md](./docs/licensing.md) |
