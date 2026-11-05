import fs from 'node:fs';
import path from 'node:path';
import { test } from 'node:test';
import assert from 'node:assert/strict';

import { resolveLoraName, isHostedEndpoint, getBundledCliRoot } from './model-name';

const CLI_ROOT = getBundledCliRoot();
const REG = JSON.parse(fs.readFileSync(
  path.join(CLI_ROOT, 'src', 'captchakraken', 'models.json'), 'utf-8'));
const HOSTED = 'https://api.captchakraken.com/v1';

test('our endpoint is asked for the hosted default', () => {
  const name = resolveLoraName({ cliRoot: CLI_ROOT, env: {}, baseUrl: HOSTED });
  const repo = REG.served_aliases[name];
  assert.equal(repo, REG.hosted_default,
    `${name} should be an alias of ${REG.hosted_default}`);
});

test('and asked for the v2 pointer model', () => {
  const name = resolveLoraName({ cliRoot: CLI_ROOT, env: {}, baseUrl: HOSTED });
  const entry = REG.models[REG.served_aliases[name]];
  assert.equal(entry?.prompt_version, '4');
  assert.equal(entry?.kind, 'merged');
});

test("someone else's vLLM is asked for the download default", () => {
  for (const url of ['http://localhost:8000/v1', 'http://10.0.0.5:8000/v1',
                     'https://vllm.someone-else.example/v1']) {
    assert.equal(resolveLoraName({ cliRoot: CLI_ROOT, env: {}, baseUrl: url }),
      REG.models[REG.latest].lora_name, `${url} must not get the hosted default`);
  }
});

test('an unknown endpoint, or none at all, gets the download default', () => {
  assert.equal(resolveLoraName({ cliRoot: CLI_ROOT, env: {} }),
    REG.models[REG.latest].lora_name);
  assert.equal(resolveLoraName({ cliRoot: CLI_ROOT, env: {}, baseUrl: 'not a url' }),
    REG.models[REG.latest].lora_name);
});

test('an explicit pin still wins, hosted or not', () => {
  assert.equal(
    resolveLoraName({ cliRoot: CLI_ROOT, env: { CAPTCHA_LORA_NAME: 'captcha-v12' },
                      baseUrl: HOSTED }),
    'captcha-v12');
});

test('a staging gateway can be added, and nothing else is', () => {
  const env = { CAPTCHA_HOSTED_HOSTS: 'staging.captchakraken.com' };
  assert.equal(isHostedEndpoint('https://staging.captchakraken.com/v1', env), true);
  assert.equal(isHostedEndpoint('https://evil.example/v1', env), false);
  assert.equal(isHostedEndpoint('https://staging.captchakraken.com/v1', {}), false);
});

test('the hosted default is the registered public v2 model', () => {
  const entry = REG.models[REG.hosted_default];
  assert.ok(entry, `${REG.hosted_default} is not in the registry`);
  assert.equal(entry.availability ?? 'public', 'public');
  assert.equal(entry.prompt_version, REG.models[REG.latest].prompt_version,
    'hosted and download defaults must share a prompt generation, or the two '
    + 'halves of one client send prompts their model was not trained on');
});
