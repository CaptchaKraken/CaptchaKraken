/**
 * The rate card `get_pricing` reads from `/api/v1/pricing`, and the text it prints.
 *
 * The per-captcha ceiling has had two shapes. The older card capped a captcha at a number of
 * billable responses (`max_billable_responses_per_session`); the current one caps it in credits and
 * states the dollar figure itself (`max_credits_per_session`, `max_usd_per_1000_attempts`). This
 * reads either, so one published server works against both, and prints no ceiling at all rather than
 * "undefined" or "$NaN" when a card carries neither.
 */

export interface PricingClass {
  puzzle_class: string;
  label: string;
  covers: string;
  credits_per_response: number;
  usd_per_1000_responses: number;
  typical_responses_per_captcha: string;
}

export interface Pricing {
  credits_per_usd: number;
  /** Current card: the ceiling in credits, the same for every class. */
  max_credits_per_session?: number;
  /** Current card: that ceiling as dollars per 1,000 captchas. */
  max_usd_per_1000_attempts?: number;
  /** Older card: the ceiling as a count of billable responses. */
  max_billable_responses_per_session?: number;
  max_responses_per_session: number;
  free_challenges: string[];
  classes: PricingClass[];
  credit_packs: Array<{ usd: number; credits: number }>;
}

const isNumber = (value: unknown): value is number => typeof value === 'number' && Number.isFinite(value);

/** The ceiling sentence, or null when the card states no ceiling this server can read. */
export function describeCeiling(pricing: Pricing): string | null {
  const abandon = isNumber(pricing.max_responses_per_session)
    ? ` The attempt is abandoned after ${pricing.max_responses_per_session} responses.`
    : '';
  const credits = pricing.max_credits_per_session;
  if (isNumber(credits)) {
    const usd = isNumber(pricing.max_usd_per_1000_attempts)
      ? pricing.max_usd_per_1000_attempts
      : isNumber(pricing.credits_per_usd) && pricing.credits_per_usd > 0
        ? (credits * 1000) / pricing.credits_per_usd
        : null;
    const dollars = usd === null ? '' : ` ($${usd.toFixed(2)} per 1,000)`;
    return `One captcha costs at most ${credits.toLocaleString('en-US')} credits${dollars}, whatever its class. ` +
      `Responses past that are served free.${abandon}`;
  }
  const responses = pricing.max_billable_responses_per_session;
  if (isNumber(responses)) {
    const image = pricing.classes.find((row) => row.puzzle_class === 'image')?.usd_per_1000_responses;
    const dollars = isNumber(image) ? ` ($${(image * responses).toFixed(2)} per 1,000 for images)` : '';
    return `One captcha costs at most ${responses} billable responses${dollars}. ` +
      `Responses past that are served free.${abandon}`;
  }
  return null;
}

/** The whole `get_pricing` answer. */
export function describePricing(pricing: Pricing): string {
  const lines = [
    `Billed per inference response. $1.00 = ${pricing.credits_per_usd.toLocaleString('en-US')} credits.`,
    '',
  ];
  for (const row of pricing.classes) {
    lines.push(
      `${row.label}: $${row.usd_per_1000_responses.toFixed(2)} per 1,000 (${row.credits_per_response} credits each)`,
      `  ${row.covers}`,
      `  Typically ${row.typical_responses_per_captcha} response(s) per captcha`,
    );
  }
  lines.push('', `Free (never reach the model): ${pricing.free_challenges.join(', ')}`);
  const ceiling = describeCeiling(pricing);
  if (ceiling) lines.push(ceiling);
  lines.push(`Packs: ${pricing.credit_packs.map((pack) => `$${pack.usd}`).join(', ')}`);
  return lines.join('\n');
}
