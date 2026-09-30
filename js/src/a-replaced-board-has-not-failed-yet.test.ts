// A replaced board has failed nothing yet, so it gets no second look.
//
// The second look buys a recording for a board that did not solve as a still, and `repeatedAnswerSeen` is
// what arms it. "One film, one board" gave every board its own look by resetting `animatedProbeDone` when the
// vendor deals a new one — but left the arm standing, so evidence found on ONE board (a repeat, the widget
// moving mid-inference) filmed every still board dealt after it. Python had the same shape and ran a Tier 3
// fixture that re-deals after every answer in 48.3s against the client's own 45s budget, 28.8s of it recording
// boards that had never failed.
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

/** A still board every round; the first one turns up evidence that arms the second look. */
function stillBoards(freshBoards: boolean) {
  const solver: any = photographsItself(new CaptchaKrakenSolver({
    videoBurstDurationMs: 120,
    videoBurstFps: 50,
    speculativeBurstEnabled: false,
    maxSolveLoops: 3,
    postSolveOutcomeTimeoutMs: 60,
  }));
  const probed: boolean[] = [];
  let frame = 0;
  let answer = 0;

  solver.answerBox = async () => null;
  solver.classifyByRecording = async () => 'settled';
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
  solver.bannerKind = async () => null;
  solver.human.reset = async () => {};
  solver.isChallengeFreshlyRendered = async () => freshBoards;
  solver.shot = async (_el: any, dest: string) => fs.writeFileSync(dest, `screen-${frame++ % 3}`);
  // Distinct per ask, so the no-progress fence never trips and only the arm is under test.
  const reply = () => {
    answer++;
    return { actions: [{ action: 'click', target_bounding_boxes: [[0.1 * answer, 0.1, 0.2 * answer, 0.2]] }], token_usage: [] };
  };
  solver.getSolution = async () => {
    // What the freshness guard or a repeated answer leaves behind on the board it was found on.
    if (answer === 0) solver.repeatedAnswerSeen = true;
    return reply();
  };
  solver.getAnimatedSolution = async () => reply();
  const shouldRetry = solver.shouldRetryAsAnimated.bind(solver);
  solver.shouldRetryAsAnimated = (source: any) => {
    const fires = shouldRetry(source);
    probed.push(fires);
    return fires;
  };
  return { solver, probed };
}

test('evidence found on one board does not film the boards the vendor deals after it', async () => {
  const { solver, probed } = stillBoards(true);
  await solver.solveImpl({}).catch(() => {});   // ends on the solve-loop ceiling, which is not what is under test
  assert.deepEqual(probed, [false, false, false],
    'a board nobody had answered yet was recorded because the board before it armed the second look');
  await solver.stopAnimatedFilm();
});

test('a board that is still up keeps its second look', async () => {
  const { solver, probed } = stillBoards(false);
  await solver.solveImpl({}).catch(() => {});
  assert.equal(probed[1], true, 'the second look is the only retry a still-looking animated board has');
  await solver.stopAnimatedFilm();
});
