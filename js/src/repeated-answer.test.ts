// An answer cache keyed on screenshot bytes replayed a failed answer on cycling boards: 81 loops, 12 model calls, 69 cache hits, 0 solves.
// A repeat is evidence, so it escalates to a recording; reCAPTCHA never is; the flag is per challenge.
import { test } from 'node:test';
import assert from 'node:assert/strict';

import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

import { CaptchaKrakenSolver } from './solver';
import { VerdictLog } from './verdicts';

const ANSWER = { actions: [{ action: 'click', target_bounding_boxes: [[0.1, 0.1, 0.2, 0.2]] }], token_usage: [] };

function solverWithFixedAnswer(config: Record<string, unknown> = {}): { solver: any; calls: () => number } {
  const solver: any = new CaptchaKrakenSolver(config);
  let calls = 0;
  solver.askModel = async () => {
    calls += 1;
    return ANSWER;
  };
  return { solver, calls: () => calls };
}

test('the same picture is not answered twice from cache', async () => {
  const { solver, calls } = solverWithFixedAnswer();

  const first = await solver.answerFor('same-picture', () => solver.askModel());
  const second = await solver.answerFor('same-picture', () => solver.askModel());

  assert.deepEqual(first.actions, ANSWER.actions);

  assert.equal(calls(), 1, 'the second identical picture should not cost a model call');
  assert.deepEqual(second.actions, ANSWER.actions);
});

test('a repeated picture is recorded as evidence the still reading was wrong', async () => {
  const { solver } = solverWithFixedAnswer();

  assert.equal(solver.repeatedAnswerSeen, false, 'nothing has repeated yet');
  await solver.answerFor('same-picture', () => solver.askModel());
  assert.equal(solver.repeatedAnswerSeen, false, 'one answer is not a repeat');

  await solver.answerFor('same-picture', () => solver.askModel());
  assert.equal(solver.repeatedAnswerSeen, true, 'the second identical picture is the signal');
});

test('a different picture each round never trips the signal', async () => {
  const { solver, calls } = solverWithFixedAnswer();

  for (const key of ['round-1', 'round-2', 'round-3', 'round-4']) {
    await solver.answerFor(key, () => solver.askModel());
  }

  assert.equal(solver.repeatedAnswerSeen, false);
  assert.equal(calls(), 4, 'four distinct boards are four model calls');
});

test('the signal escalates a non-reCAPTCHA challenge to the recorded path', async () => {
  const { solver } = solverWithFixedAnswer();

  assert.equal(solver.shouldRetryAsAnimated('unknown'), false);
  solver.repeatedAnswerSeen = true;
  assert.equal(solver.shouldRetryAsAnimated('unknown'), true);
  assert.equal(solver.shouldRetryAsAnimated('hcaptcha'), true);
});

test('reCAPTCHA is left alone', async () => {
  const { solver } = solverWithFixedAnswer();
  solver.repeatedAnswerSeen = true;

  assert.equal(solver.shouldRetryAsAnimated('recaptcha'), false);
});

test('a caller who turned video solving off is not escalated into it', async () => {
  const { solver } = solverWithFixedAnswer({ videoSolveEnabled: false });
  solver.repeatedAnswerSeen = true;

  assert.equal(solver.shouldRetryAsAnimated('unknown'), false);
});

test('the signal does not survive into the next solve', async () => {
  const { solver } = solverWithFixedAnswer();
  await solver.answerFor('same-picture', () => solver.askModel());
  await solver.answerFor('same-picture', () => solver.askModel());
  assert.equal(solver.repeatedAnswerSeen, true);

  solver.resetSolveState();

  assert.equal(solver.repeatedAnswerSeen, false);
  assert.equal(solver.shouldRetryAsAnimated('unknown'), false);
});

test('a repeated answer is reported so the round performs nothing', () => {
  const { solver } = solverWithFixedAnswer();

  assert.equal(solver.noteAnswer(ANSWER.actions, null), false, 'the first answer runs');
  assert.equal(solver.noteAnswer(ANSWER.actions, null), true, 'the same answer again already ran and changed nothing');
  assert.equal(solver.noProgressRounds, 1);
});

test('the same point on a new page is not a repeat', () => {
  const { solver } = solverWithFixedAnswer();

  assert.equal(solver.noteAnswer(ANSWER.actions, null, 'page-1'), false);
  assert.equal(solver.noteAnswer(ANSWER.actions, null, 'page-2'), false, 'a new board has not run this point yet');
  assert.equal(solver.noteAnswer(ANSWER.actions, null, 'page-2'), true, 'on the same board it is still a repeat');
});

test("the model's other plans reach the round that needs them", async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'ck-plans-'));
  const plan = [{ action: 'click', target_bounding_boxes: [[0.5, 0.5, 0.6, 0.6]] }];
  const cli = path.join(dir, 'cli.sh');
  fs.writeFileSync(cli, `#!/bin/sh\ncat <<'EOF'\n${JSON.stringify({ ...ANSWER, fallbacks: [plan] })}\nEOF\n`, { mode: 0o755 });
  try {
    const solver: any = new CaptchaKrakenSolver({});
    solver.resolveCli = () => ({ cliRoot: dir, py: cli });
    const asked = await solver.askModel(path.join(dir, 'board.png'));
    assert.deepEqual(asked.fallbacks, [plan], 'askModel should hand on the plans the CLI printed');

    const fresh = await solver.answerFor('same-picture', async () => asked);
    assert.deepEqual(fresh.fallbacks, [plan]);
    const cached = await solver.answerFor('same-picture', async () => asked);
    assert.deepEqual(cached.fallbacks, [plan], 'a repeated picture still has its other plans to try');
  } finally {
    fs.rmSync(dir, { recursive: true, force: true });
  }
});

function widgetTraffic(): { log: any; say: (type: string) => void } {
  const listeners = new Set<(r: any) => void>();
  const log = new VerdictLog({ on: (_: string, l: any) => listeners.add(l), off: () => {} } as any);
  const say = (type: string) => listeners.forEach((l) => l({
    url: () => 'https://widget.example/round', status: () => 200, text: async () => '',
    request: () => ({ resourceType: () => type }),
  }));
  return { log, say };
}

test('a repeat on a board that never answered earns no further press', () => {
  const { solver } = solverWithFixedAnswer();
  const { log, say } = widgetTraffic();
  solver.verdicts = log;

  solver.noteAnswer(ANSWER.actions, null, 'board');
  say('image');
  assert.equal(solver.noteAnswer(ANSWER.actions, null, 'board'), true);
  assert.equal(solver.fallbackArmed, false, 'nothing refused the answer, and another plan is one more press');
});

test('a repeat after the widget answered moves to the next plan', () => {
  const { solver } = solverWithFixedAnswer();
  const { log, say } = widgetTraffic();
  solver.verdicts = log;

  solver.noteAnswer(ANSWER.actions, null, 'board');
  say('fetch');
  assert.equal(solver.noteAnswer(ANSWER.actions, null, 'board'), true);
  assert.equal(solver.fallbackArmed, true);
});

test('a page that cannot be listened to keeps the repeat as its only evidence', () => {
  const { solver } = solverWithFixedAnswer();
  solver.verdicts = new VerdictLog({} as any);

  solver.noteAnswer(ANSWER.actions, null, 'board');
  assert.equal(solver.noteAnswer(ANSWER.actions, null, 'board'), true);
  assert.equal(solver.fallbackArmed, true);
});

test('a filmed picture and a plain one of the same board are one board', async () => {
  const { solver } = solverWithFixedAnswer();
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'board-'));
  const plain = Buffer.from('the board, as the element paints it');
  solver.shot = async (_el: unknown, p: string) => fs.writeFileSync(p, plain);
  const filmed = path.join(dir, 'filmed.png');
  const shot = path.join(dir, 'shot.png');
  fs.writeFileSync(filmed, 'the same board, out of a recording');
  fs.writeFileSync(shot, plain);

  try {
    assert.equal(await solver.boardHash(null, filmed, true), await solver.boardHash(null, shot, false));
  } finally {
    fs.rmSync(dir, { recursive: true, force: true });
  }
});
