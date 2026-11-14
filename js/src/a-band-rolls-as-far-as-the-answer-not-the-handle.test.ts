// DingXiang's restore: the handle rolls one of two picture strips by its background, which strip and how far per
// handle pixel dealt per board (measured live: 0.52 to 1.77, and on some boards the upper strip rolls instead). The
// slide must stop when the strip has rolled as far as the answer's two points are apart, read off the DOM, whatever
// the handle travelled to get there.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';

import { CaptchaKrakenSolver, bandRoll } from './solver';
import { Vendor } from './kinds';
import { fakeDom, photographsItself } from './fake-dom.test';

// The live card, 412x335: picture x 16..396, cut 92 px below its top at y 54, handle at (51, 252).
const ELEMENT = { x: 434, y: 326, width: 412, height: 335 };
const HANDLE = [51, 252] as const;
const UPPER = { x: ELEMENT.x + 16, y: ELEMENT.y + 54, width: 380, height: 92 };
const LOWER = { x: ELEMENT.x + 16, y: ELEMENT.y + 146, width: 380, height: 73 };
const PERIOD = 380;

const box = (p: readonly number[]): [number, number, number, number] =>
  [(p[0] - 2) / ELEMENT.width, (p[1] - 2) / ELEMENT.height, (p[0] + 2) / ELEMENT.width, (p[1] + 2) / ELEMENT.height];

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

/** Drive one slide on a card whose `rolls` strip ('upper', 'lower' or neither) moves `slope` px per handle px. */
async function drive(action: any, rolls: 'upper' | 'lower' | null, slope: number) {
  let at: [number, number] = [0, 0];
  let down: [number, number] | null = null;
  const travel = () => (down ? at[0] - down[0] : 0);
  const style = (which: 'upper' | 'lower') => ({
    get backgroundPositionX() { return `${rolls === which ? slope * travel() : 0}px`; },
    backgroundSize: `${PERIOD}px 165px`,
  });
  const nodes = [
    { matches: ['.dx_captcha_basic_pic .upper'], box: UPPER, style: style('upper') },
    { matches: ['.dx_captcha_basic_pic .lower'], box: LOWER, style: style('lower') },
  ];
  const g = globalThis as any;
  const before = g.getComputedStyle;
  g.getComputedStyle = (el: any) => el.style;
  const tracked: unknown[] = [];
  const solver: any = photographsItself(new CaptchaKrakenSolver({}));
  solver.human = {
    at: [0, 0],
    move: async (_p: unknown, xy: [number, number]) => { at = [xy[0], xy[1]]; },
    press: async () => { down = at; },
    release: async () => {},
    pause: async () => {},
  };
  solver.runCvTool = async (_cmd: string, req: unknown) => { tracked.push(req); return { error: 'the pixel tracker was asked' }; };
  const element: any = { screenshot: async ({ path: p }: { path: string }) => writePng(p, ELEMENT.width, ELEMENT.height) };
  try {
    assert.equal(await solver.executeSlide({}, element, fakeDom(nodes as any), action, ELEMENT, Vendor.DINGXIANG), true);
  } finally {
    g.getComputedStyle = before;
  }
  return { rolled: slope * travel(), travel: travel(), tracked };
}

// The answer as trained: a point on the lower strip just below the cut, and where it belongs just above it.
const restore = (from: number, to: number) => ({
  action: 'slide', handle_bounding_box: box(HANDLE), source_bounding_box: box([from, 149]), target_bounding_box: box([to, 142]),
});

test('the lower strip stops where it has rolled the answer, at every slope the live widget dealt', async () => {
  for (const slope of [0.52, 0.72, 0.92, 1.15, 1.77]) {
    const { rolled, tracked } = await drive(restore(60, 180), 'lower', slope);
    assert.ok(Math.abs(rolled - 120) <= 2, `slope ${slope}: rolled ${rolled.toFixed(1)}px for a 120px answer`);
    assert.deepEqual(tracked, [], 'a strip the DOM measures is not handed to the pixel tracker');
  }
});

test('when the upper strip rolls, it carries the target round to the point instead', async () => {
  // The target is 250 px right of the point; rolling the upper strip right brings it round in 380 - 250 = 130 px.
  const { rolled } = await drive(restore(40, 290), 'upper', 0.6);
  assert.ok(Math.abs(rolled - 130) <= 2, `rolled ${rolled.toFixed(1)}px, wanted 130`);
});

test('a slide no strip follows is handed to the pixel tracker, not steered by a zero', async () => {
  const { tracked } = await drive(restore(60, 180), null, 1);
  assert.equal(tracked.length, 1);
});

test('the roll is read the way the probe went, within one turn of the picture', () => {
  const read = (x: number, top: number) => ({ x, top, bottom: top + 50, period: 380 });
  const rest = [read(0, 0), read(0, 50)];
  // The point's own strip rolls right: target 30 px LEFT of it means nearly a whole turn.
  assert.deepEqual(bandRoll(rest, [read(0, 0), read(4, 50)], [100, 60], [70, 40]), { band: 1, roll: 350 });
  // A strip that rolls left reaches the meeting the other way round, as a negative roll.
  assert.deepEqual(bandRoll(rest, [read(0, 0), read(-4, 50)], [100, 60], [130, 40]), { band: 1, roll: -350 });
  assert.equal(bandRoll(rest, [read(0.2, 0), read(0, 50)], [100, 60], [130, 40]), null, 'under half a pixel is not a roll');
});
