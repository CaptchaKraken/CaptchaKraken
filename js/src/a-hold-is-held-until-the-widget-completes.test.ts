// Press & Hold (prompt generation 3): one press, kept down until the widget completes. A press let go early fails
// the widget exactly as a click does, and a held button is never left down, whatever the completion check throws.
import { strict as assert } from 'node:assert';
import test from 'node:test';

import { hold, NullHumanizer } from './humanize.js';
import { ActionKind, Vendor } from './kinds.js';
import { SELECTORS, SelectorTable } from './selectors.js';
import type { Page } from './playwright-types.js';

class RecordingPage {
  events: string[] = [];
  mouse = {
    move: async () => { this.events.push('move'); },
    down: async () => { this.events.push('down'); },
    up: async () => { this.events.push('up'); },
  };
  viewportSize() { return { width: 800, height: 600 }; }
  asPage() { return this as unknown as Page; }
}

test('hold is an action kind of its own', () => {
  assert.equal(ActionKind.HOLD, 'hold');
});

test('the press lasts until the widget says done, and the hand drifts while it holds', async () => {
  const page = new RecordingPage();
  let looks = 0;
  assert.equal(await hold(new NullHumanizer(), page.asPage(), [100, 100], async () => ++looks === 2, 60_000), true);
  assert.equal(page.events.filter((e) => e === 'down').length, 1);
  assert.equal(page.events[page.events.length - 1], 'up');
  const held = page.events.slice(page.events.indexOf('down') + 1, -1);
  assert.ok(held.length >= 2 && held.every((e) => e === 'move'), `held: ${held}`);
});

test('the press is released at the cap, and when the completion check throws', async () => {
  const capped = new RecordingPage();
  assert.equal(await hold(new NullHumanizer(), capped.asPage(), [100, 100], async () => false, 0), false);
  assert.equal(capped.events[capped.events.length - 1], 'up');

  const broken = new RecordingPage();
  await assert.rejects(hold(new NullHumanizer(), broken.asPage(), [100, 100], async () => { throw new Error('page went away'); }, 60_000));
  assert.equal(broken.events[broken.events.length - 1], 'up');
});

test('the vendors whose hold completes on its own are named, so the fill reaching its mark is not a release', () => {
  // HUMAN's button verifies only once it has drawn its done state, and resets when let go at full.
  assert.equal(SELECTORS[Vendor.HUMAN].holdCompletes, true);
  assert.equal(SELECTORS[Vendor.FUNCAPTCHA].holdCompletes, true);
  // A hold graded on where it lets go (a line to fill to a mark) is released at the mark.
  assert.ok(!SELECTORS[Vendor.UNKNOWN].holdCompletes);
});

test('your own entry is released at its mark unless it says it completes', () => {
  assert.ok(!new SelectorTable({ widget: ['#gauge'] }).selectors[Vendor.UNKNOWN].holdCompletes);
  assert.equal(new SelectorTable({ widget: ['#button'], holdCompletes: true }).selectors[Vendor.UNKNOWN].holdCompletes, true);
});
