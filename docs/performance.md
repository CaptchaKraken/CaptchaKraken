# 📊 Performance

How accurate the model is, how fast it runs on your hardware, and why real-world
solve rates depend on more than the model.

## Accuracy

**Every figure we publish is on one page: [benchmarks.md](./benchmarks.md)** —
the real-captcha browser runs and the per-puzzle model accuracy side by side,
because neither answers the other's question. The headline is the browser table:
nine puzzle types, each driven on the vendor's own public demo page through
the hosted API, every attempt scored, recorded
2026-08-19 against the adapter the hosted API serves today. Counts rather than
percentages, and a median whole-solve time taken from the run rather than from
the footage.

That is deliberately an **end-to-end** number — detect, read, click, verify, and
the vendor accepting — not a model score. It is the one worth quoting because it
is the one you experience.

An earlier revision of this page carried per-type model accuracy taken on
2026-07-27 against the then-deployed v1.1 adapter. Those figures were withdrawn:
the eval split of the day let some hand-labeled captures reach training, so they
measured memorisation alongside skill, by an amount that varied per puzzle type
and was largest exactly where the headline number was highest. The split was
replaced — **every** real capture is held out and nothing hand-labeled trains,
which is the only arrangement in which real captures can still detect drift in
the training data — and the model has been re-measured against it since. The
re-measured per-puzzle rates are on [benchmarks.md](./benchmarks.md), printed
beside the browser counts rather than alone, because on its own a model score
tells you very little about whether a captcha actually clears.

The method behind the recorded solves: exact set match — every correct tile
selected and no incorrect ones, no partial credit, because a partially-correct
grid answer is a rejected captcha — taken over the full customer path
(HTTPS → gateway → vLLM) rather than against a local checkpoint, so it includes
anything the serving stack does to a request.

Per-response latency, measured end to end including the network: **p10 0.84 s,
median 1.36 s, p90 1.76 s**, median prompt 341 tokens. That is one model
response; a captcha usually takes one or two, and the whole-solve medians in the
README are the number that includes the vendor's own waiting.

### Grids must be sent with the cell numbers drawn on

This is the single biggest thing to get right in a client, and getting it wrong
does not look like a bug — it looks like a bad model.

`solver.py` runs `find_grid`, renders `get_numbered_grid_overlay` (red labels,
top-right, all cells 1..N — byte-identical to the overlay the training data was
built with) and sends *that* image. The model reads the labels. It does not
infer a numbering from tile positions, because it was never trained to.

Measured over 300 samples, overlay versus raw un-numbered screenshots. This is a
within-run ablation — the same images, the same model, the numbering the only
difference — so it is reported as a relative effect:

| Challenge | Raw screenshot, relative to the overlay |
|---|---|
| reCAPTCHA 3×3 | drops by roughly a sixth |
| reCAPTCHA 4×4 | **collapses to zero — not one board solved** |

The 4×4 collapse is the tell. A 4×4 is one continuous photograph with sixteen
cells and no separate subjects to anchor on, so with no labels to read the
model invents a convention and answers `1..k` — right number of tiles, wrong
region, mean IoU 0.33. A 3×3 of nine distinct photographs degrades far more
gently, which is exactly why this mistake can hide.

### The model is trained on the prompt the client sends

A model answers in whatever schema its prompt asks for, so a client that
paraphrases the prompt does not get an error — it gets worse answers, on every
puzzle, silently. The shipped grid and pixel prompts are therefore byte-identical
to the ones the model was trained against, and a build check compares all five
rather than trusting that they still match.

This is also why prompts are versioned **per model** rather than per client
release: [`models.json`](../python/src/captchakraken/models.json) maps every
published model to the prompt generation it was trained on, and the client ships
the built-ins for each generation still in service. Pin a specific model with
`CAPTCHA_LORA_ADAPTER` and you get that model's prompts; leave it unset and the
weights and the prompts move forward together.

If you are writing your own client, send the prompts this one sends. Do not
reword them.

**Browser solve rates are a different measurement.** In a live run against
`google.com/recaptcha/api2/demo` on 2026-07-27, Camoufox cleared 3/3 challenges,
taking 5–8 model rounds — reCAPTCHA replaces tiles after every click, and each
replacement is a fresh puzzle. The run came from a datacenter IP, which is the
least favourable condition available; see
[below](#rate-limiting--ip-reputation).

## A note on speed

Solve time is dominated by how fast your hardware generates tokens, and LLM
generation is **memory-bandwidth bound** — each token streams the model's weights
through memory once. So speed tracks your GPU/SoC **memory bandwidth**, not its
capacity: roughly `tokens/sec ≈ bandwidth × ~50% ÷ bytes-per-token`, where the
8-bit (FP8) model reads ~9 GB/token and the 4-bit (AWQ) ~4.5 GB/token. (Measured
on a 5090: ~100 tok/s on FP8, ~200 tok/s on AWQ — both match this formula.)
<!-- TODO: re-confirm on latest LoRA -->

Estimated throughput for common devices:

| Device | Memory bandwidth | FP8 (8-bit) | AWQ (4-bit) |
|---|---|---|---|
| NVIDIA H100 | ~3.35 TB/s | ~186 | ~370 |
| NVIDIA A100 | ~2.0 TB/s | ~111 | ~222 |
| **NVIDIA RTX 5090** | **~1.79 TB/s** | **~100** | **~200** |
| NVIDIA RTX 4090 | ~1.0 TB/s | ~56 | ~112 |
| NVIDIA RTX 5080 / 3090 | ~0.95 TB/s | ~53 | ~105 |
| NVIDIA RTX 5070 Ti | ~896 GB/s | ~50 | ~100 |
| AMD RX 7900 XTX | ~960 GB/s | ~53 | ~106 |
| NVIDIA RTX 3080 / 4080 | ~0.7–0.76 TB/s | ~40 | ~80 |
| Apple M2 / M3 Ultra | ~800 GB/s | ~44 | ~88 |
| NVIDIA RTX 5070 | ~672 GB/s | ~37 | ~74 |
| Apple M5 Max | ~614 GB/s | ~34 | ~68 |
| Apple M4 Max | ~546 GB/s | ~30 | ~60 |
| NVIDIA RTX 4070 | ~504 GB/s | ~28 ⚠️ | ~56 |
| Apple M1–M3 Max | ~400 GB/s | ~22 ⚠️ | ~44 |
| Apple M5 Pro | ~307 GB/s | ~17 ⚠️ | ~34 |
| Apple M4 Pro | ~273 GB/s | ~15 ⚠️ | ~30 |
| Apple M5 (base) | ~154 GB/s | ~8 ⚠️ | ~17 ⚠️ |

(Rough estimates at ~50% bandwidth efficiency; real numbers vary with batching,
KV-cache length, and driver. AWQ is faster but slightly less accurate.) Sources:
NVIDIA / AMD / Apple spec sheets.

**Cards that comfortably self-host** (≥ 30 tok/s): NVIDIA 5090 · 5080 · 5070 Ti ·
5070 · 4090 · 4080(Ti) · 3090 · 3080; AMD 7900 XTX / 7900 XT; Apple **Ultra**
chips and the **M4/M5 Max**. Most other cards fall under ~30 tok/s on the 8-bit
model — 4070 and below, older Apple **Max** chips (fine on the 4-bit model), Apple
**Pro**/base laptops, and older mid-range AMD.

> ⏳ **Below ~30 tokens/sec, self-hosting feels sluggish.** If that is your card,
> use the **hosted API** instead — it runs the production adapter on our fleet
> with no GPU of yours involved, at the per-response latency measured above
> (median 1.36 s end to end, including the network). Sign in at
> [captchakraken.com](https://captchakraken.com/signin). `setup.sh` estimates
> your speed from your device's bandwidth (NVIDIA / AMD / Apple) and flags this
> automatically.

## Rate limiting & IP reputation

> ⚠️ **Solving many captchas fast from one IP lowers your success rate.** This is
> normal anti-abuse behavior — once a provider distrusts an IP, it rejects
> submissions **even when the answer is correct** and serves harder challenges.

CaptchaKraken only produces the answer. Managing your IP reputation is **your
job**. In production you'll usually want to:

- **Use rotating / residential proxies** instead of one IP.
- **Space out requests** — avoid rapid bursts.
- **Rotate the IP** when you notice correct answers being rejected or challenges
  getting harder, rather than retrying on the same one.

This only affects whether the provider *accepts* a solve — it doesn't change the
model's accuracy.

---

← Back to [docs index](./README.md)
