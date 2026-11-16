// An unchanged board keeps its hash: the verdict toast a widget shows after a miss is not part of the board.
//
// The board's identity was the sha1 of its whole photograph, toast included. On an hCaptcha-style line board the
// "Please try again" toast is up for 2.2s after a wrong answer, so whether a round's shot caught it was down to timing:
// one unchanged board read 5fe699bd, 80c5b1fd, 80c5b1fd, 5fe699bd over four rounds. The new hash in round 2 let the
// same wrong answer be pressed again, and the change back in round 4 threw away three armed fallback plans. The
// Python test of the same name drives the same cases.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import crypto from 'node:crypto';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

import { CaptchaKrakenSolver } from './solver';
import { DEFAULT_TABLE } from './selectors';

function optional(name: string): any | null {
  try {
    return require(name);
  } catch {
    return null;
  }
}

const playwright = optional('playwright');

// The widget as a test fixture draws it: a board, and a toast pinned to its bottom edge that fades in after a miss.
const WIDGET =
  '<div id="widget" style="position:relative;width:240px;height:240px;background:#8ac">' +
  '<div style="position:absolute;left:40px;top:40px;width:60px;height:60px;background:#c84"></div>' +
  '<div id="ck-toast" style="position:absolute;left:0;right:0;bottom:0;z-index:9999;padding:8px;' +
  'background:#d33;color:#fff;font:14px sans-serif;display:none">Please try again</div></div>';

/** A page whose widget photographs itself with the toast drawn unless the capture's stylesheet hides it. */
function fakeWidget(toastShown: () => boolean): { page: any; el: any } {
  const page = {
    viewportSize: () => ({ width: 800, height: 600 }),
    // Wider than the viewport: the element is photographed by itself, so no viewport capture needs cropping.
    evaluate: async () => ({ width: 1200, scale: 1 }),
  };
  const el = {
    screenshot: async ({ path: p, style }: { path: string; style?: string }) => {
      const hidden = (style ?? '').includes('[id*="toast" i] { display: none !important; }');
      fs.writeFileSync(p, toastShown() && !hidden ? 'board with a toast' : 'board');
    },
  };
  return { page, el };
}

test('the board reads the same hash with and without its verdict toast', async () => {
  let toast = false;
  const { page, el } = fakeWidget(() => toast);
  const solver: any = new CaptchaKrakenSolver();
  solver.page = page;

  const before = await solver.boardHash(el);
  toast = true;
  const during = await solver.boardHash(el);
  toast = false;
  assert.equal(during, before, 'the toast changed the board\'s identity');
  assert.equal(await solver.boardHash(el), before);
});

test('every vendor\'s own verdict banner is left out of the identity too', () => {
  for (const [vendor, s] of DEFAULT_TABLE.vendors) {
    for (const [selector] of s.banners ?? []) {
      assert.ok(DEFAULT_TABLE.feedback.includes(selector), `${vendor}'s banner ${selector} is part of the board's identity`);
    }
  }
});

test('in a browser, an unchanged board keeps its hash while the toast comes and goes', { skip: !playwright && 'playwright not installed' }, async (t) => {
  const cache = path.join(os.homedir(), '.cache', 'ms-playwright');
  const cached = (fs.existsSync(cache) ? fs.readdirSync(cache) : []).filter((d) => d.startsWith('chromium-')).sort().reverse()
    .map((d) => path.join(cache, d, 'chrome-linux64', 'chrome')).filter((exe) => fs.existsSync(exe));
  let browser: any = null;
  const failures: string[] = [];
  for (const executablePath of [undefined, ...cached]) {
    try {
      browser = await playwright.chromium.launch({ headless: true, executablePath, args: ['--no-sandbox', '--disable-dev-shm-usage'] });
      break;
    } catch (err) {
      failures.push(String(err).split('\n')[0]);
    }
  }
  if (!browser) {
    t.skip(`no chromium: ${failures.join('; ')}`);
    return;
  }
  try {
    const page = await browser.newPage();
    await page.setContent(WIDGET);
    const solver: any = new CaptchaKrakenSolver();
    solver.page = page;
    const widget = await page.$('#widget');
    const toast = (shown: boolean) => page.evaluate((s: boolean) => { document.getElementById('ck-toast')!.style.display = s ? 'block' : 'none'; }, shown);

    const photo = async (): Promise<string> => {
      const p = path.join(os.tmpdir(), `ck-toast-${process.pid}.png`);
      try {
        await solver.shot(widget, p);
        return crypto.createHash('sha1').update(fs.readFileSync(p)).digest('hex');
      } finally {
        fs.rmSync(p, { force: true });
      }
    };

    const before = await solver.boardHash(widget);
    const plain = await photo();
    await toast(true);
    assert.equal(await solver.boardHash(widget), before, 'the toast changed the board\'s identity');
    // Only the identity leaves the toast out: the photograph the model reads still shows it.
    assert.notEqual(await photo(), plain, 'the toast never reached the photograph, so this test proves nothing');
    await toast(false);
    assert.equal(await solver.boardHash(widget), before);
  } finally {
    await browser.close();
  }
});
