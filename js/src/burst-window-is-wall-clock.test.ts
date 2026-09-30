import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import { resolve } from 'node:path';

import { CaptchaKrakenSolver } from './solver';
import { photographsItself } from './fake-dom.test';

const FLOOR_MS = 500;
const CEILING_MS = 1500;
const FRAME_COST_MS = 200;

function slowCamera(screens: string[]) {
  let n = 0;
  return {
    shots: () => n,
    element: {
      screenshot: async ({ path }: { path: string }) => {
        const body = screens[n % screens.length];
        n += 1;
        await new Promise((r) => setTimeout(r, FRAME_COST_MS));
        fs.writeFileSync(path, body);
      },
    } as any,
  };
}

function solver() {
  return photographsItself(new CaptchaKrakenSolver({
    videoBurstDurationMs: FLOOR_MS,
    videoBurstMaxMs: CEILING_MS,
    videoBurstFps: 10,
  })) as any;
}

test('a still board does not hold the burst longer than the floor', async () => {
  const cam = slowCamera(['one-screen']);
  const s = solver();
  const t0 = Date.now();
  const rec = s.startKeyframeBurst(cam.element);
  const { dir } = await rec.finish();
  const elapsed = Date.now() - t0;
  fs.rmSync(dir, { recursive: true, force: true });

  assert.ok(elapsed <= FLOOR_MS + FRAME_COST_MS * 2,
    `a still board held the burst for ${elapsed}ms against a ${FLOOR_MS}ms floor `
    + `(${cam.shots()} frames). The window is counted in frames, so a camera `
    + `slower than the interval spends the budget it was given`);
});

test('the floor is still a floor when the camera is fast', async () => {
  let n = 0;
  const element: any = {
    screenshot: async ({ path }: { path: string }) => {
      n += 1;
      fs.writeFileSync(path, 'one-screen');
    },
  };
  const s = solver();
  const t0 = Date.now();
  const rec = s.startKeyframeBurst(element);
  const { dir } = await rec.finish();
  const elapsed = Date.now() - t0;
  fs.rmSync(dir, { recursive: true, force: true });

  assert.ok(elapsed >= FLOOR_MS,
    `a still board was filmed for only ${elapsed}ms against a ${FLOOR_MS}ms floor (${n} frames)`);
});

test('a board that never settles stops at the ceiling in seconds', async () => {
  const cam = slowCamera(['a', 'b', 'c']);
  const s = solver();
  const t0 = Date.now();
  const rec = s.startKeyframeBurst(cam.element);
  const { dir } = await rec.finish();
  const elapsed = Date.now() - t0;
  fs.rmSync(dir, { recursive: true, force: true });

  assert.ok(elapsed <= CEILING_MS * 1.4,
    `a board that never settles filmed for ${elapsed}ms against a ${CEILING_MS}ms `
    + `ceiling (${cam.shots()} frames)`);
});

test('the recording reports the rate it achieved, not the one it aimed at', async () => {
  const cam = slowCamera(['one-screen']);
  const s = solver();
  const rec = s.startKeyframeBurst(cam.element);
  const { dir } = await rec.finish();
  fs.rmSync(dir, { recursive: true, force: true });

  assert.ok(s.lastBurstFps < 10,
    `the burst reported ${s.lastBurstFps}fps from a camera costing ${FRAME_COST_MS}ms a frame`);
});

test('the python port counts the same window in milliseconds', () => {
  const py = fs.readFileSync(resolve(
    __dirname, '..', '..', 'python', 'src', 'captchakraken', 'page_solver.py'), 'utf8');
  assert.ok(py.includes('elapsed_ms - last_new_ms >= floor_ms'),
    'the python burst still counts its settled window in frames');
});
