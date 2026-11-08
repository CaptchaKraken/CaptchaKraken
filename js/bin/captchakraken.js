#!/usr/bin/env node
// `npx captchakraken fetch`, `start`, `stop`, `demo`: the Python engine's command, from its bundled environment.
const { spawnSync } = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');

const root = path.resolve(__dirname, '..');
const python = path.join(root, 'python', '.venv', 'bin', 'python');
const windowsPython = path.join(root, 'python', '.venv', 'Scripts', 'python.exe');

function engine() {
  return [python, windowsPython].find((p) => fs.existsSync(p));
}

// A package manager that skips install scripts leaves the environment for now.
if (!engine()) {
  spawnSync(process.execPath, [path.join(root, 'scripts', 'setup-python.js')], { stdio: 'inherit' });
}
const found = engine();
if (!found) {
  console.error('[captchakraken] The Python engine is not installed. This needs Python 3.10 or newer.');
  process.exit(1);
}
const { status, signal } = spawnSync(found, ['-m', 'captchakraken.cli', ...process.argv.slice(2)], { stdio: 'inherit' });
process.exit(status ?? (signal ? 1 : 0));
