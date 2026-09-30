# 🧑‍💻 Usage

Install a port, hand the solver a browser page (or a screenshot), and it does
detect → grid → click → verify.

> **Set up the model first.** Everything below assumes the solver knows where to
> send inference requests: [Hosted API](./hosted-api.md) (no GPU, ~1 minute) or
> [Self-hosting](./self-hosting.md) (your own card).

## Install

Two ports, pick your language. The **TypeScript** port (npm) is the browser
driver; the **Python** port (PyPI) is the engine + CLI (also usable standalone
to solve a screenshot). Both talk to the same vLLM server and are model-agnostic.

```bash
npm install captchakraken          # TypeScript browser driver
# or
pip install captchakraken          # Python engine + `captchakraken` CLI
```

Python one-liner (solve a screenshot → JSON click plan):

```bash
captchakraken path/to/captcha.png      # local server auto-starts on first call
```

## Two drivers: TypeScript and Python

Since **2.3.0** the solver drives a browser from either language, and both are
first-class:

| | import | notes |
|---|---|---|
| TypeScript | `import { CaptchaKrakenSolver } from 'captchakraken'` | async; spawns the Python engine as a subprocess |
| Python | `from captchakraken import PageSolver` | **sync only**; calls the engine in-process |

They are mirrors of each other, deliberately. The split is identical on both
sides: **vision, CV and prompting live in the shared Python half**
(`solver.py`, `planner.py`, `tool_calls/`) and the driver only finds the
challenge and clicks. The TypeScript driver reaches that half by spawning the
CLI and talking JSON over a pipe; the Python driver calls the very same
functions in-process — no subprocess, no CV worker. That is the *only* intended
difference, so the two cannot drift on anything that decides accuracy.

```python
from playwright.sync_api import sync_playwright
from captchakraken import PageSolver

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)
    page = browser.new_page()
    page.goto("https://example.com/protected")

    result = PageSolver().solve(page)
    print(result.is_solved, result.token_usage)
```

Errors are typed, because they mean different things about the page:
`NoCaptchaFoundError` (no widget appeared within `detection_timeout_ms` —
reCAPTCHA v3 / invisible, nothing to solve), `VendorBlockedError` (the vendor
refused to serve this client at all), `UnsupportedChallengeError` (the model had
no usable answer on any round), `AnimatedChallengeError` (an animated challenge
we could not RECORD — note this no longer means "the challenge moves"; a moving
challenge is recorded and solved from keyframes), and `CaptchaSolveError` for
everything else, including every loop spent without a solve.

A solve gives up when the vendor refuses to serve the client, when
`max_solve_loops` is spent, or when `overall_solve_timeout_ms` (default 45 s)
runs out; any other failed round counts a loop and the next one goes again. A
solve that takes much longer reads as automated to the vendor, so raise the
budget only for a page that needs it. It also waits up to `detection_timeout_ms` (default 15 s) for a
widget the page has not drawn yet, so you can call `solve()` straight after
`goto(..., wait_until="domcontentloaded")`; that wait is not charged to
`overall_solve_timeout_ms`. Where the vendor's answer-check response is
readable, `result.verdicts` lists its answer to each round, and an accepted
verdict is what ends the solve. `max_no_progress_rounds`,
`max_stale_element_retries` and `max_unsupported_resolves` are still accepted
but ignored since 3.2.0.

Tune with `PageSolverConfig`. Its fields are the snake_cased names of the
TypeScript `CaptchaKrakenConfig` keys, so a value tuned on one driver is
findable on the other — with the exceptions below, which are worth knowing
because guessing wrong is silent on the Python side.

**Three keys are not a plain snake_case of the TypeScript name.** The TS names
capitalise the `S` in "re-solve":

| Python | TypeScript |
|---|---|
| `stale_frame_resolve_enabled` | `staleFrameReSolveEnabled` |
| `max_stale_frame_resolves` | `maxStaleFrameReSolves` |
| `max_unsupported_resolves` | `maxUnsupportedReSolves` |

**Two have different shapes.** `starting_mouse_position` is a `(x, y)` tuple in
Python and a `{ x, y }` object in TypeScript; `touch_transform`'s `origin` is a
tuple in Python and an array in TypeScript.

**A few exist on one side only**, because they configure something only that
side has:

| Only in Python | Only in TypeScript |
|---|---|
| `animated_probe_enabled` | `onStep` — a per-step callback for progress UI |
| `slide_tolerance_px` | `idleMouseWander` |
| `slide_max_corrections` | `repoPath`, `pythonCommand` — where the bundled engine lives |
| | `model`, `apiKey` — Python takes these on `PageSolver(...)` itself |

Everything that decides **accuracy** — the prompts, the CV, the pixel budget,
the model — lives in the shared Python half and is identical by construction.
The differences above are all in the driving layer.

> **The Python driver is synchronous only.** A sync Playwright handle cannot be
> driven from inside an event loop, so `async_playwright` and `AsyncCamoufox`
> are not supported by it — use the TypeScript driver for async work until the
> async mirror lands.

### camoufox (Python)

```bash
pip install "camoufox[captcha]"
```

```python
from camoufox.sync_api import Camoufox
from camoufox.captcha import solve_captcha

with Camoufox(headless=False) as browser:
    page = browser.new_page()
    page.goto("https://example.com/protected")
    solve_captcha(page)
```

---

## Bring your own browser

Neither driver launches the browser for you — you **bring your
own** browser and hand the solver a page. Install whichever automation framework
you prefer alongside it. The solver itself ships **no browser dependency**.

| Framework | Install | Pass to `solve()` |
|---|---|---|
| [Playwright](https://www.npmjs.com/package/playwright) (vanilla) | `npm i playwright` | the `page` directly |
| [Patchright](https://www.npmjs.com/package/patchright) (stealth Chromium) | `npm i patchright` | the `page` directly |
| [camoufox-js](https://www.npmjs.com/package/camoufox-js) (Firefox stealth) | `npm i camoufox-js` | the `page` directly |
| [Puppeteer](https://www.npmjs.com/package/puppeteer) | `npm i puppeteer` | `fromPuppeteer(page)` |

The first three are Playwright-compatible (they return a standard Playwright
`Page`), so you pass the page straight in. Puppeteer's API differs slightly, so
wrap its page once with `fromPuppeteer()`. All four are tested end-to-end against
the live reCAPTCHA demo.

In every example the solver reads `VLLM_BASE_URL` + `CAPTCHA_KRAKEN_API_KEY`
from the environment, or from `~/.captchakraken/credentials` if they are unset.
Set them up either way first — [Hosted API](./hosted-api.md) (no GPU) or
[Self-hosting](./self-hosting.md#configuration) (`setup.sh`, then
`source captchakraken.env`). Then `solve()` does detect → grid → click → verify.

### Playwright (vanilla)

```typescript
import { chromium } from 'playwright';
import { CaptchaKrakenSolver } from 'captchakraken';

const browser = await chromium.launch({ headless: false });
const page = await (await browser.newContext()).newPage();
await page.goto('https://www.google.com/recaptcha/api2/demo');

const solver = new CaptchaKrakenSolver();
await solver.solve(page);

await browser.close();
```

### Patchright (stealth-patched Chromium)

Drop-in for vanilla Playwright — same API, just a stealthier Chromium.

```typescript
import { chromium } from 'patchright';
import { CaptchaKrakenSolver } from 'captchakraken';

const browser = await chromium.launch({ headless: false });
const page = await (await browser.newContext()).newPage();
await page.goto('https://www.google.com/recaptcha/api2/demo');

const solver = new CaptchaKrakenSolver();
await solver.solve(page);

await browser.close();
```

### camoufox-js (Firefox stealth)

[`camoufox-js`](https://github.com/apify/camoufox-js) exposes a `Camoufox()`
launcher that returns a standard Playwright Browser. (On first run it may prompt
you to fetch its Firefox build: `npx camoufox-js fetch`.)

```typescript
import { Camoufox } from 'camoufox-js';
import { CaptchaKrakenSolver } from 'captchakraken';

const browser = await Camoufox({ headless: false });
const page = await (await browser.newContext()).newPage();
await page.goto('https://www.google.com/recaptcha/api2/demo');

const solver = new CaptchaKrakenSolver();
await solver.solve(page);

await browser.close();
```

### Puppeteer (via `fromPuppeteer`)

Puppeteer isn't Playwright-API-compatible, so wrap its page with the bundled
`fromPuppeteer()` adapter. Drive the **raw** Puppeteer page as usual (navigate,
etc.); only the object you hand `solve()` needs wrapping.

```typescript
import puppeteer from 'puppeteer';
import { CaptchaKrakenSolver, fromPuppeteer } from 'captchakraken';

const browser = await puppeteer.launch({ headless: false });
const page = await browser.newPage();
await page.goto('https://www.google.com/recaptcha/api2/demo');

const solver = new CaptchaKrakenSolver();
await solver.solve(fromPuppeteer(page));

await browser.close();
```

That's it — no model name to pass, no provider to choose, and **no browser locked
in**. The solver defaults to the unified captcha LoRA and the endpoint from your
env, and works with whatever browser you handed it.

### Puppeteer in Python — there isn't one

`fromPuppeteer()` is TypeScript-only, because Puppeteer is a Node library.
Python's `pyppeteer` last released in February 2024, pins `urllib3 <2.0.0`
against CaptchaKraken's own `requests`, and is async-only against a synchronous
driver — two independent blockers. Playwright is the Python path, and
`patchright` / `camoufox` are stealth-patched builds of it.

## How it moves — mouse, mobile, none, or yours

Solving a captcha is two jobs: reading the puzzle, and *performing* the answer.
The second one is a choice of **input device**, and it is yours to make.

```typescript
new CaptchaKrakenSolver({ humanization: 'mouse' })   // default
new CaptchaKrakenSolver({ humanization: 'mobile' })  // touch events
new CaptchaKrakenSolver({ humanization: 'none' })    // straight to the DOM effect
new CaptchaKrakenSolver({ humanizer: myOwn })        // yours; overrides the above
```

```python
PageSolver(config=PageSolverConfig(humanization="mobile"))
PageSolver(config=PageSolverConfig(humanizer=my_own))
```

Unset, both ports read `CAPTCHA_HUMANIZATION` and then fall back to `mouse`.
The env var deliberately **loses** to anything set in code: which mode is right
is a property of the page you are driving, and a stray env var flipping a
desktop solve to touch dispatch would break every one of them silently.

| Mode | What it dispatches | Use it when |
|---|---|---|
| `mouse` | Trajectories recorded from real people, morphed onto the requested endpoints and re-noised (Cursory) | Default. Desktop pages. |
| `mobile` | Real touch events with finger kinematics — see below | The page is a mobile site, or you are driving a phone |
| `none` | One move, one press, one release. No dwell, no jitter | Your own fixtures, or your stack humanises elsewhere |
| custom | Whatever you write | You already model your users' input |

### `mobile` — touch, not a smaller mouse

A mousemove at a touch-only widget is not weaker humanisation, it is **the wrong
event**: the page's touch handlers never fire, and the solve fails for a reason
nothing reports. So mobile mode never touches `page.mouse`. It emits
`touchstart` / `touchmove` / `touchend`, with the differences that actually
distinguish a finger from a cursor —

- **there is no hover.** A move with nothing touching the glass dispatches
  nothing at all; the tile-hover and the idle drift during inference switch
  themselves off.
- **taps carry a contact wobble.** A finger held for 90 ms does not report one
  unchanging coordinate — the centroid of the contact patch rolls a pixel or two
  under pressure. A tap with zero movement in between is a synthetic tap.
- **swipes have their own kinematics.** A finger leaves fast and brakes late,
  bows far less than a hand crossing a desk, and never overshoots — it occludes
  its own target and commits. Jitter is a low-frequency wander of the reported
  centroid, not white noise scaled by speed.
- **everything is slower**, and more variable, including soft-keyboard typing.

In a browser, that needs a Chromium-family page with touch turned on:

```typescript
import { chromium, devices } from 'playwright';

const context = await browser.newContext({ ...devices['Pixel 7'], hasTouch: true });
const page = await context.newPage();

await new CaptchaKrakenSolver({ humanization: 'mobile' }).solve(page);
```

### On a real device — Appium, WebdriverIO, Selenium

Point `touchDriver` at the WebDriver session and the gestures go out as **W3C
pointer actions** with `pointerType: "touch"` instead of CDP. A whole swipe is
sent as **one action chain with per-sample durations**, so the kinematics are
reproduced by the device rather than by a loop round-tripping over the wire —
over which a 90 Hz path is not 90 Hz at all.

```typescript
const solver = new CaptchaKrakenSolver({
  humanization: 'mobile',
  touchDriver: driver,                            // your Appium / WebdriverIO session
  touchTransform: { scale: 3, origin: [0, 132] }, // CSS px -> screen px
});
```

```python
PageSolver(config=PageSolverConfig(
    humanization="mobile",
    touch_driver=driver,
    touch_transform={"scale": 3.0, "origin": (0, 132)},
))
```

**`touchDriver` moves the finger; it does not replace the page.** Detection and
screenshots still go through a Playwright-compatible `page`, so the usual shape
for a real handset is *two objects*: attach Playwright to the device's Chrome
over CDP for the DOM reads, and hand the Appium session to `touchDriver` for the
gestures.

```bash
adb forward tcp:9222 localabstract:chrome_devtools_remote
```

```typescript
const browser = await chromium.connectOverCDP('http://localhost:9222');
const page = browser.contexts()[0].pages()[0];

await new CaptchaKrakenSolver({
  humanization: 'mobile',
  touchDriver: appiumDriver,
}).solve(page);
```

That split is the point, not a workaround: the touches are injected by the
**operating system**, where a real one comes from, while the DOM reads take the
cheap path. If you do not need OS-level injection, drop `touchDriver` — mobile
mode dispatches CDP touch events at that same page on its own.

`touchTransform` exists because everything upstream is **CSS pixels in the
page's viewport** — that is what `boundingBox()` returns — while a handset wants
**screen pixels**. The two differ by `window.devicePixelRatio` and by whatever
browser chrome sits above the webview. The default is the identity transform,
which is right for emulation and for anyone who has already mapped the
coordinates.

**A missing `scale` is refused, not guessed.** Get the transform wrong and
nothing raises: the action chain is valid W3C, the device performs it, and the
finger lands somewhere else — the solve then fails looking exactly like a model
that cannot read the puzzle. So if you pass a `touchDriver`, set no `scale`, and
the page reports a `devicePixelRatio` other than 1, the first gesture raises and
names the value to use. Passing `scale: 1` explicitly is how you say *"I have
already mapped these"* — an unset scale and an explicit 1 are different facts and
only the first is checked. The ratio is read once per solve, not per gesture.

`origin` is never checked, because it cannot be measured from inside the page at
all: it is the webview's top-left in screen coordinates, and only the device
knows it. The refusal names it so you set both halves together.

Nothing here imports Selenium: the payload is the raw WebDriver one, sent
through `performActions()` / `execute("actions", …)`, so any client that speaks
the protocol works. Press and release are separate calls on purpose — W3C input
state persists per *session*, which is what lets the puzzle-slider driver press,
screenshot, steer, screenshot and only then let go.

### Writing your own

Implement the gesture vocabulary — `move`, `press`, `release`, `typeText`, plus
a pause table — and `click` / `drag` compose themselves. The humanizer also owns
the pointer position, because a mode that dispatches no motion still has to
answer where the next gesture starts.

```typescript
import { NullHumanizer, type Humanizer } from 'captchakraken';

class HardwareMouse extends NullHumanizer implements Humanizer {
  async move(page, to) {
    await myUsbPointer.glideTo(to[0], to[1]);
    this.at = to;
  }
}

new CaptchaKrakenSolver({ humanizer: new HardwareMouse() });
```

This is also the right answer when your **browser already humanises**. Camoufox's
`humanize` juggler re-humanises every `mouse.move()` it is handed, so running it
against `mouse` mode composes two models: measured **82.1 s against 13.4 s** on
one geetest slide, because each of the 60 trajectory points became its own
humanised sub-trajectory. Use `none` there, and let camoufox do it.

## Solve captchas as they appear

`solve(page)` is a one-shot: it solves whatever challenge is on the page right
now. When you do not know *where* in a script a captcha will show up, install a
watcher instead and let it handle them underneath your automation.

**TypeScript** — returns immediately, watches in the background:

```typescript
const solver = new CaptchaKrakenSolver();
const watcher = solver.watch(page, {
  onSolved: (r) => console.log('solved:', r.isSolved),
});

await page.goto('https://example.com/protected');   // solved as it appears
// ... the rest of your automation ...

await watcher.stop();                               // waits for a solve in flight
```

**Python** — the same idea, in the two shapes a synchronous driver allows:

```python
solver = PageSolver()

solver.watch(page).run()          # blocking: hold this page clean

watcher = solver.watch(page)      # or cooperatively, inside your own loop
while working():
    watcher.poll_once()
```

Options are the same on both (snake_cased in Python): `interval_ms` (default
1000), `max_solves`, `error_backoff_ms` (default 5000, applied only after a
solve *raises*), `on_solved`, `on_error`.

### Why Python blocks and TypeScript does not

A synchronous Playwright handle is bound to the greenlet that created it, so a
worker thread cannot drive the page — `threading` would buy an exception, not a
background watcher. The TypeScript driver is async and has no such limit. This
is the one place the two ports deliberately differ.

### It injects nothing into the page

The obvious implementation is a `MutationObserver` in the page that calls out
through an exposed binding. That reacts faster, and it is the one design that
cannot be made stealthy everywhere: an exposed binding puts a function on
`window`, and an observer is script the page can enumerate.

So the watcher injects nothing at all. It drives the same `detectCaptcha()` the
solver already uses, from the driver side, on a timer — there is no new
detection surface on any launcher. Under camoufox the DOM reads that probe
performs run in the sandboxed Juggler world, because that is camoufox's default
for **all** Playwright evaluation (`main_world_eval` and an `mw:` prefix are the
opt-*out*). Nothing here opts out, so the page can no more see the watcher than
it can see Playwright itself.

The trade is latency: a captcha that appears just after a tick waits up to one
`interval_ms` to be noticed. Against a solve measured in seconds, that is not
the number that matters.

## Cloning this repo

If you're cloning instead of installing from npm, initialize the submodule that
holds the detection/planner CLI:

```bash
git submodule update --init --recursive
npm install        # builds the solver + a local CLI venv (postinstall)
```

## Migrating from v1

> **⚠️ v2 is a breaking change.** It's a full rewrite. The old multi-provider
> setup (Gemini / OpenRouter / Ollama) is gone — v2 runs one purpose-built grid
> model on a local **vLLM** server.

- The `apiProvider` / `model` / `apiKey` options for Gemini/OpenRouter/Ollama are
  **removed**. v2 talks only to a vLLM server.
- Set **`VLLM_BASE_URL`** and **`CAPTCHA_KRAKEN_API_KEY`** (or run `setup.sh`,
  or point them at the [hosted API](./hosted-api.md)) instead of provider keys.
- `new CaptchaKrakenSolver()` now needs no model/provider — it defaults to the
  grid LoRA.
- v1's `transformers` / `torch` / SAM3 dependencies are gone from the solver venv.

---

← Back to [docs index](./README.md)
