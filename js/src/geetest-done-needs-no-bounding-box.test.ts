// `done` must not require a box: GeeTest closes the panel on accept, and 22 of 22 drags across four puzzles died there and were
// banked as model errors. Allow-list direction, so a new coordinate-bearing action fails loudly.
import { test } from 'node:test';
import assert from 'node:assert/strict';

import { answerNeedsElementBox, isClosedTargetError, isStaleHandleError } from './solver';

test('a done-only answer needs no box', () => {
  assert.equal(answerNeedsElementBox([{ action: 'done' }]), false);
  assert.equal(answerNeedsElementBox([{ action: 'done' }, { action: 'done' }]), false);
});

test('every coordinate-bearing action still needs one', () => {
  for (const action of ['click', 'drag', 'type', 'slide', 'move']) {
    assert.equal(answerNeedsElementBox([{ action }]), true, action);
  }
});

test('a done mixed with real work still needs one', () => {
  assert.equal(answerNeedsElementBox([{ action: 'done' }, { action: 'click' }]), true);
  assert.equal(answerNeedsElementBox([{ action: 'click' }, { action: 'done' }]), true);
});

test('an unrecognised action defaults to needing one', () => {
  assert.equal(answerNeedsElementBox([{ action: 'some_future_gesture' }]), true);
  assert.equal(answerNeedsElementBox([{}]), true);
});

test('an empty answer needs nothing', () => {
  assert.equal(answerNeedsElementBox([]), false);
});

test('a vanished bounding box is the widget moving on', () => {
  assert.equal(isStaleHandleError('Could not get bounding box of captcha element'), true);
});

test('the shapes hCaptcha produces are still recognised', () => {
  for (const m of [
    'Timeout 3000ms exceeded',
    'element is not visible',
    'Element is not attached to the DOM',
  ]) {
    assert.equal(isStaleHandleError(m), true, m);
  }
});

test('a closed page is not a stale handle, in the words both engines use', () => {
  for (const m of ['Target closed', 'Target page, context or browser has been closed', 'Session closed']) {
    assert.equal(isClosedTargetError(m), true, m);
    assert.equal(isStaleHandleError(m), false, m);
  }
});

test('a real failure is not mistaken for a transition', () => {
  for (const m of [
    'Captcha still detected after 6 solve loops',
    'No progress: the model returned the same answer 3 times running',
    'Cannot solve this kind of captcha — UNSUPPORTED_CAPTCHA',
    'account is out of credits',
  ]) {
    assert.equal(isStaleHandleError(m), false, m);
  }
});
