// Each vendor's widget as its own page ships it, measured on its demo or a live page, is found and named by its own row.
// Frames are matched off their real `src`; inline widgets off their real id and class tokens.
import assert from 'node:assert/strict';
import test from 'node:test';

import { CaptchaKrakenSolver } from './solver';
import { SUBMIT_SELECTORS, WIDGET_PROBES } from './selectors';
import { fakeDom, FakeNode, iframeMatches } from './fake-dom.test';

interface Measured {
  tag: string;
  id?: string;
  classes?: string[];
  visible?: boolean;
}

/** The inline probes an element answers to. Only the shapes the inline rows use: `.a.b`, `tag.a`, `tag[id^="x"]`. */
function answersTo(el: Measured): string[] {
  return WIDGET_PROBES.map((p) => p.selector).filter((sel) => {
    const m = /^([a-z]*)((?:\.[\w-]+)*)(?:\[id\^="([^"]+)"\])?$/.exec(sel);
    if (!m) return false;
    const [, tag, classes, idPrefix] = m;
    return (!tag || tag === el.tag)
      && classes.split('.').filter(Boolean).every((c) => el.classes?.includes(c))
      && (!idPrefix || !!el.id?.startsWith(idPrefix))
      && (!!classes || !!idPrefix);
  });
}

const inline = (el: Measured): FakeNode => ({ matches: answersTo(el), visible: el.visible });
const frame = (src: string): FakeNode => ({ matches: iframeMatches(src) });
const detect = async (nodes: FakeNode[]) => {
  const found = await (new CaptchaKrakenSolver({}) as any).detectCaptcha(fakeDom(nodes));
  return found ? [found.vendor, found.role] : null;
};

test('reCAPTCHA Enterprise is reCAPTCHA, in both frame roles', async () => {
  assert.deepEqual(await detect([frame('https://www.google.com/recaptcha/enterprise/bframe?hl=en&v=abc&k=6Lf')]), ['recaptcha', 'challenge']);
  assert.deepEqual(await detect([frame('https://www.google.com/recaptcha/enterprise/anchor?ar=1&k=6Lf&co=aHR0&hl=en&size=normal')]), ['recaptcha', 'checkbox']);
  assert.equal(await detect([frame('https://www.google.com/recaptcha/enterprise/anchor?ar=1&k=6Lf&size=invisible')]), null);
});

test('FunCaptcha is found by the outer Arkose frame the host page carries', async () => {
  assert.deepEqual(await detect([frame('https://iframe.arkoselabs.com/B7D8911C-5CC8-A9A3-35B0-554ACEE604DA/index.html?mkt=en')]), ['funcaptcha', 'unknown']);
  assert.deepEqual(await detect([frame('https://client-api.arkoselabs.com/fc/assets/ec-game-core/game-core/1.40.0/standard/index.html?session=1')]), ['funcaptcha', 'unknown']);
});

test('Proton is found by its captcha frame, on the API host and under the app\'s own /api/', async () => {
  assert.deepEqual(await detect([frame('https://account-api.proton.me/core/v4/captcha?Token=abc&ForceWebMessaging=1')]), ['proton', 'unknown']);
  assert.deepEqual(await detect([frame('https://verify.proton.me/api/core/v4/captcha?Token=abc&ForceWebMessaging=1')]), ['proton', 'unknown']);
});

test('the AWS WAF card is found', async () => {
  assert.deepEqual(await detect([inline({ tag: 'div', classes: ['amzn-captcha-modal'] })]), ['awswaf', 'unknown']);
});

// Measured on captchafox.com: `<div id="cf-widget-<hex>">` holds `.cf-button`, and the puzzle opens in
// `div.cf-modal > div.cf-modal__wrap > div.cf-modal__challenge` with that box still showing.
const CAPTCHAFOX_BOX: Measured = { tag: 'div', id: 'cf-widget-2d5fe02ef9734' };
const CAPTCHAFOX_MODAL: Measured[] = [
  { tag: 'div', id: 'cf-modal-1a2b', classes: ['cf-modal'] },
  { tag: 'div', classes: ['cf-modal__wrap'] },
  { tag: 'div', classes: ['cf-modal__challenge'] },
];

test('the CaptchaFox box is a checkbox, and its open puzzle outranks it', async () => {
  assert.deepEqual(await detect([inline(CAPTCHAFOX_BOX)]), ['captchafox', 'checkbox']);
  assert.deepEqual(await detect([inline(CAPTCHAFOX_BOX), ...CAPTCHAFOX_MODAL.map(inline)]), ['captchafox', 'challenge']);
});

// Measured on dingxiang-inc.com/business/captcha: the trigger bar sits in `div.captcha-trigger.dx_captcha`, a hidden
// loading card is `div.dx_captcha.dx_captcha_loading-style-popup`, and the open card is the one-step popup.
const DINGXIANG_TRIGGER: Measured = { tag: 'div', classes: ['captcha-trigger', 'dx_captcha'] };
const DINGXIANG_LOADING: Measured = { tag: 'div', id: 'get-price-captcha', classes: ['dx_captcha', 'dx_captcha_loading-style-popup'], visible: false };
const DINGXIANG_POPUP: Measured = {
  tag: 'div',
  id: 'dx_captcha_oneclick_one-step_1',
  classes: ['dx_captcha_oneclick_one-step', 'dx_captcha', 'dx_captcha_clickword', 'dx_captcha-type-clickword', 'dx_captcha_clickword-style-popup'],
};

test('the Dingxiang popup is found, and its trigger bar is not a widget', async () => {
  assert.equal(await detect([inline(DINGXIANG_TRIGGER), inline(DINGXIANG_LOADING)]), null);
  assert.deepEqual(await detect([inline(DINGXIANG_TRIGGER), inline(DINGXIANG_LOADING), inline(DINGXIANG_POPUP)]), ['dingxiang', 'unknown']);
});

test('the new rows claim no other vendor\'s frame', async () => {
  assert.deepEqual(await detect([frame('https://service.mtcaptcha.com/mtcv1/client/iframe.html?v=2')]), ['mtcaptcha', 'unknown']);
  assert.deepEqual(await detect([frame('https://newassets.hcaptcha.com/captcha/v1/abc/static/hcaptcha.html#frame=challenge&id=0x1')]), ['hcaptcha', 'challenge']);
});

test('a card whose submit says Confirm is submitted', async () => {
  // A <button> answers to every text probe whose word its text contains.
  const confirm: FakeNode = { matches: SUBMIT_SELECTORS.filter((sel) => [...sel.matchAll(/'([a-z]+)'\)/g)].pop()?.[1] === 'confirm'), text: 'Confirm' };
  const found = await (new CaptchaKrakenSolver({}) as any).getVerifyButton(fakeDom([confirm]));
  assert.equal(found?.node, confirm, 'the AWS WAF card answers with Confirm, and nothing pressed it');
});
