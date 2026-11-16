// A click board with no Verify submits itself at a count. A fallback plan of another count never submits: its tiles stay
// ticked, and the next plan's clicks untick them.
import { test } from 'node:test';
import assert from 'node:assert/strict';

import { CaptchaKrakenSolver } from './solver';

const click = (n: number) => ({ action: 'click', target_bounding_boxes: Array(n).fill([0.2, 0.2, 0.3, 0.3]) });

test('a board that submitted itself keeps only the plans of that many clicks', () => {
  const solver: any = new CaptchaKrakenSolver({});
  const refresh = { action: 'refresh' };
  solver.fallbackPlans = [[click(3)], [click(4)], [refresh]];
  solver.keepPlansOfThisManyClicks([click(4)]);
  assert.deepEqual(solver.fallbackPlans, [[click(4)], [refresh]]);
});

test('a round that was not clicks leaves the plans alone', () => {
  const solver: any = new CaptchaKrakenSolver({});
  solver.fallbackPlans = [[click(3)], [click(4)]];
  solver.keepPlansOfThisManyClicks([{ action: 'drag' }]);
  assert.equal(solver.fallbackPlans.length, 2);
});

test("a re-ask's fresh plans are held to the count the board already showed", () => {
  // Yidun 点击两下 on Tier 3: the first answer's queue was cut to two-click plans, the re-ask on the same board
  // brought a fresh queue led by a one-click plan, and that one press stayed on the board as a stray mark.
  const solver: any = new CaptchaKrakenSolver({});
  solver.fallbackPlans = [[click(1)], [click(2)], [click(1)]];
  solver.keepPlansOfThisManyClicks([click(2)]);
  solver.fallbackPlans = [[click(1)], [click(2)], [click(1)]];
  solver.holdFallbacksToSubmitCount();
  assert.deepEqual(solver.fallbackPlans, [[click(2)]]);
});

test('a new solve forgets the count', () => {
  const solver: any = new CaptchaKrakenSolver({});
  solver.keepPlansOfThisManyClicks([click(2)]);
  solver.resetSolveState();
  solver.fallbackPlans = [[click(1)], [click(3)]];
  solver.holdFallbacksToSubmitCount();
  assert.equal(solver.fallbackPlans.length, 2);
});
