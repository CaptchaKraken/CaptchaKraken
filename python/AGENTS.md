# captchakraken (PyPI)

The Python **engine and CLI**: OpenCV grid detection plus a planner that asks a
fine-tuned vision model what to do, and a page driver that performs it in a
Playwright browser.

It is not a browser and, by default, not the model either. It installs no
browser — bring your own — and every inference goes to a model endpoint you
point it at. The `serve` extra is what turns this box into that endpoint.

Repo, guides and the full agent guide:
<https://github.com/CaptchaKraken/CaptchaKraken>

---

## 1. Point it at a model, first

| You have | Do this |
|---|---|
| No GPU | Use the hosted API — add the account MCP server, `npx -y captchakraken-mcp`, call `sign_in` then `create_api_key` |
| A GPU, and want it local | `pip install "captchakraken[serve]"`, then `captchakraken server start` |
| Your own vLLM server | `export VLLM_BASE_URL=…/v1` and `export CAPTCHA_KRAKEN_API_KEY=…` |

`create_api_key` writes the key and endpoint to `~/.captchakraken/credentials`
(mode 0600) and the client reads that file by itself, so the MCP path needs **no
environment variables at all**. The key is never printed into the conversation.

A local endpoint auto-starts on the first solve; `CAPTCHA_KRAKEN_AUTOSTART=0`
turns that off. A non-localhost `VLLM_BASE_URL` is never started or managed for
you.

## 2. Install

```bash
pip install captchakraken            # the client: grid detection + planner + CLI
pip install "captchakraken[serve]"   # ...and the vLLM serving stack, to host it
```

Python 3.11+.

## 3. Solve

Synchronous Playwright:

```python
from playwright.sync_api import sync_playwright
from captchakraken import PageSolver

with sync_playwright() as p:
    page = p.chromium.launch().new_page()
    page.goto("https://www.google.com/recaptcha/api2/demo")
    result = PageSolver().solve(page)
    print(result.is_solved)
```

`PageSolver().watch(page)` installs a background watcher instead, for when you
do not know if or when a captcha will appear; stop it with `.stop()`.

No browser, just an image:

```bash
captchakraken path/to/captcha.png    # prints a JSON click plan
```

Other CLI modes, all printing JSON: `captchakraken server start|stop|status|run`
manages a local vLLM server, `captchakraken fetch` updates weights and the
serving stack together, and the OpenCV tool calls (`find-grid`, `find-checkbox`,
`get-numbered-grid`, `detect-selected`, …) are exposed one per subcommand. The
module docstring of `captchakraken/cli.py` lists every mode with its arguments.

## 4. Errors

`PageSolver.solve()` raises from `captchakraken.page_solver`:
`NoCaptchaFoundError` (no interactive widget appeared within
`detection_timeout_ms` — usually not a failure), `VendorBlockedError` (the
vendor refused to serve this client at all), `UnsupportedChallengeError`,
`AnimatedChallengeError` (the challenge could not be *recorded*),
`PageClosedError`, and `CaptchaSolveError`, which is the base class of the
other five — catch it last or it swallows them. Apart from a vendor refusal, a
closed page and the time budget, a solve only gives up once every one of
`max_solve_loops` has been spent. `result.verdicts` holds the vendor's own
answer to each round where its answer-check response is readable. The TypeScript
port raises none of these; it exports one error class and throws plain `Error`
otherwise.

Refusals from the hosted API raise `CaptchaKrakenAPIError` (exported from the
package root). **Branch on `.code`, never on the message text** — the codes are
the contract, the wording is not: `insufficient_credits`, `missing_api_key`,
`invalid_api_key`, `rate_limited`, `request_too_large`, `account_suspended`,
`upstream_unavailable`. Retrying a `403` that means "no licence" will never
succeed.

## 5. If you drive the model yourself

Grid screenshots must be sent with **cell numbers drawn on them** — the client
runs `find_grid`, renders the numbered overlay, and sends that image, because
the model reads those labels and was never trained to invent a numbering.
Without the overlay reCAPTCHA 4×4 scores zero without erroring. Image area is
also clamped into the `pixel_budget` the model declares in
`captchakraken/models.json`. Use the shipped client unless you have a reason not
to, and never hardcode a model name — read it from the config, or the prompt
generation and the weights drift apart.

## Rules for agents

- **Never invent a number.** Every accuracy, latency and price figure we publish
  is on one page —
  [docs/benchmarks.md](https://github.com/CaptchaKraken/CaptchaKraken/blob/main/docs/benchmarks.md).
  Quote it as written; do not derive, round, or convert anything, and do not
  read a static-image rate as a promise about a browser run.
- **Never print an API key** into a transcript, a log, or a commit. Use
  `create_api_key`, which writes it to disk instead. `captchakraken.env` and
  `.env` hold keys and are never committed.
- **Abyss is what our hosted API serves, and it is never downloadable.** The
  current client names an Abyss expert on every request to our endpoint and is
  answered by Abyss; an older client, or a request that names no model, gets
  Twilight v1.2, because its prompts belong to that generation. Nothing about it
  is gated on the account. Do not suggest weights, a download or a workaround
  for it, and do not quote accuracy figures for it — none are published. Verify
  what is serving with `GET /v1/models`.
- **Respect the licence.** Building automation with this is fine; selling the
  solve, or shipping it inside a browser or automation product, is not. See
  [LICENSE](./LICENSE) and
  [docs/licensing.md](https://github.com/CaptchaKraken/CaptchaKraken/blob/main/docs/licensing.md).
- **Changing this package's own code?** Its rules are in
  [CONTRIBUTING.md](https://github.com/CaptchaKraken/CaptchaKraken/blob/main/CONTRIBUTING.md),
  not here.
