// No `.at(-1)` here (ES2020 target), and every mapping is asserted because the header once claimed 'verified' with no test behind it.
import { test } from 'node:test';
import assert from 'node:assert/strict';

import { fromPuppeteer } from './puppeteer-adapter';

interface Call { method: string; args: any[]; }

const last = (calls: Call[]): Call => calls[calls.length - 1];

function fakeHandle(calls: Call[], name = 'handle') {
  const handle: any = {
    screenshot: async (o: any) => { calls.push({ method: `${name}.screenshot`, args: [o] }); return Buffer.from(''); },
    contentFrame: async () => { calls.push({ method: `${name}.contentFrame`, args: [] }); return fakeFrame(calls); },
    boundingBox: async () => { calls.push({ method: `${name}.boundingBox`, args: [] }); return { x: 1, y: 2, width: 3, height: 4 }; },
    scrollIntoView: async () => { calls.push({ method: `${name}.scrollIntoView`, args: [] }); },
    isVisible: async () => { calls.push({ method: `${name}.isVisible`, args: [] }); return true; },
    evaluate: async (fn: Function, ...args: any[]) => {
      calls.push({ method: `${name}.evaluate`, args });

      return fn({ getAttribute: (n: string) => `attr:${n}`, textContent: 'text!', value: 'typed' }, ...args);
    },
    $$: async (sel: string) => { calls.push({ method: `${name}.$$`, args: [sel] }); return [fakeHandle(calls, 'child')]; },
  };
  return handle;
}

function fakeFrame(calls: Call[]) {
  return {
    $$: async (sel: string) => { calls.push({ method: 'frame.$$', args: [sel] }); return [fakeHandle(calls)]; },
    waitForSelector: async (sel: string, o: any) => { calls.push({ method: 'frame.waitForSelector', args: [sel, o] }); return fakeHandle(calls); },
    waitForFunction: async (fn: any, ...rest: any[]) => { calls.push({ method: 'frame.waitForFunction', args: [fn, ...rest] }); return true; },
  };
}

function fakePage(calls: Call[], over: Record<string, any> = {}) {
  return {
    mouse: {
      move: async (x: number, y: number, o: any) => { calls.push({ method: 'mouse.move', args: [x, y, o] }); },
      down: async (o: any) => { calls.push({ method: 'mouse.down', args: [o] }); },
      up: async (o: any) => { calls.push({ method: 'mouse.up', args: [o] }); },
    },
    keyboard: {
      type: async (t: string, o: any) => { calls.push({ method: 'keyboard.type', args: [t, o] }); },
      press: async (k: string, o: any) => { calls.push({ method: 'keyboard.press', args: [k, o] }); },
      down: async (k: string, o: any) => { calls.push({ method: 'keyboard.down', args: [k, o] }); },
      up: async (k: string) => { calls.push({ method: 'keyboard.up', args: [k] }); },
    },
    waitForSelector: async (sel: string, o: any) => { calls.push({ method: 'waitForSelector', args: [sel, o] }); return fakeHandle(calls); },
    viewport: () => { calls.push({ method: 'viewport', args: [] }); return { width: 1280, height: 720 }; },
    screenshot: async (o: any) => { calls.push({ method: 'screenshot', args: [o] }); return new Uint8Array([137, 80]); },
    $$: async (sel: string) => { calls.push({ method: '$$', args: [sel] }); return [fakeHandle(calls), fakeHandle(calls)]; },
    evaluate: async (fn: any) => { calls.push({ method: 'evaluate', args: [fn] }); return fn(); },
    isClosed: () => false,
    ...over,
  } as any;
}

test('viewportSize() reads Puppeteer viewport()', () => {
  const calls: Call[] = [];
  const page = fromPuppeteer(fakePage(calls));
  assert.deepEqual(page.viewportSize(), { width: 1280, height: 720 });
  assert.equal(calls[0].method, 'viewport', 'called Playwright viewportSize() on Puppeteer');
});

test('waitForTimeout resolves on a timer — Puppeteer removed the method', async () => {
  const page = fromPuppeteer(fakePage([]));
  const start = Date.now();
  await page.waitForTimeout(30);
  assert.ok(Date.now() - start >= 25, 'returned early; a solver wait would be skipped');
});

test('{state:visible|hidden} becomes Puppeteer {visible|hidden}', async () => {
  const calls: Call[] = [];
  const page = fromPuppeteer(fakePage(calls));

  await page.waitForSelector('#a', { state: 'visible', timeout: 500 });
  assert.deepEqual(last(calls).args[1], { timeout: 500, visible: true });

  await page.waitForSelector('#b', { state: 'hidden' });
  assert.deepEqual(last(calls).args[1], { hidden: true });
});

test("{state:'attached'} passes no visibility flag", async () => {
  const calls: Call[] = [];
  const page = fromPuppeteer(fakePage(calls));
  await page.waitForSelector('#c', { state: 'attached', timeout: 10 });
  const opts = last(calls).args[1];
  assert.deepEqual(opts, { timeout: 10 });
  assert.ok(!('visible' in opts) && !('hidden' in opts), 'attached must not imply visible');
});

test('no options stays undefined rather than becoming {}', async () => {
  const calls: Call[] = [];
  const page = fromPuppeteer(fakePage(calls));
  await page.waitForSelector('#d');
  assert.equal(last(calls).args[1], undefined);
});

test('getAttribute and textContent go through evaluate()', async () => {
  const calls: Call[] = [];
  const page = fromPuppeteer(fakePage(calls));
  const handle = (await page.locator('#x').elementHandle())!;

  assert.equal(await handle.getAttribute('src'), 'attr:src');
  assert.equal(last(calls).method, 'handle.evaluate');
  assert.deepEqual(last(calls).args, ['src'], 'attribute name must reach the page function');

  assert.equal(await handle.textContent(), 'text!');
  assert.equal(last(calls).method, 'handle.evaluate');

  assert.equal(await handle.inputValue(), 'typed', 'the live value, not the attribute');
  assert.equal(last(calls).method, 'handle.evaluate');
});

test('scrollIntoViewIfNeeded maps to scrollIntoView', async () => {
  const calls: Call[] = [];
  const page = fromPuppeteer(fakePage(calls));
  await (await page.locator('#x').elementHandle())!.scrollIntoViewIfNeeded();
  assert.equal(last(calls).method, 'handle.scrollIntoView');
});

test("a 'Control+A' combo is held, pressed, released — Puppeteer has no combo syntax", async () => {
  const calls: Call[] = [];
  const page = fromPuppeteer(fakePage(calls));
  await page.keyboard.press('Control+A');

  assert.deepEqual(
    calls.map((c) => `${c.method}:${c.args[0]}`),
    ['keyboard.down:Control', 'keyboard.press:A', 'keyboard.up:Control'],
    'a bare press("Control+A") types a literal string in Puppeteer and never selects anything',
  );
});

test('a plain key is pressed once, with no modifier traffic', async () => {
  const calls: Call[] = [];
  const page = fromPuppeteer(fakePage(calls));
  await page.keyboard.press('Enter');
  assert.deepEqual(calls.map((c) => c.method), ['keyboard.press']);
});

test('waitForFunction swaps Playwright (fn, arg, opts) to Puppeteer (fn, opts, arg)', async () => {
  const calls: Call[] = [];
  const page = fromPuppeteer(fakePage(calls));
  const frame = await (await page.locator('#f').elementHandle())!.contentFrame();

  const fn = () => true;
  await frame!.waitForFunction(fn, { some: 'arg' }, { timeout: 99 });

  const call = calls.find((c) => c.method === 'frame.waitForFunction')!;
  assert.equal(call.args[0], fn);
  assert.deepEqual(call.args[1], { timeout: 99 }, 'options must be the SECOND positional arg for Puppeteer');
  assert.deepEqual(call.args[2], { some: 'arg' }, 'the arg must come last');
});

test('a locator is one $$ per query, and all() yields one wrapped handle per match', async () => {
  const calls: Call[] = [];
  const page = fromPuppeteer(fakePage(calls));
  const each = await page.locator('iframe').all();
  assert.equal(each.length, 2);
  assert.equal(await page.locator('iframe').count(), 2);
  for (const at of each) {
    const h = (await at.elementHandle())!;
    assert.equal(typeof h.getAttribute, 'function', 'an unwrapped Puppeteer handle would have no getAttribute');
  }
  assert.deepEqual(calls.filter((c) => c.method === '$$').map((c) => c.args[0]), ['iframe', 'iframe'], 'all() and count() each queried once');
});

test('filter({ visible }) asks each handle, and a nested locator goes through the parent handle', async () => {
  const calls: Call[] = [];
  const page = fromPuppeteer(fakePage(calls));
  assert.equal(await page.locator('iframe').filter({ visible: true }).count(), 2);
  assert.equal(calls.filter((c) => c.method === 'handle.isVisible').length, 2);
  assert.equal(await page.locator('body').locator('.inner').count(), 2, 'one child per parent handle');
  assert.deepEqual(last(calls), { method: 'handle.$$', args: ['.inner'] });
});

test('a missing element stays null instead of becoming a broken wrapper', async () => {
  const calls: Call[] = [];
  const page = fromPuppeteer(fakePage(calls, { $$: async () => [], waitForSelector: async () => null }));
  assert.equal(await page.locator('#nope').elementHandle(), null);
  assert.equal(await page.locator('#nope').count(), 0);
  assert.equal(await page.waitForSelector('#nope'), null);
});

test('isClosed is forwarded — the watcher needs it to end its loop', async () => {
  let closed = false;
  const page = fromPuppeteer(fakePage([], { isClosed: () => closed }));
  assert.equal(page.isClosed!(), false);
  closed = true;
  assert.equal(page.isClosed!(), true, 'a watcher would poll a dead page forever');
});

test('screenshot() takes the whole viewport as a PNG Buffer, dropping the Playwright-only options', async () => {
  const calls: Call[] = [];
  const page = fromPuppeteer(fakePage(calls));
  const png = await page.screenshot({ timeout: 2500, animations: 'allow' });
  assert.ok(Buffer.isBuffer(png), 'the driver crops a Buffer; Puppeteer 22+ returns a Uint8Array');
  assert.deepEqual([...png], [137, 80]);
  assert.deepEqual(last(calls), { method: 'screenshot', args: [{ type: 'png' }] });
});
