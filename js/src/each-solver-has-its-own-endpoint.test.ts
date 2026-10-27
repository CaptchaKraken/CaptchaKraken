// One process can drive browsers whose captchas belong to different servers, each with its own key. The endpoint
// therefore travels with the solver, not the process: a VLLM_BASE_URL set for one must not route the other.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

import { CaptchaKrakenSolver } from './solver';
import { getBundledCliRoot, resolveLoraName } from './model-name';

const CLI_ROOT = getBundledCliRoot();
const HOSTED = 'https://api.captchakraken.com/v1';
const LOCAL = 'http://localhost:8000/v1';
const NAMES = ['VLLM_BASE_URL', 'VLLM_API_KEY', 'CAPTCHA_KRAKEN_API_KEY', 'CAPTCHA_LORA_NAME', 'CAPTCHA_HOSTED_HOSTS'];

function withEnv(env: Record<string, string>, fn: () => void): void {
  const before = Object.fromEntries(NAMES.map((n) => [n, process.env[n]]));
  for (const n of NAMES) delete process.env[n];
  Object.assign(process.env, env);
  try {
    fn();
  } finally {
    for (const n of NAMES) if (before[n] === undefined) delete process.env[n]; else process.env[n] = before[n];
  }
}

test('two solvers in one process hand their own endpoint and key to the engine', () => {
  withEnv({ VLLM_BASE_URL: 'http://process.example/v1', CAPTCHA_KRAKEN_API_KEY: 'PROCESS-KEY' }, () => {
    const pro: any = new CaptchaKrakenSolver({ baseUrl: 'https://lease.example/v1', apiKey: 'PRO-KEY' });
    const own: any = new CaptchaKrakenSolver({ baseUrl: 'http://vllm.internal:8000/v1', apiKey: 'OWN-KEY' });
    const [a, b] = [pro, own].map((s) => s.solveEnvironment(os.tmpdir(), s.apiKey));
    assert.equal(a.VLLM_BASE_URL, 'https://lease.example/v1');
    assert.equal(a.CAPTCHA_KRAKEN_API_KEY, 'PRO-KEY');
    assert.equal(b.VLLM_BASE_URL, 'http://vllm.internal:8000/v1');
    assert.equal(b.CAPTCHA_KRAKEN_API_KEY, 'OWN-KEY');
  });
});

test('without the option the process endpoint and key still apply', () => {
  withEnv({ VLLM_BASE_URL: LOCAL, VLLM_API_KEY: 'PROCESS-KEY' }, () => {
    const solver: any = new CaptchaKrakenSolver();
    const env = solver.solveEnvironment(os.tmpdir(), solver.apiKey);
    assert.equal(env.VLLM_BASE_URL, LOCAL);
    assert.equal(env.CAPTCHA_KRAKEN_API_KEY, 'PROCESS-KEY');
    assert.equal(solver.modelName(CLI_ROOT), resolveLoraName({ cliRoot: CLI_ROOT, env: {}, baseUrl: LOCAL }));
  });
});

test('the model is resolved for the solver\'s own endpoint, not the process one', () => {
  const hostedName = resolveLoraName({ cliRoot: CLI_ROOT, env: {}, baseUrl: HOSTED });
  assert.notEqual(hostedName, resolveLoraName({ cliRoot: CLI_ROOT, env: {}, baseUrl: LOCAL }), 'the registry must tell the two apart');
  withEnv({ VLLM_BASE_URL: LOCAL }, () => {
    assert.equal((new CaptchaKrakenSolver({ baseUrl: HOSTED }) as any).modelName(CLI_ROOT), hostedName);
  });
  // With no process endpoint the CLI is not told a model at all, unless this solver names one.
  withEnv({}, () => {
    assert.equal((new CaptchaKrakenSolver() as any).modelName(CLI_ROOT), undefined);
    assert.equal((new CaptchaKrakenSolver({ baseUrl: HOSTED }) as any).modelName(CLI_ROOT), hostedName);
  });
});

test('the outcome report goes to the solver\'s own endpoint with its own key', async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'ck_engine_'));
  const py = path.join(dir, 'python');
  fs.writeFileSync(py, `#!/bin/sh\necho "$VLLM_BASE_URL $CAPTCHA_KRAKEN_API_KEY" > ${JSON.stringify(path.join(dir, 'env'))}\necho '{"reported":true,"supported":true}'\n`, { mode: 0o755 });
  const solver: any = new CaptchaKrakenSolver({ baseUrl: 'https://lease.example/v1', apiKey: 'PRO-KEY' });
  solver.resolveCli = () => ({ cliRoot: os.tmpdir(), py });
  let report: Promise<void> = Promise.resolve();
  withEnv({ VLLM_BASE_URL: LOCAL, CAPTCHA_KRAKEN_API_KEY: 'PROCESS-KEY' }, () => { report = solver.reportOutcome('SESSION-1', true); });
  const alive = setInterval(() => {}, 50);
  try { await report; } finally { clearInterval(alive); }
  assert.equal(fs.readFileSync(path.join(dir, 'env'), 'utf8').trim(), 'https://lease.example/v1 PRO-KEY');
});
