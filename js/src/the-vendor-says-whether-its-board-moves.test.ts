// A board's motion is read off the file the vendor deals it as, and the 4s burst is kept for boards nobody described.
// Measured 2026-11-14 on the live demos: hCaptcha loads every still board as image/jpeg and every animated one as
// video/webm; GeeTest v4's /load names the challenge type, and only its svg types move. Mirrors
// python/tests/test_the_vendor_says_whether_its_board_moves.py.
import { test } from 'node:test';
import assert from 'node:assert/strict';

import { VerdictLog } from './verdicts';
import { CaptchaKrakenSolver } from './solver';
import { Vendor } from './kinds';
import type { PlaywrightPage, PlaywrightResponse } from './playwright-types';

const HC_DEAL = 'https://api.hcaptcha.com/getcaptcha/7fcac73c-0096-446a-9c58-c080553a6fa8?s=1';
const HC_BOARD = 'https://imgs3.hcaptcha.com/tip/310c65b96dbc0a2f92ed212cc49e88ade109b81f71ca21795dc0ae47f048e367';
const GT_LOAD = 'https://gcaptcha4.geetest.com/load?captcha_id=x&callback=geetest_1';

function response(url: string, contentType = '', body = '', resourceType = 'image', status = 200): PlaywrightResponse {
  return {
    url: () => url,
    status: () => status,
    text: async () => body,
    headers: () => ({ 'content-type': contentType }),
    request: () => ({ resourceType: () => resourceType }),
  };
}

function fakePage() {
  const listeners: ((r: PlaywrightResponse) => void)[] = [];
  const page = { on: (_e: string, l: (r: PlaywrightResponse) => void) => listeners.push(l), off: () => {} };
  return { page: page as unknown as PlaywrightPage, send: (...rs: PlaywrightResponse[]) => rs.forEach((r) => listeners.forEach((l) => l(r))) };
}

const hcDeal = () => response(HC_DEAL, 'application/octet-stream', 'Ä=¯', 'xhr');
const gtLoad = (kind: string) => response(GT_LOAD, 'text/javascript;charset=UTF-8',
  `geetest_1({"status": "success", "data": {"lot_number": "8916", "captcha_type": "${kind}"}})`, 'script');

test('an hCaptcha board dealt as a video moves and one dealt as a jpeg is still', async () => {
  const { page, send } = fakePage();
  const log = new VerdictLog(page);
  assert.equal(await log.boardMotion(Vendor.HCAPTCHA), null);
  send(hcDeal(), response(HC_BOARD, 'video/webm', '', 'media', 206));
  assert.equal(await log.boardMotion(Vendor.HCAPTCHA), true);
  send(hcDeal());
  assert.equal(await log.boardMotion(Vendor.HCAPTCHA), null, 'the next deal inherited the last board\'s motion');
  send(response(HC_BOARD, 'image/jpeg'));
  assert.equal(await log.boardMotion(Vendor.HCAPTCHA), false);
});

test('one moving file makes the board a moving one', async () => {
  const { page, send } = fakePage();
  const log = new VerdictLog(page);
  send(hcDeal(), response(HC_BOARD, 'video/webm', '', 'media'), response(HC_BOARD, 'image/jpeg'));
  assert.equal(await log.boardMotion(Vendor.HCAPTCHA), true);
});

for (const [kind, moves] of [['svg_icon', true], ['svg_seed', true], ['slide', false], ['nine', false],
  ['match', false], ['ai', null]] as const) {
  test(`GeeTest ${kind} reads as ${moves}`, async () => {
    const { page, send } = fakePage();
    const log = new VerdictLog(page);
    send(gtLoad(kind));
    assert.equal(await log.boardMotion(Vendor.GEETEST), moves);
  });
}

test('a type nobody measured keeps the film', async () => {
  const { page, send } = fakePage();
  const log = new VerdictLog(page);
  send(gtLoad('svg_icon'), gtLoad('ai'));
  assert.equal(await log.boardMotion(Vendor.GEETEST), null);
});

test('a still file is asked at once and an undescribed board is still filmed', () => {
  const solver: any = new CaptchaKrakenSolver({ speculativeBurstEnabled: true });
  assert.equal(solver.shouldSpeculate(Vendor.HCAPTCHA, false, null), true);
  assert.equal(solver.shouldSpeculate(Vendor.HCAPTCHA, false, false), false);
  assert.equal(solver.shouldSpeculate(Vendor.HCAPTCHA, false, true), true);
});
