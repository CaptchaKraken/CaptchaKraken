// A board's motion is read off the file the vendor deals it as, and the 4s burst is kept for boards nobody described.
// Measured 2026-11-14 on the live demos: hCaptcha loads every still board as image/jpeg and every animated one as
// video/webm; GeeTest v4's /load names the challenge type, and only its svg types move. Mirrors
// python/tests/test_the_vendor_says_whether_its_board_moves.py.
import { test } from 'node:test';
import assert from 'node:assert/strict';

import { TIMELINE_JS, VerdictLog, motionFromTimeline, type Timeline } from './verdicts';
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

const siara = (board: string) => response('https://embed.mycybersiara.com/api/GenerateCaptcha/Captcha',
  'application/json; charset=utf-8', `{"HttpStatusCode":0,"Message":"success","HtmlFormate":"${board}"}`, 'xhr');

test('a png board is still and a gif says nothing', async () => {
  for (const [contentType, moves] of [['image/png', false], ['image/gif', null]] as const) {
    const { page, send } = fakePage();
    const log = new VerdictLog(page);
    send(hcDeal(), response(HC_BOARD, contentType));
    assert.equal(await log.boardMotion(Vendor.HCAPTCHA), moves, contentType);
  }
});

test('CyberSiara names a gif board and it moves', async () => {
  const a = fakePage();
  const log = new VerdictLog(a.page);
  a.send(siara('https://embed.mycybersiara.com/CyberSiara/SiaraShield.639303158624783419.gif'));
  assert.equal(await log.boardMotion(Vendor.CYBERSIARA), true);
  const b = fakePage();
  const other = new VerdictLog(b.page);
  b.send(siara('https://embed.mycybersiara.com/CyberSiara/board.png'));
  assert.equal(await other.boardMotion(Vendor.CYBERSIARA), null);
});

const GT_POLICY = (kind: string) => `https://static.geetest.com/captcha_v4/policy/ccbb7c7507/${kind}/339970/2026-11-15T12/bg/0bca.png`;

test('a GeeTest board dealt before solve is read off the timeline', () => {
  const read = (entries: [string, string][], full = false) => motionFromTimeline(Vendor.GEETEST, { full, entries });
  assert.equal(read([['script', GT_LOAD], ['img', GT_POLICY('slide')]]), false);
  assert.equal(read([['script', GT_LOAD], ['xmlhttprequest', GT_POLICY('svg_icon')]]), true);
  assert.equal(read([['img', GT_POLICY('svg_icon')], ['script', GT_LOAD]]), null, 'a board before the latest deal');
  assert.equal(read([['img', GT_POLICY('svg_icon')]]), null);
  assert.equal(read([['script', GT_LOAD], ['img', GT_POLICY('slide')]], true), null, 'a full buffer');
});

function timelinePage(...frames: [string, string][][]) {
  const page = fakePage();
  (page.page as any).frames = () => frames.map((entries) => ({
    evaluate: async (script: string) => {
      assert.equal(script, TIMELINE_JS);
      return { full: false, entries } as Timeline;
    },
  }));
  return page;
}

test('the listener falls back to each frame\'s timeline', async () => {
  let p = timelinePage([['script', 'https://example.com/app.js']], [['xmlhttprequest', HC_DEAL], ['img', HC_BOARD]]);
  assert.equal(await new VerdictLog(p.page).boardMotion(Vendor.HCAPTCHA), false);
  p = timelinePage([['xmlhttprequest', HC_DEAL], ['video', HC_BOARD]]);
  assert.equal(await new VerdictLog(p.page).boardMotion(Vendor.HCAPTCHA), true);
  p = timelinePage([['xmlhttprequest', 'https://embed.mycybersiara.com/api/GenerateCaptcha/Captcha'],
    ['img', 'https://embed.mycybersiara.com/CyberSiara/SiaraShield.6393.gif']]);
  assert.equal(await new VerdictLog(p.page).boardMotion(Vendor.CYBERSIARA), true);
});

test('what the network said wins over the timeline', async () => {
  const p = timelinePage([['xmlhttprequest', HC_DEAL], ['img', HC_BOARD]]);
  const log = new VerdictLog(p.page);
  p.send(hcDeal(), response(HC_BOARD, 'video/webm', '', 'media'));
  assert.equal(await log.boardMotion(Vendor.HCAPTCHA), true);
});

test('a still file is asked at once and an undescribed board is still filmed', () => {
  const solver: any = new CaptchaKrakenSolver({ speculativeBurstEnabled: true });
  assert.equal(solver.shouldSpeculate(Vendor.HCAPTCHA, false, null), true);
  assert.equal(solver.shouldSpeculate(Vendor.HCAPTCHA, false, false), false);
  assert.equal(solver.shouldSpeculate(Vendor.HCAPTCHA, false, true), true);
});
