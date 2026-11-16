# 🗺️ Roadmap

Where CaptchaKraken is headed. Legend: 🟢 shipped · 🟡 in progress · ⚪ planned.

## 🟢 Recently shipped

| Item | Status | Notes |
|---|---|---|
| 🛡️ **Stale-frame freshness guard** | 🟢 shipped | Re-checks the frame after inference and re-solves if tiles faded in mid-generation, so we never click a stale answer. See [How it works](./how-it-works.md#freshness-guard-no-acting-on-a-stale-frame). |
| ⬇️ **Unified `fetch` command** | 🟢 shipped | `captchakraken fetch` pulls the latest weights from HF **and** upgrades vLLM in one step. See [Self-hosting → Updating](./self-hosting.md#updating). |
| ♻️ **Per-solve solution dedup** | 🟢 shipped | Byte-identical frames are never re-sent to vLLM. |
| ☁️ **Hosted cloud API** | 🟢 shipped | `api.captchakraken.com`. Self-serve signup with GitHub, free credits on the account, metered per inference round. Answers with **Midnight V2 4B Q4**. |
| 🧩 **Click / drag puzzles** | 🟢 shipped | The v2 pointer model returns pixel-space click and drag actions. |
| 🪶 **v2 models** | 🟢 shipped | Sunlight 0.8B, Twilight 2B, and Midnight 4B in merged, LoRA, and GGUF forms. Midnight Q4 is the one-command default. All are public on [Hugging Face](https://huggingface.co/collections/CaptchaKraken/captchakraken-v2). |
| 🎥 **Video challenge support** | 🟢 shipped | Animated challenges are clipped into frames and answered with the action's time; the driver acts at that moment. |
| 🎯 **v2 pointer architecture** | 🟢 shipped | A pointer model behind `/v1/pointer` that reads the bare board, with one-command vLLM self-hosting. The CNN detector is no longer part of the client. |
| 📱 **Mobile / touch input** | 🟢 shipped | `humanization: 'mobile'` dispatches real touch events with finger kinematics, in a Chromium page with `hasTouch` or at a real handset over Appium / WebdriverIO / Selenium. See [Usage → How it moves](./usage.md#how-it-moves--mouse-mobile-none-or-yours). |

## 🟡 In progress

| Item | Status | Notes |
|---|---|---|
| 📈 **More real labeled data** | 🟡 in progress | Broader coverage for under-represented prompts. |

## ⚪ Planned

| Item | Status | Notes |
|---|---|---|
| 🎯 **Freehand drag/path accuracy** | ⚪ planned | Connect-the-path and the numbered-line / missing-piece drags are the families the model is least reliable on. They are routed and driven today; this is about how often they land. |

---

> 📣 **Watch the repo to hear about these as they ship**, and ⭐ star if the
> project is useful to you — it genuinely helps:
> [**CaptchaKraken**](https://github.com/CaptchaKraken/CaptchaKraken). Use GitHub's
> **Watch → All Activity** for release notifications.

---

← Back to [docs index](./README.md)
