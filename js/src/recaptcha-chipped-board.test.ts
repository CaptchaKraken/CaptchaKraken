// A chip is a kept photo (submit); a centred check is a swap (look again). All-or-nothing: calling a swapping board finished submits half
// an answer, calling a chipped one unfinished costs one inference. A Verify press is an interaction, and the grid-load wait was once paid twice (2148ms x2).
import { test } from 'node:test';
import assert from 'node:assert/strict';

import { CaptchaKrakenSolver } from './solver';
import { photographsItself } from './fake-dom.test';

const GRID = [
  [0, 0, 100, 100], [100, 0, 200, 100], [200, 0, 300, 100],
  [0, 100, 100, 200], [100, 100, 200, 200], [200, 100, 300, 200],
  [0, 200, 100, 300], [100, 200, 200, 300], [200, 200, 300, 300],
];
const ELEMENT_BOX = { x: 0, y: 0, width: 300, height: 300 };
const GRID_ARG = { boxes: GRID, size: 3 as const, screenshotW: 300, screenshotH: 300 };

const CELL_5: [number, number, number, number] = [0.4, 0.4, 0.6, 0.6];

const CLICK_5 = { action: 'click', target_bounding_boxes: [CELL_5] };
const DONE = { action: 'done' };

interface Log { rounds: number; clicked: any[]; waits: number; submits: number; }

function driver(states: any, answers: any[]): { solver: any; log: Log } {
  const solver: any = photographsItself(new CaptchaKrakenSolver({
    recaptchaFadeOnsetGraceMs: 60,
    recaptchaDynamicFadePollMs: 1,
    recaptchaDynamicFadeWaitMs: 20,
  }));
  const log: Log = { rounds: 0, clicked: [], waits: 0, submits: 0 };

  solver.waitForGridCellsLoaded = async () => true;
  solver.gridCellStates = async () => states;
  solver.hoverCell = async () => {};
  solver.emitStep = async () => {};
  solver.saveImageForDebug = () => {};
  solver.archiveLatestDebugRun = () => {};
  solver.initGridDebug = () => {};
  solver.gridDebug = () => {};

  solver.solveFrameFreshnessGuarded = async () => {
    const answer = answers[Math.min(log.rounds, answers.length - 1)];
    log.rounds += 1;
    return { actions: [answer], token_usage: [{ total_tokens: 1 }] };
  };
  solver.executeClick = async (_p: any, _el: any, action: any) => {
    log.clicked.push(action.target_bounding_box);
  };
  solver.waitForAnyClickedTileLoaded = async () => { log.waits += 1; return true; };
  solver.getVerifyButton = async () => ({});
  solver.moveAndClick = async () => { log.submits += 1; };
  return { solver, log };
}

function fakeElement(): any {
  return {
    screenshot: async () => Buffer.from(''),
    contentFrame: async () => ({}),
    boundingBox: async () => ({ ...ELEMENT_BOX }),
  };
}

const session = () => ({
  gridBoxes: GRID,
  elementBox: { ...ELEMENT_BOX },
  scaleX: 1, scaleY: 1, screenshotW: 300, screenshotH: 300,
});

const solve = (solver: any) =>
  solver.solveRecaptchaGrid({}, fakeElement(), 1, null, GRID_ARG, { ...ELEMENT_BOX });

test('a chipped tile submits without a second inference', async () => {
  const { solver, log } = driver(
    { empty: [], changing: [5], loaded: [1, 2, 3, 4, 6, 7, 8, 9], selected: [5] },
    [CLICK_5, DONE],
  );
  const result = await solve(solver);

  assert.equal(log.rounds, 1, 'a ticked board must not be read a second time');
  assert.deepEqual(log.clicked, [CELL_5]);
  assert.equal(log.waits, 0, 'nothing is being replaced, so there is nothing to wait for');
  assert.equal(log.submits, 1);
  assert.equal(result.didInteract, true);
  assert.deepEqual(result.tokenUsage, [{ total_tokens: 1 }]);
});

test('a swapping tile still costs another round', async () => {
  const { solver, log } = driver(
    { empty: [5], changing: [], loaded: [1, 2, 3, 4, 6, 7, 8, 9], selected: [] },
    [CLICK_5, DONE],
  );
  const result = await solve(solver);

  assert.equal(log.rounds, 2, 'a replaced tile has to be read once it lands');
  assert.equal(log.waits, 1);
  assert.equal(log.submits, 1);
  assert.equal(result.didInteract, true);
});

test('one chip among the clicked tiles is not a verdict', async () => {
  const { solver } = driver({ empty: [], changing: [5, 6], loaded: [], selected: [5] }, []);
  const seen = await solver.watchClickedTiles({}, fakeElement(), session(), [5, 6]);

  assert.equal(seen.chipped, false);
  assert.deepEqual(seen.loading, [5, 6]);
});

test('a chip on a tile we did not click is not a verdict', async () => {
  const { solver } = driver({ empty: [], changing: [], loaded: [5], selected: [2] }, []);
  const seen = await solver.watchClickedTiles({}, fakeElement(), session(), [5]);

  assert.equal(seen.chipped, false);
});

function countingDriver(states: any, answers: any[]) {
  const { solver, log } = driver(states, answers);
  const counted = log as Log & { gridLoads: number };
  counted.gridLoads = 0;
  solver.waitForGridCellsLoaded = async () => { counted.gridLoads += 1; return true; };
  return { solver, log: counted };
}

const CHIPPED = { empty: [], changing: [5], loaded: [1, 2, 3, 4, 6, 7, 8, 9], selected: [5] };
const SWAPPING = { empty: [5], changing: [], loaded: [1, 2, 3, 4, 6, 7, 8, 9], selected: [] };

test('a round that only presses Verify still reports an interaction', async () => {
  const { solver, log } = countingDriver(CHIPPED, [DONE]);
  const result = await solve(solver);

  assert.deepEqual(log.clicked, [], 'the model said `done`; nothing should be clicked');
  assert.equal(log.submits, 1, 'a `done` answer is submitted by pressing Verify');
  assert.equal(result.didInteract, true,
    'the driver pressed Verify and reported that it did nothing. The caller then '
    + 'sleeps postSolveDelayMs instead of polling for the verdict, and throws '
    + "'performed no interactions' if the widget has not vanished yet — on an "
    + 'answer that was correctly sent.');
});

test('a round-cap exit still reports no interaction', async () => {
  const { solver, log } = countingDriver(SWAPPING, [{ action: 'wait' }]);
  const result = await solve(solver);

  assert.equal(log.submits, 0, 'nothing was answered, so nothing may be submitted');
  assert.equal(result.didInteract, false);
});

test('round one inherits the caller`s grid-load wait', async () => {
  const { solver, log } = countingDriver(CHIPPED, [DONE]);
  await solve(solver);

  assert.equal(log.gridLoads, 0,
    'round 1 waited for the grid to load; solveSingle has just done exactly '
    + 'that and nothing has touched the board in between');
});

test('later rounds still wait for the board they changed', async () => {
  const { solver, log } = countingDriver(SWAPPING, [CLICK_5, DONE]);
  await solve(solver);

  assert.equal(log.rounds, 2, 'a replaced tile has to be read once it lands');
  assert.equal(log.gridLoads, 1,
    'round 2 opens on a board this driver has just clicked, so it must wait for '
    + 'the replacement to paint before the model reads it');
});
