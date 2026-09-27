# captchakraken (npm)

The TypeScript **browser driver**. You hand it a Playwright-compatible `Page`;
it finds the captcha, has a vision model read it, and clicks, drags, slides or
types through to a token.

It is not a browser and it is not the model. It installs no browser — bring your
own launcher — and every inference goes to a model endpoint you point it at.

Repo, guides and the full agent guide:
<https://github.com/CaptchaKraken/CaptchaKraken>

---

## 1. Point it at a model, first

Nothing solves until the driver knows where inference goes. Two ways:

| You have | Do this |
|---|---|
| No GPU | Use the hosted API — add the account MCP server, `npx -y captchakraken-mcp`, call `sign_in` then `create_api_key` |
| Your own vLLM server | `export VLLM_BASE_URL=…/v1` and `export CAPTCHA_KRAKEN_API_KEY=…` |

`create_api_key` writes the key and endpoint to `~/.captchakraken/credentials`
(mode 0600) and the driver reads that file by itself, so the MCP path needs **no
environment variables at all**. The key is never printed into the conversation.

## 2. Install

```bash
npm install captchakraken
```

The install runs a `postinstall` that creates a venv inside the package and
installs the bundled Python engine the driver shells out to. It needs a Python
3.10+ interpreter on `PATH`.

| Variable | Effect |
|---|---|
| `CAPTCHA_KRAKEN_SKIP_PYTHON_SETUP=1` | Skip the bootstrap (you will supply the engine yourself) |
| `CAPTCHA_KRAKEN_PYTHON=/path/to/python3` | Use this interpreter instead of probing `python3` then `python` |

## 3. Solve

```typescript
import { chromium } from 'playwright';
import { CaptchaKrakenSolver } from 'captchakraken';

const page = await (await (await chromium.launch()).newContext()).newPage();
await page.goto('https://www.google.com/recaptcha/api2/demo');

await new CaptchaKrakenSolver().solve(page);   // detect → solve → click → verify
```

Any Playwright-compatible launcher works with no adapter (`playwright`,
`patchright`, `camoufox-js`). Puppeteer needs one wrap:

```typescript
import { CaptchaKrakenSolver, fromPuppeteer } from 'captchakraken';
await new CaptchaKrakenSolver().solve(fromPuppeteer(page));
```

Do not know when a captcha will appear? Install the watcher instead of calling
`solve()`:

```typescript
const watcher = solver.watch(page);
// ... your automation ...
await watcher.stop();
```

Touch devices: `new CaptchaKrakenSolver({ humanization: 'mobile' })` emits real
touch events (needs `hasTouch` on the context, or an Appium/WebdriverIO driver
via `touchDriver`). `'none'` skips humanisation entirely.

## 4. Errors

`solve()` resolves to a `SolveResult` (`isSolved`), and throws when it cannot
drive the widget at all — no captcha on the page, a puzzle this build does not
handle, or the round budget exhausted. Only one error class is exported.

Refusals from the hosted API arrive as `CaptchaKrakenAPIError`. **Branch on
`e.code`, never on the message** — the codes are the contract, the wording is
not. `insufficient_credits`, `missing_api_key`, `invalid_api_key`,
`rate_limited`, `request_too_large`, `account_suspended` and
`upstream_unavailable` each name their own fix; `e.resolutionUrl` carries a link
where one exists. Retrying a `403` that means "no licence" will never succeed.

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
