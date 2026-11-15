// A slider or a hold is never animated, yet every one was filmed for 4s before the model's answer was used: on the 5.0
// Tier 3 run that was a quarter of each board's budget. DataDome's pass is painted inside its own frame and the page
// reloads a second later; unread, the next round filmed the closing frame.
import { test } from 'node:test';
import assert from 'node:assert/strict';

import { CaptchaKrakenSolver } from './solver';
import { SELECTORS } from './selectors';
import { Vendor } from './kinds';
import { fakeDom } from './fake-dom.test';

const DATADOME_FRAME = 'iframe[src*="captcha-delivery.com/captcha"]';
const DATADOME_PASS = '.sliderContainer.slider-success .slider';

test('only vendors that can animate are filmed', () => {
  for (const still of [Vendor.TENCENT, Vendor.DATADOME, Vendor.HUMAN, Vendor.FUNCAPTCHA, Vendor.DINGXIANG]) {
    assert.equal(SELECTORS[still].stillsOnly, true, `${still} is all sliders and holds, yet it would be filmed`);
  }
  for (const moving of [Vendor.HCAPTCHA, Vendor.GEETEST, Vendor.CYBERSIARA]) {
    assert.ok(!SELECTORS[moving].stillsOnly, `${moving} deals animated boards; it must stay filmed`);
  }
});

test('a still vendor is asked without a burst', () => {
  const solver: any = new CaptchaKrakenSolver({ speculativeBurstEnabled: true });
  assert.equal(solver.shouldSpeculate(Vendor.TENCENT, false), false);
  assert.equal(solver.shouldSpeculate(Vendor.HCAPTCHA, false), true);
});

test("DataDome's pass inside its frame is a solve", async () => {
  const dom = fakeDom([{ matches: [DATADOME_FRAME], frame: [{ matches: [DATADOME_PASS] }] }]);
  assert.equal(await (new CaptchaKrakenSolver({}) as any).isCaptchaSolved(dom), true);
});

test('an unfinished DataDome slide is not a solve', async () => {
  const dom = fakeDom([{ matches: [DATADOME_FRAME], frame: [{ matches: ['.sliderContainer .slider'] }] }]);
  assert.equal(await (new CaptchaKrakenSolver({}) as any).isCaptchaSolved(dom), false);
});

test('the slide loop tracks frames at one pixel per CSS pixel', () => {
  const fs = require('node:fs') as typeof import('fs');
  const path = require('node:path') as typeof import('path');
  const src = fs.readFileSync(path.resolve(__dirname, '..', 'src', 'solver.ts'), 'utf8');
  for (const shot of ['first', 'probed', 'current']) {
    assert.ok(src.includes(`await this.shot(element, ${shot}, timeout, 'disabled', undefined, 'css');`),
      `the slide loop's ${shot} frame is taken at device scale: a phone's is ~7x the pixels to track`);
  }
});
