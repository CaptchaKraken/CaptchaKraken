import type { RoundVerdict } from './verdicts';
import type { Humanizer, TouchTransform } from './humanize.js';
import type { ActionKind, FrameRole, HumanizationMode, PromptFamily, SolveStage, Vendor } from './kinds';

/** One intermediate stage of a solve, handed to `CaptchaKrakenConfig.onStep`. */
export interface SolveStepEvent {
  /** 1-based, increasing across the whole solve. */
  index: number;
  stage: SolveStage;
  label: string;
  /** PNG of the captcha element at this step; owned by the callback. Null if the screenshot failed. */
  screenshotPath: string | null;
  puzzleSource?: Vendor;
  frameRole?: FrameRole;
  attempt: number;
  elapsedMs: number;
  meta?: Record<string, any>;
}

/** Tunables. Every field mirrors a `PageSolverConfig` field on the Python port; defaults are in SOLVE_DEFAULTS. */
export interface CaptchaKrakenConfig {
  /** Input device; default `mouse`. Falls back to CAPTCHA_HUMANIZATION. */
  humanization?: HumanizationMode;
  /** Your own gesture implementation; overrides `humanization`. */
  humanizer?: Humanizer;
  /** Mobile only: an Appium / WebdriverIO driver on a real handset. Unset dispatches CDP touch at the page. */
  touchDriver?: any;
  /** Mobile only: CSS-pixel to device-pixel transform for `touchDriver`. */
  touchTransform?: TouchTransform;
  /** Observer fired at each intermediate stage; errors are swallowed. */
  onStep?: (event: SolveStepEvent) => void | Promise<void>;
  /** Path to the bundled Python engine. Auto-resolved when omitted. */
  repoPath?: string;
  /** Python interpreter for the engine. Default: the bundled venv, else `python3`, else `python`. */
  pythonCommand?: string;
  /** Served model name. Default: resolved from models.json for the endpoint in use. */
  model?: string;
  /** Force one expert of a routed model. Also CAPTCHA_EXPERT. */
  expert?: PromptFamily;
  /** Bearer token; also read from CAPTCHA_KRAKEN_API_KEY / VLLM_API_KEY. */
  apiKey?: string;
  /** Where the pointer starts. Default { x: 100, y: 100 }. */
  startingMousePosition?: { x: number, y: number };
  /** Solve rounds that fit the timeout. Default 6. */
  maxSolveLoops?: number;
  /** How long to keep looking for a widget the page has not drawn yet, before "no captcha" is believed. Not charged to `overallSolveTimeoutMs`. Default 15000. */
  detectionTimeoutMs?: number;
  /** @deprecated Ignored since 3.2.0: a round that makes no progress now counts against `maxSolveLoops`. */
  maxNoProgressRounds?: number;
  /** @deprecated Ignored since 3.2.0: a round that performed nothing goes straight on to the next. */
  postSolveDelayMs?: number;
  /** Whole-solve time limit. Default 45000. */
  overallSolveTimeoutMs?: number;
  /** reCAPTCHA grid-load poll interval. Default 250. */
  gridLoadPollIntervalMs?: number;
  /** reCAPTCHA grid-load timeout. Default 8000. */
  gridLoadTimeoutMs?: number;
  /** Board-paint gate poll interval. Default 180. */
  boardPaintPollMs?: number;
  /** How long to wait for a widget to paint its puzzle. Default 2500. */
  boardPaintTimeoutMs?: number;
  /** Share of the panel's centre that must carry structure. Default: the engine's own. */
  boardPaintFloor?: number;
  /** reCAPTCHA 3x3: how long to wait for a clicked tile to reload. Default 6000. */
  recaptchaDynamicFadeWaitMs?: number;
  /** reCAPTCHA 3x3: gap between the two frames the fade detectors diff. Default 250. */
  recaptchaDynamicFadePollMs?: number;
  /** reCAPTCHA 3x3: grace window after a click for the fade to begin. Default 4000. A window, not a snapshot: a clicked tile stays selected 1-3s and only then blanks. */
  recaptchaFadeOnsetGraceMs?: number;
  /** reCAPTCHA 3x3: cap on click/refresh rounds per puzzle. Default 8. */
  recaptchaMaxDynamicRounds?: number;
  /** reCAPTCHA 3x3: hover the reloading tiles while waiting. Default true. */
  recaptchaTileHoverEnabled?: boolean;
  /** Drift the cursor over the challenge while the model thinks. Default true. */
  idleMouseWander?: boolean;
  /** How long to watch for the vendor's verdict after an action. Default 1000. */
  postSolveOutcomeTimeoutMs?: number;
  /** Poll interval inside that window. Default 75. */
  postSolveOutcomePollMs?: number;
  /** Re-solve when the frame changed during inference. Default true. */
  staleFrameReSolveEnabled?: boolean;
  /** Fraction of pixels that must differ to count as changed. Default 0.02. */
  staleFrameDiffThreshold?: number;
  /** Re-solves allowed per round. Default 2. */
  maxStaleFrameReSolves?: number;
  /** Settle monitor: fraction of pixels that still count as moving. Default 0.01. */
  settleDiffThreshold?: number;
  /** How long to wait for hCaptcha's task images to paint. Default 3000. */
  hcaptchaImagesTimeoutMs?: number;
  /** Settle monitor poll interval. Default 220. */
  settlePollMs?: number;
  /** Consecutive still frame pairs that mean settled. Default 2. */
  settleFrames?: number;
  /** Settle monitor timeout. Default 9000. */
  settleTimeoutMs?: number;
  /** Still moving after this long means animated. Default 4500. */
  animatedChallengeAfterMs?: number;
  /** Record and solve animated challenges from keyframes. Default true. */
  videoSolveEnabled?: boolean;
  /** Burst floor. Default 4000; matches the training corpus. */
  videoBurstDurationMs?: number;
  /** Burst frame rate. Default 10; matches the training corpus. */
  videoBurstFps?: number;
  /** How long to hold a click waiting for the chosen keyframe. Default 9000: GeeTest svg dwells up to 2.7s a screen, so a 3-screen cycle is 8.1s worst case and 6s gave up one screen short. */
  keyframeWaitTimeoutMs?: number;
  /** Poll interval while waiting. Default 120. */
  keyframeWaitPollMs?: number;
  /** Burst ceiling for a board that never repeats a screen. Default 12000. */
  videoBurstMaxMs?: number;
  /** Safety ceiling on the camera that films an animated board across rounds. Default 120000: it is meant to end with the solve, not on this clock. */
  videoFilmMaxMs?: number;
  /** Consecutive moved settle polls that mean animated. Default 5. */
  animatedMotionStreak?: number;
  /** Record while the still is being read, so a cycling board is known before its answer runs. Default true. */
  speculativeBurstEnabled?: boolean;
  /** Extra wall clock granted once when a solve escalates to a recording. Default 8000. */
  videoExtraInferenceMs?: number;
  /** After a submit, how long to wait for the frame to change. Default 4000. */
  postSubmitChangeTimeoutMs?: number;
  /** Per-call timeout for element screenshots. Default 8000. */
  elementScreenshotTimeoutMs?: number;
  /** Timeout for an `onStep` screenshot. Default 2000. */
  stepScreenshotTimeoutMs?: number;
  /** @deprecated Ignored since 3.2.0: a stale handle now counts against `maxSolveLoops`. */
  maxStaleElementRetries?: number;
  /** The pause before a failed round is tried again. Default 900. */
  staleElementBackoffMs?: number;
  /** @deprecated Ignored since 3.2.0: an unusable answer now counts against `maxSolveLoops`. */
  maxUnsupportedReSolves?: number;
}

export interface BoundingBox {
  0: number;
  1: number;
  2: number;
  3: number;
}

/** Present only on actions from an animated challenge: the keyframe the answer was read off. */
export interface AnimatedActionFields {
  await_keyframe?: string | null;
  frame?: number | null;
}

export interface ClickAction extends AnimatedActionFields {
  action: typeof ActionKind.CLICK;
  /** Normalised [x1, y1, x2, y2] boxes, one click each. */
  target_bounding_boxes?: Array<[number, number, number, number]>;
  target_number?: number | null;
  target_bounding_box?: [number, number, number, number] | null;
  target_coordinates?: [number, number] | null;
}

export interface DragAction extends AnimatedActionFields {
  action: typeof ActionKind.DRAG;
  /** Null on a puzzle-piece slider: the driver finds the handle and closes the loop on the piece. */
  source_bounding_box: [number, number, number, number] | null;
  target_bounding_box: [number, number, number, number];
}

export interface TypeAction {
  action: typeof ActionKind.TYPE;
  text: string;
}

export interface DoneAction {
  action: typeof ActionKind.DONE;
}

export interface WaitAction {
  action: typeof ActionKind.WAIT;
  duration_ms: number;
}

export type CaptchaAction = ClickAction | WaitAction | DragAction | TypeAction | DoneAction;
export type SolverResult = CaptchaAction | CaptchaAction[];

export interface TokenUsage {
  input_tokens: number;
  output_tokens: number;
  cached_input_tokens?: number;
  model: string;
}

export interface CliResponse {
  actions: SolverResult;
  token_usage: TokenUsage[];
}

export interface Vector {
  x: number;
  y: number;
}

export interface SolveResult {
  isSolved: boolean;
  finalMousePosition: Vector;
  tokenUsage: {
    modelName: string;
    inputTokens: number;
    outputTokens: number;
    cachedInputTokens: number;
    estimatedCost: number;
  };
  /** Milliseconds per phase, plus `total`. */
  phases?: Record<string, number>;
  /** What the vendor's own server answered, in order, for the vendors whose answer is readable. */
  verdicts: RoundVerdict[];
}
