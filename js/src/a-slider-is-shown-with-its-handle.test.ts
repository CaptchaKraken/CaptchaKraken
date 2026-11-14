// Yidun's float layout pops its 320x175 picture (.yidun_panel) above a separate 320x40 bar (.yidun_control) with the handle.
// Every board the pointer trained on shows the bar; on the bare panel it had no handle to name and dragged the piece,
// which Yidun ignores (live 0/8). The shot covers the panel and the bar under it, and nothing far away.
import { test } from 'node:test';
import assert from 'node:assert/strict';

import { CaptchaKrakenSolver, withAnswerBox } from './solver';
import { DEFAULT_TABLE, SELECTORS } from './selectors';
import { Vendor } from './kinds';

function handle(box: { x: number; y: number; width: number; height: number }): any {
  return { boundingBox: async () => box, contentFrame: async () => null, tag: 'panel' };
}

// The live page, 2026-11-12: panel at (630.5, 621) 320x175, bar at (630.5, 796) 320x40.
const panel = { x: 630.5, y: 621, width: 320, height: 175 };

test('the shot covers the Yidun panel and the bar under it', async () => {
  const el = withAnswerBox(handle(panel), handle({ x: 630.5, y: 796, width: 320, height: 40 }), 2);
  assert.deepEqual(await el.boundingBox(), { x: 630.5, y: 621, width: 320, height: 215 });
  assert.equal((el as any).tag, 'panel');
});

test('a track that would more than double the shot leaves it alone', async () => {
  const el = withAnswerBox(handle(panel), handle({ x: 630.5, y: 1100, width: 320, height: 40 }), 2);
  assert.deepEqual(await el.boundingBox(), panel);
});

// Yidun's click modes (请依次点击) put the prompt naming the marks, and their order, in that same bar, with no slider
// handle in it. On the bare panel the pointer saw no prompt and went 0/6 live on 2026-11-13; with the bar, 20/20.

const bar = { x: 630.5, y: 796, width: 320, height: 40 };

/** A scope holding `found[selector]` elements; `xpath=ancestor::*[1]` is the scope `parent`. */
function scope(found: Record<string, any[]>, parent?: any): any {
  return {
    locator: (q: string) => q.startsWith('xpath=ancestor') ? (q.endsWith('[1]') ? parent ?? scope({}) : scope({}))
      : { filter: () => ({ all: async () => found[q] ?? [] }) },
  };
}
const located = (box: typeof panel): any => ({
  elementHandle: async () => handle(box), locator: () => ({ elementHandle: async () => handle({ ...box, height: 215 }) }),
});
const solver = (): any => Object.assign(Object.create(CaptchaKrakenSolver.prototype), { sel: DEFAULT_TABLE });

test('the shipped config names Yidun\'s bar', () => {
  assert.ok(SELECTORS[Vendor.YIDUN].bar?.includes('.yidun_control'));
});

test('a click board is shown with its prompt bar, taken itself and not its parent', async () => {
  const at = scope({}, scope({ '.yidun_control': [located(bar)] }));
  const got = await solver().trackOutside(scope({}), Vendor.YIDUN, handle(panel), at);
  assert.deepEqual(await got.boundingBox(), bar);
  assert.deepEqual(await withAnswerBox(handle(panel), got, 2).boundingBox(), { x: 630.5, y: 621, width: 320, height: 215 });
});

test('a bar inside the widget does not widen the shot', async () => {
  const inside = { x: 630.5, y: 700, width: 320, height: 40 };
  const got = await solver().trackOutside(scope({ '.yidun_control': [located(inside)] }), Vendor.YIDUN, handle(panel), null);
  assert.equal(got, null);
});
