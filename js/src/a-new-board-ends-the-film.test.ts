// ONE FILM, ONE BOARD, at the point the board actually changes.
//
// The whole-solve camera keeps filming across rounds so each ask sees a longer film, and a recorded answer
// may be reused once — the widget refuses it, `noteAnswer` spots the repeat, and the next round re-asks. That
// reuse was never bounded to the board it was cut from. When the vendor deals a DIFFERENT puzzle, the plan
// survived it, and the next animated round replayed the old board's coordinates onto the new one.
//
// Measured live on 2026-09-16 (Abyss, hCaptcha, attempt 17 of the diagnosis run): a keyframe answer cut from
// round 3's board — `[[0.809, 0.088, 0.833, 0.112]]`, the top-right of the banner, which is where hCaptcha
// paints the REFERENCE PHOTO — was replayed in round 5 against a board two deals later, logged as "reusing
// the recorded answer — same board, same screens". Nothing had checked that claim. Six rounds produced no
// real attempt and the run ended "still detected after 6 solve loops".
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';

import { CaptchaKrakenSolver } from './solver';
import { photographsItself } from './fake-dom.test';

const BOX = { x: 0, y: 0, width: 100, height: 100 };
const WIDGET = {
  el: { contentFrame: async () => null, boundingBox: async () => BOX },
  at: {},
  vendor: 'hcaptcha',
  role: 'challenge',
};

/** A fresh board every round, and a distinct answer for each, so nothing here trips the repeat fence. */
function boardChangingSolver(freshBoards: boolean) {
  const solver: any = photographsItself(new CaptchaKrakenSolver({
    videoBurstDurationMs: 120,
    videoBurstFps: 50,
    speculativeBurstEnabled: false,
    maxSolveLoops: 2,
    postSolveOutcomeTimeoutMs: 60,
  }));
  const asks: string[] = [];
  let frame = 0;
  let answer = 0;

  solver.answerBox = async () => null;
  solver.classifyByRecording = async () => 'animated';
  solver.isCaptchaSolved = async () => false;
  solver.waitForBoardPainted = async () => ({ waitedMs: 0 });
  solver.getVerifyButton = async () => null;
  solver.captchaFrameChangedSince = async () => false;
  solver.executeClick = async () => {};
  solver.emitStep = async () => {};
  // The pointer leaving the board before it is judged has tests of its own; these fakes have no viewport.
  solver.stepOffTheBoard = async () => {};
  solver.detectCaptcha = async () => WIDGET;
  solver.hasInteractiveWidgetInDom = async () => false;
  // Outer-loop reads that need a real page; this test drives the loop, not the DOM.
  solver.bannerKind = async () => null;
  solver.human.reset = async () => {};
  // The board the vendor is showing right now. `true` means it deals a new one after every answer.
  solver.isChallengeFreshlyRendered = async () => freshBoards;
  solver.shot = async (_el: any, dest: string) => fs.writeFileSync(dest, `screen-${frame++ % 3}`);
  solver.getSolution = async () => ({ actions: [{ action: 'click', target_bounding_boxes: [[0.1, 0.1, 0.2, 0.2]] }], token_usage: [] });
  solver.getAnimatedSolution = async (dir: string) => {
    asks.push(dir);
    answer++;
    // Distinct per ask: a repeated answer would be dropped by the no-progress fence instead, which is a
    // different mechanism and would hide whether the plan itself was bounded to its board.
    return { actions: [{ action: 'click', target_bounding_boxes: [[0.1 * answer, 0.1, 0.2 * answer, 0.2]], frame: 1 }], token_usage: [] };
  };
  return { solver, asks };
}

test('a new board gets its own ask, not the last board\'s recorded answer', async () => {
  const { solver, asks } = boardChangingSolver(true);
  await solver.solveImpl({}).catch(() => {});   // ends on the solve-loop ceiling, which is not what is under test
  assert.equal(asks.length, 2,
    `the vendor dealt a second board and the driver asked ${asks.length} time(s); a recorded answer cut from the first board cannot describe the second`);
  await solver.stopAnimatedFilm();
});

test('the recorded answer is dropped the moment the board is replaced', async () => {
  const { solver } = boardChangingSolver(true);
  await solver.solveImpl({}).catch(() => {});
  assert.equal(solver.animatedPlan, null,
    'a plan that outlives its board gets replayed onto the next one');
  await solver.stopAnimatedFilm();
});

test('a board that is still up keeps its film, so the reuse-once path survives', async () => {
  // The guard must fire on a REPLACED board only. Dropping the film whenever a round ends would re-film and
  // re-ask every round, which is the round inflation "one film, one board" was measured to remove.
  const { solver, asks } = boardChangingSolver(false);
  await solver.solveImpl({}).catch(() => {});
  assert.equal(asks.length, 1,
    `the same board was re-asked ${asks.length} times; with the board still up the recorded answer is reused once`);
  await solver.stopAnimatedFilm();
});
