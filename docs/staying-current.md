# 🔄 Staying current

The client, the hosted API and the served model move together. A client that
stays on an old version keeps solving with old detection logic and asks for a
model generation the server may have retired. Install `captchakraken` so that
every deploy picks up the current release.

## The trap: `"latest"` plus a lockfile that persists

Depending on `"captchakraken": "latest"`, directly or through a package that
pulls it in as an optional dependency, is **not enough**. When a
`package-lock.json` exists, `npm install` keeps the version it already locked,
even when that version no longer matches the tag. Only `npm update` re-resolves
it:

| Starting point | `npm install` | `npm update captchakraken` |
|---|---|---|
| No lockfile | current release | current release |
| Lockfile pinned to 2.6.1 (direct dep) | **stays 2.6.1** | current release |
| Lockfile pinned to 2.6.1 (nested optional dep) | **stays 2.6.1** | current release |

This bites long-lived deploy directories. When the lockfile is gitignored and
the deploy runs `git pull && npm install`, the file survives every deploy, so
the server stays on whatever version it first installed. CI usually checks out
clean and installs fresh, so **CI passes on a version production never runs.**

### Fix

Re-resolve the solver after the install step of every deploy:

```bash
npm install
npm update captchakraken
```

`npm update` moves only this package. The rest of the tree keeps its locked
versions.

## Telling which version is actually running

Don't trust `package.json` or CI. Read the server's own error text:

| Message | Version |
|---|---|
| `No interactive captcha widget detected (likely reCAPTCHA v3 / invisible or a click-triggered challenge). Failing fast.` | **2.x** (stale) |
| `No interactive captcha widget detected (no vendor captcha code loaded on this page — …)` | 3.x |
| `No interactive captcha widget detected, BUT <vendor> code IS loaded and running on this page. …` | 3.x; the vendor's markup no longer matches `SELECTORS` |

If you see the 2.x message, apply the fix above and redeploy.
