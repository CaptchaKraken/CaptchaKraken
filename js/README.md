<p align="center">
  <img src="https://raw.githubusercontent.com/CaptchaKraken/CaptchaKraken/main/docs/assets/logo-card.png" alt="CaptchaKraken" width="128" height="128">
</p>

<h1 align="center">captchakraken</h1>

<p align="center">
  <b>A captcha solver for browser automation.</b><br>
  The TypeScript driver for <a href="https://github.com/CaptchaKraken/CaptchaKraken">CaptchaKraken</a>.
</p>

Hand it a Playwright or Puppeteer `Page`. It finds the captcha, reads the whole
puzzle with a fine-tuned **Qwen3.5-9B** vision model, and clicks, drags, slides
or types human-like through to a token.

Run the model on **your own hardware**, or point it at the **hosted API** and run
nothing at all.

> Full docs — demo videos, accuracy, self-hosting — live in the main repo
> **[CaptchaKraken](https://github.com/CaptchaKraken/CaptchaKraken)**.

## Watch it work

<p align="center">
  <img src="https://raw.githubusercontent.com/CaptchaKraken/CaptchaKraken/main/docs/assets/demo/hcaptcha_grid.webp" width="260"
       alt="A live hCaptcha image select challenge being solved end to end">
  <img src="https://raw.githubusercontent.com/CaptchaKraken/CaptchaKraken/main/docs/assets/demo/recaptcha_4x4.webp" width="260"
       alt="A live reCAPTCHA 4×4 tile grid challenge being solved end to end">
  <img src="https://raw.githubusercontent.com/CaptchaKraken/CaptchaKraken/main/docs/assets/demo/geetest_slide.webp" width="260"
       alt="A live GeeTest slide jigsaw challenge being solved end to end">
</p>

hCaptcha image select 12/12 in 10.5s · reCAPTCHA 4×4 tile grid 9/10 in 8.7s · GeeTest slide jigsaw 10/10 in 7.6s — median of the solved attempts, measured 2026-08-19 on **captcha-v12**
against each vendor's own public demo page. Counts rather than percentages
because ten attempts is not a percentage. Idle time is cut from the clips, so
they run shorter than the solves they show.

**Ten more puzzle types**, as video and with the full method, at
[captchakraken.com](https://captchakraken.com) and in the
[main repo](https://github.com/CaptchaKraken/CaptchaKraken#watch-it-work).

## Install

```bash
npm install captchakraken
```

The package bundles the Python engine (`captchakraken`) and, on `postinstall`,
creates a local venv with its lightweight core deps, so tile detection and the
inference client work out of the box. It ships **no browser** — bring your own
Playwright-compatible launcher (camoufox and patchright both work).

- Skip the Python bootstrap: `CAPTCHA_KRAKEN_SKIP_PYTHON_SETUP=1`
- To **self-host** the model, run the repo's `setup.sh` (installs vLLM + weights).
  Otherwise point `VLLM_BASE_URL` at a server you already run.

## No GPU? Use the hosted API

Point the client at `https://api.captchakraken.com/v1` and run no model at all.
Sign in at [captchakraken.com/signin](https://captchakraken.com/signin) for a
`ck_live_…` key, or let the MCP server write one for you:

```bash
claude mcp add captchakraken -- npx -y captchakraken-mcp
# then call sign_in, then create_api_key
```

`create_api_key` writes the key and the endpoint to `~/.captchakraken/credentials`,
which the client reads on its own — **no environment variables needed**.

## What it solves

| Vendor | Puzzles |
|---|---|
| **reCAPTCHA** | 3×3 and 4×4 image grids, including the dynamic re-deal |
| **hCaptcha** | Image grids, click, drag, connect-the-path, tetris-fit, animated |
| **GeeTest** v3 + v4 | Slide, icon, nine, svg, gobang, iconcrush |
| **NetEase Yidun** | Jigsaw, picture-click, icon-click |
| **Tencent, Lemin, Prosopo** | Slide, cropped-image and grid flows |
| **BotDetect, MTCaptcha, Yandex** | Distorted text — read and typed, not clicked |
| **Cloudflare Turnstile** | Via the checkbox flow (free on the hosted API) |

**44 puzzle types**, driven end to end in CI against generated fixtures on both
the TypeScript and Python ports. Animated challenges are recorded, sliced into
keyframes and answered with the frame the action belongs to.

## Usage

```typescript
import { chromium } from 'playwright';            // or patchright / camoufox-js
import { CaptchaKrakenSolver } from 'captchakraken';

const browser = await chromium.launch({ headless: false });
const page = await (await browser.newContext()).newPage();
await page.goto('https://www.google.com/recaptcha/api2/demo');

// Reads VLLM_BASE_URL + CAPTCHA_KRAKEN_API_KEY from the environment.
const solver = new CaptchaKrakenSolver();
await solver.solve(page);            // detect → read → act → verify

await browser.close();
```

Puppeteer users wrap the page once with `fromPuppeteer(page)`.

## How it moves — mouse, mobile, none, or yours

Solving a captcha is two jobs: reading the puzzle, and *performing* the answer.
The second is a choice of **input device**, not a realism dial.

```typescript
new CaptchaKrakenSolver({ humanization: 'mouse' })   // default
new CaptchaKrakenSolver({ humanization: 'mobile' })  // real touch events
new CaptchaKrakenSolver({ humanization: 'none' })    // straight to the DOM effect
new CaptchaKrakenSolver({ humanizer: myOwn })        // yours; overrides the above
```

Unset, it reads `CAPTCHA_HUMANIZATION` and then falls back to `mouse` — which is
byte-for-byte what the driver did before the option existed, so nothing moves for
an existing caller. Anything set in code **wins** over the env var: which mode is
right is a property of the page you are driving, not a deployment decision.

`mobile` never touches `page.mouse`. A mousemove at a touch-only widget is the
*wrong event*, not a weaker one — the page's touch handlers never fire and the
solve fails for a reason nothing reports. It needs a Chromium-family page with
touch turned on:

```typescript
import { chromium, devices } from 'playwright';

const context = await browser.newContext({ ...devices['Pixel 7'], hasTouch: true });
await new CaptchaKrakenSolver({ humanization: 'mobile' }).solve(await context.newPage());
```

Or drive a real handset over **Appium / WebdriverIO / Selenium** — gestures go
out as W3C pointer actions with `pointerType: "touch"`:

```typescript
new CaptchaKrakenSolver({
  humanization: 'mobile',
  touchDriver: driver,                            // your Appium / WebdriverIO session
  touchTransform: { scale: 3, origin: [0, 132] }, // CSS px -> screen px
});
```

`touchTransform` is required rather than guessed: get it wrong and nothing
raises — the action chain is valid, the device performs it, and the finger lands
somewhere else. A `touchDriver` with no `scale` on a page reporting
`devicePixelRatio !== 1` refuses on the first gesture and names the value to pass.

Full details, including writing your own humanizer:
[docs/usage.md § How it moves](https://github.com/CaptchaKraken/CaptchaKraken/blob/main/docs/usage.md#how-it-moves--mouse-mobile-none-or-yours).

## Configuration

| Variable | Meaning | Default |
|---|---|---|
| `VLLM_BASE_URL` | Inference endpoint (local vLLM, a server you run, or `https://api.captchakraken.com/v1`) | credentials file, else `http://localhost:8000/v1` |
| `CAPTCHA_KRAKEN_API_KEY` | Bearer token (`VLLM_API_KEY` also accepted) | credentials file, else `EMPTY` |
| `CAPTCHA_HUMANIZATION` | How gestures are performed: `mouse`, `mobile` or `none`. Loses to anything set in code | `mouse` |
| `CAPTCHA_BASE_MODEL` | Base weights vLLM loads | `RedHatAI/Qwen3.5-9B-FP8-dynamic` |
| `CAPTCHA_LORA_ADAPTER` | Captcha adapter (HF id or path) | `CaptchaKraken/CaptchaKraken-Lora-v1.2` |
| `CAPTCHA_LORA_NAME` | Served adapter name sent as `model` | `captcha-v12` |
| `CAPTCHA_KRAKEN_AUTOSTART` | `0` never auto-starts a local server | `1` |
| `CAPTCHA_KRAKEN_PYTHON` | Interpreter used for the bundled engine | the package's venv, else `python3` |
| `CAPTCHA_KRAKEN_SKIP_PYTHON_SETUP` | `1` skips the `postinstall` bootstrap | unset |
| `CAPTCHA_DEBUG` | `1` prints solver diagnostics to stderr | `0` |

`VLLM_BASE_URL` and `CAPTCHA_KRAKEN_API_KEY` fall back to
`~/.captchakraken/credentials` when unset, so the hosted API needs no
environment variables at all.

**Why the model and server variables appear here.** This package bundles the
Python engine and spawns it, forwarding the environment wholesale — so every
variable the engine reads applies to a TypeScript solve too. The full list, and
the vLLM server knobs, are in
[AGENTS.md § Environment variables](https://github.com/CaptchaKraken/CaptchaKraken/blob/main/AGENTS.md#environment-variables).

## License

**CaptchaKraken Source-Available License v1.1** — see [LICENSE](./LICENSE).
Build *with* it (scrapers, QA tooling) and run it against **any** browser you
like, stealth or not. You may **not sell the solve itself**, ship a thin wrapper
(browser extension, hosted solving API), or **bundle it as a built-in feature of
a stealth/antidetect browser you distribute** — using it with one is fine. Those
three are licensable, not categorically refused: open an issue to ask.
