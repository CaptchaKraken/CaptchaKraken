// hCaptcha's secure-api.js draws no frame on the host page. Every frame it owns sits inside a full-viewport enclave
// iframe, one enclave per render, and only the visible one holds the open challenge.
//
// Measured on a live job-board posting on 2026-10-15: after hcaptcha.execute() the host page held two enclaves and nothing
// else, so detection found no widget, and the tripwire blamed the selector table for a challenge that was on
// screen and still matched every selector inside its frame. The Python test of the same name drives the same cases.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import http from 'node:http';
import path from 'node:path';
import type { AddressInfo } from 'node:net';

import { CaptchaKrakenSolver } from './solver';
import { ENCLAVE_SELECTORS, VENDORS, WIDGET_PROBES } from './selectors';
import { FakeHandle, FakeNode, fakeDom, iframeMatches } from './fake-dom.test';
import type { PlaywrightPage } from './playwright-types';

const ASSETS = 'https://newassets.hcaptcha.com/captcha/v1/06f8dac28bb865a058d94cbd615a79d63217dd86/static';
const ENCLAVE = `${ASSETS}/hcaptcha-enclave.html#frame=enclave&_channel=1vx5ycvkplus&host=careers.example.com`;
const challengeSrc = (id: string) => `${ASSETS}/hcaptcha.html#frame=challenge&id=${id}&host=careers.example.com&size=invisible`;
const INVISIBLE = `${ASSETS}/hcaptcha.html#frame=checkbox-invisible`;

// Every iframe selector the driver reads on a host page, so a fake frame answers to exactly what a CSS engine would.
const HOST_IFRAME_SELECTORS = [...new Set([
  ...WIDGET_PROBES.map((p) => p.selector), ...ENCLAVE_SELECTORS,
  ...VENDORS.flatMap(([, s]) => [...(s.passive ?? []), ...s.hosts.map((h) => `iframe[src*="${h}"]`)]),
])];
const iframe = (src: string, node: Partial<FakeNode> = {}): FakeNode => ({ matches: iframeMatches(src, HOST_IFRAME_SELECTORS), ...node });
const enclave = (visible: boolean, frame: FakeNode[]): FakeNode => iframe(ENCLAVE, { visible, frame });
const response = (value = ''): FakeNode => ({ matches: ['[name="h-captcha-response"]'], visible: false, value });
const asPage = (nodes: FakeNode[]) => fakeDom(nodes) as unknown as PlaywrightPage;

test('the open challenge is found inside the visible enclave, not the hidden one', async () => {
  // The hidden enclave's challenge is not hidden inside its own document, so the enclave's visibility is what decides.
  const idle = iframe(challengeSrc('0ewuzu8hdfwo'));
  const live = iframe(challengeSrc('0so2b8l008q'));
  const page = asPage([
    enclave(false, [idle, iframe(INVISIBLE, { visible: false }), response()]),
    enclave(true, [live, iframe(INVISIBLE, { visible: false }), response()]),
  ]);
  const widget = await new CaptchaKrakenSolver().detectCaptcha(page);
  assert.ok(widget, 'nothing detected through the enclave');
  assert.equal(widget.vendor, 'hcaptcha');
  assert.equal(widget.role, 'challenge');
  assert.equal((widget.el as FakeHandle).node, live, 'detected the challenge in the hidden enclave');
});

test('an enclave nobody has raised holds no widget', async () => {
  const page = asPage([enclave(false, [iframe(challengeSrc('a'))]), enclave(false, [iframe(challengeSrc('b'))])]);
  assert.equal(await new CaptchaKrakenSolver().detectCaptcha(page), null);
});

test('the invisible checkbox is never a checkbox to click', async () => {
  assert.deepEqual(iframeMatches(INVISIBLE), [], 'a probe names the invisible checkbox frame');
  assert.equal(await new CaptchaKrakenSolver().detectCaptcha(asPage([enclave(true, [iframe(INVISIBLE)])])), null);
});

test('a token written inside the enclave is a solve', async () => {
  const solver: any = new CaptchaKrakenSolver();
  assert.equal(await solver.isCaptchaSolved(asPage([enclave(true, [iframe(challengeSrc('a')), response()])])), false);
  assert.equal(await solver.isCaptchaSolved(asPage([enclave(true, [iframe(challengeSrc('a')), response('P1_eyJ0')])])), true);
});

test('an enclave is not a frame the selector table missed', async () => {
  const solver: any = new CaptchaKrakenSolver();
  const quiet = asPage([enclave(true, [iframe(INVISIBLE, { visible: false })]), enclave(false, [])]);
  assert.deepEqual(await solver.unmatchedVendorFrames(quiet), [], 'blamed the table for a frame that is never interactive');
  // A frame inside the enclave that no selector names IS the table going stale, and must still say so.
  const renamed = asPage([enclave(true, [iframe(`${ASSETS}/hcaptcha.html#frame=puzzle&id=a`)])]);
  assert.deepEqual(await solver.unmatchedVendorFrames(renamed), ['hcaptcha']);
});

// The same page through a real browser: two origins, two levels of frames, the layout that page served.
function optional(name: string): any | null {
  try {
    return require(name);
  } catch {
    return null;
  }
}

const playwright = optional('playwright');
const FIXTURES = path.join(__dirname, '..', '..', 'python', 'tests', 'fixtures', 'hcaptcha_enclave');
// Where the live enclave puts its challenge: the wrapper's offset plus its 1px border, at the frame's own size.
const CHALLENGE_BOX = { x: 441, y: 151, width: 400, height: 600 };
// Tiles 2 and 6 of the recorded 3x3, as the model answers: fractions of the challenge frame.
const TILE = (n: number): [number, number, number, number] => {
  const [col, row] = [(n - 1) % 3, Math.floor((n - 1) / 3)];
  const [x, y] = [10 + col * 130, 130 + row * 130];
  return [x / 400, y / 600, (x + 120) / 400, (y + 120) / 600];
};

/** host.html on one origin; the enclaves and the challenge on another, as hCaptcha serves them. */
async function serveFixtures(): Promise<{ url: string; close: () => Promise<void> }> {
  const server = http.createServer((req, res) => {
    const file = req.url!.split(/[?#]/)[0].split('/').pop();
    const name = { 'host.html': 'host.html', 'hcaptcha-enclave.html': 'enclave.html', 'hcaptcha.html': 'challenge.html' }[file ?? ''];
    if (!name) { res.writeHead(404).end(); return; }
    const { port } = server.address() as AddressInfo;
    res.writeHead(200, { 'content-type': 'text/html' })
      .end(fs.readFileSync(path.join(FIXTURES, name), 'utf8').replace(/FRAMES_ORIGIN/g, `http://localhost:${port}`));
  });
  await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve));
  const { port } = server.address() as AddressInfo;
  return { url: `http://127.0.0.1:${port}/host.html`, close: () => new Promise((resolve) => server.close(() => resolve())) };
}

async function onTheRecordedPage(run: (page: any) => Promise<void>): Promise<void> {
  const served = await serveFixtures();
  const browser = await playwright.chromium.launch({ headless: true, args: ['--no-sandbox', '--disable-dev-shm-usage'] });
  try {
    const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
    await page.goto(served.url);
    await page.frameLocator('iframe[src*="/live/"]').frameLocator('iframe[src*="frame=challenge"]').locator('.button-submit').waitFor();
    await run(page);
  } finally {
    await browser.close();
    await served.close();
  }
}

const liveChallenge = (page: any) => page.frames().find((f: any) => f.url().includes('/live/hcaptcha.html#frame=challenge'));

test('through real frames, the challenge is found where it is on screen', { skip: !playwright && 'playwright not installed' }, async () => {
  await onTheRecordedPage(async (page) => {
    const widget = await new CaptchaKrakenSolver().detectCaptcha(page);
    assert.ok(widget, 'nothing detected through the enclave');
    assert.equal(widget.role, 'challenge');
    assert.equal(await widget.el.contentFrame(), liveChallenge(page), 'detected the challenge in the hidden enclave');
    // Clicks and crops are placed in page coordinates, so the box must be measured from the top frame.
    assert.deepEqual(await widget.el.boundingBox(), CHALLENGE_BOX);
  });
});

test('through real frames, a solve clicks the tiles it was told to and reads the token', { skip: !playwright && 'playwright not installed' }, async () => {
  await onTheRecordedPage(async (page) => {
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
    const pressed = await liveChallenge(page).locator('.task[aria-pressed="true"]').evaluateAll(
      (tasks: Element[]) => tasks.map((t) => t.getAttribute('aria-label')));
    assert.deepEqual(pressed, ['Challenge Image 2', 'Challenge Image 6'], 'the clicks landed on other tiles');
    assert.deepEqual(shown, [CHALLENGE_BOX.width, CHALLENGE_BOX.height], 'the model was shown something other than the challenge');
    assert.equal(result?.isSolved, true, 'the token the enclave received was not read as a solve');
  });
});
