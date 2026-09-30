// The gate keys on steady-screen COUNT, not slicing mode: `even` means the slicer could not prove recurrence, and 32 clips sliced `even`
// while sitting on 2-3 steady screens. The pointer parks first (a 274-647ms move against a 1500ms dwell), the budget is 2.7s x 3 screens,
// the local-evidence wait is capped at one burst (uncapped it ran 36s), and a touched board is never re-classified by filming it.
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { test } from 'node:test';
import assert from 'node:assert/strict';

import { CaptchaKrakenSolver, SOLVE_DEFAULTS } from './solver';
import { SettleVerdict } from './kinds';
import { photographsItself } from './fake-dom.test';

function gated(opts: { mode: string | null; screens: number; matchAfter?: number }) {
  const solver: any = photographsItself(new CaptchaKrakenSolver({ keyframeWaitPollMs: 1 }));
  solver.keyframeMode = opts.mode;
  solver.keyframeSteadyScreens = opts.screens;
  let probes = 0;
  solver.runCvTool = async () => {
    probes += 1;
    return { match: probes >= (opts.matchAfter ?? 1), diff: 0.01 };
  };
  const element: any = { screenshot: async () => undefined };
  return { solver, element, probes: () => probes };
}

test('a clip that sits on steady screens waits, even when sliced `even`', async () => {
  const { solver, element, probes } = gated({ mode: 'even', screens: 3 });
  const matched = await solver.waitForKeyframe(element, '/tmp/kf.png', 0.5, 0.5);
  assert.equal(matched, true, 'the gate must run for a board that holds screens');
  assert.ok(probes() >= 1, 'it must actually look at the widget');
});

test('a one-way animation still does not wait', async () => {
  const { solver, element, probes } = gated({ mode: 'even', screens: 0 });
  const matched = await solver.waitForKeyframe(element, '/tmp/kf.png', 0.5, 0.5);
  assert.equal(matched, false);
  assert.equal(probes(), 0, 'a clip with no steady screens must not be polled at all');
});

test('no steady screens, but the answer AREA comes back — then it waits', async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'kfset_'));
  for (const n of ['frame_01.png', 'frame_02.png', 'frame_03.png']) {
    fs.writeFileSync(path.join(dir, n), '');
  }
  const solver: any = photographsItself(new CaptchaKrakenSolver({ keyframeWaitPollMs: 1 }));
  solver.keyframeSteadyScreens = 0;
  let probes = 0;
  solver.runCvTool = async (tool: string) => {
    if (tool === 'match-region') probes += 1;
    return { match: true, diff: 0.0 };
  };
  const element: any = { screenshot: async () => undefined };
  try {
    const matched = await solver.waitForKeyframe(
      element, path.join(dir, 'frame_01.png'), 0.5, 0.5);
    assert.equal(matched, true, 'an answer area that recurs is worth waiting for');
    assert.ok(probes >= 2, 'it must compare against the clip, then poll the widget');
  } finally {
    fs.rmSync(dir, { recursive: true, force: true });
  }
});

test('the wait is bounded by the evidence that opened it', async () => {
  const BURST_FLOOR_MS = 4000;
  assert.ok(BURST_FLOOR_MS < SOLVE_DEFAULTS.keyframeWaitTimeoutMs,
    'the local-evidence cap must be shorter than the full budget, or it is not a cap');
});

test('a proven cycle still waits', async () => {
  const { solver, element, probes } = gated({ mode: 'cycle', screens: 3 });
  assert.equal(await solver.waitForKeyframe(element, '/tmp/kf.png', 0.5, 0.5), true);
  assert.ok(probes() >= 1);
});

test('the gate polls until the screen comes round, then reports the match', async () => {
  const { solver, element, probes } = gated({ mode: 'even', screens: 2, matchAfter: 5 });
  assert.equal(await solver.waitForKeyframe(element, '/tmp/kf.png', 0.5, 0.5), true);
  assert.equal(probes(), 5, 'it must keep looking, not answer from the first frame');
});

test('the pointer is parked on the target BEFORE the gate opens', async () => {
  const solver: any = photographsItself(new CaptchaKrakenSolver({ keyframeWaitPollMs: 1 }));
  solver.keyframeMode = 'even';
  solver.keyframeSteadyScreens = 3;

  const events: string[] = [];
  solver.runCvTool = async () => { events.push('probe'); return { match: true, diff: 0.01 }; };
  solver.human = {
    move: async (_p: any, to: [number, number]) => { events.push(`move:${to[0]},${to[1]}`); },
    click: async (_p: any, to: [number, number]) => { events.push(`click:${to[0]},${to[1]}`); },
    pause: async () => {},
  };

  const element: any = { screenshot: async () => undefined };
  const box = { x: 100, y: 200, width: 300, height: 400 };
  await solver.clickWhenFrameMatches(
    {} as any, element,
    { action: 'click', target_bounding_box: [0.4, 0.4, 0.6, 0.6] },
    box, '/tmp/kf.png',
  );

  const moved = events.findIndex((e) => e.startsWith('move:'));
  const probed = events.indexOf('probe');
  const clicked = events.findIndex((e) => e.startsWith('click:'));
  assert.ok(moved >= 0 && probed >= 0 && clicked >= 0, `missing step in ${events.join(' ')}`);
  assert.ok(moved < probed, `pointer must be parked before the gate opens: ${events.join(' ')}`);
  assert.ok(probed < clicked, `the click must come after the match: ${events.join(' ')}`);

  assert.equal(events[clicked].slice('click:'.length), events[moved].slice('move:'.length),
    `parked and pressed different points: ${events.join(' ')}`);
});

test('the wait budget can hold one worst-case cycle', () => {
  const budget = SOLVE_DEFAULTS.keyframeWaitTimeoutMs;
  assert.ok(budget >= 8_100,
    `keyframeWaitTimeoutMs is ${budget}ms; a 3-screen cycle runs to 8100ms`);
});

test('the gate stops early once the widget is clearly a different board', async () => {
  const solver: any = photographsItself(new CaptchaKrakenSolver({ keyframeWaitPollMs: 1 }));
  solver.keyframeMode = 'even';
  solver.keyframeSteadyScreens = 3;
  let probes = 0;
  solver.runCvTool = async () => { probes += 1; return { match: false, diff: 0.77 }; };
  const element: any = { screenshot: async () => undefined };

  const t0 = Date.now();
  const matched = await solver.waitForKeyframe(element, '/tmp/kf.png', 0.5, 0.5);
  const took = Date.now() - t0;

  assert.equal(matched, false);
  assert.ok(probes <= 5, `gave up after ${probes} polls; it should need only a few`);
  assert.ok(took < 2_000, `spent ${took}ms deciding the board was gone`);
});

test('a WRONG SCREEN of the right board is still waited for', async () => {
  const solver: any = photographsItself(new CaptchaKrakenSolver({ keyframeWaitPollMs: 1 }));
  solver.keyframeMode = 'even';
  solver.keyframeSteadyScreens = 3;
  let probes = 0;
  solver.runCvTool = async () => {
    probes += 1;
    return probes >= 8 ? { match: true, diff: 0.0 } : { match: false, diff: 0.0056 };
  };
  const element: any = { screenshot: async () => undefined };
  assert.equal(await solver.waitForKeyframe(element, '/tmp/kf.png', 0.5, 0.5), true);
  assert.equal(probes, 8, 'it gave up on the right board while the wrong screen was up');
});

test('a cycling board is recorded after ONE round, not two', async () => {
  const solver: any = photographsItself(new CaptchaKrakenSolver({}));
  let changes = 0;
  solver.captchaFrameChangedSince = async () => { changes += 1; return true; };
  solver.answerFor = async (_k: string, run: () => any) => run();
  const el: any = { screenshot: async () => undefined };
  let queries = 0;
  await solver.solveFrameFreshnessGuarded(el, '/tmp/shot.png', async () => {
    queries += 1;
    return { actions: [], token_usage: [] };
  });
  assert.equal(solver.shouldRetryAsAnimated('unknown'), true,
    'two changes in one round and it still wants another round to be sure');
  assert.ok(queries <= 2, `${queries} inferences spent re-solving a board that never holds still`);
});

test('a board we have already touched is not re-classified by filming it', async () => {
  const solver: any = photographsItself(new CaptchaKrakenSolver({}));
  let filmed = 0;
  solver.startKeyframeBurst = () => {
    filmed += 1;
    return {
      moved: () => true, screensSeen: () => 9, stableFrame: () => null,
      ready: async () => SettleVerdict.ANIMATED, verdict: async () => true,
      abandon: async () => {}, finish: async () => '/tmp/nope',
    };
  };
  const element: any = { screenshot: async () => undefined };

  assert.equal(await solver.classifyByRecording(element), SettleVerdict.ANIMATED);
  assert.equal(filmed, 1);

  solver.actedOnBoard = true;
  assert.equal(await solver.classifyByRecording(element), SettleVerdict.SETTLED);
  assert.equal(filmed, 1, 'a touched board must not be filmed to classify it');
});
