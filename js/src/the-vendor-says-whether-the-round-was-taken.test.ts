// The vendor's own answer-check response decides a round, and only a refusal to serve ends the solve early.
//
// A DOM done-signal only says something changed on the page; the answer-check response says whether the round was
// taken. The shapes in python/tests/fixtures/vendor_verdicts.json were recorded on the vendors' public demo pages and
// then stripped of every token; the Python port reads the same file, so the two parsers cannot drift apart.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import path from 'node:path';

import { CaptchaKrakenSolver } from './solver';
import { VerdictLog, readVerdict } from './verdicts';
import { Verdict } from './kinds';
import type { PlaywrightPage, PlaywrightResponse } from './playwright-types';

interface Case { name: string; url: string; status: number; body: string; vendor: string | null; verdict: string | null }
const CASES: Case[] = JSON.parse(readFileSync(
  path.join(__dirname, '..', '..', 'python', 'tests', 'fixtures', 'vendor_verdicts.json'), 'utf8')).cases;
const byName = (name: string) => CASES.find((c) => c.name === name) as Case;

for (const c of CASES) {
  test(`recorded response: ${c.name}`, () => {
    assert.deepEqual(readVerdict(c.url, c.status, c.body), c.verdict === null ? null : { vendor: c.vendor, verdict: c.verdict });
  });
}

/** Just the event surface: the page emits a response by calling what was registered. */
function listeningPage() {
  const listeners = new Set<(r: PlaywrightResponse) => void>();
  const read: string[] = [];
  const page = {
    on: (_: 'response', l: (r: PlaywrightResponse) => void) => listeners.add(l),
    off: (_: 'response', l: (r: PlaywrightResponse) => void) => listeners.delete(l),
    emit: (c: Case) => listeners.forEach((l) => l({
      url: () => c.url, status: () => c.status, text: async () => { read.push(c.url); return c.body; },
    })),
  };
  return { page: page as unknown as PlaywrightPage & { emit: (c: Case) => void }, listeners, read };
}

test('the log reads only the bodies it can judge and lets go of the page', async () => {
  const { page, listeners, read } = listeningPage();
  const log = new VerdictLog(page);
  page.emit(byName("A page's own traffic is not read"));
  page.emit(byName('hCaptcha refuses the answer'));
  page.emit(byName('hCaptcha takes the answer'));
  assert.deepEqual((await log.fresh()).map((v) => v.verdict), [Verdict.REJECTED, Verdict.ACCEPTED]);
  assert.ok(!read.includes(byName("A page's own traffic is not read").url), 'a body the driver cannot judge was read anyway');
  assert.deepEqual(await log.fresh(), [], 'a verdict was handed out twice');
  assert.equal(log.decisive(), Verdict.ACCEPTED);
  await log.close();
  assert.equal(listeners.size, 0);
});

test('a page that cannot be listened to records nothing and throws nothing', async () => {
  const log = new VerdictLog({} as PlaywrightPage);
  assert.deepEqual(await log.fresh(), []);
  assert.equal(log.decisive(), null);
  await log.close();
});

/** A solver whose every round interacts and then lets `onRound` put traffic on the page's wire. */
function driver(onRound: (n: number) => void, opts: { solved?: () => boolean; present?: () => boolean } = {}) {
  const solver: any = new CaptchaKrakenSolver({ maxSolveLoops: 6, postSolveOutcomeTimeoutMs: 40, postSolveOutcomePollMs: 5,
    staleElementBackoffMs: 0, detectionTimeoutMs: 0 });
  const state = { rounds: 0 };
  solver.solveSingle = async () => { state.rounds++; onRound(state.rounds); return { didInteract: true, tokenUsage: [] }; };
  solver.detectCaptcha = async () => ((opts.present ?? (() => true))() ? { vendor: 'hcaptcha', role: 'challenge' } : null);
  solver.isCaptchaSolved = async () => (opts.solved ?? (() => false))();
  solver.isChallengeFreshlyRendered = async () => false;
  solver.bannerKind = async () => null;
  solver.isBlocked = async () => false;
  solver.human.reset = async () => {};
  return { solver, state };
}

test('an accepted verdict ends the solve as solved', async () => {
  const { page } = listeningPage();
  const { solver, state } = driver(() => page.emit(byName('hCaptcha takes the answer')));
  const result = await solver.solveImpl(page);
  assert.equal(result.isSolved, true);
  assert.equal(state.rounds, 1);
  assert.deepEqual(result.verdicts, [{ vendor: 'hcaptcha', verdict: Verdict.ACCEPTED }]);
});

test('a rejected verdict counts the loop and the next one can still win', async () => {
  const { page } = listeningPage();
  const said = ['GeeTest refuses the answer', 'GeeTest refuses the answer', 'GeeTest takes the answer'];
  const { solver, state } = driver((n) => page.emit(byName(said[n - 1])));
  const result = await solver.solveImpl(page);
  assert.equal(result.isSolved, true);
  assert.equal(state.rounds, 3);
  assert.deepEqual(result.verdicts.map((v: { verdict: string }) => v.verdict), [Verdict.REJECTED, Verdict.REJECTED, Verdict.ACCEPTED]);
});

test('a widget that vanishes after a rejection was not solved', async () => {
  const { page } = listeningPage();
  let gone = false;
  const { solver } = driver(() => { page.emit(byName('hCaptcha refuses the answer')); gone = true; }, { present: () => !gone });
  await assert.rejects(solver.solveImpl(page), /rejected the last answer/);
});

test('every rejected round is spent before giving up', async () => {
  const { page } = listeningPage();
  const { solver, state } = driver(() => page.emit(byName('reCAPTCHA refuses the answer and deals the next board')));
  await assert.rejects(solver.solveImpl(page), /after 6 solve loops/);
  assert.equal(state.rounds, 6);
});

test('a vendor that refuses to serve ends the solve at once', async () => {
  const { page } = listeningPage();
  const { solver, state } = driver(() => page.emit(byName('hCaptcha refuses to serve at all')));
  await assert.rejects(solver.solveImpl(page), /429/);
  assert.equal(state.rounds, 1);
});

test('a try-again-later screen ends the solve at once', async () => {
  const { page } = listeningPage();
  const { solver, state } = driver(() => {});
  solver.isBlocked = async () => true;
  await assert.rejects(solver.solveImpl(page), /try-again-later/);
  assert.equal(state.rounds, 1);
});

test('the reported outcome is the vendor\'s verdict over the DOM', async () => {
  const { page } = listeningPage();
  let round = 0;
  const { solver } = driver((n) => { round = n; page.emit(byName('hCaptcha refuses the answer')); }, { solved: () => round >= 1 });
  const reports: boolean[] = [];
  solver.reportOutcome = (_session: string, solved: boolean) => reports.push(solved);
  solver.stopAnimatedFilm = async () => {};
  assert.equal((await solver.solve(page)).isSolved, true);
  assert.deepEqual(reports, [false]);
});

test('without a readable verdict the DOM decides the report', async () => {
  const { page } = listeningPage();
  const { solver } = driver(() => {}, { solved: () => true });
  const reports: boolean[] = [];
  solver.reportOutcome = (_session: string, solved: boolean) => reports.push(solved);
  solver.stopAnimatedFilm = async () => {};
  assert.deepEqual((await solver.solve(page)).verdicts, []);
  assert.deepEqual(reports, [true]);
});
