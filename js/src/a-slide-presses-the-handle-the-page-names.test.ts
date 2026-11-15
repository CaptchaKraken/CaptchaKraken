// Two driver guards from the 2026-11-14 Tier 3 rerun (client 2383fbf). DataDome: a model answered a slide-to-end bar
// with its handle point on the target and its source on the real handle, and the press grabbed empty track. Proton: the
// board, its pieces and its Next live a frame below the widget's, and Verify was looked for in the wrong one.
import { test } from 'node:test';
import assert from 'node:assert/strict';

import { CaptchaKrakenSolver, boardFrame } from './solver';
import { DEFAULT_TABLE } from './selectors';

const element = { x: 100, y: 50, width: 600, height: 200 };
const named = { x: 140, y: 130, width: 40, height: 40 }; // board px 40-80, 80-120
const target: [number, number, number, number] = [400, 80, 440, 120];

function scope(boxes: Array<typeof named>, asked: string[] = []): any {
  const found = boxes.map((b) => ({ elementHandle: async () => ({ boundingBox: async () => b }) }));
  return { locator: (q: string) => { asked.push(q); return { filter: () => ({ all: async () => found }) }; } };
}
const press = (s: any, handle: [number, number], seed: [number, number]): Promise<[number, number]> =>
  (Object.assign(Object.create(CaptchaKrakenSolver.prototype), { sel: DEFAULT_TABLE }) as any)
    .pressPoint(s, element, handle, seed, target);

test('a handle answered on its target is pressed on the named handle', async () => {
  assert.deepEqual(await press(scope([named]), [420, 100], [60, 100]), [60, 100]);
});

test('a handle away from its target is pressed where the answer names it, and the page is not read', async () => {
  const asked: string[] = [];
  assert.deepEqual(await press(scope([named], asked), [60, 100], [300, 100]), [60, 100]);
  assert.deepEqual(asked, []);
});

test('a source on no named handle leaves the answer alone', async () => {
  assert.deepEqual(await press(scope([named]), [420, 100], [250, 100]), [420, 100]);
  assert.deepEqual(await press(scope([]), [420, 100], [60, 100]), [420, 100]);
});

test('a handle point that is itself on a named handle is kept', async () => {
  const onTarget = { x: 500, y: 130, width: 40, height: 40 };
  assert.deepEqual(await press(scope([named, onTarget]), [420, 100], [60, 100]), [420, 100]);
});

const frame = (children: any[] = []): any => ({ childFrames: () => children });
const owned = (owner: any): any => ({ ownerFrame: async () => owner });

test('a board in a frame below the widget becomes the scope', async () => {
  const board = frame();
  const widget = frame([frame([board])]);
  assert.equal(await boardFrame(owned(board), widget), board);
});

test('the widget frame, the host page and a sibling are no board', async () => {
  const sibling = frame();
  const widget = frame([frame()]);
  const page = frame([widget, sibling]);
  assert.equal(await boardFrame(owned(widget), widget), null);
  assert.equal(await boardFrame(owned(page), widget), null);
  assert.equal(await boardFrame(owned(sibling), widget), null);
  assert.equal(await boardFrame(owned(null), widget), null);
  assert.equal(await boardFrame(owned(frame()), null), null);
  assert.equal(await boardFrame({} as any, widget), null);
});
