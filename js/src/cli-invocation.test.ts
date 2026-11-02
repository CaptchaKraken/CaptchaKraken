// The key rides in env because argv is world-readable; the args are an array so no shell ever sees them.
import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  API_KEY_ENV,
  buildSolveArgs,
  redactCommand,
  solveEnv,
  type SolveInvocation,
} from './cli-invocation';
import { RetryMode, Vendor } from './kinds';

// Hardcoded, not read from the env: with both undefined every assertion here would pass while testing nothing.
const TRACER = 'not-a-key-just-a-string-this-test-follows';

const invocation: SolveInvocation = {
  imagePath: '/tmp/captcha_123.png',
  model: 'captcha-v12',
  puzzleSource: Vendor.HCAPTCHA,
};

test('the api key never appears in argv', () => {
  const args = buildSolveArgs(invocation);
  for (const arg of args) {
    assert.ok(
      !arg.includes(TRACER),
      `argv carried the credential (${arg}). /proc/<pid>/cmdline is world-readable.`,
    );
  }
});

test('the key is passed through the environment instead', () => {
  const env = solveEnv({ PATH: '/usr/bin' }, TRACER);
  assert.equal(env[API_KEY_ENV], TRACER);
  assert.equal(env.PATH, '/usr/bin', 'the base environment must survive');
});

test('no credential in the environment when none was configured', () => {
  const env = solveEnv({ PATH: '/usr/bin' });
  assert.ok(!(API_KEY_ENV in env));
});

test('a logged command is redacted even if a key reaches it', () => {
  const line = `python -m captchakraken.cli shot.png captcha-v12 captchaKrakenApi ${TRACER}`;
  const redacted = redactCommand(line, TRACER);
  assert.ok(!redacted.includes(TRACER), 'the printed command still contained the token');
  assert.ok(redacted.includes('***'));
});

test('args are an array for execFile, not a shell string', () => {
  const args = buildSolveArgs({ ...invocation, imagePath: "/tmp/a b'c.png" });
  assert.ok(Array.isArray(args));
  assert.ok(
    args.includes("/tmp/a b'c.png"),
    'the path must be one literal argv entry, not shell-quoted text',
  );
});

test('vendor hint, retry mode and text mode still reach the CLI', () => {
  const args = buildSolveArgs({
    ...invocation,
    retryMode: RetryMode.MISSED_TILES,
    textMode: true,
  });
  assert.ok(args.includes('--puzzle-source=hcaptcha'));
  assert.ok(args.includes('--retry-mode=missed-tiles'));
  assert.ok(args.includes('--text-mode'));
  assert.ok(args.includes('captcha-v12'));
});

