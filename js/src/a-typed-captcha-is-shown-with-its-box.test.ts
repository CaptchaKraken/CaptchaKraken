// BotDetect's widget is a 280x50 strip holding only the image; every board the pointer trained on shows the text
// box under it. On the bare strip it read the image as a click puzzle, so the shot covers the image and its box.
import { test } from 'node:test';
import assert from 'node:assert/strict';

import { withAnswerBox } from './solver';

function handle(box: { x: number; y: number; width: number; height: number }): any {
  return { boundingBox: async () => box, contentFrame: async () => null, tag: 'image' };
}

test('the shot covers the image and the text box under it', async () => {
  const el = withAnswerBox(handle({ x: 10, y: 10, width: 280, height: 50 }), handle({ x: 10, y: 64, width: 200, height: 22 }));
  assert.deepEqual(await el.boundingBox(), { x: 10, y: 10, width: 280, height: 76 });
  assert.equal((el as any).tag, 'image');
  assert.equal(await el.contentFrame(), null);
});

test('a text box far from the image leaves the shot alone', async () => {
  const el = withAnswerBox(handle({ x: 10, y: 10, width: 280, height: 50 }), handle({ x: 10, y: 600, width: 200, height: 22 }));
  assert.deepEqual(await el.boundingBox(), { x: 10, y: 10, width: 280, height: 50 });
});
