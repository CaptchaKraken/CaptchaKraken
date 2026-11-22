// A widget is found inside a frame that is not the vendor's: a bot-protection block page, a modal, an embed.
//
// Imperva's block page holds one same-origin iframe and nothing else, and the captcha is drawn inside that iframe's
// document. Detection read only the top page and the vendor's own enclaves, so it found no widget on a page with a
// challenge open on it. The Python test of the same name drives the same cases.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import http from 'node:http';
import path from 'node:path';
import type { AddressInfo } from 'node:net';

import { CaptchaKrakenSolver, hostScopes } from './solver';
import { DEFAULT_TABLE, FRAME_SELECTORS, VENDORS, WIDGET_PROBES } from './selectors';
import { FakeHandle, FakeNode, fakeDom, iframeMatches } from './fake-dom.test';
import type { PlaywrightPage } from './playwright-types';

const BLOCK_PAGE = '/_Incapsula_Resource?SWUDNSAI=30&xinfo=1-11111111-0&incident_id=000000000000000000-000000000000000000';
const ASSETS = 'https://newassets.hcaptcha.com/captcha/v1/06f8dac28bb865a058d94cbd615a79d63217dd86/static';
const CHECKBOX = `${ASSETS}/hcaptcha.html#frame=checkbox&id=0so2b8l008q&host=example.com`;
const CHALLENGE = `${ASSETS}/hcaptcha.html#frame=challenge&id=0so2b8l008q&host=example.com`;
const ANCHOR = 'https://www.google.com/recaptcha/api2/anchor?k=6LeSYNTHETIC&co=aHR0cHM6Ly9leGFtcGxlLmNvbQ';

// Every iframe selector the driver reads on a host page, so a fake frame answers to exactly what a CSS engine would.
const HOST_IFRAME_SELECTORS = [...new Set([
  ...WIDGET_PROBES.map((p) => p.selector), ...FRAME_SELECTORS,
  ...VENDORS.flatMap(([, s]) => [...(s.passive ?? []), ...s.hosts.map((h) => `iframe[src*="${h}"]`)]),
])];
const iframe = (src: string, node: Partial<FakeNode> = {}): FakeNode => ({ matches: iframeMatches(src, HOST_IFRAME_SELECTORS), ...node });
const blockPage = (frame: FakeNode[], visible = true): FakeNode => iframe(BLOCK_PAGE, { visible, frame });
const response = (value = ''): FakeNode => ({ matches: ['[name="h-captcha-response"]'], visible: false, value });
const asPage = (nodes: FakeNode[]) => fakeDom(nodes) as unknown as PlaywrightPage;

test('a checkbox inside the block page is found', async () => {
  const box = iframe(CHECKBOX);
  const widget = await new CaptchaKrakenSolver().detectCaptcha(asPage([blockPage([box, response()])]));
  assert.ok(widget, "nothing detected through the block page's frame");
  assert.equal(widget.vendor, 'hcaptcha');
  assert.equal(widget.role, 'checkbox');
  assert.equal((widget.el as FakeHandle).node, box);
});

test('the open challenge inside the block page comes before its checkbox', async () => {
  const live = iframe(CHALLENGE);
  const widget = await new CaptchaKrakenSolver().detectCaptcha(asPage([blockPage([iframe(CHECKBOX), live, response()])]));
  assert.equal(widget?.role, 'challenge');
  assert.equal((widget!.el as FakeHandle).node, live);
});

test('a widget two frames down is found', async () => {
  // A modal with no src of its own (srcdoc) around a site's embed around the vendor's frame.
  const anchor = iframe(ANCHOR);
  const modal: FakeNode = { matches: iframeMatches('about:srcdoc', HOST_IFRAME_SELECTORS),
    frame: [iframe('https://forms.example.com/embed/contact', { frame: [anchor] })] };
  const widget = await new CaptchaKrakenSolver().detectCaptcha(asPage([modal]));
  assert.ok(widget, 'nothing detected two frames below the page');
  assert.equal(widget.vendor, 'recaptcha');
  assert.equal(widget.role, 'checkbox');
  assert.equal((widget.el as FakeHandle).node, anchor);
});

test('a frame holding nothing of a vendor\'s is walked through but not read', async () => {
  // An ad frame, and a modal whose only content is a site's embed: neither is a scope the probes are read in, but the
  // embed inside the modal, holding the vendor's frame, is.
  const ad: FakeNode = { ...iframe('https://ads.example.net/slot/1'), frame: [{ matches: ['div'] }, iframe('about:blank', { frame: [] })] };
  const modal: FakeNode = { ...iframe('about:srcdoc'), frame: [iframe('https://forms.example.com/embed/contact', { frame: [iframe(ANCHOR)] })] };
  assert.equal((await hostScopes(asPage([ad]), DEFAULT_TABLE)).length, 1, 'an ad frame is read as a page');
  assert.equal((await hostScopes(asPage([ad, modal]), DEFAULT_TABLE)).length, 2, 'the walk kept the wrong frames');
});

test('a hidden frame is not searched', async () => {
  // Playwright judges visibility within the frame's own document, so the hidden frame's checkbox reads as visible.
  assert.equal(await new CaptchaKrakenSolver().detectCaptcha(asPage([blockPage([iframe(CHECKBOX)], false)])), null);
});

test("a vendor's own frame is never a frame to search", () => {
  // Inside a widget's frame is the vendor's business: the probes there are read through that frame, not as a page.
  for (const src of [CHECKBOX, CHALLENGE, ANCHOR]) assert.deepEqual(iframeMatches(src, FRAME_SELECTORS), [], `${src} would be searched as a page`);
  assert.ok(iframeMatches(BLOCK_PAGE, FRAME_SELECTORS).length, "the block page's frame is not searched");
});

test('a token written inside the block page is a solve', async () => {
  const solver: any = new CaptchaKrakenSolver();
  assert.equal(await solver.isCaptchaSolved(asPage([blockPage([iframe(CHALLENGE), response()])])), false);
  assert.equal(await solver.isCaptchaSolved(asPage([blockPage([iframe(CHALLENGE), response('P1_eyJ0')])])), true);
});

test('a frame inside the block page that no selector names is the table going stale', async () => {
  const page = asPage([blockPage([iframe(`${ASSETS}/hcaptcha.html#frame=puzzle&id=a`)])]);
  assert.deepEqual(await (new CaptchaKrakenSolver() as any).unmatchedVendorFrames(page), ['hcaptcha']);
});

// The same page through a real browser: the archived block page, wrapping the recorded enclave and its challenge.
function optional(name: string): any | null {
  try {
    return require(name);
  } catch {
    return null;
  }
}

const playwright = optional('playwright');
const FIXTURES = path.join(__dirname, '..', '..', 'python', 'tests', 'fixtures');
const SERVED: Record<string, string> = {
  'host.html': path.join(FIXTURES, 'imperva_block_page', 'host.html'),
  '_Incapsula_Resource': path.join(FIXTURES, 'imperva_block_page', 'incapsula.html'),
  'hcaptcha-enclave.html': path.join(FIXTURES, 'hcaptcha_enclave', 'enclave.html'),
  'hcaptcha.html': path.join(FIXTURES, 'hcaptcha_enclave', 'challenge.html'),
};
// The block page's frame has no border and sits at the origin, so the challenge is where the enclave puts it.
const CHALLENGE_BOX = { x: 441, y: 151, width: 400, height: 600 };
// Tiles 2 and 6 of the recorded 3x3, as the model answers: fractions of the challenge frame.
const TILE = (n: number): [number, number, number, number] => {
  const [col, row] = [(n - 1) % 3, Math.floor((n - 1) / 3)];
  const [x, y] = [10 + col * 130, 130 + row * 130];
  return [x / 400, y / 600, (x + 120) / 400, (y + 120) / 600];
};

/** The block page and its frame on one origin, the vendor's frames on another, as they are served. */
async function serveFixtures(): Promise<{ url: string; close: () => Promise<void> }> {
  const server = http.createServer((req, res) => {
    const file = SERVED[req.url!.split(/[?#]/)[0].split('/').pop() ?? ''];
    if (!file) { res.writeHead(404).end(); return; }
    const { port } = server.address() as AddressInfo;
    res.writeHead(200, { 'content-type': 'text/html' })
      .end(fs.readFileSync(file, 'utf8').replace(/FRAMES_ORIGIN/g, `http://localhost:${port}`));
  });
  await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve));
  const { port } = server.address() as AddressInfo;
  return { url: `http://127.0.0.1:${port}/host.html`, close: () => new Promise((resolve) => server.close(() => resolve())) };
}

async function onTheBlockPage(run: (page: any) => Promise<void>): Promise<void> {
  const served = await serveFixtures();
  // The server is open before the browser is: a launch that throws must still close it, or node --test hangs.
  let browser: any;
  try {
    browser = await playwright.chromium.launch({ headless: true, args: ['--no-sandbox', '--disable-dev-shm-usage'] });
    const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
    await page.goto(served.url);
    await page.frameLocator('#main-iframe').frameLocator('iframe[src*="frame=enclave"]')
      .frameLocator('iframe[src*="frame=challenge"]').locator('.button-submit').waitFor();
    await run(page);
  } finally {
    await browser?.close();
    await served.close();
  }
}

const challenge = (page: any) => page.frames().find((f: any) => f.url().includes('/live/hcaptcha.html#frame=challenge'));

test('through real frames, the challenge inside the block page is found where it is on screen', { skip: !playwright && 'playwright not installed' }, async () => {
  await onTheBlockPage(async (page) => {
    const widget = await new CaptchaKrakenSolver().detectCaptcha(page);
    assert.ok(widget, "nothing detected through the block page's frame");
    assert.equal(widget.role, 'challenge');
    assert.equal(await widget.el.contentFrame(), challenge(page));
    assert.deepEqual(await widget.el.boundingBox(), CHALLENGE_BOX);
  });
});

test('through real frames, a solve on the block page clicks its tiles and reads the token', { skip: !playwright && 'playwright not installed' }, async () => {
  await onTheBlockPage(async (page) => {
    const solver: any = new CaptchaKrakenSolver({ humanization: 'none', videoSolveEnabled: false, maxSolveLoops: 1,
      detectionTimeoutMs: 2_000, postSolveOutcomeTimeoutMs: 2_000 });
    solver.runCvTool = async (cmd: string) => (cmd === 'board-painted' ? { painted: true } : { has_movement: false });
    let shown: number[] = [];
    solver.getSolution = async (image: string) => {
      const png = fs.readFileSync(image);
      shown = [png.readUInt32BE(16), png.readUInt32BE(20)];
      return { actions: [{ action: 'click', target_bounding_boxes: [TILE(2), TILE(6)] }], token_usage: [] };
    };
    solver.reportOutcome = async () => {};

    const result = await solver.solve(page);
    const pressed = await challenge(page).locator('.task[aria-pressed="true"]').evaluateAll(
      (tasks: Element[]) => tasks.map((t) => t.getAttribute('aria-label')));
    assert.deepEqual(pressed, ['Challenge Image 2', 'Challenge Image 6'], 'the clicks landed on other tiles');
    assert.deepEqual(shown, [CHALLENGE_BOX.width, CHALLENGE_BOX.height], 'the model was shown something other than the challenge');
    assert.equal(result?.isSolved, true, 'the token the enclave received was not read as a solve');
  });
});
