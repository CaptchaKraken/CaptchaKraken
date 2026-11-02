// A board the model has no answer for is skipped, as a person would. Measured on the Tier 3 gauntlet, 2026-10-27:
// the engine's "cannot solve" bypassed "an empty plan still presses Verify/Skip", and the driver re-asked about the
// same, pixel-identical board until the loop cap (~30s) instead of pressing Skip for a new one.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';

import { CaptchaKrakenSolver } from './solver';

function round(vendor: string, textBox: boolean): { solver: any; pressed: string[] } {
  const solver: any = new CaptchaKrakenSolver({});
  const pressed: string[] = [];
  solver.answerBox = async () => (textBox ? 'box' : null);
  solver.classifyByRecording = async () => 'settled';
  solver.isCaptchaSolved = async () => false;
  solver.waitForBoardPainted = async () => ({ waitedMs: 0 });
  solver.stepOffTheBoard = async () => {};
  solver.shot = async (_el: any, dest: string) => fs.writeFileSync(dest, 'board');
  solver.captchaFrameChangedSince = async () => false;
  solver.shouldSpeculate = () => false;
  solver.askModel = async () => {
    const e: any = new Error('UNSUPPORTED_CAPTCHA: Cannot solve this kind of captcha');
    e.unsupported = true;
    throw e;
  };
  solver.getVerifyButton = async () => 'skip';
  solver.moveAndClick = async (_page: any, button: string) => { pressed.push(button); };
  solver.elementFrameHash = async () => null;
  solver.emitStep = async () => {};
  return { solver, pressed };
}

const widget = (vendor: string) => ({
  el: { contentFrame: async () => null, boundingBox: async () => ({ x: 0, y: 0, width: 300, height: 200 }) },
  at: {},
  vendor,
  role: 'challenge',
});

test('a board with no answer presses Skip', async () => {
  const { solver, pressed } = round('hcaptcha', false);
  await solver.solveSingle({}, widget('hcaptcha'), 1, null);
  assert.deepEqual(pressed, ['skip'], 'no answer for this board, and the driver did not press Skip for a new one');
});

test('an unreadable text captcha is not submitted empty', async () => {
  // hCaptcha never types, so the text case is a generic widget.
  const { solver, pressed } = round('unknown', true);
  await assert.rejects(solver.solveSingle({}, widget('unknown'), 1, null), (e: any) => e?.unsupported === true);
  assert.deepEqual(pressed, []);
});
