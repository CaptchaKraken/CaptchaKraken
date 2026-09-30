// A one-shot burst can only show the model the screens that fell inside its window, and the answer it
// produces is identical next round by construction — greedy sampling, same frames. So a board whose answer
// lived on a screen the window missed had no second chance: the stored answer was re-pressed until the
// no-progress fence tripped, three rounds in, with half the solve budget unspent. Measured live on
// 2026-09-15, hCaptcha's animated board read 2/15 and 6/12 on the two served models that way, against 36/36
// on the driver that still re-filmed every round.
//
// The camera now runs for the whole solve and every round slices a STRICTLY LONGER film. These tests drive
// the real recorder — a fake `shot` is the only stub in the filming path — because the bug was in when the
// recording stopped, and a fake recorder cannot be wrong about that.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';

import { CaptchaKrakenSolver } from './solver';
import { photographsItself } from './fake-dom.test';

/** The gap a real round has between answering and being told no: the outer loop's verdict wait. */
const verdictWait = () => new Promise((r) => setTimeout(r, 150));

const BOX = { x: 0, y: 0, width: 100, height: 100 };
const WIDGET = {
  el: { contentFrame: async () => null, boundingBox: async () => BOX },
  at: {},
  vendor: 'geetest',
  role: 'challenge',
};

/** One answer, every time: the point is that the ASK happens again, not that the answer changed. */
const ANSWER = {
  actions: [{ action: 'click', target_bounding_boxes: [[0.4, 0.4, 0.5, 0.5]], frame: 1 }],
  token_usage: [],
};

function cyclingSolver() {
  const solver: any = photographsItself(new CaptchaKrakenSolver({
    // A 3-screen cycle at 50fps closes in well under the floor, so the test costs ~0.3s rather than ~4s.
    videoBurstDurationMs: 120,
    videoBurstFps: 50,
    speculativeBurstEnabled: false,
  }));
  const slices: number[] = [];
  const films: { events: string[] }[] = [];
  let frame = 0;

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
  // Three distinct screens on a loop: enough for the recorder to see a screen come back and call it a cycle.
  solver.shot = async (_el: any, dest: string) => fs.writeFileSync(dest, `screen-${frame++ % 3}`);
  solver.getSolution = async () => ANSWER;
  solver.getAnimatedSolution = async (dir: string) => {
    slices.push(fs.readdirSync(dir).length);
    return ANSWER;
  };

  // The real recorder, with only pause/resume observed.
  const realStart = solver.startKeyframeBurst.bind(solver);
  solver.startKeyframeBurst = (el: any, continuous?: boolean) => {
    const rec = realStart(el, continuous);
    const events: string[] = [];
    films.push({ events });
    return {
      ...rec,
      pause: () => { events.push('pause'); rec.pause(); },
      resume: () => { events.push('resume'); rec.resume(); },
    };
  };
  return { solver, slices, films };
}

test('the camera survives the round that sliced it', async () => {
  const { solver } = cyclingSolver();
  await solver.solveSingle({}, WIDGET, 1, null);
  assert.ok(solver.animatedFilm, 'the recording was ended by the round that used it, so the next round has nothing longer to ask with');
  await solver.stopAnimatedFilm();
});

test('a refused answer is re-asked against a longer film, not re-pressed', async () => {
  const { solver, slices } = cyclingSolver();

  await solver.solveSingle({}, WIDGET, 1, null);          // films, asks, clicks
  const film = solver.animatedFilm;
  await verdictWait();
  await solver.solveSingle({}, WIDGET, 2, null);          // reuses, the widget refused it, plan is dropped
  await verdictWait();
  await solver.solveSingle({}, WIDGET, 3, null);          // asks again, over a film 2 rounds longer

  assert.equal(slices.length, 2, 'the refused answer was re-pressed instead of re-asked');
  assert.ok(slices[1] > slices[0],
    `the second ask saw ${slices[1]} frames against the first ask's ${slices[0]}; a re-ask over the same film asks the same question`);
  assert.equal(solver.animatedFilm, film, 'the camera was restarted rather than left running');
  await solver.stopAnimatedFilm();
});

test('the camera does not film our own answer landing', async () => {
  const { solver, films } = cyclingSolver();
  await solver.solveSingle({}, WIDGET, 1, null);
  assert.deepEqual(films[0].events, ['pause'],
    'a frame of the board wearing our clicks is not a screen the board ever showed on its own');
  await solver.stopAnimatedFilm();
});

test('the film ends with the solve, not with the round', async () => {
  const { solver } = cyclingSolver();
  await solver.solveSingle({}, WIDGET, 1, null);
  const dir = (solver.animatedFilm as any) && solver.animatedPlan?.burstDir;
  assert.ok(dir, 'nothing was planned');
  await solver.stopAnimatedFilm();
  assert.equal(solver.animatedFilm, null, 'a camera left running outlives the page it is filming');
});

test('a refused answer with no camera still re-asks on the frames it has', async () => {
  // #41's path, and it has to keep working: the plan can outlive the film — the board changed, the camera
  // was stopped, and only the slice the answer came from is left. Re-asking on that is worse than re-asking
  // on a longer one, and much better than pressing the refused answer again.
  const { solver, slices } = cyclingSolver();
  await solver.solveSingle({}, WIDGET, 1, null);
  const held = solver.animatedPlan.burstDir;

  // How this arises for real: the speculative path banks a plan from a burst it started itself and never
  // installs it as `animatedFilm`, so a refusal there leaves frames with no camera behind them.
  // Abandon rather than just drop the handle: a recorder nobody holds keeps filming to its own ceiling.
  // The plan's slice is a separate hardlinked directory, so it outlives the film it was cut from.
  await solver.animatedFilm.abandon();
  solver.animatedFilm = null;
  solver.animatedPlan = { burstDir: held, response: null };
  await solver.solveSingle({}, WIDGET, 2, null);

  assert.equal(slices.length, 2, 'the refused answer was not re-asked');
  assert.equal(solver.animatedPlan.burstDir, held, 'it filmed afresh instead of using the frames in hand');
});

test('stopping a camera that is not the current one leaves the current one alone', async () => {
  const { solver } = cyclingSolver();
  await solver.solveSingle({}, WIDGET, 1, null);
  const film = solver.animatedFilm;
  assert.ok(film, 'nothing was filmed');
  await solver.stopAnimatedFilm();
  assert.equal(solver.animatedFilm, null);
  await solver.stopAnimatedFilm();            // idempotent: a second stop must not throw
  assert.equal(solver.animatedFilm, null);
});

test('a film that never cycles does not hold the first slice to the camera ceiling', async () => {
  // MEASURED: a board took 121.9s against a 20s gate ceiling, because the wait before slicing ran until the
  // recorder loop ended and a continuous loop ends at videoFilmMaxMs. How long to wait before slicing and
  // how long the camera may run are different numbers; this pins the first to the burst ceiling.
  const solver: any = photographsItself(new CaptchaKrakenSolver({
    videoBurstDurationMs: 60,
    videoBurstMaxMs: 200,        // the slice wait
    videoFilmMaxMs: 60_000,      // the camera, deliberately far longer
    videoBurstFps: 50,
  }));
  let n = 0;
  // Every frame a brand new screen: never a closed cycle, never a settle.
  solver.shot = async (_el: any, dest: string) => fs.writeFileSync(dest, `unique-${n++}`);

  const rec = solver.startKeyframeBurst({}, true);
  const t0 = Date.now();
  await rec.settledOrCycled();
  const waited = Date.now() - t0;
  await rec.abandon();

  assert.ok(waited < 2_000, `waited ${waited}ms before slicing; the burst ceiling is 200ms and the camera's is 60s`);
});

// ── one film, one board ──────────────────────────────────────────────────────────────────────────────────
//
// Filming on is only better while it is film of the SAME board. GeeTest's svg board reshuffles its
// candidates every time it refuses an answer, and a film spanning both states describes neither: six
// keyframes cut across six screens where the board only ever shows three, `_detect_cycle` gives up on the
// extra states, and the frame the model names is one the widget will never show again — so the click waits
// out the whole keyframeWaitTimeoutMs for a picture that is gone. Measured on the gate: that board went from
// 6.9s to 30s, burning every solve loop, and the worst board in the run hit 50.9s against a 49s ceiling.

/** A board that deals a fresh set of screens each time it refuses an answer. */
function reshufflingSolver() {
  const solver: any = photographsItself(new CaptchaKrakenSolver({
    videoBurstDurationMs: 120,
    videoBurstFps: 50,
    speculativeBurstEnabled: false,
  }));
  const asks: string[][] = [];
  let board = 0;
  let frame = 0;

  solver.answerBox = async () => null;
  solver.classifyByRecording = async () => 'animated';
  solver.isCaptchaSolved = async () => false;
  solver.waitForBoardPainted = async () => ({ waitedMs: 0 });
  solver.getVerifyButton = async () => null;
  solver.captchaFrameChangedSince = async () => false;
  solver.emitStep = async () => {};
  // The pointer leaving the board before it is judged has tests of its own; these fakes have no viewport.
  solver.stepOffTheBoard = async () => {};
  solver.shot = async (_el: any, dest: string) => fs.writeFileSync(dest, `board${board}-screen-${frame++ % 3}`);
  // The refusal: every answer deals a new puzzle, so nothing filmed before it is on screen any more.
  solver.executeClick = async () => { board += 1; };
  solver.getSolution = async () => ANSWER;
  solver.getAnimatedSolution = async (dir: string) => {
    asks.push(fs.readdirSync(dir).sort().map((n) => fs.readFileSync(`${dir}/${n}`, 'utf8')));
    return ANSWER;
  };
  return { solver, asks };
}

test('a film of a board the vendor replaced is cut, not extended', async () => {
  const { solver, asks } = reshufflingSolver();

  await solver.solveSingle({}, WIDGET, 1, null);   // films board 0, asks, clicks — the click deals board 1
  await verdictWait();
  await solver.solveSingle({}, WIDGET, 2, null);   // reuses the answer; the widget refused it, so it is dropped
  await verdictWait();
  await solver.solveSingle({}, WIDGET, 3, null);   // re-asks — and board 0 is gone

  assert.equal(asks.length, 2, 'the refused answer was re-pressed instead of re-asked');
  const stale = asks[1].filter((f) => f.startsWith('board0-'));
  assert.deepEqual(stale, [],
    `the re-ask was cut over ${stale.length} frames of a board the vendor had already replaced; the model can `
    + 'only answer those with a frame number the widget will never show');
  assert.ok(asks[1].length > 0, 'the re-ask had no frames of the board that is actually on screen');
  await solver.stopAnimatedFilm();
});

test('a board that did not change is still re-asked over the whole film', async () => {
  // The cut is not a reset: this is the case the camera exists for, and cutting it every round would throw
  // away exactly the extra screens that give a refused answer a different one to give.
  const { solver, slices } = cyclingSolver();
  await solver.solveSingle({}, WIDGET, 1, null);
  await verdictWait();
  await solver.solveSingle({}, WIDGET, 2, null);
  await verdictWait();
  await solver.solveSingle({}, WIDGET, 3, null);

  assert.equal(slices.length, 2);
  assert.ok(slices[1] > slices[0],
    `the second ask saw ${slices[1]} frames against the first ask's ${slices[0]}; a board whose screens keep `
    + 'coming back was never replaced, so its film is read whole');
  await solver.stopAnimatedFilm();
});

test('a board that never repeats a screen is not mistaken for a new board', async () => {
  // hCaptcha's continuous animations never show the same screen twice, so "a screen from before the answer
  // came back" can never be proved for them — and a cut on the ABSENCE of that proof threw the whole film
  // away every round and waited out the burst ceiling to do it. Measured: 110.3s and 78.4s boards against a
  // 49s gate ceiling. A replacement has to be PROVED, not assumed.
  const asks: number[] = [];
  const solver: any = photographsItself(new CaptchaKrakenSolver({
    videoBurstDurationMs: 120,
    videoBurstMaxMs: 3_000,     // the ceiling this must not wait out on the re-ask
    videoFilmMaxMs: 60_000,
    videoBurstFps: 50,
    speculativeBurstEnabled: false,
  }));
  let n = 0;
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
  solver.shot = async (_el: any, dest: string) => fs.writeFileSync(dest, `unique-${n++}`);
  solver.getSolution = async () => ANSWER;
  solver.getAnimatedSolution = async (dir: string) => { asks.push(fs.readdirSync(dir).length); return ANSWER; };

  await solver.solveSingle({}, WIDGET, 1, null);
  await verdictWait();
  await solver.solveSingle({}, WIDGET, 2, null);
  await verdictWait();
  const t0 = Date.now();
  await solver.solveSingle({}, WIDGET, 3, null);
  const reaskMs = Date.now() - t0;

  assert.equal(asks.length, 2, 'the refused answer was re-pressed instead of re-asked');
  assert.ok(asks[1] > asks[0],
    `the re-ask saw ${asks[1]} frames against the first ask's ${asks[0]}; a board that never repeats a screen `
    + 'has not been replaced, it has simply never repeated, and its film is the only record of it');
  assert.ok(reaskMs < 2_500,
    `the re-ask waited ${reaskMs}ms out of a 3000ms burst ceiling for a cycle that is never coming`);
  await solver.stopAnimatedFilm();
});
