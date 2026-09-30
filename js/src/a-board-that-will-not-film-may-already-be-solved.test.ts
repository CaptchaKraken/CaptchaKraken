// A recording that catches NOTHING is not a verdict about the board.
//
// The recorder returns no frames only when every screenshot in its window failed. A still
// photographs fine, so nothing coming back does not mean "this board is static" — it means the
// widget would not screenshot at all, and the commonest reason for that is that it is CLOSING,
// because the answer was accepted.
//
// Every other failure in the solve loop asked `isCaptchaSolved` before giving up; the animated
// branch threw instead. Measured on the python port, which fails the same way: prosopo_grid_3x3
// solved 8/8 across six runs on 09-12 and 09-13, then lost four attempts on 09-17 to exactly this,
// each after its FIRST board came back from the fixture's own /fx/verify graded `solved: true`.
//
// The two ports must behave identically here; this drives the same rounds as the Python test of the same name.
import { test } from 'node:test';
import assert from 'node:assert/strict';

import { CaptchaKrakenSolver } from './solver';

/** A solver whose round `blankAt` (or every round from it, with `everyRound`) cannot film, and whose widget reports `solvedAfter` afterwards. */
function driver(blankAt: number, solvedAfter: boolean, opts: { everyRound?: boolean; videoSolveEnabled?: boolean } = {}) {
  const solver: any = new CaptchaKrakenSolver({ maxSolveLoops: 6, postSolveOutcomeTimeoutMs: 1, postSolveDelayMs: 1,
    staleElementBackoffMs: 0, videoSolveEnabled: opts.videoSolveEnabled });
  const state = { rounds: 0, solved: false, asked: 0 };
  solver.solveSingle = async () => {
    state.rounds++;
    if (state.rounds === blankAt || (opts.everyRound && state.rounds > blankAt)) {
      state.solved = solvedAfter;
      const e: any = new Error('ANIMATED_CHALLENGE: could not record the animated challenge (no frame screenshotted).');
      e.animated = true;
      throw e;
    }
    return { didInteract: true, tokenUsage: [] };
  };
  solver.detectCaptcha = async () => ({ vendor: 'prosopo', role: 'unknown' });
  solver.isCaptchaSolved = async () => { state.asked++; return state.solved; };
  solver.bannerKind = async () => null;
  solver.isChallengeFreshlyRendered = async () => false;
  solver.isBlocked = async () => false;
  solver.human.reset = async () => {};
  return { solver, state };
}

test('a board the vendor took is not lost because the next one would not film', async () => {
  const { solver, state } = driver(2, true);
  const result = await solver.solveImpl({});
  assert.equal(result.isSolved, true, 'an accepted board was thrown away by a failed recording');
  assert.ok(state.asked > 0, 'the solve ended without asking whether the answer was taken');
});

test('a board that will not film and is not solved is filmed again, until the loops are spent', async () => {
  const { solver, state } = driver(1, false, { everyRound: true });
  await assert.rejects(solver.solveImpl({}), /after 6 solve loops/);
  assert.equal(state.rounds, 6);
});

test('a first round that cannot film is not the end of the solve', async () => {
  const { solver, state } = driver(1, false);
  await assert.rejects(solver.solveImpl({}));
  assert.equal(state.rounds, 6, `gave up after ${state.rounds} rounds with loops still in hand`);
});

test('a board that will not film with recording off is a hard stop', async () => {
  const { solver, state } = driver(1, false, { videoSolveEnabled: false });
  await assert.rejects(solver.solveImpl({}), /Animated challenge could not be solved/);
  assert.equal(state.rounds, 1);
});
