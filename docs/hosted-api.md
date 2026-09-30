# ☁️ Hosted API

Send screenshots to `https://api.captchakraken.com/v1`. No GPU, no model
download, no server to run.

The hosted API answers the current client with **Abyss** — trained against the
failures of the open weights, and routed across four specialist adapters on the
same Qwen3.5-9B base as Twilight and Sunlight. It is hosted-only: the weights are
not published and there is nothing to download. Every hosted account gets it;
the client names an expert on each request and there is nothing to hold or buy
first.

An older client, or a request that names no model, is answered by **Twilight
v1.2**, running on the same fleet — the same weights we publish, merged from the
same LoRA on the same base — because its prompts belong to that generation.
Never a silent substitution the other way.

The client code is identical to the self-hosted path. Only the endpoint changes.

## Sign in without touching a key

The easiest setup. The account MCP server signs you in and writes the key
straight to disk, so **you set no environment variables** and the key never
appears in your terminal or in an AI agent's transcript.

```bash
claude mcp add captchakraken -- npx -y captchakraken-mcp
```

Then, from your MCP client:

1. Call **`sign_in`**. It prints a link and a short code. Open the link, approve
   with GitHub. New accounts are created on the spot with free trial credits.
2. Call **`create_api_key`**.

`create_api_key` writes the key and the endpoint to `~/.captchakraken/credentials`
(mode 0600). The solver reads that file by itself.

Check it worked:

```bash
captchakraken server status     # should show api.captchakraken.com, local: false
```

### The other MCP tools

| Tool | What it does |
|---|---|
| `get_account` | Who is signed in, the balance, and the endpoint |
| `get_balance` | The balance, and nothing else |
| `get_usage` | Billable responses and credits, per day and in total |
| `get_pricing` | The current rate card |
| `get_models` | The model lineup, so you can decide whether to self-host |
| `list_api_keys` | Your solving keys, masked |
| `revoke_api_key` | Kills one by id, effective within ~30 seconds |
| `get_topup_link` | A Stripe URL for you to open. Charges nothing by itself |
| `sign_out` | Revokes this client's token and deletes it from disk |

**Two credentials, two blast radii.** The `ckm_…` token the MCP server holds
manages the account and cannot solve a captcha. The `ck_live_…` key solves
captchas and cannot manage the account. A key leaked from a scraper cannot mint
its own replacements, and your balance stays a hard bound on the damage.

## Sign in by hand

If you'd rather not use MCP: sign in at
[captchakraken.com/signin](https://captchakraken.com/signin), copy your
`ck_live_…` key, and set two variables.

```bash
export VLLM_BASE_URL=https://api.captchakraken.com/v1
export CAPTCHA_KRAKEN_API_KEY=ck_live_your_key_here
```

These override the credentials file, so you can keep both and switch by
exporting or unsetting.

## Then solve

Nothing here is hosted-specific — this is the same code as every other setup.

```bash
npm install captchakraken        # or: pip install captchakraken
```

```typescript
import { CaptchaKrakenSolver } from 'captchakraken';
await new CaptchaKrakenSolver().solve(page);
```

Full examples for every browser framework are in [Usage](./usage.md).

## Pricing

| What | Credits per response | Price |
|---|---|---|
| reCAPTCHA checkbox, Cloudflare Turnstile | 0 | **Free** |
| Image response — grids, click, drag | 3 | $0.30 per 1,000 |
| Video response | 10 | $1.00 per 1,000 |

10,000 credits = $1.00. Credit packs are $10, $25, and $100.

**You are billed per model response, not per captcha.** One captcha usually
takes 1–2 responses. reCAPTCHA 3×3 replaces tiles after each click and every
replacement is a fresh puzzle, so a hard one takes more.

**One solve attempt is capped at 5 billable responses**, so a captcha that
refuses to clear cannot run up an unbounded bill. Anything past the cap is still
solved, just not charged.

### How the cap works

The cap counts responses inside one **session**. The driver mints a session id
per `solve()` call and sends it as an `X-CK-Session` header on every round of
that solve. Both the TypeScript and Python drivers do this for you.

If you write your own HTTP client, set `CAPTCHA_KRAKEN_SESSION` to one value per
captcha — or send the header yourself. Without it, every round is a separate
session and every round is billed.

### Outcome reports

When a solve ends, the driver tells the hosted API whether the captcha was
accepted: `POST /v1/solve-outcome` with `{"session": "<id>", "solved": true}`.
The answer is the vendor's own verdict where its answer-check response is
readable, and the page's done-signal otherwise. Hosted requests also carry
`X-CK-Vendor` (which captcha vendor) and `X-CK-Site` (the page's hostname —
never its path or query). A failed report never changes the solve's result; it
is logged as a warning. Set `CAPTCHA_REPORT_OUTCOME=0` to send none.

## Errors

Refusals arrive as `CaptchaKrakenAPIError` with a machine-readable `code`.
**Branch on the code, never on the message text** — wording changes, codes are
the contract.

```typescript
import { CaptchaKrakenAPIError } from 'captchakraken';
```

```python
from captchakraken import CaptchaKrakenAPIError
```

| `code` | Meaning | What to do |
|---|---|---|
| `insufficient_credits` | Balance is empty | Top up — MCP `get_topup_link`, or the dashboard |
| `missing_api_key` / `invalid_api_key` | Key missing or rejected | Run `create_api_key` |
| `rate_limited` | Too many requests | Back off; honour `retry_after_seconds` |
| `request_too_large` | Screenshot too big | Capture the captcha element, not the whole page |
| `account_suspended` | Solving is disabled | Contact support |
| `upstream_unavailable` | Our fleet is unreachable | Retry shortly — this is on our side |

Every error carries a `resolution_url` pointing at the page that fixes it.

Codes are added over time. An unrecognised one still produces a useful message,
because the server's own text is carried through rather than replaced.

## Common problems

| Symptom | Cause | Fix |
|---|---|---|
| `Connection refused` on `localhost:8000` | You set a key but no endpoint | Set `VLLM_BASE_URL`, or run `create_api_key`, which writes both |
| vLLM tries to start on your machine | Your endpoint is still localhost | Same as above |
| `401` right after signing in | Signed in against a different deployment | Check `CAPTCHAKRAKEN_BASE_URL`, then `sign_in` again |

## Privacy

Screenshots you send are processed by our gateway and the model fleet. If that
is not acceptable for your use case, [self-host](./self-hosting.md) — the open
weights run entirely on your hardware and nothing leaves your machine.

---

← Back to [docs index](./README.md)
