<p align="center">
  <img src="https://raw.githubusercontent.com/JWriter20/CaptchaKraken/main/docs/assets/logo-card.png" alt="CaptchaKraken" width="128" height="128">
</p>

<h1 align="center">captchakraken</h1>

<p align="center">
  <b>A captcha solver for browser automation.</b><br>
  The Python engine and CLI behind <a href="https://github.com/JWriter20/CaptchaKraken">CaptchaKraken</a>.
</p>

OpenCV tile detection plus a fine-tuned **Qwen3.5-9B** vision model. Give it a
screenshot of a captcha and it returns the plan to solve it — which tiles to
select, where to click, what to drag, how far to slide, or what text to type.
Ships the `captchakraken` command.

Run the model on **your own hardware**, or point it at the **hosted API** and run
nothing at all.

> For demo videos, accuracy numbers, the browser driver, and the full
> self-hosting guide, see the main repo
> **[CaptchaKraken](https://github.com/JWriter20/CaptchaKraken)**.

## Watch it work

<p align="center">
  <img src="https://raw.githubusercontent.com/JWriter20/CaptchaKraken/main/docs/assets/demo/recaptcha_4x4.webp" width="260"
       alt="A live reCAPTCHA 4×4 tile grid challenge being solved end to end">
  <img src="https://raw.githubusercontent.com/JWriter20/CaptchaKraken/main/docs/assets/demo/geetest_slide.webp" width="260"
       alt="A live GeeTest slide jigsaw challenge being solved end to end">
</p>

reCAPTCHA 4×4 tile grid 9/10 in 8.7s · GeeTest slide jigsaw 10/10 in 7.6s — median of the solved attempts, measured 2026-08-19 on **captcha-v12**
against each vendor's own public demo page. Counts rather than percentages
because ten attempts is not a percentage. Idle time is cut from the clips, so
they run shorter than the solves they show.

**More puzzle types**, as video and with the full method, at
[captchakraken.com](https://captchakraken.com) and in the
[main repo](https://github.com/JWriter20/CaptchaKraken#watch-it-work).

## What it solves

| Vendor | Puzzles |
|---|---|
| **reCAPTCHA** | 3×3 and 4×4 image grids, including the dynamic re-deal |
| **GeeTest** v3 + v4 | Slide, icon, nine, svg, gobang, iconcrush |
| **NetEase Yidun** | Jigsaw, picture-click, icon-click |
| **Tencent, Lemin, Prosopo** | Slide, cropped-image and grid flows |
| **BotDetect, MTCaptcha, Yandex** | Distorted text — read and typed, not clicked |
| **Cloudflare Turnstile** | Via the checkbox flow (free on the hosted API) |

**44 puzzle types**, driven end to end in CI against generated fixtures on both
the TypeScript and Python ports. Animated challenges are recorded, sliced into
keyframes and answered with the frame the action belongs to.

## Install

```bash
pip install captchakraken            # client: OpenCV detection + vLLM HTTP planner
pip install "captchakraken[serve]"   # + the serving stack (vLLM/torch) to self-host
```

The base install is lightweight — everything you need to solve captchas against
a vLLM server (local or remote). The `[serve]` extra pulls the heavy stack only
if you want to run the model yourself. The one-command
[`setup.sh`](https://github.com/JWriter20/CaptchaKraken) installs `[serve]`,
downloads the weights, and writes an env file for you.

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

## Hands-off server

The vLLM server is managed for you. On your first solve, if the configured
endpoint is **local** and nothing is listening, a server is started
automatically and reused. Point `VLLM_BASE_URL` at a server you already run to
skip local management entirely.

```bash
captchakraken server start | stop | status | run
```

## Usage

```bash
# Solve an image/video: classify → find_grid → plan. Prints the click actions.
captchakraken path/to/captcha.png
captchakraken path/to/captcha.png --puzzle-source hcaptcha
```

```python
from captchakraken import CaptchaSolver

solver = CaptchaSolver()          # connects to / auto-starts a local vLLM
actions = solver.solve("captcha.png")
```

Pure-OpenCV tool subcommands (no model): `find-grid`, `find-checkbox`,
`detect-selected`, `grid-cell-states`, and a persistent `serve` worker the browser driver polls.

## Configuration (model-agnostic)

Everything model-specific lives in `captchakraken.config` and is env-overridable
— the solver never hard-codes a model.

| Variable | Meaning | Default |
|---|---|---|
| `VLLM_BASE_URL` | Inference endpoint | `~/.captchakraken/credentials`, else `http://localhost:8000/v1` |
| `CAPTCHA_KRAKEN_API_KEY` | Bearer token (`VLLM_API_KEY` also accepted) | `~/.captchakraken/credentials`, else `EMPTY` |
| `CAPTCHA_BASE_MODEL` | Base weights vLLM loads | `RedHatAI/Qwen3.5-9B-FP8-dynamic` |
| `CAPTCHA_LORA_ADAPTER` | Captcha adapter (HF id or path) | `CaptchaKraken/CaptchaKraken-Lora-v1.2` |
| `CAPTCHA_LORA_NAME` | Served adapter name the client requests | `captcha-v12` |
| `CAPTCHA_KRAKEN_AUTOSTART` | `0` disables local auto-start | `1` |
| `CAPTCHA_HUMANIZATION` | How gestures are performed: `mouse`, `mobile` or `none` | `mouse` |

**How it moves** is a choice of input device, not a realism dial. `mobile`
dispatches real touch events with finger kinematics and never touches
`page.mouse`; `none` goes straight to the DOM effect. Set it in code (which wins
over the env var, because the right mode is a property of the page you are
driving), and pass your own object to override ours entirely:

```python
from captchakraken import PageSolver
from captchakraken.page_solver import PageSolverConfig

PageSolver(config=PageSolverConfig(humanization="mobile"))
PageSolver(config=PageSolverConfig(humanization="none"))
PageSolver(config=PageSolverConfig(humanizer=my_own))

# A real handset over Appium / Selenium — W3C touch pointer actions.
PageSolver(config=PageSolverConfig(
    humanization="mobile",
    touch_driver=driver,
    touch_transform={"scale": 3.0, "origin": (0, 132)},   # CSS px -> screen px
))
```

## License

**CaptchaKraken Source-Available License v1.1** — see [LICENSE](./LICENSE).
Build *with* it (scrapers, QA tooling) and run it against **any** browser you
like, stealth or not. You may **not sell the solve itself**, ship a thin wrapper
(browser extension, hosted solving API), or **bundle it as a built-in feature of
a stealth/antidetect browser you distribute** — using it with one is fine. Those
three are licensable, not categorically refused: open an issue to ask.
