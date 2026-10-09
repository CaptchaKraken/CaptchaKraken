// A board that changed only because we pointed at it is a still board. Measured before this: after a refused answer
// the cursor sat on the board, the "second look" recording saw the hover and press feedback come and go, read "a
// screen came back" as a cycle, and filmed a still board as animated (+29s on the recording path). Mirror of
// python/tests/test_our_own_gesture_is_not_animation.py.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';

import { CaptchaKrakenSolver, INPUT_SETTLE_MS } from './solver';

const BOARD = { x: 100, y: 100, width: 300, height: 300 };
const page: any = { viewportSize: () => ({ width: 1280, height: 800 }) };
const board: any = { boundingBox: async () => BOARD };

function solverAt(at: [number, number], config: Record<string, unknown> = {}) {
  const solver: any = new CaptchaKrakenSolver(config);
  const moves: Array<[number, number]> = [];
  solver.human = { hovers: true, at, move: async (_p: any, to: [number, number]) => { moves.push(to); solver.human.at = to; } };
  return { solver, moves };
}

const onBoard = ([x, y]: [number, number]) => x >= BOARD.x && x <= BOARD.x + BOARD.width && y >= BOARD.y && y <= BOARD.y + BOARD.height;

test('the pointer leaves the board before the board is judged', async () => {
  const { solver, moves } = solverAt([150, 250]);
  solver.actedOnBoard = true;
  solver.lastInputAt = Date.now();
  await solver.stepOffTheBoard(page, board);
  assert.equal(moves.length, 1, 'the pointer stayed on the board it was about to judge');
  const [x, y] = moves[0];
  assert.ok(!onBoard([x, y]) && x >= 0 && x < 1280 && y >= 0 && y < 800, `moved to ${[x, y]}`);
  assert.ok(x < BOARD.x, 'left by a far edge instead of the nearest one');
  assert.ok(Date.now() - solver.lastInputAt >= INPUT_SETTLE_MS - 1, 'judged while our own feedback was still fading');
});

test('a board dealt under a resting pointer is not stepped off', async () => {
  // Nothing of ours is on a board we have not pointed at, so stepping off it would only cost the round a gesture.
  const { solver, moves } = solverAt([150, 250]);
  const t0 = Date.now();
  await solver.stepOffTheBoard(page, board);
  assert.deepEqual(moves, [], 'moved off a board we never touched');
  assert.ok(Date.now() - t0 < INPUT_SETTLE_MS / 2, 'waited out feedback that was never there');
});

test('a pointer already off the board is not moved', async () => {
  const { solver, moves } = solverAt([20, 20]);
  await solver.stepOffTheBoard(page, board);
  assert.deepEqual(moves, []);
});

test('a board that only changed under our gesture films as still', async () => {
  // Hover feedback flickers between two looks for 350ms after we move — a CSS transition — then the still board shows.
  const { solver } = solverAt([20, 20], { videoBurstDurationMs: 500, videoBurstMaxMs: 500, videoBurstFps: 20 });
  const touched = Date.now();
  solver.lastInputAt = touched;
  let flicker = 0;
  solver.shot = async (_el: any, p: string) => fs.writeFileSync(p, Date.now() - touched < 350 ? `hover-${flicker++ % 2}` : 'board');
  const rec = solver.startKeyframeBurst({});
  const moved = await rec.verdict();
  const screens = rec.screensSeen();
  await rec.abandon();
  assert.equal(moved, false, 'our own hover feedback was filmed as the board animating');
  assert.equal(screens, 1, `${screens} screens of a board that never moved by itself`);
});

// JS only: the idle wander, which hovers the board while the model reads it, has no Python counterpart.
test('a board that changed while our pointer wandered over it is not taken to cycle', async () => {
  for (const wandered of [true, false]) {
    const { solver } = solverAt([20, 20]);
    solver.shot = async (_el: any, p: string) => fs.writeFileSync(p, 'x');
    solver.captchaFrameChangedSince = async () => true;
    const ask = async () => {
      if (wandered) solver.lastInputAt = Date.now();
      return { actions: [], token_usage: [] };
    };
    await solver.solveFrameFreshnessGuarded({}, '/dev/null', ask, { recordingInFlight: true });
    assert.equal(solver.repeatedAnswerSeen, !wandered,
      wandered ? 'our own wander over the board armed the second look' : 'a board moving by itself no longer arms it');
  }
});
