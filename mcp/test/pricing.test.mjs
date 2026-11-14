// get_pricing against both shapes of /api/v1/pricing. Runs on the built output: `npm test` builds first.
import assert from 'node:assert/strict';
import { test } from 'node:test';

import { describeCeiling, describePricing } from '../dist/pricing.js';

const classes = [
  { puzzle_class: 'image', label: 'Image captchas', covers: 'grids, sliders', credits_per_response: 3,
    usd_per_1000_responses: 0.4, typical_responses_per_captcha: '1-3' },
  { puzzle_class: 'video', label: 'Video captchas', covers: 'animated boards', credits_per_response: 6,
    usd_per_1000_responses: 0.8, typical_responses_per_captcha: '1-2' },
];
const common = {
  credits_per_usd: 7500,
  max_responses_per_session: 10,
  free_challenges: ['checkbox'],
  classes,
  credit_packs: [{ usd: 5, credits: 37500 }, { usd: 20, credits: 150000 }],
};

// The card the control plane serves now: the ceiling in credits, and its dollar figure stated.
const current = { ...common, max_credits_per_session: 11, max_usd_per_1000_attempts: 1.5 };
// The card it served before: the ceiling as a count of billable responses.
const older = { ...common, max_billable_responses_per_session: 5 };

test('the current card prints its ceiling in credits and its own dollar figure', () => {
  const out = describePricing(current);
  assert.match(out, /at most 11 credits \(\$1\.50 per 1,000\)/);
  assert.match(out, /abandoned after 10 responses/);
  assert.doesNotMatch(out, /undefined|NaN/);
});

test('the older card still prints its ceiling in billable responses', () => {
  const out = describePricing(older);
  assert.match(out, /at most 5 billable responses \(\$2\.00 per 1,000 for images\)/);
  assert.doesNotMatch(out, /undefined|NaN/);
});

test('a card naming credits but no dollar figure derives it from the exchange rate', () => {
  const { max_usd_per_1000_attempts: _drop, ...noUsd } = current;
  assert.match(describeCeiling(noUsd), /11 credits \(\$1\.47 per 1,000\)/);
});

test('a card with neither ceiling field prints no ceiling rather than undefined', () => {
  assert.equal(describeCeiling(common), null);
  const out = describePricing(common);
  assert.doesNotMatch(out, /undefined|NaN|at most/);
  assert.match(out, /Packs: \$5, \$20/);
});
