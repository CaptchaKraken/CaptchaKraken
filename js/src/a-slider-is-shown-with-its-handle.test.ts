// Yidun's float layout pops its 320x175 picture (.yidun_panel) above a separate 320x40 bar (.yidun_control) with the handle.
// Every board the pointer trained on shows the bar; on the bare panel it had no handle to name and dragged the piece,
// which Yidun ignores (live 0/8). The shot covers the panel and the bar under it, and nothing far away.
import { test } from 'node:test';
import assert from 'node:assert/strict';

import { withAnswerBox } from './solver';

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
