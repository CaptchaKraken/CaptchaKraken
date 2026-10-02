# 🐙 CaptchaKraken — Documentation

Everything beyond the [project overview](../README.md), organized into focused
guides. Start here.

> One repo, two published ports — the TypeScript browser driver
> (npm: `captchakraken`) and the Python engine (PyPI: `captchakraken`). ⭐ **Star
> & watch** [the repo](https://github.com/CaptchaKraken/CaptchaKraken) for smaller
> models and new puzzle types.

## 📚 Guides

| Guide | What's inside |
|---|---|
| [☁️ Hosted API](./hosted-api.md) | Sign in, keys, pricing, per-session billing, and every error code — the no-GPU path. |
| [🖥️ Self-hosting](./self-hosting.md) | One-command install, model-size gate, server management, configuration, and **updating** (`captchakraken fetch`). |
| [🧑‍💻 Usage](./usage.md) | Install both ports, the Python one-liner, all four browser frameworks (Playwright / Patchright / camoufox-js / Puppeteer), **how it moves** (mouse / mobile touch / none / your own), and migrating from v1. |
| [🔄 Staying current](./staying-current.md) | Why `"latest"` plus a kept lockfile pins an old client, the one-line deploy fix, and how to tell which version is running. |
| [⚙️ How it works](./how-it-works.md) | The detect → grid → click → verify pipeline, the OpenCV grid tracer, the stale-frame freshness guard, and solution dedup. |
| [📊 Benchmarks](./benchmarks.md) | The canonical numbers — real captchas driven in a browser, and per-puzzle model accuracy on held-out real captures, with what each measures and why they differ. |
| [⚡ Performance](./performance.md) | The memory-bandwidth speed model + per-device throughput, and IP-reputation guidance. |
| [🗺️ Roadmap](./roadmap.md) | What shipped recently, what's in progress, and what's planned (more captcha types). |
| [⚖️ Licensing](./licensing.md) | Plain-English explainer of the source-available license — what you may and may not build. |

## ✅ What it solves today

CaptchaKraken detects the captcha, solves it, clicks, and verifies.

| Captcha type | Status |
|---|---|
| ✅ Checkbox / "I'm not a robot" | Works end-to-end |
| ✅ **reCAPTCHA 3×3** (dynamic) | Works end-to-end |
| ✅ **reCAPTCHA 4×4** (one-shot) | Works end-to-end |
| ✅ Cloudflare Turnstile | Works via the checkbox flow |
| ✅ **GeeTest** (v3 + v4) | Slide, icon, nine, svg, gobang, iconcrush |
| ✅ **NetEase Yidun** | Jigsaw, picture-click, icon-click |
| ✅ **Lemin, Prosopo, Tencent** | Cropped-image, grid, and slide flows |
| ✅ **Distorted text** | BotDetect, MTCaptcha, Yandex — read and typed, not clicked |
| ✅ **Animated / video challenges** | Recorded (4 s @ 10 fps), cut into keyframes, solved as one multi-image prompt, then clicked once the widget returns to the chosen frame. The model half shipped with **v1.2**, which `setup.sh` installs and the hosted API serves |

44 puzzle types in all. The per-type record — each puzzle
driven on the vendor's own demo page, with the attempts scored — is in the
[main README](../README.md#watch-it-work).

Non-grid still-image puzzles — **click** ("click each …"), **drag** ("drag the
piece into place"), path/connect, "choose the card" — route to the full-puzzle
model, which returns pixel-space click/drag actions the browser replays. If the
model can't produce a usable action for a given frame, the solver fails fast
rather than guessing.

---

← Back to the [project overview](../README.md)
