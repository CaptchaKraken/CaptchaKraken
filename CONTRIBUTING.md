# Contributing to CaptchaKraken

Thanks for your interest! Contributions are welcome — bug fixes, better grid
detection, solver robustness, docs, and especially **real labeled samples** for
the puzzle types we're still weak on.

By contributing you agree that your contributions are licensed under the
repository's [LICENSE](LICENSE) (the CaptchaKraken Source-Available License).

**This file is the one to read before changing this code — agent or human.**
[AGENTS.md](AGENTS.md) is the product's own documentation, written for people
*using* CaptchaKraken; it is not the contributor guide.

---

# General rules

The same in every repository we maintain. A repo may add a constraint below,
never relax one.

## Before you touch anything

1. **Is this repo public or private?** If public, the Professionalism rules
   below govern every line, commit, and PR title you write.
2. **Read `TRIBAL_KNOWLEDGE.md`** — the decisions made here and why.
3. **Branch off `dev`.** Never commit to `main`, never push to `main`.

## Before you write a function

Grep `repomix-output.md` for likely names, then check `FILE_PURPOSES.md` for
where that behavior belongs. Write new code only after confirming nothing
comparable exists; if something close exists, extend it rather than fork it.
Duplicated logic is a serious defect. `npm run repomix` rebuilds the map (~2s)
if it is stale.

Update `FILE_PURPOSES.md` when you add or delete a tracked file — CI fails on a
missing entry and on a stale one. It covers `git ls-files` and nothing else:
never add an entry for build output, `node_modules/`, a virtualenv, a log, or
anything else gitignored.

## Professionalism (public repos)

**IMPORTANT: a public repository is a FINISHED PRODUCT.** Customers, investors,
and candidates judge the business by what is in it, and they do not ask what a
file was for.

- **No garbage, ever.** No scratch files, `tmp/`, diagnostic scripts, saved test
  output, logs, debug logging, commented-out code, dead code, placeholder text,
  stub docs, or `TODO`s left as a note to self.
- **Nothing from a private repo** reaches a public one — not in code, comments,
  commits, PRs, issues, or branch names. No proprietary results or metrics.
- **Experiments live in `src/experiments/`, gitignored.** That is the only place
  unfinished work may exist here.
- Commits and PR titles are written for a stranger reading them in a year.
- **IMPORTANT: documentation is never stale here.** The first thing a stranger
  does is run the first README snippet. If it fails, that is the product.

## Code

- **Less code.** More code is a cost, not an achievement. Minimal, general
  changes; delete dead code when you find it.
- **No band-aids.** Fix the main flow. A hard-coded value or a patch at the call
  site is a bug relocated, not fixed.
- **Fallbacks are a desperate measure.** They turn a loud failure into a silent
  wrong answer and hide the real defect. Fail loudly instead.
- **Read the provider's docs** before writing against a third-party API. Never
  infer an endpoint, field, or rate limit from memory.
- **Run independent work concurrently.** N queries that do not depend on each
  other go through one `Promise.all()`, never an `await` in a loop; a loop
  that awaits one query per iteration is a bug, not a style.
- **Strong typing, always.** Closed sets are enums, tables are typed records
  keyed by those enums, and a shape is an interface or a frozen dataclass —
  never `Record<string, any>`, `Dict[str, Any]` or a bare tuple. The type
  checker is the first reviewer.
- **Functional over imperative.** Prefer `map`/`filter`/`flatMap`/`find` and
  comprehensions to hand-rolled loops, accumulators and early-return ladders.
  A `for` loop that builds an array, or a chain of `if (x) return x` over a
  list, should be one expression.
- **Comments say why, in a sentence or two.** Simple code needs none. Anything
  longer is a decision — put it in `TRIBAL_KNOWLEDGE.md`.
- **Docs ship with the code that changed them.** Update the README and `docs/`
  in the same PR — never "later". Every snippet must run as written, and every
  snippet needs a test proving it does.

## Tests

- **Run the failing test, not the suite.** CI runs the full suite on every PR.
- **Write test output to a log file and grep the file.** Piping a run into
  `grep` throws away output you will need and forces a second run. Delete the
  log afterward.
- **Every bug gets a regression test, in this order:** reproduce it with a test
  that you verify fails → fix → verify it passes → land it in CI.
- **No flakes.** An intermittent failure means the code is non-deterministic.
  Fix the behavior. Never retry, loosen, or skip.
- **Never write a test just to pass, or code just to pass a test.**

## Security

- **Never commit a credential** — not in code, config, fixtures, logs, or commit
  messages. Secrets live in the managed store; `.env` is local only, and only
  once you have verified it is gitignored.
- **Least privilege.** No wildcard permissions, no admin role where a scoped one
  works, no write scope on a read-only credential.
- **No `0.0.0.0/0`.** Internal and admin endpoints are IP-allowlisted before
  authentication.
- **Dependencies are pinned exactly** and never auto-upgraded. Adding one is a
  decision worth recording.

## Working with the user

- Say when the direction is wrong, before starting, with the reason.
- Review your own code the way a strict senior manager would. You are biased
  toward what you just wrote.
- Explain plainly and briefly. The user is technical; short beats complete.

## Parallel work

Separate PRs → one agent per task, each in its own worktree, at the same time.
One PR, independent slow parts → subagents in worktrees, merge each into your
branch as it finishes, then delete the worktrees. Shared files or ordering
requirements → one agent.

---

# This repository

## Ground rules

- **The model is Qwen3.5-9B.** Never reference Qwen2 / Qwen2.5 / Qwen-VL anywhere;
  grep before any change that touches serving or the planner.
- **`find_grid` is the foundation.** It's pure OpenCV (no model) and the most
  heavily gated code here: every geometry gate in
  `python/tests/test_grid_geometry_gates.py` exists because one specific false
  positive happened. Read the test named for a gate before you change it.
- **Locators, never `page.$()` / `page.$$()` / `query_selector()`.** The
  driver reads the page through `scope.locator(sel).filter({ visible: true })`
  (`filter(visible=True)` in Python), `.all()`, `.count()` and
  `.elementHandle()`; the structural `Page` type in `js/src/playwright-types.ts`
  deliberately has no `$`. Query every selector of a pass at once (see the
  `visible()` helper in `solver.ts`), not one after another.
- **Every selector lives in `js/src/selectors.ts` and
  `python/src/captchakraken/selectors.py`.** They are one typed table,
  `SELECTORS: Record<Vendor, VendorSelectors>`, with a row per vendor: hosts,
  challenge and checkbox iframes, inline widget shapes, response field,
  accepted and checked markers, submit controls, text inputs, slider handles,
  pieces. Import from it; never write a selector string in the driver. Adding
  a vendor is adding a row, and the two files stay in the same order because
  table order is detection order.
- **General first, vendor second.** There are only a few puzzle types — drag,
  grid selection, text, clicking, slider, grid fading, grid boundary (the 4×4
  reCAPTCHA) and video clicking — and the model handles the divergence between
  vendors; the driver's job is to photograph the board, send it, and perform
  the answer. Write the general flow, then express what a vendor needs as a
  field in its `SELECTORS` row. Code that runs for exactly one vendor is the
  last resort, needs a why-comment, and is the first thing a reviewer asks to
  remove.
- **The two ports must agree.** `contract.json` records the public surface of
  both, and `js/src/contract.test.ts` plus `python/tests/test_public_contract.py`
  fail on a new divergence. After an intended change, regenerate it with
  `CONTRACT_WRITE=1 npm test` in `js/` and commit the diff.
- **`FILE_PURPOSES.md` is the map of this repo**, and `TRIBAL_KNOWLEDGE.md` is
  why it looks like this. Adding or deleting a tracked file means editing
  `FILE_PURPOSES.md` in the same commit — CI checks both directions and fails
  before it runs a single test.
- **Grep `repomix-output.md` before you write a helper.** It is a
  comment-stripped signature map of all three ports, gitignored and rebuilt in
  under a second:

  ```bash
  npm install          # once, at the repo root — tooling only, see below
  npm run repomix      # writes repomix-output.md
  grep -nE "function foo|const foo =|def foo" repomix-output.md
  ```

  The map tool wants **Node 22+** while the packages and CI run Node 20; that
  is deliberate and the root manifest declares it. The only versions of repomix
  that run on Node 20 carry an unpatched command-injection advisory, and a
  contributor tool is not worth an RCE.

## Dev setup

One repo, two published ports plus an account server: `js/` (TypeScript browser
driver → npm `captchakraken`), `python/` (the engine and `captchakraken` CLI →
PyPI), and `mcp/` (→ npm `captchakraken-mcp`).

```bash
git clone git@github.com:CaptchaKraken/CaptchaKraken.git
cd CaptchaKraken

# Repo tooling: repomix and the codebase-map gate. NOT a published package —
# the root package.json is `private: true` and exists only so these two have
# somewhere to live that is not one of the three shipped manifests.
npm install

# TypeScript port
cd js && npm install && npm run build && cd ..

# Python port
cd python && pip install -e ".[dev]" && cd ..

# Account MCP server
cd mcp && npm install && npm run build && cd ..
```

Every dependency in all four manifests is pinned to an exact version, and CI
installs from the lockfiles with `npm ci`. Changing a version is a reviewed
change, never a side effect of installing.

**A Python pin has to install on 3.11**, which is what `requires-python`
promises — not merely on whatever interpreter you have. Resolve against the
floor before changing one:

```bash
uv venv --python 3.11 /tmp/ck311 && VIRTUAL_ENV=/tmp/ck311 uv pip install -e "python[dev]"
```

The `js` package ships **no browser** — it types its public API against an
implementation-neutral Playwright `Page`, and you bring your own
Playwright-compatible launcher (vanilla `playwright`, `patchright`,
`camoufox-js`, …). Install whichever one you want before driving a real solve.

To run a solver against a model you'll need a vLLM server — see
[`setup.sh`](setup.sh) and [docs/self-hosting.md](docs/self-hosting.md).

## Tests & CI

Three gates run on every PR, into `dev` and into `main` alike, cheapest first.

**1. The codebase map**, in seconds, before anything is installed:
`FILE_PURPOSES.md` must match `git ls-files` exactly, in both directions. Run it
yourself with `npm run file-map` at the repo root. Nothing else starts until it
passes, because a missing entry is one line to add and there is no reason to
spend a test run discovering it.

**2. A hermetic suite** (no GPU, no network, no weights) — everything you can
run locally:

```bash
# Python: the whole suite, on 3.11 and 3.12 in CI
cd python && python -m pytest -q

# TypeScript driver: type-check, then the node:test suite
cd js
node scripts/copy-python.mjs      # bundles the engine the driver shells out to
npx tsc --noEmit -p tsconfig.json
npm test

# MCP server: type-check, build, and prove it answers a handshake
cd mcp
npx tsc --noEmit -p tsconfig.json && npm run build
node ../.github/scripts/mcp-smoke.mjs node dist/index.js
```

Coverage comes off those same runs, and the floor is enforced locally exactly as
CI enforces it:

```bash
cd python && python -m pytest -q --cov      # floor in pyproject.toml
cd js && npm run coverage                   # floor in .c8rc.json
```

Both floors are set at what the suites measure today, not at a number we would
like: a gate that is red the day it lands teaches people to route around it. They
go up, never down. `mcp/` has no test suite — its checks are a type-check, a
build and an MCP handshake — so it has no coverage floor and no coverage number.

**3. A driver gate.** Both shipped ports are driven end to end through a real
browser against a fixture suite, and the result comes back as the
`tier3/driver-gate` commit status plus a PR comment with per-port and
per-vendor pass rates. The fixtures, generators and adapter are not in this
repo, so [`.github/workflows/tier3-request.yml`](.github/workflows/tier3-request.yml)
asks the repo that holds them to run the gate and post a redacted result back —
you cannot run it locally, and you do not need to. It is the gate that catches
what a type-check cannot: a selector that moved, a click landing off-widget, or
one port asking for something the other does not.

This repo has **no browser tests of its own** — it never launches a browser, and
it ships none.

If you add a tracked file, add its `FILE_PURPOSES.md` row in the same commit; if
you add a dependency, pin it exactly and say in the PR why it is worth a
permanent supply-chain surface.

> On a **fork PR** the driver gate cannot run: GitHub does not expose the
> dispatch secret to a fork's workflow, so the check sits as pending. That is
> expected. A maintainer re-runs it by pushing your branch into this repo.

## Pull requests

- **Open your PR against `dev`.** `main` is the release branch and only ever
  takes a `dev` → `main` merge — `.github/workflows/promote.yml` fails any PR
  into `main` from anywhere else, because a push to `main` publishes both ports
  to npm and PyPI and a published version can never be reused.
- Keep PRs focused, and describe what you changed and how you verified it.
- New end-to-end solving capability? Say which vendor and puzzle it covers and
  how you drove it. The driver gate above will exercise it; you do not need to
  produce your own recording.
- Bumping a published version means bumping `python/pyproject.toml`,
  `js/package.json` and `python/src/captchakraken/__init__.py` in the same
  commit. `test_the_version_is_one_number_everywhere` in
  `python/tests/test_public_contract.py` fails on any drift between the three.

## What we'd love help with

- More **real labeled samples** for under-represented grid prompts.
- Robustness on **reCAPTCHA 4×4** (our weakest grid type end-to-end).
- Accuracy on the **freehand drag/path puzzles** — connect-the-path, the
  numbered-line and missing-piece drags. Every puzzle family now routes and is
  driven; these are the ones where the model is least reliable.
- Smaller / faster quantizations so lower-VRAM hardware can self-host.

Questions? Open an issue. Please don't open PRs that add a paid captcha-solving
API or thin wrapper — those are outside what the license permits (see
[LICENSE](LICENSE) §3).
