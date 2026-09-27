# ⚙️ How it works

From a browser page to a verified token: detect → grid → click → verify, with a
couple of safeguards that keep the model from acting on a stale frame.

## The pipeline

```
browser ─▶ detect captcha ─▶ screenshot frame
                                   │
                    OpenCV find_grid (color-agnostic line tracer)
                                   │  tile boxes
                                   ▼
                    Qwen3.5-9B captcha LoRA on vLLM  ─▶  tile selection
                                   │
                    click plan ─▶ execute (human-like) ─▶ re-detect / verify
```

- **`find_grid`** finds the grid lines with plain OpenCV — no model needed. It
  lives in the Python port ([`python/`](../python/), the `captchakraken`
  package).
- The **grid model** runs on your local vLLM server and says which tiles to
  click.
- The **browser driver** (the [`js/`](../js/) TypeScript port) clicks, waits for
  reCAPTCHA's refreshing tiles, and keeps going until the captcha is solved. It
  shells out to the bundled Python engine for detection + planning.

### Freshness guard (no acting on a stale frame)

Grid vendors fade fresh tiles in over ~1 second — on first load and on
the in-place dynamic refresh after a click. If the frame changes **while the
model is generating**, the answer that comes back describes a stale
("undeveloped") frame: its tile picks and bounding boxes no longer line up with
what's now on screen, so replaying them would click the wrong squares.

To prevent that, after **every** model query the solver re-screenshots the
captcha element and diffs it against the exact frame it sent (reusing the same
`check-movement` frame-diff primitive the settle detectors use). If the frame
moved, it discards the answer and re-solves on the developed frame. This runs on
both the one-shot path and the reCAPTCHA 3×3 dynamic driver.

Tunable via the solver config:

| Option | Default | Meaning |
|---|---|---|
| `staleFrameReSolveEnabled` | `true` | Master toggle for the guard. |
| `staleFrameDiffThreshold` | `0.02` | Fraction of pixels that must differ to count the frame as "changed during inference". |
| `maxStaleFrameReSolves` | `2` | How many times to re-screenshot + re-solve before acting on the latest answer (better to act than to spin). Set `0` to detect-and-log only. |

### Solution dedup

Within a single solve, model answers are cached keyed by the **screenshot's
content hash** (plus puzzle source + retry mode). If the frame hasn't changed
since we last asked — a byte-identical screenshot — the solver reuses the prior
answer instead of paying for another vLLM call. Any real page change (tile
refresh, new challenge, a fade) alters the pixels and misses the cache, so the
dedup never stales a genuinely-changed puzzle. It pairs naturally with the
freshness guard above: unchanged frames are free, changed frames are re-solved.

---

← Back to [docs index](./README.md)
