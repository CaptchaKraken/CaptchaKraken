// Waits on a count rather than a fixed sleep: the sleep flaked under node --test parallelism.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

import { fromPuppeteer } from './puppeteer-adapter';
import { watchPage } from './watcher';
import { PlaywrightPage } from './playwright-types';
import { CaptchaKrakenSolver } from './solver';

function optional(name: string): any | null {
  try {
    return require(name);
  } catch {
    return null;
  }
}

const puppeteer = optional('puppeteer');
const playwright = optional('playwright');
const LAUNCH_ARGS = ['--no-sandbox', '--disable-dev-shm-usage'];

const HTML =
  '<body style="height:3000px">' +
  '<div id="target" data-vendor="recaptcha">hello captcha</div>' +
  '<div id="hidden" style="display:none">nope</div>' +
  '<input id="field" value="typed" />' +
  '<iframe id="frame" srcdoc="<div id=\'inner\'>inner text</div>"></iframe>' +
  '</body>';

async function exerciseSurface(page: PlaywrightPage): Promise<void> {
  assert.deepEqual(page.viewportSize(), { width: 1280, height: 720 }, 'viewportSize');

  const target = await page.locator('#target').elementHandle();
  assert.ok(target, 'locator().elementHandle() returned nothing');
  assert.equal(await target!.getAttribute('data-vendor'), 'recaptcha', 'getAttribute');
  assert.equal((await target!.textContent())?.trim(), 'hello captcha', 'textContent');
  assert.equal(await target!.isVisible(), true, 'isVisible (visible element)');
  assert.ok((await target!.boundingBox())!.width > 0, 'boundingBox');
  await target!.scrollIntoViewIfNeeded();
  assert.ok((await target!.screenshot()).length > 0, 'element screenshot');
  assert.ok((await page.screenshot({ timeout: 5000, animations: 'disabled' })).length > 0, 'viewport screenshot');

  const hidden = await page.locator('#hidden').elementHandle();
  assert.equal(await hidden!.isVisible(), false, 'isVisible (display:none)');

  assert.equal(await page.locator('div').count(), 2, 'count');
  assert.equal((await page.locator('div').all()).length, 2, 'all');
  assert.equal((await page.locator('div').filter({ visible: true }).all()).length, 1, 'filter({visible:true})');
  assert.equal(await page.locator('body').locator('#target').count(), 1, 'nested locator');
  assert.equal(await page.locator('#missing').filter({ visible: true }).count(), 0, 'an absent selector counts zero, without waiting');
  assert.ok(await page.waitForSelector('#target', { state: 'visible', timeout: 5000 }), 'waitForSelector {state:visible}');
  assert.equal(await target!.evaluate((el) => el.id), 'target', 'handle.evaluate');
  assert.equal(await (await page.locator('#field').elementHandle())!.inputValue(), 'typed', 'inputValue reads the live value');

  const started = Date.now();
  await page.waitForTimeout(50);
  assert.ok(Date.now() - started >= 45, 'waitForTimeout returned early');

  const frame = await (await page.locator('#frame').elementHandle())!.contentFrame();
  assert.ok(frame, 'contentFrame');
  assert.equal(await frame!.locator('#inner').count(), 1, 'frame.locator');
  assert.ok(await frame!.waitForSelector('#inner', { state: 'visible', timeout: 5000 }), 'frame.waitForSelector');

  await frame!.waitForFunction((sel: any) => !!document.querySelector(sel), '#inner', { timeout: 5000 });

  await page.mouse.move(100, 100, { steps: 4 });
  await page.mouse.down({ button: 'left' });
  await page.mouse.up({ button: 'left' });

  await page.keyboard.type('abc', { delay: 1 });
  await page.keyboard.press('Control+A');
  await page.keyboard.press('Backspace');

  assert.equal(page.isClosed!(), false, 'isClosed on an open page');
}

test('vanilla Playwright satisfies the solver surface with no adapter', { skip: !playwright && 'playwright not installed' }, async () => {
  const browser = await playwright.chromium.launch({ headless: true, args: LAUNCH_ARGS });
  try {
    const context = await browser.newContext({ viewport: { width: 1280, height: 720 } });
    const page = await context.newPage();
    await page.setContent(HTML);
    await page.focus('#field');
    await exerciseSurface(page as unknown as PlaywrightPage);
  } finally {
    await browser.close();
  }
});

test('Puppeteer satisfies it through fromPuppeteer()', { skip: !puppeteer && 'puppeteer not installed' }, async () => {
  const browser = await puppeteer.launch({ headless: true, args: LAUNCH_ARGS });
  try {
    const raw = await browser.newPage();
    await raw.setViewport({ width: 1280, height: 720 });
    await raw.setContent(HTML);
    await raw.focus('#field');

    const page = fromPuppeteer(raw);
    await exerciseSurface(page);

    await browser.close();
    assert.equal(page.isClosed!(), true, 'isClosed did not follow the real page shut');
  } finally {
    if (browser.connected) await browser.close();
  }
});

test('the watcher solves a captcha that appears after it is installed', { skip: !playwright && 'playwright not installed' }, async () => {
  const browser = await playwright.chromium.launch({ headless: true, args: LAUNCH_ARGS });
  try {
    const page = await browser.newPage();
    await page.setContent('<body></body>');

    let solves = 0;
    const solver = {
      async detectCaptcha(p: any) { return (await p.locator('#late-captcha').count()) > 0 ? {} : null; },
      async solve(p: any) {
        await p.locator('#late-captcha').evaluate((el: any) => el.remove());
        solves += 1;
        return { isSolved: true } as any;
      },
    };

    const watcher = watchPage(solver, page as unknown as PlaywrightPage, { intervalMs: 25 });
    await page.evaluate(() => {
      setTimeout(() => {
        const el = document.createElement('div');
        el.id = 'late-captcha';
        document.body.appendChild(el);
      }, 100);
    });

    await new Promise((r) => setTimeout(r, 700));
    await watcher.stop();

    assert.equal(solves, 1, 'the captcha was solved ' + solves + ' times, expected exactly once');
    assert.equal(watcher.running, false);
  } finally {
    await browser.close();
  }
});

test('one watcher covers every navigation on the page', { skip: !playwright && 'playwright not installed' }, async () => {
  const browser = await playwright.chromium.launch({ headless: true, args: LAUNCH_ARGS });
  try {
    const page = await browser.newPage();
    let solves = 0;
    const solver = {
      async detectCaptcha(p: any) { return (await p.locator('#c').count()) > 0 ? {} : null; },
      async solve(p: any) {
        await p.locator('#c').evaluate((el: any) => el.remove());
        solves += 1;
        return { isSolved: true } as any;
      },
    };

    const until = async (want: number, why: string) => {
      const deadline = Date.now() + 15_000;
      while (solves < want && Date.now() < deadline) await new Promise((r) => setTimeout(r, 25));
      assert.equal(solves, want, why);
    };

    const watcher = watchPage(solver, page as unknown as PlaywrightPage, { intervalMs: 25 });

    await page.goto('data:text/html,<body>one</body>');
    await page.goto('data:text/html,<body>two</body>');
    await new Promise((r) => setTimeout(r, 500));
    assert.equal(solves, 0, 'solved something on a page with no captcha');

    await page.goto('data:text/html,<body><div id="c"></div>three</body>');
    await until(1, 'the watcher did not survive navigation');

    await page.goto('data:text/html,<body><div id="c"></div>four</body>');
    await until(2, 'the watcher stopped arming after its first solve');

    await watcher.stop();
  } finally {
    await browser.close();
  }
});

const CAPTURE_FIXTURE =
  '<body style="margin:0;height:2400px;background:#fafafa;font:14px sans-serif">' +
  '<div id="board" style="position:absolute;left:37.5px;top:61.25px;width:301.3px;height:151.6px;border:3px solid #222;' +
  'background:linear-gradient(90deg,#c33,#3c3 40%,#33c)">a still board</div>' +
  '<iframe id="framed" style="position:absolute;left:420px;top:40px;width:260px;height:180px;border:1px solid #888" ' +
  'srcdoc="<body style=\'margin:0;background:#fe9\'><div style=\'margin:20px;width:90px;height:60px;background:#069\'></div>framed</body>"></iframe>' +
  '<div id="below" style="position:absolute;left:50px;top:1500px;width:200px;height:120px;background:#9c6">below the fold</div>' +
  '</body>';

for (const dpr of [1, 2]) {
  test(`the viewport crop is what an element screenshot shows (dpr ${dpr})`, { skip: !playwright && 'playwright not installed' }, async () => {
    // The model-facing picture did not change when the capture did: same rect, same scale, same pixels. Compared
    // decoded, through the page itself, because the two PNG encoders are free to differ byte for byte.
    const browser = await playwright.chromium.launch({ headless: true, args: LAUNCH_ARGS });
    try {
      const page = await (await browser.newContext({ viewport: { width: 1280, height: 720 }, deviceScaleFactor: dpr })).newPage();
      await page.setContent(CAPTURE_FIXTURE);
      await (await (await page.locator('#framed').elementHandle()).contentFrame()).waitForSelector('div');
      const solver: any = new CaptchaKrakenSolver({});
      solver.page = page;
      const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'ck_crop_'));
      for (const selector of ['#board', '#framed', '#below']) {
        const handle = await page.locator(selector).elementHandle();
        const ours = path.join(dir, 'ours.png');
        await solver.shot(handle, ours);
        const theirs = await handle.screenshot({ animations: 'disabled' });
        const decode = (png: Buffer) => page.evaluate(async (b64: string) => {
          const img = await createImageBitmap(await (await fetch(`data:image/png;base64,${b64}`)).blob());
          const canvas = new OffscreenCanvas(img.width, img.height);
          const ctx = canvas.getContext('2d')!;
          ctx.drawImage(img, 0, 0);
          return { w: img.width, h: img.height, px: Array.from(ctx.getImageData(0, 0, img.width, img.height).data) };
        }, png.toString('base64'));
        const [a, b] = [await decode(fs.readFileSync(ours)), await decode(theirs)];
        assert.deepEqual([a.w, a.h], [b.w, b.h], `${selector} at dpr ${dpr}`);
        assert.ok(a.px.every((v: number, i: number) => v === b.px[i]), `${selector} at dpr ${dpr}: the crop differs from the element screenshot`);
      }
    } finally {
      await browser.close();
    }
  });
}
