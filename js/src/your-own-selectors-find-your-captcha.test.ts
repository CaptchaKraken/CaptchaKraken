// A captcha the built-in table does not know is found and driven through the caller's own selectors.
// Mirror of python/tests/test_your_own_selectors_find_your_captcha.py.
import assert from 'node:assert/strict';
import test from 'node:test';
import { CaptchaKrakenSolver } from './solver';
import { DEFAULT_TABLE, SelectorTable, type CustomSelectors } from './selectors';
import { fakeDom, FakeNode } from './fake-dom.test';

// A site's own image captcha: a picture and a code box in a container of its own, with a button that says "Check".
const SIGNUP: CustomSelectors = {
  widget: ['#signup-captcha'], textInput: ['#signup-code'], submit: ['#signup-check'], refresh: ['#signup-new-image'],
};

const detect = async (config: object, nodes: FakeNode[]) => {
  const found = await (new CaptchaKrakenSolver(config) as any).detectCaptcha(fakeDom(nodes));
  return found ? [found.vendor, found.role] : null;
};

test('a captcha only your selectors name is found', async () => {
  const page = [{ matches: ['#signup-captcha'] }];
  assert.equal(await detect({}, page), null);
  assert.deepEqual(await detect({ customSelectors: SIGNUP }, page), ['unknown', 'unknown']);
});

test('your controls are tried before the generic ones', async () => {
  const table = new SelectorTable(SIGNUP);
  assert.equal(table.textInput[0], '#signup-code');
  assert.equal(table.refresh[0], '#signup-new-image');
  const check: FakeNode = { matches: ['#signup-check'], text: 'Check' };
  const found = await (new CaptchaKrakenSolver({ customSelectors: SIGNUP }) as any).getVerifyButton(fakeDom([check]));
  assert.equal(found?.node, check, "the site's own Check button was not pressed");
});

test('your selectors leave every other solver alone', async () => {
  new CaptchaKrakenSolver({ customSelectors: SIGNUP });
  assert.ok(!DEFAULT_TABLE.widgetProbes.some((p) => p.selector === '#signup-captcha'));
  assert.equal(await detect({}, [{ matches: ['#signup-captcha'] }]), null);
});

test('an entry that names nothing to detect is refused', () => {
  assert.throws(() => new CaptchaKrakenSolver({ customSelectors: { textInput: ['#code'] } }), /nothing to detect/);
});
