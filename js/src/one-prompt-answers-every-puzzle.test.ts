// Prompt generation 3: one prompt, one answer shape, and `refresh` for a board a person would not solve. The prompt,
// the parser and the grid live in the engine; this is the driver half. Mirror of
// python/tests/test_one_prompt_answers_every_puzzle.py.
import { strict as assert } from 'node:assert';
import test from 'node:test';

import { NullHumanizer } from './humanize.js';
import { ActionKind, SolveStage, Vendor } from './kinds.js';
import { REFRESH_SELECTORS, SELECTORS } from './selectors.js';
import { CaptchaKrakenSolver } from './solver';
import { fakeDom, FakeNode } from './fake-dom.test';

const BOX = { x: 0, y: 0, width: 400, height: 400 };
const AT_ARROW = { action: ActionKind.REFRESH, target_bounding_box: [0.09, 0.89, 0.11, 0.91] as [number, number, number, number] };

function driver(): { solver: any; page: any; at: Array<[number, number]> } {
  const at: Array<[number, number]> = [];
  const page = {
    mouse: { move: async (x: number, y: number) => { at.push([Math.round(x), Math.round(y)]); }, down: async () => {}, up: async () => {} },
    viewportSize: () => ({ width: 800, height: 600 }),
  };
  return { solver: new CaptchaKrakenSolver({ humanizer: new NullHumanizer() }) as any, page, at };
}

test('refresh is an action and a step of its own', () => {
  assert.equal(ActionKind.REFRESH, 'refresh');
  assert.equal(SolveStage.REFRESH, 'refresh');
});

test("the vendor's own control is pressed first", async () => {
  const { solver, page, at } = driver();
  const control: FakeNode = { matches: ['#recaptcha-reload-button'], box: { x: 300, y: 300, width: 20, height: 20 } };
  assert.equal(await solver.executeRefresh(page, null, fakeDom([control]), AT_ARROW, BOX), true);
  const [x, y] = at[at.length - 1];
  assert.ok(x >= 300 && x <= 320 && y >= 300 && y <= 320, `pressed ${x},${y}, not the control`);
});

test("without a control the model's point is pressed", async () => {
  const { solver, page, at } = driver();
  assert.equal(await solver.executeRefresh(page, null, fakeDom([]), AT_ARROW, BOX), true);
  const [x, y] = at[at.length - 1];
  assert.ok(x >= 35 && x <= 45 && y >= 355 && y <= 365, `pressed ${x},${y}`);
});

test('with neither the round ends having done nothing', async () => {
  const { solver, page, at } = driver();
  assert.equal(await solver.executeRefresh(page, null, fakeDom([]), { action: ActionKind.REFRESH }, BOX), false);
  assert.deepEqual(at, []);
});

test('a second refresh is a second board, not a repeated answer', () => {
  const { solver } = driver();
  const refresh = [AT_ARROW];
  assert.equal(solver.noteAnswer(refresh, null), false);
  assert.equal(solver.noteAnswer(refresh, null), false);
  assert.equal(solver.noProgressRounds, 0);
  const click = [{ action: ActionKind.CLICK, target_bounding_boxes: [[0.4, 0.4, 0.6, 0.6]] }];
  assert.equal(solver.noteAnswer(click, null), false);
  assert.equal(solver.noteAnswer(click, null), true, 'an ordinary repeated answer is still caught');
});

test('every refresh control is a vendor-named one', () => {
  assert.deepEqual(REFRESH_SELECTORS, Object.values(SELECTORS).flatMap((s) => s.refresh ?? []));
  assert.ok(REFRESH_SELECTORS.includes('#recaptcha-reload-button'));
});

test('the press-and-hold widget is found by its container', async () => {
  const widget = await (new CaptchaKrakenSolver({}) as any).detectCaptcha(fakeDom([{ matches: ['#px-captcha'] }]));
  assert.equal(widget.vendor, Vendor.HUMAN);
});
