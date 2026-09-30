// `animations: 'disabled'` waits for stillness, which once made every step snapshot cost 8s on a trace.
import { test } from 'node:test';
import assert from 'node:assert/strict';

import { CaptchaKrakenSolver } from './solver';
import { photographsItself } from './fake-dom.test';

const MAX_STEP_SNAPSHOT_MS = 3000;

function seen(config: Record<string, any> = {}) {
  const shots: any[] = [];
  const solver: any = photographsItself(new CaptchaKrakenSolver({ onStep: async () => {}, ...config }));
  const element = { screenshot: async (opts: any) => { shots.push(opts); } };
  return { solver, element, shots };
}

test('the step snapshot has its own short budget', async () => {
  const { solver, element, shots } = seen({ elementScreenshotTimeoutMs: 8000 });
  await solver.emitStep(element, 'initial', 'x', 'unknown', 'challenge', 1);

  assert.equal(shots.length, 1);
  assert.ok(shots[0].timeout <= MAX_STEP_SNAPSHOT_MS,
    `an onStep snapshot may block the solve for ${shots[0].timeout}ms. That is `
    + "the model's screenshot budget, and this picture is a trace — with "
    + 'animations disabled it waits for the widget to stop moving, which on an '
    + 'animated challenge means the whole budget, on every step.');
});

test('the caller can still size it', async () => {
  const { solver, element, shots } = seen({ stepScreenshotTimeoutMs: 500 });
  await solver.emitStep(element, 'initial', 'x', 'unknown', 'challenge', 1);
  assert.equal(shots[0].timeout, 500);
});

test('no observer, no snapshot', async () => {
  const solver: any = photographsItself(new CaptchaKrakenSolver({}));
  const shots: any[] = [];
  await solver.emitStep({ screenshot: async (o: any) => { shots.push(o); } },
    'initial', 'x', 'unknown', 'challenge', 1);
  assert.equal(shots.length, 0);
});
