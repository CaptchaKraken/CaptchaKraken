// Every URL pattern and selector the solver uses comes from captchakraken.config.json at the repository root, and a
// file of the caller's own is laid over it. Mirror of python/tests/test_the_selector_config_is_the_table.py: both ports
// are held to the same file, so they read it identically.
import assert from 'node:assert/strict';
import { mkdtempSync, readFileSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import test from 'node:test';
import { Vendor } from './kinds';
import { CaptchaKrakenSolver } from './solver';
import { DEFAULT_CONFIG_PATH, DEFAULT_TABLE, SELECTORS, SelectorConfigError, SelectorTable, loadConfig, submitByText, type SelectorConfigFile } from './selectors';
import { fakeDom } from './fake-dom.test';

const ROOT_CONFIG = resolve(__dirname, '..', '..', 'captchakraken.config.json');
const RAW = JSON.parse(readFileSync(ROOT_CONFIG, 'utf8'));
const CAMEL: Record<string, string> = { text_input: 'textInput', slider_handle: 'sliderHandle', hold_completes: 'holdCompletes' };

/** One vendor's entry as the file spells it, in this port's names, without the fields the file leaves empty. */
const expected = (raw: Record<string, unknown>) => Object.fromEntries(Object.entries(raw)
  .filter(([k, v]) => k !== 'note' && v !== false && v !== null && (k === 'hosts' || !Array.isArray(v) || v.length))
  .map(([k, v]) => [CAMEL[k] ?? k, v]));

test('a checkout reads the file at the repository root', () => {
  assert.equal(DEFAULT_CONFIG_PATH, ROOT_CONFIG);
});

test("every vendor is the file's entry in the file's order", () => {
  assert.deepEqual(Object.keys(SELECTORS), Object.keys(RAW.vendors).filter((k) => !k.startsWith('_')));
  for (const [vendor, entry] of Object.entries(SELECTORS)) {
    assert.deepEqual(entry, expected(RAW.vendors[vendor]), `vendors.${vendor} is not what the file says`);
  }
});

test("the generic fallbacks come last in the file's order", () => {
  const g = RAW.generic;
  assert.deepEqual(DEFAULT_TABLE.textInput.slice(-g.text_input.length), g.text_input);
  assert.deepEqual(DEFAULT_TABLE.sliderHandle.slice(-g.slider_handle.length), g.slider_handle);
  assert.deepEqual(DEFAULT_TABLE.piece.slice(-g.piece.length), g.piece);
  assert.deepEqual(DEFAULT_TABLE.submit.slice(0, g.submit_text.length), g.submit_text.map(submitByText));
  assert.equal(RAW.custom, null);
  assert.equal(loadConfig().custom, null);
});

const SIGNUP = { widget: ['#signup-captcha'], text_input: ['#signup-code'], submit: ['#signup-check'] };

test('a file with only your entry finds your captcha first', async () => {
  const mine = join(mkdtempSync(join(tmpdir(), 'ck-config-')), 'mine.json');
  writeFileSync(mine, JSON.stringify({ custom: SIGNUP }));
  const solver = new CaptchaKrakenSolver({ selectors: mine }) as any;
  const found = await solver.detectCaptcha(fakeDom([{ matches: ['#signup-captcha', '.geetest_box'] }]));
  assert.deepEqual([found?.vendor, found?.role], ['unknown', 'unknown']);
  assert.equal(solver.sel.textInput[0], '#signup-code');
  assert.equal(solver.sel.vendors.length, Object.keys(SELECTORS).length, 'a built-in vendor was dropped');
  const plain = new CaptchaKrakenSolver({}) as any;
  assert.equal(await plain.detectCaptcha(fakeDom([{ matches: ['#signup-captcha'] }])), null);
});

test('a parsed object works like a file', () => {
  assert.equal((new CaptchaKrakenSolver({ selectors: { custom: SIGNUP } }) as any).sel.vendors[0][0], Vendor.UNKNOWN);
});

test('a vendor you give replaces that vendor and keeps its place', () => {
  const table = new SelectorTable(undefined, { vendors: { geetest: { hosts: ['geetest.example'], widget: ['.my-geetest'] } } });
  assert.deepEqual(table.vendors.map(([v]) => v), Object.keys(SELECTORS));
  assert.deepEqual(table.selectors[Vendor.GEETEST].widget, ['.my-geetest']);
  assert.equal(table.selectors[Vendor.GEETEST].checkbox, undefined, 'the whole entry is replaced, not merged');
  assert.deepEqual(table.selectors[Vendor.RECAPTCHA], SELECTORS[Vendor.RECAPTCHA]);
});

test('a generic list you give replaces that list', () => {
  const table = new SelectorTable(undefined, { generic: { submit_text: ['weiter'] } });
  assert.equal(table.submit[0], submitByText('weiter'));
  assert.ok(!table.submit.includes(submitByText('verify')));
  assert.deepEqual(table.textInput, DEFAULT_TABLE.textInput);
});

test("customSelectors still wins over the file's entry", () => {
  const table = new SelectorTable({ widget: ['#old-way'] }, { custom: SIGNUP });
  assert.deepEqual(table.selectors[Vendor.UNKNOWN].widget, ['#old-way']);
});

const BAD: Array<[unknown, RegExp]> = [
  [{ vendor: {} }, /vendor: not a config key/],
  [{ vendors: { geetest: { hosts: [], widgets: ['.x'] } } }, /vendors\.geetest\.widgets: not a selector field/],
  [{ vendors: { mysite: { hosts: [] } } }, /vendors\.mysite: not a vendor/],
  [{ vendors: { geetest: { widget: ['.x'] } } }, /vendors\.geetest\.hosts: missing/],
  [{ vendors: { recaptcha: { hosts: [], banners: [['.b', 'maybe']] } } }, /vendors\.recaptcha\.banners\[0\]: verdict/],
  [{ vendors: { human: { hosts: [], hold_completes: 'yes' } } }, /vendors\.human\.hold_completes: must be true/],
  [{ custom: { widget: '.one-string' } }, /custom\.widget: must be a list of strings/],
  [{ custom: { text_input: ['#code'] } }, /nothing to detect/],
  [{ generic: { buttons: [] } }, /generic\.buttons: not a generic list/],
];

test('a bad key is named', () => {
  for (const [doc, names] of BAD) {
    assert.throws(() => new SelectorTable(undefined, doc as SelectorConfigFile), (e: unknown) => e instanceof SelectorConfigError && names.test(e.message),
      `${JSON.stringify(doc)} did not raise ${names}`);
  }
});

test('a file that is not JSON names the file', () => {
  const bad = join(mkdtempSync(join(tmpdir(), 'ck-config-')), 'broken.json');
  writeFileSync(bad, '{"custom": ');
  assert.throws(() => new CaptchaKrakenSolver({ selectors: bad }), /broken\.json: cannot be read as JSON/);
});
