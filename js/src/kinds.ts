/**
 * Every closed set of names the two ports agree on. Mirrored in python/src/captchakraken/kinds.py; keep both in the same order.
 * `as const` objects rather than `enum`: a literal off the wire (`'click'`) type-checks against them, an `enum` would not.
 */

/** `puzzleSource` everywhere. UNKNOWN must stay permissive: GeeTest and Prosopo report it, and so does the offline grader. */
export const Vendor = {
  HCAPTCHA: 'hcaptcha',
  RECAPTCHA: 'recaptcha',
  TURNSTILE: 'turnstile',
  GEETEST: 'geetest',
  TENCENT: 'tencent',
  YIDUN: 'yidun',
  YANDEX: 'yandex',
  LEMIN: 'lemin',
  PROSOPO: 'prosopo',
  MTCAPTCHA: 'mtcaptcha',
  BOTDETECT: 'botdetect',
  UNKNOWN: 'unknown',
} as const;
export type Vendor = (typeof Vendor)[keyof typeof Vendor];

export const ActionKind = { CLICK: 'click', DRAG: 'drag', TYPE: 'type', WAIT: 'wait', DONE: 'done' } as const;
export type ActionKind = (typeof ActionKind)[keyof typeof ActionKind];

export const RetryMode = { MISSED_TILES: 'missed-tiles' } as const;
export type RetryMode = (typeof RetryMode)[keyof typeof RetryMode];

export const SettleVerdict = { SETTLED: 'settled', ANIMATED: 'animated', TIMEOUT: 'timeout' } as const;
export type SettleVerdict = (typeof SettleVerdict)[keyof typeof SettleVerdict];

export const PaintVerdict = { PAINTED: 'painted', BLANK: 'blank', UNKNOWN: 'unknown' } as const;
export type PaintVerdict = (typeof PaintVerdict)[keyof typeof PaintVerdict];

/** EVEN means the slicer could not prove recurrence, not that the board is still. */
export const KeyframeMode = { STATIC: 'static', CYCLE: 'cycle', EVEN: 'even' } as const;
export type KeyframeMode = (typeof KeyframeMode)[keyof typeof KeyframeMode];

export const RecaptchaBanner = { SELECT_MORE: 'select-more', DYNAMIC_MORE: 'dynamic-more', REJECTED: 'rejected' } as const;
export type RecaptchaBanner = (typeof RecaptchaBanner)[keyof typeof RecaptchaBanner];

/** One expert per family; `pixel` is spelled to match ckgate's prompt markers. */
export const PromptFamily = { PIXEL: 'pixel', GRID: 'grid', VIDEO: 'video', TEXT: 'text' } as const;
export type PromptFamily = (typeof PromptFamily)[keyof typeof PromptFamily];

export const HumanizationMode = { MOUSE: 'mouse', MOBILE: 'mobile', NONE: 'none' } as const;
export type HumanizationMode = (typeof HumanizationMode)[keyof typeof HumanizationMode];

export const PauseKind = { TAP: 'tap', BETWEEN: 'between', GRAB: 'grab', DROP: 'drop', PROBE: 'probe', SETTLE: 'settle', KEY: 'key' } as const;
export type PauseKind = (typeof PauseKind)[keyof typeof PauseKind];

export const Outcome = { SOLVED: 'solved', FAILED: 'failed' } as const;
export type Outcome = (typeof Outcome)[keyof typeof Outcome];

/** What the vendor's own server answered a round: BLOCKED is a refusal to serve at all, not a wrong answer. */
export const Verdict = { ACCEPTED: 'accepted', REJECTED: 'rejected', NEW_CHALLENGE: 'new-challenge', BLOCKED: 'blocked' } as const;
export type Verdict = (typeof Verdict)[keyof typeof Verdict];

/** Timing phases. Only INFERENCE and MOUSE are productive; everything else is waiting. */
export const Phase = {
  INFERENCE: 'inference',
  MOUSE: 'mouse',
  SCREENSHOT: 'screenshot',
  DETECT: 'detect',
  SETTLE: 'settle',
  BURST: 'burst',
  GRID: 'grid',
  GRID_LOAD: 'grid-load',
  FADE_WAIT: 'fade-wait',
  BOARD_PAINT: 'board-paint',
  HCAPTCHA_IMAGES: 'hcaptcha-images',
  AWAIT_NEXT_ROUND: 'await-next-round',
  AWAIT_VERDICT: 'await-verdict',
  POST_SUBMIT_DELAY: 'post-submit-delay',
} as const;
export type Phase = (typeof Phase)[keyof typeof Phase];

export const SolveStage = { INITIAL: 'initial', CLICK: 'click', DRAG: 'drag', TYPE: 'type', WAIT: 'wait', SUBMIT: 'submit', ROUND: 'round' } as const;
export type SolveStage = (typeof SolveStage)[keyof typeof SolveStage];

export const FrameRole = { CHECKBOX: 'checkbox', CHALLENGE: 'challenge', UNKNOWN: 'unknown' } as const;
export type FrameRole = (typeof FrameRole)[keyof typeof FrameRole];

/** The hosted API's machine-readable codes. Unknown codes still carry the server's message through; this is not a filter. */
export const ErrorCode = {
  MISSING_API_KEY: 'missing_api_key',
  INVALID_API_KEY: 'invalid_api_key',
  ACCOUNT_SUSPENDED: 'account_suspended',
  INSUFFICIENT_CREDITS: 'insufficient_credits',
  RATE_LIMITED: 'rate_limited',
  SOLVE_ABANDONED: 'solve_abandoned',
  UNRECOGNIZED_PROMPT: 'unrecognized_prompt',
  INVALID_REQUEST: 'invalid_request',
  REQUEST_TOO_LARGE: 'request_too_large',
  UPSTREAM_UNAVAILABLE: 'upstream_unavailable',
} as const;
export type ErrorCode = (typeof ErrorCode)[keyof typeof ErrorCode];

export function isOneOf<T extends Record<string, string>>(set: T, value: unknown): value is T[keyof T] {
  return typeof value === 'string' && (Object.values(set) as string[]).includes(value);
}
