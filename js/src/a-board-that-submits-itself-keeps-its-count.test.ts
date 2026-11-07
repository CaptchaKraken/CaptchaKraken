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
