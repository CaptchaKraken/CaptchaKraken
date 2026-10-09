// A blank rebuild panel is the stillest state, and the model answers it dead centre (6 of 52 requests). Structure is measured from the
// middle because chrome paints early, the floor is blank-vs-anything, and the freshsolve re-query needs the gate too.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import { resolve } from 'node:path';

import { CaptchaKrakenSolver } from './solver';
import { photographsItself } from './fake-dom.test';

const el = () => ({
  async screenshot({ path }: { path: string }) { fs.writeFileSync(path, 'x'); },
});

function solverSeeing(verdicts: Array<boolean | null>, config: Record<string, unknown> = {}) {
  const s: any = photographsItself(new CaptchaKrakenSolver({ boardPaintPollMs: 1, boardPaintTimeoutMs: 60, ...config }));
  let i = 0;
  s.calls = 0;
  s.runCvTool = async () => {
    s.calls++;
    const v = verdicts[Math.min(i++, verdicts.length - 1)];
    return { painted: v, texture: v ? 0.5 : 0.0, floor: 0.015 };
  };
  return s;
}

test('a painted board is photographed at once, with no wait', async () => {
  const s = solverSeeing([true]);
  const { verdict, waitedMs } = await s.waitForBoardPainted(el());
  assert.equal(verdict, 'painted');
  assert.equal(s.calls, 1);
  assert.ok(waitedMs < 60, `should not have waited, waited ${waitedMs}ms`);
});

test('a blank board is polled until it paints, and is not photographed blank', async () => {
  const s = solverSeeing([false, false, false, true]);
  const { verdict } = await s.waitForBoardPainted(el());
  assert.equal(verdict, 'painted');
  assert.equal(s.calls, 4, 'should have kept looking until there was a puzzle');
});

test('a board that never paints falls through rather than stalling the solve', async () => {
  const s = solverSeeing([false]);
  const started = Date.now();
  const { verdict } = await s.waitForBoardPainted(el());
  assert.equal(verdict, 'blank');
  assert.ok(Date.now() - started < 2000, 'must be bounded by boardPaintTimeoutMs');
});

test('an unreadable image is not treated as a blank one', async () => {
  const s = solverSeeing([null]);
  const { verdict } = await s.waitForBoardPainted(el());
  assert.equal(verdict, 'unknown');
  assert.equal(s.calls, 1);
});

test('a screenshot that throws is a skipped poll, not a verdict', async () => {
  const s = solverSeeing([true]);
  let first = true;
  const flaky = {
    async screenshot({ path }: { path: string }) {
      if (first) { first = false; throw new Error('element is detaching'); }
      fs.writeFileSync(path, 'x');
    },
  };
  const { verdict } = await s.waitForBoardPainted(flaky);
  assert.equal(verdict, 'painted');
});

test('the freshness re-solve waits for paint before it re-photographs', async () => {
  const src = fs.readFileSync(resolve(__dirname, '..', 'src', 'solver.ts'), 'utf8');
  const at = src.indexOf('`freshsolve_${Date.now()}');
  assert.notEqual(at, -1, 'could not find the freshness re-solve frame');
  const before = src.slice(Math.max(0, at - 1200), at);
  assert.ok(
    before.includes('await this.waitForBoardPainted(captchaElement);'),
    'the freshness re-solve must wait for the board to paint before grabbing a '
    + 'fresh frame — it fires precisely when the board is mid-rebuild',
  );
});
