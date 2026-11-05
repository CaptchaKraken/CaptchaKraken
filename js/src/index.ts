// The published surface: what a caller constructs, configures, receives or implements. Everything else is internal
// and can change in any release; add a name here only when a caller needs to write it.

// Solving
export { CaptchaKrakenSolver } from './solver';
export { watchPage } from './watcher';
export type { CaptchaWatcher, WatchOptions, WatchableSolver } from './watcher';
export { fromPuppeteer } from './puppeteer-adapter';
export type { Page, PlaywrightPage, PlaywrightFrame, PlaywrightElementHandle, PlaywrightLocator, PlaywrightScope } from './playwright-types';

// Configuration
export type { CaptchaKrakenConfig } from './types';
export { DEFAULT_CONFIG_PATH, SelectorConfigError, loadConfig } from './selectors';
export type { CustomSelectors, DetectorModel, SelectorConfig, SelectorConfigFile, VendorSelectors } from './selectors';
export { HumanizationMode, PromptFamily, Vendor } from './kinds';

// Results, events and errors
export type { SolveResult, SolveStepEvent, Vector } from './types';
export type { RoundVerdict } from './verdicts';
export { ErrorCode, FrameRole, Outcome, SolveStage, Verdict } from './kinds';
export { CaptchaKrakenAPIError } from './errors';
export type { CaptchaKrakenErrorCode } from './errors';

// Humanizers: the built-in three, and what one of your own implements
export { MobileHumanizer, MouseHumanizer, NullHumanizer } from './humanize';
export type { Humanizer, Point, TouchBackend, TouchTransform } from './humanize';
export { PauseKind } from './kinds';
