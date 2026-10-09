// Masked to the handle's band the loop derived a 135.4px piece on Tencent's track; masked to the widget's bottom, 42.0px. The mask must be
// in the shot's pixel space, not CSS pixels.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';

import { CaptchaKrakenSolver } from './solver';
import { fakeDom, photographsItself } from './fake-dom.test';

const DPR = 2.625;
const WIDGET_W = 400;
const WIDGET_H = 400;
const PIECE_LEFT = 10;
const PIECE_W = 40;
const HANDLE = { x: 120, y: 420, width: 40, height: 30 };
const ELEMENT = { x: 100, y: 100, width: WIDGET_W, height: WIDGET_H };

function writePng(file: string, width: number, height: number): void {
  const ihdr = Buffer.alloc(13);
  ihdr.writeUInt32BE(width, 0);
  ihdr.writeUInt32BE(height, 4);
  ihdr[8] = 8; ihdr[9] = 2;
  const len = Buffer.alloc(4); len.writeUInt32BE(13, 0);
  fs.writeFileSync(file, Buffer.concat([
    Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
    len, Buffer.from('IHDR'), ihdr, Buffer.alloc(4),
  ]));
}

function rig(targetPx: number, dpr: number) {
  const moves: Array<[number, number]> = [];
  const excludes: number[][] = [];
  const startX = HANDLE.x + HANDLE.width / 2;

  const element: any = {
    screenshot: async ({ path: p }: { path: string }) =>
      writePng(p, Math.round(WIDGET_W * dpr), Math.round(WIDGET_H * dpr)),
  };
  const page: any = {
    mouse: {
      move: async (x: number, y: number) => { moves.push([x, y]); },
      down: async () => {},
      up: async () => {},
    },
  };
  const scope = fakeDom([{ matches: ['.geetest_slider_button'], box: { ...HANDLE } }]);

  const solver: any = photographsItself(new CaptchaKrakenSolver({}));
  solver.trackPiece = async (
    _el: unknown, _before: string, _after: string, exclude: number[],
  ) => {
    excludes.push([...exclude]);
    const offset = moves[moves.length - 1][0] - startX;
    const right = PIECE_LEFT + PIECE_W + offset;

    return {
      bbox: [Math.round(PIECE_LEFT * dpr), 0, Math.round(right * dpr), Math.round(20 * dpr)],
      piece: null,
    };
  };

  const frac = targetPx / WIDGET_W;
  const action = { target_bounding_box: [frac, 0.4, frac, 0.6] };
  return { solver, page, element, scope, action, moves, excludes, startX };
}

test('a hidpi screen still lands the piece on the slot', async () => {
  const r = rig(150, DPR);
  await r.solver.executeSlide(r.page, r.element, r.scope, r.action, ELEMENT);
  const releasedAt = r.moves[r.moves.length - 1][0];
  assert.ok(
    Math.abs((releasedAt - r.startX) - 120) <= 2,
    `released at ${releasedAt - r.startX}px of travel, wanted 120`,
  );
});

test("the handle's mask is in the shot's pixel space", async () => {
  const r = rig(150, DPR);
  await r.solver.executeSlide(r.page, r.element, r.scope, r.action, ELEMENT);

  const [x1, y1, x2, y2] = r.excludes[0];
  assert.equal(x1, 0);
  assert.ok(Math.abs(x2 - WIDGET_W * DPR) <= 1, `mask spans ${x2}, wanted ${WIDGET_W * DPR}`);
  assert.ok(y1 <= 320 * DPR && y2 >= 350 * DPR, `mask covers ${y1}..${y2}, not the handle`);
});

test('a 1x screen is unchanged', async () => {
  const r = rig(150, 1);
  await r.solver.executeSlide(r.page, r.element, r.scope, r.action, ELEMENT);
  const releasedAt = r.moves[r.moves.length - 1][0];
  assert.ok(Math.abs((releasedAt - r.startX) - 120) <= 2);

  const [x1, y1, x2, y2] = r.excludes[0].map(Math.round);
  assert.deepEqual([x1, y1, x2], [0, 310, WIDGET_W], 'the band is not the raw CSS box');
  assert.equal(y2, WIDGET_H, 'the mask must reach the bottom of the widget');
});

