import { test } from 'node:test';
import assert from 'node:assert/strict';

import { CaptchaKrakenSolver } from './solver';
import { SELECTORS } from './selectors';
import { RecaptchaBanner, Vendor } from './kinds';
import { fakeDom } from './fake-dom.test';

const [BFRAME] = SELECTORS[Vendor.RECAPTCHA].challenge as readonly string[];

const pageShowing = (selector: string | null, text = 'banner text') =>
  fakeDom([{ matches: [BFRAME], frame: selector ? [{ matches: [selector], text }] : [] }]);

const solver = () => new CaptchaKrakenSolver({ apiKey: 'test' }) as any;

test('"Please try again" is a rejection', async () => {
  assert.equal(await solver().bannerKind(pageShowing('.rc-imageselect-incorrect-response', 'Please try again.')), 'rejected');
});

test('"Please select all matching images" is an under-selection', async () => {
  assert.equal(await solver().bannerKind(pageShowing('.rc-imageselect-error-select-more', 'Please select all matching images.')), 'select-more');
});

test('"Please also check the new images" is PROGRESS, not an error', async () => {
  assert.equal(
    await solver().bannerKind(pageShowing('.rc-imageselect-error-dynamic-more', 'Please also check the new images.')),
    'dynamic-more',
    'the dynamic variant\'s "more images arrived" notice must not be classified with the two ' +
      'genuine errors — doing so aborts every dynamic board at round two',
  );
});

test('a clean board reports no banner', async () => {
  assert.equal(await solver().bannerKind(pageShowing(null)), null);
});

test('an empty banner is a placeholder, not a verdict', async () => {
  assert.equal(await solver().bannerKind(pageShowing('.rc-imageselect-incorrect-response', '  ')), null);
});

test('only an under-selection banner asks for the missed tiles', async () => {
  const s = solver();
  const missed = async (sel: string, text: string) => (await s.bannerKind(pageShowing(sel, text))) === RecaptchaBanner.SELECT_MORE;
  assert.equal(await missed('.rc-imageselect-error-select-more', 'Please select all matching images.'), true);
  assert.equal(await missed('.rc-imageselect-error-dynamic-more', 'Please also check the new images.'), false);
  assert.equal(await missed('.rc-imageselect-incorrect-response', 'Please try again.'), false);
});
