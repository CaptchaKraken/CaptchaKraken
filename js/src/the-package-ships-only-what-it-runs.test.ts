// The npm tarball is the JS driver plus the one thing it shells out to: the Python engine's installable source.
//
// 3.1.0 shipped the engine's examples and Dockerfile inside the npm package, because the bundler copied `python/`
// wholesale and only knew what to leave out. It now names what goes in, and this reads the real pack list.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import path from 'node:path';

const ROOT = path.join(__dirname, '..');
const SHIPPED = [
  /^package\.json$/, /^README\.md$/, /^AGENTS\.md$/, /^LICENSE$/, /^NOTICE$/,
  /^dist\//,
  /^scripts\/setup-python\.js$/,
  /^python\/(pyproject\.toml|README\.md|AGENTS\.md|LICENSE|NOTICE)$/,
  /^python\/src\/captchakraken\//,
];

test('npm pack lists only the driver and the engine it installs', () => {
  const [pack] = JSON.parse(execFileSync('npm', ['pack', '--dry-run', '--json', '--ignore-scripts'], { cwd: ROOT, encoding: 'utf8' }));
  const paths: string[] = pack.files.map((f: { path: string }) => f.path);
  assert.ok(paths.some((p) => p.startsWith('python/src/captchakraken/')), 'the engine the driver shells out to is missing');
  assert.deepEqual(paths.filter((p) => !SHIPPED.some((re) => re.test(p))), [], 'the tarball carries files the driver never runs');
  assert.deepEqual(paths.filter((p) => /__pycache__|\.pyc$|\/tests\/|\/examples\//.test(p)), []);
});
