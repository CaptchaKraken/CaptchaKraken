// A page just navigated has often not drawn its widget, and "no captcha" is only believed after a bounded wait.
//
// Measured on a vendor's public demo: `solve()` straight after `goto(..., { waitUntil: 'domcontentloaded' })` failed
// "no interactive captcha widget detected ... the vendor's markup no longer matches anything in SELECTORS" 3 times
// out of 3, while the same code solved 2 of 3 once the page had settled. It was a race, and the message blamed the
// table. The Python test of the same name drives the same cases.
import { test } from 'node:test';
import assert from 'node:assert/strict';

import { CaptchaKrakenSolver } from './solver';
import type { PlaywrightPage } from './playwright-types';

function driver(appearsAfterMs: number, detectionTimeoutMs: number) {
  const solver: any = new CaptchaKrakenSolver({ detectionTimeoutMs, maxSolveLoops: 1, overallSolveTimeoutMs: 1_000,
    postSolveOutcomeTimeoutMs: 1 });
  const started = Date.now();
  const rounds: number[] = [];
  solver.detectCaptcha = async () => (Date.now() - started >= appearsAfterMs ? { vendor: 'hcaptcha', role: 'checkbox' } : null);
  solver.isCaptchaSolved = async () => rounds.length > 0;
  solver.solveSingle = async () => { rounds.push(Date.now() - started); return { didInteract: true, tokenUsage: [] }; };
  solver.human.reset = async () => {};
  // Outer-loop reads that need a real page; this test drives the loop, not the DOM.
  solver.bannerKind = async () => null;
  solver.isChallengeFreshlyRendered = async () => false;
  return { solver, rounds };
}

test('a widget that draws late is found and solved', async () => {
  const { solver, rounds } = driver(400, 5_000);
  assert.equal((await solver.solveImpl({})).isSolved, true);
  assert.ok(rounds[0] >= 400 && rounds[0] < 1_400, `first round at ${rounds[0]}ms`);
});

test('the wait is not charged to the solve budget', async () => {
  // A 300ms budget, a widget that took 1.2s to draw, and a board that needs a second round: the second round runs.
  const { solver, rounds } = driver(1_200, 5_000);
  solver.config.overallSolveTimeoutMs = 300;
  solver.config.maxSolveLoops = 2;
  solver.isCaptchaSolved = async () => rounds.length >= 2;
  assert.equal((await solver.solveImpl({})).isSolved, true);
  assert.equal(rounds.length, 2);
});

test('a widget that never draws is given up on at the timeout', async () => {
  const { solver } = driver(Infinity, 600);
  solver.vendorsOnTheWire = async () => [];
  const started = Date.now();
  await assert.rejects(solver.solveImpl({}), /within 600ms \(no vendor captcha code loaded/);
  assert.ok(Date.now() - started >= 600, 'gave up before the timeout');
});

async function message(loaded: string[], unmatched: string[]): Promise<string> {
  const { solver } = driver(Infinity, 0);
  solver.vendorsOnTheWire = async () => loaded;
  solver.unmatchedVendorFrames = async () => unmatched;
  let text = '';
  await solver.solveImpl({}).catch((e: Error) => { text = e.message; });
  return text;
}

test('loaded code with no frame does not blame the selectors', async () => {
  const text = await message(['hcaptcha'], []);
  assert.doesNotMatch(text, /matches nothing in SELECTORS|re-measuring/);
  assert.match(text, /code is loaded but drew no widget/);
});

test('a frame nothing matches is reported as changed markup', async () => {
  assert.match(await message(['hcaptcha'], ['hcaptcha']), /hcaptcha is showing a frame that matches nothing in SELECTORS/);
});

/** Answers `iframe[src*="..."]` from a list of frame URLs, which is all the unmatched-frame check asks. */
function framesPage(srcs: string[]): PlaywrightPage {
  const locator = (selector: string): any => {
    const needle = selector.includes('src*="') ? selector.split('src*="')[1].split('"')[0] : null;
    const hits = srcs.filter((s) => needle && s.includes(needle));
    return { filter: () => locator(selector), all: async () => hits.map(() => ({})), count: async () => hits.length };
  };
  return { locator } as unknown as PlaywrightPage;
}

test('an invisible badge is not an unmatched frame', async () => {
  const solver: any = new CaptchaKrakenSolver();
  assert.deepEqual(await solver.unmatchedVendorFrames(framesPage(['https://www.google.com/recaptcha/api2/anchor?k=SITE-KEY&size=invisible'])), []);
  assert.deepEqual(await solver.unmatchedVendorFrames(framesPage(['https://newassets.hcaptcha.com/captcha/v1/static/hcaptcha.html#frame=checkbox-renamed'])), ['hcaptcha']);
});
