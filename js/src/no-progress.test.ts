// The missed-tiles retry legitimately overlaps the answer before it, coordinates are compared rounded, and the loop cap is the real
// bound: six rounds at 4-7s each is 24-42s, inside the 45s cap.
import { test } from 'node:test';
import assert from 'node:assert/strict';

import { CaptchaKrakenSolver, SOLVE_DEFAULTS } from './solver';

type Box = [number, number, number, number];

function click(...boxes: Box[]) {
  return [{ action: 'click', target_bounding_boxes: boxes.map((b) => [...b]) }];
}

const MEASURED_4X4 = [
  click([0.1, 0.1, 0.2, 0.2], [0.3, 0.1, 0.4, 0.2], [0.5, 0.5, 0.6, 0.6]),
  ...Array.from({ length: 9 }, () => click([0.1, 0.1, 0.2, 0.2], [0.3, 0.1, 0.4, 0.2])),
];

const solver = (config: Record<string, unknown> = {}): any =>
  new CaptchaKrakenSolver(config);

test('the measured 4x4 sequence stops at round four', () => {
  const s = solver();
  let stoppedAt: number | null = null;
  for (let i = 0; i < MEASURED_4X4.length; i++) {
    s.noteAnswer(MEASURED_4X4[i], null);
    if (s.noProgressRounds >= (s.config.maxNoProgressRounds ?? 2)) {
      stoppedAt = i + 1;
      break;
    }
  }
  assert.equal(stoppedAt, 4, 'rounds 2,3,4 are identical, so round 4 is where it gives up');
});

test('a changing answer never trips it', () => {
  const s = solver();
  for (let i = 0; i < 10; i++) {
    s.noteAnswer(click([0.1 * i, 0.1, 0.2, 0.2]), null);
    assert.equal(s.noProgressRounds, 0, 'a solve making progress must not be cut off');
  }
});

test('the retry mode is part of the answer', () => {
  const s = solver();
  s.noteAnswer(click([0.1, 0.1, 0.2, 0.2]), null);
  s.noteAnswer(click([0.1, 0.1, 0.2, 0.2]), 'missed-tiles');
  assert.equal(s.noProgressRounds, 0);
});

test('the first repeat escalates to a recording before the second abandons', () => {
  const s = solver();
  s.noteAnswer(click([0.1, 0.1, 0.2, 0.2]), null);
  assert.equal(s.repeatedAnswerSeen, false);
  s.noteAnswer(click([0.1, 0.1, 0.2, 0.2]), null);
  assert.equal(s.repeatedAnswerSeen, true, 'the first repeat should arm the recording path');
});

test('coordinates are compared rounded, not exactly', () => {
  const s = solver();
  s.noteAnswer(click([0.1, 0.1, 0.2, 0.2]), null);
  s.noteAnswer(click([0.10000001, 0.1, 0.2, 0.2]), null);
  assert.equal(s.noProgressRounds, 1);
});

test('an unreadable answer is not a repeat', () => {
  const s = solver();
  const hostile = { get action(): string { throw new Error('nope'); } };
  for (let i = 0; i < 5; i++) s.noteAnswer([hostile], null);
  assert.equal(s.noProgressRounds, 0);
});

test('the budget fits the loop count', () => {
  const { maxSolveLoops, overallSolveTimeoutMs } = SOLVE_DEFAULTS;
  assert.ok(
    maxSolveLoops * 7_000 <= overallSolveTimeoutMs,
    `${maxSolveLoops} rounds x 7000ms exceeds the ${overallSolveTimeoutMs}ms cap`,
  );
});

// Drop the ANSWER, keep the FRAMES: re-submitting coordinates the widget refused cannot succeed, and the
// raised sample never reaches the wire behind a cached response; re-recording screens already in hand is
// another `videoBurstMaxMs` for nothing. Mirrors `_invalidate_animated_answer` in the Python port.
test('a repeat drops the cached animated answer but keeps the frames', () => {
  const s = solver();
  s.animatedPlan = { burstDir: '/tmp/burst-abc', response: { actions: [] } };

  s.noteAnswer(click([0.1, 0.1, 0.2, 0.2]), null);
  s.noteAnswer(click([0.1, 0.1, 0.2, 0.2]), null);

  assert.equal(s.animatedPlan.response, null, 'the refused answer must not be re-served');
  assert.equal(s.animatedPlan.burstDir, '/tmp/burst-abc', 'the frames are still good');
});

test('an answer that is still making progress keeps its recording', () => {
  // Invalidating on every round would re-ask once per round on a board that is
  // being solved correctly, which is one inference per round of pure cost.
  const s = solver();
  const plan = { burstDir: '/tmp/burst-abc', response: { actions: [] } };
  s.animatedPlan = plan;

  s.noteAnswer(click([0.1, 0.1, 0.2, 0.2]), null);
  s.noteAnswer(click([0.5, 0.5, 0.6, 0.6]), null);

  assert.equal(s.animatedPlan.response, plan.response, 'a changing answer is not a refusal');
});

test('invalidating twice is not an error', () => {
  // The no-progress path can fire again before the next round reaches a
  // request; the second call must be a no-op rather than clearing the frames.
  const s = solver();
  s.animatedPlan = { burstDir: '/tmp/burst-abc', response: { actions: [] } };
  s.invalidateAnimatedAnswer();
  s.invalidateAnimatedAnswer();

  assert.equal(s.animatedPlan.response, null);
  assert.equal(s.animatedPlan.burstDir, '/tmp/burst-abc');
});

test('a repeat with nothing else to try ends the solve', async () => {
  // At temperature 0 a third ask of the same board returns the same answer, and a repeat presses nothing.
  const s: any = new CaptchaKrakenSolver({ maxSolveLoops: 6, videoSolveEnabled: false });
  let rounds = 0;
  s.isCaptchaSolved = async () => false;
  s.detectCaptcha = async () => ({ el: {}, at: {}, vendor: 'hcaptcha', role: 'challenge' });
  s.bannerKind = async () => null;
  s.human.reset = async () => {};
  s.isChallengeFreshlyRendered = async () => false;
  s.solveSingle = async () => {
    rounds++;
    s.noteAnswer(click([0.31, 0.226, 0.334, 0.25]), null);   // the model answers this board the same way every round
    return { didInteract: false, tokenUsage: [] };
  };
  let message = '';
  await s.solveImpl({}).catch((e: Error) => { message = e.message; });
  assert.match(message, /same answer 2 times/);
  assert.equal(rounds, 2, `spent ${rounds} rounds on a board the model cannot read`);
});

test('the failure reported is the last round\'s, not an earlier one\'s', async () => {
  const s: any = new CaptchaKrakenSolver({ maxSolveLoops: 3, videoSolveEnabled: true, postSolveOutcomeTimeoutMs: 0 });
  const answers = [click([0.1, 0.1, 0.2, 0.2]), click([0.1, 0.1, 0.2, 0.2]), click([0.5, 0.5, 0.6, 0.6])];
  s.isCaptchaSolved = async () => false;
  s.detectCaptcha = async () => ({ el: {}, at: {}, vendor: 'hcaptcha', role: 'challenge' });
  s.bannerKind = async () => null;
  s.human.reset = async () => {};
  s.isChallengeFreshlyRendered = async () => false;
  s.solveSingle = async () => ({ didInteract: !s.noteAnswer(answers.shift(), null), tokenUsage: [] });
  let message = '';
  await s.solveImpl({}).catch((e: Error) => { message = e.message; });
  assert.match(message, /after 3 solve loops/);
  assert.doesNotMatch(message, /same answer/);
});

test('a repeat goes on while a recording, a plan or a retry mode is left', () => {
  const s: any = new CaptchaKrakenSolver({ videoSolveEnabled: true });
  s.repeatedAnswerSeen = true;
  assert.equal(s.anotherMoveLeft(null), true, 'a board that cycles repeats, and filming it can still work');
  s.animatedProbeDone = true;
  assert.equal(s.anotherMoveLeft(null), false, 'the film is spent and no plan was earned');
  assert.equal(s.anotherMoveLeft('missed_tiles'), true, 'a retry mode is a different question');
  s.fallbackArmed = true;
  s.fallbackPlans = [[{ action: 'click' }]];
  assert.equal(s.anotherMoveLeft(null), true, 'the model has another plan');
});

test('an answer pressed earlier on this picture is a repeat after another plan', () => {
  // Dealing the same picture again clears the plans, and the first answer came back and was pressed again.
  const s: any = solver();
  assert.equal(s.noteAnswer(click([0.1, 0.1, 0.2, 0.2]), null, 'board'), false);
  assert.equal(s.noteAnswer(click([0.5, 0.5, 0.6, 0.6]), null, 'board'), false);
  assert.equal(s.noteAnswer(click([0.1, 0.1, 0.2, 0.2]), null, 'board'), true);
});

test('a paged puzzle may come back to a page', () => {
  // The earlier screens are part of the question, so the same page later is not the same ask.
  const s: any = solver();
  s.noteAnswer(click([0.1, 0.1, 0.2, 0.2]), null, 'page-1');
  s.pointerHistory.push('page-1.png');
  s.noteAnswer(click([0.5, 0.5, 0.6, 0.6]), null, 'page-1');
  assert.equal(s.noteAnswer(click([0.1, 0.1, 0.2, 0.2]), null, 'page-1'), false);
  s.pointerHistory = [];
});

test('a refresh records the picture it was meant to replace', () => {
  const s: any = solver();
  assert.equal(s.noteAnswer([{ action: 'refresh' }], null, 'board'), false);
  assert.equal(s.refreshedBoards.has('board'), true);
  s.resetSolveState();
  assert.equal(s.refreshedBoards.has('board'), false, 'a new solve has refreshed nothing');
});
