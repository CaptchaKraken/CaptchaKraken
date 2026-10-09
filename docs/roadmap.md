# 🗺️ Roadmap

Where CaptchaKraken is headed. Legend: 🟢 shipped · 🟡 in progress · ⚪ planned.

## 🟢 Recently shipped

| Item | Status | Notes |
|---|---|---|
| 🛡️ **Stale-frame freshness guard** | 🟢 shipped | Re-checks the frame after inference and re-solves if tiles faded in mid-generation, so we never click a stale answer. See [How it works](./how-it-works.md#freshness-guard-no-acting-on-a-stale-frame). |
| ⬇️ **Unified `fetch` command** | 🟢 shipped | `captchakraken fetch` pulls the latest weights from HF **and** upgrades vLLM in one step. See [Self-hosting → Updating](./self-hosting.md#updating). |
| ♻️ **Per-solve solution dedup** | 🟢 shipped | Byte-identical frames are never re-sent to vLLM. |
| ☁️ **Hosted cloud API** | 🟢 shipped | `api.captchakraken.com`. Self-serve signup with GitHub, free credits on the account, metered per inference round. Answers with **Twilight v1.2**. |
| 🧩 **Click / drag puzzles** | 🟢 shipped | Full-puzzle model → pixel-space click/drag actions. Click, drag, path/connect and tetris-fit all route and are driven. |
| 🪶 **Sunlight / Twilight merges** | 🟢 shipped | The adapter merged into the base at 4-bit (11 GB) and 8-bit (13 GB), so self-hosting is one download instead of two. Published for both v1.1 and v1.2, all public on [HuggingFace](https://huggingface.co/CaptchaKraken). |
| 🎥 **Video challenge support** | 🟢 shipped | **Both halves are out.** A challenge that never settles is recorded (4 s @ 10 fps), cut into keyframes, and sent to the model as one multi-image prompt; the answer names which keyframe it acted on, and the driver waits for the widget to return to that frame before clicking. The model half shipped with **v1.2** — trained on the keyframe format, installed by `setup.sh`, and what the hosted API answers with. |
| ⬛ **Abyss** | 🟢 shipped | Hosted-only, trained against the open weights' measured failures. What the hosted API serves the current client, which names an expert on every request; there is nothing to download. An older client, or a request that names no model, still gets **Twilight v1.2**. |
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
