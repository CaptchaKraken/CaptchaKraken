import { CaptchaKrakenSolver } from '../src/index';
import type { SolveResult } from '../src/types';
import { resolveLauncher, launchOptions, displayMode } from './launcher';

interface Site {
  id: string;
  vendor: string;
  what: string;
  url: string;

  settleMs?: number;

  open?: string[];

  ready?: string[];
}

const SITES: Site[] = [
  {
    id: 'geetest-slide',
    vendor: 'GeeTest v4',
    what: 'slide a piece into its notch',
    url: 'https://gt4.geetest.com/demov4/slide-popup-en.html',
    settleMs: 2200,
    open: ['.geetest_btn', '.geetest_btn_click', '.geetest_radar_btn', '.geetest_holder'],
    ready: ['.geetest_popup_box', '.geetest_popup_window', '.geetest_box', '.geetest_panel'],
  },
  {
    id: 'geetest-icon',
    vendor: 'GeeTest v4',
    what: 'click named icons in order',
    url: 'https://gt4.geetest.com/demov4/icon-popup-en.html',
    settleMs: 2200,
    open: ['.geetest_btn', '.geetest_btn_click', '.geetest_radar_btn', '.geetest_holder'],
    ready: ['.geetest_popup_box', '.geetest_popup_window', '.geetest_box', '.geetest_panel'],
  },
  {
    id: 'recaptcha',
    vendor: 'reCAPTCHA',
    what: 'tile grid, dealt until satisfied',
    url: process.env.RECAPTCHA_URL ?? 'https://www.google.com/recaptcha/api2/demo',
    settleMs: 3000,
  },
];

const fmtMs = (ms: number) => (ms >= 1000 ? `${(ms / 1000).toFixed(1)}s` : `${ms}ms`);

interface Outcome {
  site: Site;
  solved: boolean;

  totalMs: number;

  solveMs: number;
  tokensIn: number;
  tokensOut: number;
  note?: string;
}

function brief(note: string | undefined, width = 46): string {
  if (!note) return 'not solved';

  const first = note.split(/\.\s|\. Total usage|; /)[0].trim();
  return first.length > width ? first.slice(0, width - 1) + '…' : first;
}

function explain(err: unknown, result?: SolveResult | void): string {
  const msg = err instanceof Error ? err.message : err ? String(err) : '';
  const low = msg.toLowerCase();
  if (/econnrefused|fetch failed|connection refused|max retries/.test(low)) {
    return 'never reached the model — endpoint unreachable (check VLLM_BASE_URL)';
  }
  if (/401|403|unauthor|api key/.test(low)) return 'endpoint rejected the credential';
  if (/out of credits|too many times without settling/.test(low)) {
    return 'the vendor declined to serve a puzzle';
  }
  if (/timeout|exceeded/.test(low)) return 'the widget never became interactable';
  if (/no captcha|not find|unsupported/.test(low)) return 'no challenge appeared on the page';
  if (result && !result.isSolved) return 'answered, vendor did not accept';
  return msg || 'unknown';
}

async function reveal(page: any, site: Site): Promise<void> {
  for (const sel of site.open ?? []) {
    const el = await page.waitForSelector(sel, { state: 'visible', timeout: 8000 }).catch(() => null);
    if (!el) continue;
    const clicked = await el.click({ timeout: 4000 }).then(() => true).catch(() => false);
    if (!clicked) continue;
    for (const panel of site.ready ?? []) {
      const up = await page.waitForSelector(panel, { state: 'visible', timeout: 12_000 }).catch(() => null);
      if (up) return;
    }
    return;
  }
}

async function main(): Promise<void> {
  const argv = process.argv.slice(2);
  if (argv.includes('--list')) {
    for (const s of SITES) console.log(`  ${s.id.padEnd(16)} ${s.vendor.padEnd(12)} ${s.url}`);
    return;
  }
  const picked = argv.filter((a) => !a.startsWith('-'));
  const sites = picked.length ? SITES.filter((s) => picked.includes(s.id)) : SITES;
  if (!sites.length) {
    console.error(`no such site. Known: ${SITES.map((s) => s.id).join(', ')}`);
    process.exitCode = 2;
    return;
  }

  const { launch, from, name } = await resolveLauncher();
  const rule = '─'.repeat(66);
  console.log(`\n${rule}`);
  console.log('  CaptchaKraken — live solve');
  console.log(rule);
  console.log(`  browser   : ${name}  (${displayMode()})`);
  console.log(`  from      : ${from}`);
  console.log(`  endpoint  : ${process.env.VLLM_BASE_URL ?? 'http://127.0.0.1:8000/v1'}`);
  console.log(`  model     : ${process.env.CAPTCHA_LORA_NAME ?? process.env.MODEL ?? '(client default)'}`);
  console.log(`  sites     : ${sites.length}`);
  console.log(`${rule}\n`);

  const browser = await launch(launchOptions());
  const results: Outcome[] = [];
  const solver = new CaptchaKrakenSolver();

  try {
    for (const site of sites) {
      process.stdout.write(`  ${site.vendor} — ${site.what}\n    ${site.url}\n    solving… `);

      const context = await browser.newContext({ viewport: null });
      const t0 = Date.now();

      let s0 = t0;
      let solved = false;
      let note: string | undefined;
      let result: SolveResult | void = undefined;
      try {
        const page = await context.newPage();
        await page.goto(site.url, { waitUntil: 'domcontentloaded', timeout: 60_000 });
        await page.waitForTimeout(site.settleMs ?? 2500);
        if (site.open) await reveal(page, site);
        s0 = Date.now();
        result = await solver.solve(page);
        solved = !!result && result.isSolved;
        if (!solved) note = explain(undefined, result);
      } catch (err) {
        note = explain(err);
      } finally {
        await context.close().catch(() => {});
      }
      const totalMs = Date.now() - t0;
      const solveMs = Date.now() - s0;
      const out = result ? result.tokenUsage.outputTokens : 0;
      const inp = result ? result.tokenUsage.inputTokens : 0;
      console.log(
        solved
          ? `\x1b[32m✓ solved\x1b[0m in ${fmtMs(solveMs)}  (page open to done: ${fmtMs(totalMs)} · ${inp} in / ${out} out)\n`
          : `\x1b[31m✗ ${note}\x1b[0m  after ${fmtMs(solveMs)}\n`,
      );
      results.push({ site, solved, totalMs, solveMs, tokensIn: inp, tokensOut: out, note });
    }
  } finally {
    await browser.close().catch(() => {});
  }

  const ok = results.filter((r) => r.solved);
  console.log(rule);
  console.log(`  ${'vendor'.padEnd(13)} ${'puzzle'.padEnd(30)} ${'solve'.padStart(7)} ${'total'.padStart(7)}   result`);
  console.log(rule);
  for (const r of results) {
    console.log(
      `  ${r.site.vendor.padEnd(13)} ${r.site.what.slice(0, 30).padEnd(30)} ` +
        `${fmtMs(r.solveMs).padStart(7)} ${fmtMs(r.totalMs).padStart(7)}   ` +
        `${r.solved ? '\x1b[32m✓\x1b[0m solved' : `\x1b[31m✗\x1b[0m ${brief(r.note)}`}`,
    );
  }
  console.log(rule);
  const median = ok.length
    ? [...ok.map((r) => r.solveMs)].sort((a, b) => a - b)[Math.floor(ok.length / 2)]
    : 0;
  console.log(
    `  ${ok.length}/${results.length} solved` +
      (ok.length ? `   median solve ${fmtMs(median)}` : ''),
  );
  console.log(`${rule}\n`);
  process.exitCode = ok.length === results.length ? 0 : 1;
}

main().catch((err) => {
  console.error(`\n${err instanceof Error ? err.message : err}\n`);
  process.exitCode = 1;
});
