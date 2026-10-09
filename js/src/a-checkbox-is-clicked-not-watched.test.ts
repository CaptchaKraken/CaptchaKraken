// A checkbox is ticked, never treated as a board: no load poll, no film, no model call. Measured before this: one
// solve polled the checkbox 28 times while waiting for it to "paint", filmed it for 4s (42 frames), and asked the
// model about the checkbox picture three times — twice it answered with a drag. Mirror of
// python/tests/test_a_checkbox_is_clicked_not_watched.py.
import { test } from 'node:test';
import assert from 'node:assert/strict';

import { CaptchaKrakenSolver } from './solver';
import { FrameRole, Vendor } from './kinds';

const WIDGET_BOX = { x: 33, y: 237, width: 302, height: 76 };
const TICK_BOX = { x: 49, y: 260, width: 30, height: 30 };

const handle = (box: any, frame: any = null): any => ({
  boundingBox: async () => box,
  contentFrame: async () => frame,
  scrollIntoViewIfNeeded: async () => {},
});

/** The checkbox frame; `box` null is a frame whose box the DOM cannot reach. */
function checkboxFrame(box: any | null) {
  const asked: string[] = [];
  return {
    asked,
    waitForSelector: async (selector: string) => {
      asked.push(selector);
      if (!box) throw new Error('Timeout 10ms exceeded.');
      return box;
    },
  };
}

async function round(vendor: Vendor, frame: any) {
  const solver: any = new CaptchaKrakenSolver({ humanization: 'none', postSolveOutcomePollMs: 1 });
  const pressedAt: Array<[number, number]> = [];
  let at: [number, number] = [0, 0];
  const page: any = {
    viewportSize: () => ({ width: 1280, height: 900 }),
    mouse: { move: async (x: number, y: number) => { at = [x, y]; }, down: async () => { pressedAt.push(at); }, up: async () => {} },
  };
  solver.page = page;
  const checkbox = { el: handle(WIDGET_BOX, frame), at: null, vendor, role: FrameRole.CHECKBOX };
  const challenge = { el: handle({ x: 90, y: 11, width: 520, height: 570 }), at: null, vendor, role: FrameRole.CHALLENGE };
  const seen = { captures: 0, asks: 0, detects: 0 };
  const boardPath = async () => { throw new Error('a checkbox went down the board path'); };

  solver.shot = async () => { seen.captures++; };
  solver.runCvTool = async (cmd: string) => {
    assert.equal(cmd, 'find-checkbox');
    return [16, 23, 30, 30];
  };
  solver.shotScale = () => 1;
  solver.getSolution = async () => { seen.asks++; throw new Error('the model was asked about a checkbox'); };
  solver.getAnimatedSolution = solver.getSolution;
  solver.waitForBoardPainted = boardPath;
  solver.classifyByRecording = boardPath;
  solver.startKeyframeBurst = () => { throw new Error('a checkbox was filmed'); };
  solver.detectCaptcha = async () => (++seen.detects < 3 ? checkbox : challenge);
  solver.isCaptchaSolved = async () => false;
  const result = await solver.solveSingle(page, checkbox, 1);
  return { result, pressedAt, seen };
}

const inside = ([x, y]: [number, number], b: typeof TICK_BOX) => x >= b.x && x <= b.x + b.width && y >= b.y && y <= b.y + b.height;

for (const vendor of [Vendor.HCAPTCHA, Vendor.RECAPTCHA]) {
  test(`a ${vendor} checkbox the DOM can reach is ticked with no capture and no model`, async () => {
    const frame = checkboxFrame(handle(TICK_BOX));
    const { result, pressedAt, seen } = await round(vendor, frame);
    assert.ok(frame.asked.length, 'the box was not looked for inside the checkbox frame');
    assert.equal(seen.captures, 0, `${seen.captures} capture(s) of a checkbox`);
    assert.equal(seen.asks, 0);
    assert.deepEqual(result.tokenUsage, []);
    assert.ok(result.didInteract);
    assert.equal(pressedAt.length, 1, 'the box was not clicked exactly once');
    assert.ok(inside(pressedAt[0], TICK_BOX), `clicked ${pressedAt[0]}, outside the tick box`);
    assert.equal(seen.detects, 3, 'the round returned before the challenge had opened, so the next one re-clicks');
  });
}

for (const [name, vendor, frame] of [['no DOM selector', Vendor.TURNSTILE, null], ['a frame that refuses access', Vendor.HCAPTCHA, checkboxFrame(null)]] as const) {
  test(`a box the DOM cannot reach is found on one capture with no model (${name})`, async () => {
    const { result, pressedAt, seen } = await round(vendor, frame);
    assert.equal(seen.captures, 1, `${seen.captures} captures; one photograph finds a box that does not move`);
    assert.equal(seen.asks, 0);
    assert.deepEqual(result.tokenUsage, []);
    assert.equal(pressedAt.length, 1);
    assert.ok(inside(pressedAt[0], { x: 33 + 16, y: 237 + 23, width: 30, height: 30 }), `clicked ${pressedAt[0]}, outside the tick box OpenCV found`);
  });
}
