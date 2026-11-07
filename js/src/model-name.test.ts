// JS once defaulted to 'captcha' (gen-1) while Python resolved gen-2, losing 22 of the port's 44 puzzle types; the default comes from the registry now.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';

import { resolveLoraName } from './model-name.js';

const CLI_ROOT = path.resolve(__dirname, '..', '..', 'python');
const registry = () => JSON.parse(
  fs.readFileSync(path.join(CLI_ROOT, 'src', 'captchakraken', 'models.json'), 'utf-8'));

test('defaults to the registry `latest` entry, not a hardcoded alias', () => {
  const reg = registry();
  const expected = reg.models[reg.latest].lora_name;
  assert.equal(resolveLoraName({ cliRoot: CLI_ROOT, env: {} }), expected);
});

test('the default is a generation-4 pointer model', () => {
  const reg = registry();
  const name = resolveLoraName({ cliRoot: CLI_ROOT, env: {} });
  const repoId = reg.served_aliases[name] ?? name;
  assert.equal(reg.models[repoId].prompt_version, '4');
});

test('finds the bundled engine on its own — cliRoot is optional', () => {
  const reg = registry();
  assert.equal(resolveLoraName({ env: {} }), reg.models[reg.latest].lora_name);
  assert.equal(resolveLoraName({ env: { CAPTCHA_LORA_NAME: 'pinned' } }), 'pinned');
});

test('CAPTCHA_LORA_NAME still wins — pinning stays opt-in', () => {
  assert.equal(
    resolveLoraName({ cliRoot: CLI_ROOT, env: { CAPTCHA_LORA_NAME: 'captcha' } }),
    'captcha');
});

test('falls back to pinned_model.json when the registry is unreadable', () => {
  const pinned = JSON.parse(
    fs.readFileSync(path.join(CLI_ROOT, 'src', 'captchakraken', 'pinned_model.json'), 'utf-8'));
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'ck-model-name-'));
  fs.mkdirSync(path.join(root, 'src', 'captchakraken'), { recursive: true });
  fs.writeFileSync(path.join(root, 'src', 'captchakraken', 'pinned_model.json'),
    JSON.stringify(pinned));
  assert.equal(resolveLoraName({ cliRoot: root, env: {} }), pinned.lora_name);
});
