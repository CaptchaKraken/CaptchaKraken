// A round that performed nothing gave the page nothing to react to.
//
// A refused answer, a repeated one, or an answer with nothing to execute leaves the page exactly as it was, so the
// next round can start at once. Each of them used to pay the post-round dwell (1.2-1.5s) and then the stale-element
// backoff (0.9s) on top: a board the model kept missing spent over two seconds a round waiting on nothing, and its
// per-board time doubled. Only a widget caught mid-transition — a stale handle, a board that would not screenshot —
// is worth waiting out, and it still is.
import { test } from 'node:test';
import assert from 'node:assert/strict';

import { CaptchaKrakenSolver } from './solver';

const WIDGET = { el: {}, at: {}, vendor: 'hcaptcha', role: 'challenge' };

/** A solver every round of which is `round()`; the dwell and backoff keep their defaults unless given. */
function driver(round: () => Promise<{ didInteract: boolean; tokenUsage: any[] }>, options: Record<string, number> = {}) {
  const solver: any = new CaptchaKrakenSolver({ maxSolveLoops: 4, videoSolveEnabled: false, ...options });
  let rounds = 0;
  solver.isCaptchaSolved = async () => false;
  solver.detectCaptcha = async () => WIDGET;
  solver.bannerKind = async () => null;
  solver.human.reset = async () => {};
  solver.isChallengeFreshlyRendered = async () => false;
  solver.solveSingle = async () => { rounds++; return round(); };
  return { solver, rounds: () => rounds };
}

async function elapsedMs(solver: any): Promise<number> {
  const t0 = Date.now();
  await solver.solveImpl({}).catch(() => {});
  return Date.now() - t0;
}

test('rounds that performed nothing do not dwell or back off', async () => {
  const { solver, rounds } = driver(async () => ({ didInteract: false, tokenUsage: [] }));
  const elapsed = await elapsedMs(solver);
  assert.equal(rounds(), 4);
  // Four rounds at the old dwell plus backoff cost at least 4 x 2.1s.
  assert.ok(elapsed < 1_000, `four rounds that did nothing took ${elapsed}ms`);
});

test('a widget caught mid-transition is still waited out', async () => {
  const { solver, rounds } = driver(async () => { throw new Error('Element is not attached to the DOM'); },
    { staleElementBackoffMs: 150 });
  const elapsed = await elapsedMs(solver);
  assert.equal(rounds(), 4);
  assert.ok(elapsed >= 4 * 150, `a widget in transition was not waited out (${elapsed}ms for four rounds)`);
});
