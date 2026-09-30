// 'No captcha' is not a failure: treating it as one made the first tick sleep the whole error backoff.
import { test } from 'node:test';
import assert from 'node:assert/strict';

import { watchPage, WatchableSolver } from './watcher';
import { PlaywrightPage as Page } from './playwright-types';
import { SolveResult } from './types';

const RESULT: SolveResult = {
  isSolved: true,
  finalMousePosition: { x: 0, y: 0 },
  tokenUsage: { modelName: 'fake', inputTokens: 0, outputTokens: 0, cachedInputTokens: 0, estimatedCost: 0 },
  verdicts: [],
};

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

function fakePage(): Page & { close(): void } {
  let closed = false;
  const page = { isClosed: () => closed, close: () => { closed = true; } };
  return page as unknown as Page & { close(): void };
}

function fakeSolver(over: Partial<WatchableSolver> = {}): WatchableSolver & { detects: number; solveCalls: number } {
  const state = {
    detects: 0,
    solveCalls: 0,
    async detectCaptcha() { state.detects += 1; return {}; },
    async solve() { state.solveCalls += 1; return RESULT; },
    ...over,
  };
  return state as any;
}

test('solves a captcha it finds, and reports it', async () => {
  const seen: SolveResult[] = [];
  const solver = fakeSolver();
  const watcher = watchPage(solver, fakePage(), { intervalMs: 5, onSolved: (r) => { seen.push(r); } });

  await sleep(60);
  await watcher.stop();

  assert.ok(solver.solveCalls > 0, 'never solved');
  assert.equal(seen.length, solver.solveCalls, 'every solve should be reported once');
  assert.equal(seen[0], RESULT);
});

test('does not solve when nothing is detected', async () => {
  const solver = fakeSolver({ async detectCaptcha() { return null; } });
  const watcher = watchPage(solver, fakePage(), { intervalMs: 5 });

  await sleep(50);
  await watcher.stop();

  assert.equal(solver.solveCalls, 0, 'solved with no captcha present — that is a billable request for nothing');
});

test('stop() waits for the solve in flight instead of abandoning it', async () => {
  let finished = false;
  const solver = fakeSolver({
    async solve() { await sleep(60); finished = true; return RESULT; },
  });
  const watcher = watchPage(solver, fakePage(), { intervalMs: 5 });

  await sleep(25);
  await watcher.stop();

  assert.equal(finished, true, 'stop() resolved while a solve was still running');
  assert.equal(watcher.running, false);
});

test('solves are serial — a slow solve never overlaps the next', async () => {
  let inFlight = 0;
  let overlapped = false;
  const solver = fakeSolver({
    async solve() {
      inFlight += 1;
      if (inFlight > 1) overlapped = true;
      await sleep(20);
      inFlight -= 1;
      return RESULT;
    },
  });
  const watcher = watchPage(solver, fakePage(), { intervalMs: 1 });

  await sleep(120);
  await watcher.stop();

  assert.equal(overlapped, false, 'two solves ran at once: the same captcha would be paid for twice');
});

test('a solve that throws is reported, and the watcher survives it', async () => {
  const errors: unknown[] = [];
  let calls = 0;
  const solver = fakeSolver({
    async solve() { calls += 1; throw new Error('unsupported challenge'); },
  });
  const watcher = watchPage(solver, fakePage(), {
    intervalMs: 5,
    errorBackoffMs: 10,
    onError: (e) => { errors.push(e); },
  });

  await sleep(80);
  await watcher.stop();

  assert.ok(errors.length > 0, 'error was never reported');
  assert.ok(calls > 1, 'watcher gave up after the first failure');
  assert.equal((errors[0] as Error).message, 'unsupported challenge');
});

test('a failing solve backs off instead of hot-looping', async () => {
  let calls = 0;
  const solver = fakeSolver({ async solve() { calls += 1; throw new Error('nope'); } });
  const watcher = watchPage(solver, fakePage(), { intervalMs: 1, errorBackoffMs: 40 });

  await sleep(100);
  await watcher.stop();

  assert.ok(calls <= 5, `backoff not applied: ${calls} attempts in 100ms`);
});

test('maxSolves stops the watcher on its own', async () => {
  const solver = fakeSolver();
  const watcher = watchPage(solver, fakePage(), { intervalMs: 2, maxSolves: 2 });

  await sleep(80);

  assert.equal(watcher.solves, 2);
  assert.equal(watcher.running, false, 'watcher kept running past maxSolves');
  assert.equal(solver.solveCalls, 2);
  await watcher.stop();
});

test('a closed page ends the watcher rather than throwing forever', async () => {
  const page = fakePage();
  const solver = fakeSolver({ async detectCaptcha() { return null; } });
  const watcher = watchPage(solver, page, { intervalMs: 5 });

  await sleep(20);
  page.close();
  await sleep(30);

  assert.equal(watcher.running, false, 'watcher outlived its page');
  await watcher.stop();
});

test('a throwing onSolved callback does not stop the watcher', async () => {
  let reports = 0;
  const solver = fakeSolver();
  const watcher = watchPage(solver, fakePage(), {
    intervalMs: 5,
    onSolved: () => { reports += 1; throw new Error('caller bug'); },
  });

  await sleep(60);
  await watcher.stop();

  assert.ok(reports > 1, 'the callers own exception killed the loop');
});

test('stop() is idempotent and safe before the first tick', async () => {
  const watcher = watchPage(fakeSolver(), fakePage(), { intervalMs: 10_000 });
  await watcher.stop();
  await watcher.stop();
  assert.equal(watcher.running, false);
  assert.equal(watcher.solves, 0);
});
