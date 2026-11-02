// The vendor hint is whichever table entry detection matched. hCaptcha is keyed on the same `hcaptcha` substring as its DOM
// selectors, not the apex host (challenges come off newassets.hcaptcha.com), and an inline vendor is named rather than left
// `unknown`: the engine only narrows the grid shapes of the vendors it lists.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import test from 'node:test';

import { CaptchaKrakenSolver } from './solver';
import { fakeDom, iframeMatches } from './fake-dom.test';

const REAL_CHALLENGE = 'https://newassets.hcaptcha.com/captcha/v1/3f1a2b/static/hcaptcha.html#frame=challenge&id=0x1&host=example.com';
const REAL_CHECKBOX = 'https://newassets.hcaptcha.com/captcha/v1/3f1a2b/static/hcaptcha.html#frame=checkbox&id=0x1&host=example.com';
const FIXTURE_CHALLENGE = 'http://127.0.0.1:8080/frame?hcaptcha.html#frame=challenge';

const detect = (matches: string[]) => (new CaptchaKrakenSolver({}) as any).detectCaptcha(fakeDom([{ matches }]));
const vendorOfIframe = async (src: string) => (await detect(iframeMatches(src)))?.vendor ?? null;

test('the vendor challenge is hCaptcha, in both frame roles', async () => {
  assert.deepEqual([(await detect(iframeMatches(REAL_CHALLENGE))).vendor, (await detect(iframeMatches(REAL_CHALLENGE))).role], ['hcaptcha', 'challenge']);
  assert.deepEqual([(await detect(iframeMatches(REAL_CHECKBOX))).vendor, (await detect(iframeMatches(REAL_CHECKBOX))).role], ['hcaptcha', 'checkbox']);
});

test('an hCaptcha frame not served off the apex host is still hCaptcha', async () => {
  assert.equal(await vendorOfIframe(FIXTURE_CHALLENGE), 'hcaptcha');
});

test('the hint matches the same substring the DOM selectors do', () => {
  const config = JSON.parse(readFileSync(resolve(__dirname, '..', '..', 'captchakraken.config.json'), 'utf8'));
  const selectors = readFileSync(resolve(__dirname, '..', 'src', 'selectors.ts'), 'utf8');
  const solver = readFileSync(resolve(__dirname, '..', 'src', 'solver.ts'), 'utf8');
  assert.ok(config.vendors.hcaptcha.challenge.includes('iframe[src*="hcaptcha"][src*="frame=challenge"]'), 'the challenge selector moved — re-check what the hint keys on');
  assert.ok(!/includes\('hcaptcha\.com'\)/.test(solver + selectors), 'the apex host is being matched again somewhere; the shape gate will not engage');
});

test('reCAPTCHA is named by its api2 path', async () => {
  assert.equal(await vendorOfIframe('https://www.google.com/recaptcha/api2/bframe?k=6Le'), 'recaptcha');
  assert.equal(await vendorOfIframe('https://www.google.com/recaptcha/api2/anchor?k=6Le'), 'recaptcha');
  assert.equal(await vendorOfIframe('https://recaptcha.net/recaptcha/api2/bframe?k=6Le'), 'recaptcha');
});

test('"recaptcha" does not read as "hcaptcha"', async () => {
  assert.equal(await vendorOfIframe('/recaptcha/api2/bframe'), 'recaptcha');
});

test('an inline widget is named by its table entry, and a stray script is no widget at all', async () => {
  assert.equal((await detect(['.yidun_panel'])).vendor, 'yidun');
  assert.equal(await vendorOfIframe('https://api.geetest.com/gt.js'), null);
});
