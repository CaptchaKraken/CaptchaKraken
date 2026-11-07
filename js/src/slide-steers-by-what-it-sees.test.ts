// The JS slide loop against a simulated tracker: the Python port's tests drive the real tracker on rendered boards, and
// these hold the TypeScript driver to the same contract — where it presses, how it converts shot pixels, what it
// sends back as history, and when it lets go.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';

import { CaptchaKrakenSolver } from './solver';
import { fakeDom, photographsItself } from './fake-dom.test';

const ELEMENT = { x: 100, y: 60, width: 340, height: 220 };
const HANDLE = [30, 197] as const;        // element-relative CSS
const PIECE = [46, 104] as const;
const SLOT = [234, 104] as const;

function writePng(file: string, width: number, height: number): void {
  const ihdr = Buffer.alloc(13);
  ihdr.writeUInt32BE(width, 0);
  ihdr.writeUInt32BE(height, 4);
  ihdr[8] = 8; ihdr[9] = 2;
  const len = Buffer.alloc(4); len.writeUInt32BE(13, 0);
  fs.writeFileSync(file, Buffer.concat([
    Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]), len, Buffer.from('IHDR'), ihdr, Buffer.alloc(4),
  ]));
}

const box = (p: readonly number[]): [number, number, number, number] =>
  [(p[0] - 2) / ELEMENT.width, (p[1] - 2) / ELEMENT.height, (p[0] + 2) / ELEMENT.width, (p[1] + 2) / ELEMENT.height];

interface Rig {
  presses: [number, number][];
  moves: [number, number][];
  releases: number;
  requests: any[];
  asked: string[];
}

/**
 * The piece moves `ratio` shot pixels per shot pixel of pointer travel; the simulated tracker reads its position off
 * the pointer exactly as the real one reads it off the pixels, and plans with the ratio it was told about.
 */
async function drive(action: any, opts: { dpr?: number; ratio?: number; grabbed?: boolean; lost?: boolean;
  scope?: any } = {}): Promise<Rig> {
  const dpr = opts.dpr ?? 1;
  const ratio = opts.ratio ?? 1.27;
  const rig: Rig = { presses: [], moves: [], releases: 0, requests: [], asked: [] };
  let at: [number, number] = [0, 0];
  let down: [number, number] | null = null;

  const solver: any = photographsItself(new CaptchaKrakenSolver({}));
  solver.human = {
    at: [0, 0],
    move: async (_p: unknown, xy: [number, number]) => { at = [xy[0], xy[1]]; rig.moves.push(at); },
    press: async () => { down = at; rig.presses.push(at); },
    release: async () => { rig.releases += 1; },
    pause: async () => {},
  };
  solver.runCvTool = async (cmd: string, req: any) => {
    assert.equal(cmd, 'slide-step');
    rig.requests.push(JSON.parse(JSON.stringify(req)));
    if (opts.lost) return { error: 'nothing moved between the press and the probe' };
    const travel = ((at[0] - down![0]) * dpr);
    const dy = (at[1] - down![1]) * dpr;
    // Without a seed (generation 2) the tracker follows whatever moved most: here, the piece.
    const obj: number[] = req.seed ?? [PIECE[0] * dpr, PIECE[1] * dpr];
    const pos: [number, number] = opts.grabbed ? [obj[0] + travel, obj[1] + dy] : [obj[0] + ratio * travel, obj[1]];
    const error = Math.hypot(req.goal[0] - pos[0], req.goal[1] - pos[1]);
    const next = opts.grabbed ? [travel + req.goal[0] - pos[0], dy + req.goal[1] - pos[1]] : travel + (req.goal[0] - pos[0]) / ratio;
    return {
      pos, params: [0, pos[0] - obj[0], 0], error, grabbed: !!opts.grabbed, kind: 'slide', next, done: error <= req.tol,
      correlation: 0.99, observation: { s: req.s, params: [0, pos[0] - obj[0], 0] },
    };
  };
  const element: any = {
    screenshot: async ({ path: p }: { path: string }) => writePng(p, ELEMENT.width * dpr, ELEMENT.height * dpr),
  };
  const scope = opts.scope ?? { locator: (sel: string) => { rig.asked.push(sel); return fakeDom([]).locator(sel); } };
  assert.equal(await solver.executeSlide({}, element, scope, action, ELEMENT), true);
  return rig;
}

const slide = { action: 'slide', handle_bounding_box: box(HANDLE), source_bounding_box: box(PIECE), target_bounding_box: box(SLOT) };

test('a generation-3 slide presses where the answer names the handle, and reads nothing off the page', async () => {
  const rig = await drive(slide);
  assert.deepEqual(rig.presses, [[ELEMENT.x + HANDLE[0], ELEMENT.y + HANDLE[1]]]);
  assert.deepEqual(rig.asked, []);
  assert.equal(rig.releases, 1);
});

test('the probe nudges toward the target and the tracker is told the piece, the goal and the handle in shot pixels', async () => {
  const rig = await drive(slide, { dpr: 2 });
  const first = rig.requests[0];
  assert.equal(first.probe_s, 16);
  assert.deepEqual(first.seed.map(Math.round), [92, 208]);
  assert.deepEqual(first.goal.map(Math.round), [468, 208]);
  assert.deepEqual(first.handle.map(Math.round), [60, 394]);
  assert.equal(first.current, first.probe, 'the first look is the probe itself');
});

test('the handle ends where the piece sits on the slot, at any device pixel ratio', async () => {
  for (const dpr of [1, 2]) {
    const rig = await drive(slide, { dpr });
    const travel = rig.moves[rig.moves.length - 1][0] - rig.presses[0][0];
    assert.ok(Math.abs(PIECE[0] + 1.27 * travel - SLOT[0]) <= 2, `dpr ${dpr}: piece at ${PIECE[0] + 1.27 * travel}`);
  }
});

test('history carries every look after the probe and never the probe itself', async () => {
  const rig = await drive(slide, { ratio: 1.27 });
  assert.equal(rig.requests[0].history.length, 0);
  for (let i = 1; i < rig.requests.length; i++) assert.equal(rig.requests[i].history.length, i - 1);
});

test('a part the tracker cannot follow is released where it is, not swept by a guess', async () => {
  const rig = await drive(slide, { lost: true });
  assert.equal(rig.presses.length, 1);
  assert.equal(rig.releases, 1);
  assert.equal(rig.moves.length, 2, 'moved to the handle and probed, nothing more');
});

test('a carried piece is steered in two dimensions', async () => {
  const carried = { ...slide, handle_bounding_box: box(PIECE), target_bounding_box: box([SLOT[0], SLOT[1] + 20]) };
  const rig = await drive(carried, { grabbed: true });
  const [x, y] = rig.moves[rig.moves.length - 1];
  assert.ok(Math.abs(x - (ELEMENT.x + SLOT[0])) <= 2 && Math.abs(y - (ELEMENT.y + SLOT[1] + 20)) <= 2, `ended at ${x}, ${y}`);
});

test('a generation-2 slide finds its handle by selector and tracks whatever it moved', async () => {
  const handleBox = { x: ELEMENT.x + HANDLE[0] - 18, y: ELEMENT.y + HANDLE[1] - 14, width: 36, height: 28 };
  const scope = fakeDom([{ matches: ['.geetest_slider_button'], box: handleBox }]);
  const rig = await drive({ action: 'drag', source_bounding_box: null, target_bounding_box: box(SLOT) }, { scope });
  assert.deepEqual(rig.presses, [[ELEMENT.x + HANDLE[0], ELEMENT.y + HANDLE[1]]]);
  assert.equal(rig.requests[0].seed, null);
});
