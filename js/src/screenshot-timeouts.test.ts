// Playwright's 30s default hangs on an animating frame, and the poll budget is only consulted between iterations, so each shot bounds itself.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import path from 'node:path';

const SOLVER = readFileSync(path.join(__dirname, '..', 'src', 'solver.ts'), 'utf8');

test('every capture goes through shot(), which always bounds the timeout', () => {
  // Playwright's 30s default hangs on a challenge that is being torn down.
  const calls = [...SOLVER.matchAll(/\.screenshot\(([^)]*)\)/g)].map((m) => m[1]);
  assert.deepEqual(calls, ['{ path: p, timeout, animations }', '{ timeout, animations }'],
    'a screenshot call bypasses shot(), or shot() stopped passing its timeout');
  assert.match(SOLVER, /private async shot\(el: ElementHandle, p: string, timeout = 2500/);
});
