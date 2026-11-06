// A slide submits itself on release, so nothing is pressed after one: a Verify found then may be the host page's form.
// A board that has already taken a Verify from us is the exception. That button is the widget's, nothing else will
// submit the slide, and the piece it moved would be left on the board for the next plan to start from.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';

import { CaptchaKrakenSolver } from './solver';

const SLIDE = {
  action: 'slide',
  handle_bounding_box: [0.32, 0.86, 0.36, 0.9],
  source_bounding_box: [0.1, 0.4, 0.14, 0.44],
  target_bounding_box: [0.35, 0.4, 0.4, 0.6],
};

function round(submittedOnBoard: boolean): { solver: any; pressed: string[] } {
  const solver: any = new CaptchaKrakenSolver({});
  const pressed: string[] = [];
  solver.submittedOnBoard = submittedOnBoard;
  solver.answerBox = async () => null;
  solver.classifyByRecording = async () => 'settled';
  solver.isCaptchaSolved = async () => false;
  solver.waitForBoardPainted = async () => ({ waitedMs: 0 });
  solver.stepOffTheBoard = async () => {};
  solver.shot = async (_el: any, dest: string) => fs.writeFileSync(dest, 'board');
  solver.captchaFrameChangedSince = async () => false;
  solver.shouldSpeculate = () => false;
  solver.askModel = async () => ({ actions: [SLIDE], token_usage: [] });
  solver.executeSlide = async () => true;
  solver.getVerifyButton = async () => 'verify';
  solver.moveAndClick = async (_page: any, button: string) => { pressed.push(button); };
  solver.elementFrameHash = async () => null;
  solver.emitStep = async () => {};
  return { solver, pressed };
}

const widget = {
  el: { contentFrame: async () => null, boundingBox: async () => ({ x: 0, y: 0, width: 300, height: 200 }) },
  at: {},
  vendor: 'hcaptcha',
  role: 'challenge',
};

test('a slide is not followed by a Verify on a board that has not taken one', async () => {
  const { solver, pressed } = round(false);
  await solver.solveSingle({}, widget, 1, null);
  assert.deepEqual(pressed, []);
});

test('a slide is submitted on a board that has already taken a Verify', async () => {
  const { solver, pressed } = round(true);
  await solver.solveSingle({}, widget, 1, null);
  assert.deepEqual(pressed, ['verify']);
});
