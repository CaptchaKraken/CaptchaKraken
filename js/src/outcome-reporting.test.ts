// The outcome report goes through the same engine call as the Python port's, so the endpoint, body, timeout, opt-out
// and 404 rules are one implementation (python/tests/test_outcome_reporting.py pins those). What this port owns is
// the hand-off: the right arguments and routing env, the engine's warnings made visible, and a self-hosted "no such
// route" remembered so it is not asked again for every solve.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

import { CaptchaKrakenSolver } from './solver';
import { getBundledCliRoot } from './model-name';
import type { PlaywrightPage } from './playwright-types';

/** An executable that stands in for the engine: it records what it was called with and answers `reply`. */
function fakeEngine(reply: object, warning = ''): { py: string; calls: () => string[] } {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'ck_engine_'));
  const log = path.join(dir, 'calls');
  const py = path.join(dir, 'python');
  fs.writeFileSync(py, [
    '#!/bin/sh',
    `echo "$* vendor=$CAPTCHA_KRAKEN_VENDOR site=$CAPTCHA_KRAKEN_SITE session=$CAPTCHA_KRAKEN_SESSION" >> ${JSON.stringify(log)}`,
    warning ? `echo ${JSON.stringify(warning)} >&2` : '',
    `echo '${JSON.stringify(reply)}'`,
  ].join('\n'), { mode: 0o755 });
  return { py, calls: () => (fs.existsSync(log) ? fs.readFileSync(log, 'utf8').trim().split('\n') : []) };
}

/** The report unrefs its child so a finished script can exit; a test awaiting it keeps the loop alive itself. */
async function awaited(report: Promise<void>): Promise<void> {
  const alive = setInterval(() => {}, 50);
  try {
    await report;
  } finally {
    clearInterval(alive);
  }
}

function solverWith(py: string): any {
  const solver: any = new CaptchaKrakenSolver();
  solver.resolveCli = () => ({ cliRoot: os.tmpdir(), py });
  return solver;
}

test('the report names the session, the outcome, the vendor and the site', async () => {
  const engine = fakeEngine({ reported: true, supported: true });
  const solver = solverWith(engine.py);
  solver.solveSessionId = 'SESSION-1';
  solver.solveVendor = 'geetest';
  solver.solveSite = 'shop.example.com';
  await awaited(solver.reportOutcome('SESSION-1', true));
  assert.deepEqual(engine.calls(), ['-m captchakraken.cli report-outcome SESSION-1 solved vendor=geetest site=shop.example.com session=SESSION-1']);
});

test('a self-hosted endpoint with no outcome route is not asked again', async () => {
  const engine = fakeEngine({ reported: false, supported: false });
  const solver = solverWith(engine.py);
  await awaited(solver.reportOutcome('SESSION-1', false));
  await awaited(solver.reportOutcome('SESSION-2', false));
  assert.equal(engine.calls().length, 1);
});

test('a hosted refusal is reported every time, and its warning reaches stderr', async () => {
  const engine = fakeEngine({ reported: false, supported: true }, '[captchakraken] warning: outcome report was refused: HTTP 404');
  const solver = solverWith(engine.py);
  const written: string[] = [];
  const write = process.stderr.write.bind(process.stderr);
  (process.stderr as any).write = (chunk: any) => { written.push(String(chunk)); return true; };
  try {
    await awaited(solver.reportOutcome('SESSION-1', true));
    await awaited(solver.reportOutcome('SESSION-2', true));
  } finally {
    (process.stderr as any).write = write;
  }
  assert.equal(engine.calls().length, 2);
  assert.equal(written.filter((w) => w.includes('HTTP 404')).length, 2);
});

test('the opt-out spawns nothing', async () => {
  const engine = fakeEngine({ reported: true, supported: true });
  const solver = solverWith(engine.py);
  process.env.CAPTCHA_REPORT_OUTCOME = '0';
  try {
    await awaited(solver.reportOutcome('SESSION-1', true));
  } finally {
    delete process.env.CAPTCHA_REPORT_OUTCOME;
  }
  assert.deepEqual(engine.calls(), []);
});

test('the site is the hostname and nothing else', async () => {
  const solver: any = new CaptchaKrakenSolver();
  solver.solveImpl = async () => ({ isSolved: true, verdicts: [] });
  solver.reportOutcome = () => {};
  let site: string | null = null;
  solver.stopAnimatedFilm = async () => { site = solver.solveSite; };
  await solver.solve({ url: () => 'https://Shop.Example.com:8443/checkout/step-2?order=SYNTHETIC#pay' } as unknown as PlaywrightPage);
  assert.equal(site, 'shop.example.com');
  await solver.solve({ url: () => 'about:blank' } as unknown as PlaywrightPage);
  assert.equal(site, null);
});

test('inference carries the vendor and site to the engine alongside the session', () => {
  const solver: any = new CaptchaKrakenSolver();
  solver.solveSessionId = 'SESSION-1';
  solver.solveVendor = 'recaptcha';
  solver.solveSite = 'shop.example.com';
  const env = solver.solveEnvironment(os.tmpdir(), undefined);
  assert.equal(env.CAPTCHA_KRAKEN_SESSION, 'SESSION-1');
  assert.equal(env.CAPTCHA_KRAKEN_VENDOR, 'recaptcha');
  assert.equal(env.CAPTCHA_KRAKEN_SITE, 'shop.example.com');
});

test('inference carries the widget host, and keeps the engine from repeating the model warning', () => {
  const solver: any = new CaptchaKrakenSolver();
  solver.solveWidgetHost = 'assets.vendor.example';
  const env = solver.solveEnvironment(os.tmpdir(), undefined);
  assert.equal(env.CAPTCHA_KRAKEN_WIDGET_HOST, 'assets.vendor.example');
  assert.equal(env.CAPTCHA_KRAKEN_MODEL_WARNING, '0');
});

test('the widget host is the iframe\'s hostname and nothing else', async () => {
  const solver: any = new CaptchaKrakenSolver();
  solver.clickCheckbox = async () => { throw new Error('stop after the host is set'); };
  const frame = { url: () => 'https://Assets.Vendor.Example/challenge?k=SYNTHETIC' };
  const widget = { el: { contentFrame: async () => frame }, at: null, vendor: 'recaptcha', role: 'checkbox' };
  await assert.rejects(solver.solveSingle(null, widget, 0));
  assert.equal(solver.solveWidgetHost, 'assets.vendor.example');
});

test('a hosted model name with no route is warned about once per solver', () => {
  const solver: any = new CaptchaKrakenSolver({ model: 'captcha' });
  const before = process.env.VLLM_BASE_URL;
  const errors: string[] = [];
  const original = console.error;
  console.error = (m: string) => { errors.push(String(m)); };
  try {
    process.env.VLLM_BASE_URL = 'https://api.captchakraken.com/v1';
    solver.modelName(getBundledCliRoot());
    solver.modelName(getBundledCliRoot());
    new CaptchaKrakenSolver({ model: 'abyss-grid' } as any)['modelName'](getBundledCliRoot());
  } finally {
    console.error = original;
    if (before === undefined) delete process.env.VLLM_BASE_URL; else process.env.VLLM_BASE_URL = before;
  }
  assert.equal(errors.filter((m) => m.includes("answers the model name 'captcha' with an older model")).length, 1);
  assert.equal(errors.length, 1);
});
