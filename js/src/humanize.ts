/**
 * How the driver moves: one pluggable object per input device. Mirrors python/humanize.py.
 *
 * The pointer position lives here, not in the solver, because a touch mode that dispatches no
 * motion between taps still has to say where the next gesture starts.
 *
 * Pluggable because camoufox's juggler re-humanises every mouse.move() it is handed, and running
 * both measured 82s against 13s on one GeeTest slider; and a touch widget needs touch events, not
 * mousemove. See TRIBAL_KNOWLEDGE.md. The 2026-09 cut removed our drag-overshoot redraw and swipe
 * wobble in favour of Cursory's raw recordings; the one-pixel tap wobble stayed because a
 * motionless tap is a synthetic one.
 */

import type { ViewportSize, Page, PlaywrightElementHandle } from './playwright-types.js';
import { generateTrajectory } from 'cursory-js';
import { HumanizationMode, PauseKind, isOneOf } from './kinds.js';
export type { HumanizationMode, PauseKind } from './kinds.js';

export type Point = [number, number];

const delay = (ms: number) => new Promise<void>((r) => setTimeout(r, Math.max(0, ms)));
const log = (m: string) => console.log(`[captchakraken] ${m}`);
const uniform = (lo: number, hi: number) => lo + Math.random() * (hi - lo);
// moveAndClick clicks at the landing point; without this every click would dispatch one redundant move.
const samePoint = (a: Point, b: Point) => Math.abs(a[0] - b[0]) < 1e-6 && Math.abs(a[1] - b[1]) < 1e-6;
const gauss = (sigma: number) => {
  let u = 0;
  while (u === 0) u = Math.random();
  return sigma * Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * Math.random());
};
const closedError = (e: unknown) => /Target closed|Session closed/.test(e instanceof Error ? e.message : String(e));

/** A recorded human movement morphed onto the endpoints; timings are cumulative ms. */
export function trajectory(start: Point, end: Point, frequency: number): [Point[], number[]] {
  const { points, timings } = generateTrajectory(start, end, { frequency });
  return [points.map((q) => [Number(q[0]), Number(q[1])] as Point), timings.map(Number)];
}

/** Every inter-gesture wait the driver takes, named, so each device supplies its own table. */
export const PAUSE_KINDS: readonly PauseKind[] = Object.values(PauseKind);
/** How often a held press looks at the widget, in ms: a frame hash per look, so not every frame. */
export const HOLD_POLL_MS: readonly [number, number] = [180, 320];

/**
 * Press at `to` until `done()` says the widget completed, or `maxMs` passes; true when it completed.
 * Built on move/press/release so any humanizer can hold. The hand drifts a pixel or so meanwhile, because a
 * press that does not move for seconds is a synthetic one, and the button is released whatever `done` throws.
 */
export async function hold(human: Humanizer, page: Page, to: Point, done: () => Promise<boolean>, maxMs: number): Promise<boolean> {
  await human.move(page, to);
  const anchor: Point = [human.at[0], human.at[1]];
  await human.press(page);
  const t0 = Date.now();
  try {
    for (;;) {
      await delay(uniform(HOLD_POLL_MS[0], HOLD_POLL_MS[1]));
      const to: Point = [anchor[0] + gauss(0.8), anchor[1] + gauss(0.8)];
      await (human.drift ? human.drift(page, to) : human.move(page, to)).catch(() => undefined);
      if (await done()) return true;
      if (Date.now() - t0 >= maxMs) return false;
    }
  } finally {
    await human.release(page);
  }
}

export interface Humanizer {
  readonly name: string;
  /** False on a device with no resting cursor; switches off every hover-for-realism behaviour. */
  readonly hovers: boolean;
  at: Point;
  reset(page: Page): Promise<void>;
  move(page: Page, to: Point): Promise<void>;
  /** A pixel of wander while held; a humanizer without it drifts with `move`. */
  drift?(page: Page, to: Point): Promise<void>;
  press(page: Page): Promise<void>;
  release(page: Page): Promise<void>;
  click(page: Page, to: Point): Promise<void>;
  drag(page: Page, src: Point, dst: Point): Promise<void>;
  typeText(page: Page, field: PlaywrightElementHandle, text: string): Promise<boolean>;
  pause(kind: PauseKind): Promise<void>;
}

type PauseTable = Partial<Record<PauseKind, [number, number]>>;

export abstract class BaseHumanizer implements Humanizer {
  abstract readonly name: string;
  abstract readonly hovers: boolean;
  protected abstract readonly pauses: PauseTable;
  at: Point;

  constructor(start: Point = [0, 0]) {
    this.at = [Number(start[0]), Number(start[1])];
  }

  async reset(_page: Page): Promise<void> {}
  abstract move(page: Page, to: Point): Promise<void>;
  /**
   * A held hand's pixel of wander. `move` is a reach, and a reach overshoots: on a 1px move it wandered up to 34px,
   * off a thin bar, which the widget takes for a release.
   */
  async drift(page: Page, to: Point): Promise<void> {
    await this.move(page, to);
  }
  abstract press(page: Page): Promise<void>;
  abstract release(page: Page): Promise<void>;
  abstract typeText(page: Page, field: PlaywrightElementHandle, text: string): Promise<boolean>;

  /** An unknown kind waits nothing, so adding a pause site cannot break a custom humanizer written against an older release. */
  protected pauseMs(kind: PauseKind): number {
    const range = this.pauses[kind];
    return range ? uniform(range[0], range[1]) : 0;
  }

  async pause(kind: PauseKind): Promise<void> {
    await delay(this.pauseMs(kind));
  }

  async click(page: Page, to: Point): Promise<void> {
    await this.move(page, to);
    await this.press(page);
    await this.pause(PauseKind.TAP);
    await this.release(page);
  }

  async drag(page: Page, src: Point, dst: Point): Promise<void> {
    await this.move(page, src);
    await this.press(page);
    await this.pause(PauseKind.GRAB);
    await this.move(page, dst);
    await this.pause(PauseKind.DROP);
    await this.release(page);
  }
}

/** How much longer than the bare round trip a step takes when the browser re-draws it as a path of its own. */
export const BROWSER_PATH_MS = 100;

export class MouseHumanizer extends BaseHumanizer {
  readonly name: HumanizationMode = HumanizationMode.MOUSE;
  readonly hovers = true;
  protected readonly pauses: PauseTable = {
    tap: [20, 50], between: [80, 160], grab: [50, 100], drop: [50, 100],
    probe: [40, 80], settle: [90, 210], key: [45, 135],
  };
  private frequency: number;
  private viewportCache: ViewportSize | null | undefined;
  /** Undefined until the first move of a solve measures it. */
  private browserDrawsPath: boolean | undefined;

  constructor(start: Point = [0, 0], frequency = 60) {
    super(start);
    this.frequency = frequency;
  }

  async reset(_page: Page): Promise<void> {
    this.viewportCache = undefined;
    this.browserDrawsPath = undefined;
  }

  /** The window to keep the cursor inside; null under camoufox, which reports no viewport and whose window we ask instead. */
  private async viewport(page: Page): Promise<ViewportSize | null> {
    if (this.viewportCache !== undefined) return this.viewportCache;
    this.viewportCache = null;
    const reads: Array<() => ViewportSize | null | Promise<ViewportSize | null>> = [
      () => page.viewportSize(),
      () => page.evaluate ? page.evaluate(() => ({ width: window.innerWidth, height: window.innerHeight })) : null,
    ];
    for (const read of reads) {
      try {
        const vp = await read();
        if (vp && vp.width && vp.height) { this.viewportCache = { width: vp.width, height: vp.height }; break; }
      } catch { /* try the next read */ }
    }
    return this.viewportCache;
  }

  async drift(page: Page, to: Point): Promise<void> {
    try {
      await page.mouse.move(to[0], to[1]);
      this.at = [to[0], to[1]];
    } catch (e) {
      if (closedError(e)) log('could not move mouse; page or session closed');
    }
  }

  /** Clamp only when the viewport is known: a coordinate pinned to the edge of a guessed one deadlocks camoufox's juggler (upstream #225). */
  private async clamp(page: Page, [x, y]: Point): Promise<Point> {
    const viewport = await this.viewport(page);
    return viewport ? [Math.max(1, Math.min(x, viewport.width - 1)), Math.max(1, Math.min(y, viewport.height - 1))] : [x, y];
  }

  /**
   * Whether the browser draws its own path for every mouse.move(), as camoufox's humanize does. Ours on top has every
   * sample re-drawn: a 1px step took 190ms there against 1ms, and one GeeTest slider 82s against 13s. One short step
   * towards `to`, timed against a zero-length move (the bare round trip, so a remote browser is not mistaken for
   * one), tells them apart with no movement the page could single out.
   */
  private async measureBrowserPath(page: Page, to: Point): Promise<boolean> {
    const from = await this.clamp(page, this.at);
    const d = Math.hypot(to[0] - from[0], to[1] - from[1]);
    const step = await this.clamp(page, d <= 3 ? to : [from[0] + 3 * (to[0] - from[0]) / d, from[1] + 3 * (to[1] - from[1]) / d]);
    try {
      await page.mouse.move(from[0], from[1]);
      let t = Date.now();
      await page.mouse.move(from[0], from[1]);
      const roundTrip = Date.now() - t;
      t = Date.now();
      await page.mouse.move(step[0], step[1]);
      this.at = step;
      const drawn = Date.now() - t - roundTrip > BROWSER_PATH_MS;
      if (drawn) log('the browser draws its own pointer paths (camoufox humanize); handing it one move per gesture');
      return drawn;
    } catch (e) {
      if (closedError(e)) log('could not move mouse; page or session closed');
      return false;
    }
  }

  async move(page: Page, to: Point): Promise<void> {
    if (samePoint(this.at, to)) return;
    this.browserDrawsPath ??= await this.measureBrowserPath(page, to);
    if (this.browserDrawsPath) return this.drift(page, await this.clamp(page, to));
    const [points, timings] = trajectory(this.at, to, this.frequency);
    const startTime = Date.now();
    for (let i = 0; i < points.length; i++) {
      const [cx, cy] = await this.clamp(page, points[i]);
      try {
        await page.mouse.move(cx, cy);
      } catch (e) {
        if (closedError(e)) { log('could not move mouse; page or session closed'); return; }
        continue;
      }
      this.at = [cx, cy];
      if (timings[i] !== undefined) await delay(startTime + timings[i] - Date.now());
    }
  }

  async press(page: Page): Promise<void> { await page.mouse.down(); }
  async release(page: Page): Promise<void> { await page.mouse.up(); }

  /** Per character with a humanised pause, not type(text, {delay}): a constant inter-key delay is itself a signal these vendors score. */
  async typeText(page: Page, _field: PlaywrightElementHandle, text: string): Promise<boolean> {
    // Clear first: a retry round arrives with the previous attempt still in the box, and typing would append.
    try { await page.keyboard.press('Control+A'); } catch { /* the type below still replaces on most */ }
    for (const ch of text) {
      try {
        await page.keyboard.type(ch);
      } catch (e) {
        log(`could not type into the captcha field: ${e}`);
        return false;
      }
      await this.pause(PauseKind.KEY);
    }
    return true;
  }
}

/** `[x, y, dtMs]`: dt is the wait before that sample. */
export type TouchSample = [number, number, number];

/** Where touch events go. `move` takes a whole leg so a device driver can pace it itself. */
export interface TouchBackend {
  readonly name: string;
  down(x: number, y: number): Promise<void>;
  move(path: TouchSample[]): Promise<void>;
  up(x: number, y: number): Promise<void>;
}

/** `Input.dispatchTouchEvent` over CDP; Chromium-family pages launched with `hasTouch: true`. */
export class CdpTouchBackend implements TouchBackend {
  readonly name = 'cdp';
  private constructor(private session: any) {}

  /**
   * Checked at construction, not per gesture. WebKit and Firefox expose no touch dispatch, and emitting
   * mouse events instead is worse than not running: the page's touch handlers never fire and the report
   * reads as a model that cannot solve mobile puzzles.
   */
  static async open(page: Page): Promise<CdpTouchBackend> {
    try {
      return new CdpTouchBackend(await (page as any).context().newCDPSession(page));
    } catch (e) {
      throw new Error(
        `mobile humanisation needs touch dispatch, and this page offers none (${e}). ` +
        'Use a Chromium-family Playwright browser launched with hasTouch: true, ' +
        'or pass an Appium driver as CaptchaKrakenConfig.touchDriver.');
    }
  }

  private async send(kind: string, points: Array<[number, number]>): Promise<void> {
    // radius and force are what a real digitizer reports; a synthetic tap reports zero.
    await this.session.send('Input.dispatchTouchEvent', {
      type: kind,
      touchPoints: points.map(([x, y]) => ({
        x, y, radiusX: uniform(8, 14), radiusY: uniform(8, 14), force: uniform(0.35, 0.75), id: 1,
      })),
    });
  }

  async down(x: number, y: number): Promise<void> { await this.send('touchStart', [[x, y]]); }
  async move(path: TouchSample[]): Promise<void> {
    for (const [x, y, dt] of path) {
      if (dt > 0) await delay(dt);
      await this.send('touchMove', [[x, y]]);
    }
  }
  async up(_x: number, _y: number): Promise<void> { await this.send('touchEnd', []); }
}

/** CSS-pixel to device-pixel transform for a real handset. */
export interface TouchTransform {
  scale?: number;
  origin?: Point;
}

/**
 * W3C touch pointer actions for Appium and WebdriverIO, paced by the device from one chain per leg.
 * Raw protocol payloads so this imports no client. Press and release are separate performs because W3C
 * input state is per session: that is what lets the slider driver press, screenshot, steer, then release.
 */
export class AppiumTouchBackend implements TouchBackend {
  readonly name = 'appium';
  private scale: number;
  private origin: Point;
  private scaleGiven: boolean;
  private checked = false;

  constructor(private driver: any, transform: TouchTransform = {}, private page?: Page) {
    this.scaleGiven = transform.scale !== undefined;
    this.scale = transform.scale ?? 1;
    this.origin = transform.origin ?? [0, 0];
  }

  /**
   * Refuse an unset scale on a device whose pixel ratio is not 1: the finger would land elsewhere. An
   * explicit scale of 1 is the caller's word and is not re-checked; the ratio is read once, since a solve
   * makes hundreds of these, and an unreadable ratio is taken as 1.
   */
  private async checkScale(): Promise<void> {
    this.checked = true;
    if (this.scaleGiven || !this.page) return;
    let dpr: number;
    try {
      dpr = Number(await (this.page as any).evaluate('() => window.devicePixelRatio'));
    } catch { return; }
    if (!Number.isFinite(dpr) || Math.abs(dpr - 1) < 1e-6) return;
    throw new Error(
      `the touch driver maps CSS pixels onto a device reporting devicePixelRatio ${dpr}, and no scale ` +
      `was given. Fix: touchTransform: { scale: ${dpr}, origin: [x, y] }, where origin is the webview's ` +
      'top-left in SCREEN coordinates, or pass scale: 1 to assert the coordinates are already mapped.');
  }

  private map(x: number, y: number): [number, number] {
    return [Math.round(this.origin[0] + x * this.scale), Math.round(this.origin[1] + y * this.scale)];
  }

  private async perform(actions: any[]): Promise<void> {
    const chain = [{ type: 'pointer', id: 'ck-finger', parameters: { pointerType: 'touch' }, actions }];
    if (typeof this.driver.performActions === 'function') return this.driver.performActions(chain);
    if (typeof this.driver.execute === 'function') return this.driver.execute('actions', { actions: chain });
    throw new Error("the touch driver speaks neither performActions() nor execute('actions', …); " +
      'pass a WebDriver-compatible driver or a custom TouchBackend.');
  }

  async down(x: number, y: number): Promise<void> {
    if (!this.checked) await this.checkScale();
    const [mx, my] = this.map(x, y);
    await this.perform([
      { type: 'pointerMove', duration: 0, origin: 'viewport', x: mx, y: my },
      { type: 'pointerDown', button: 0 },
    ]);
  }

  /** The per-sample gap becomes the move's `duration`, so the device interpolates the leg itself. */
  async move(path: TouchSample[]): Promise<void> {
    if (!this.checked) await this.checkScale();
    if (!path.length) return;
    await this.perform(path.map(([x, y, dt]) => {
      const [mx, my] = this.map(x, y);
      return { type: 'pointerMove', duration: Math.max(0, Math.round(dt)), origin: 'viewport', x: mx, y: my };
    }));
  }

  async up(_x: number, _y: number): Promise<void> {
    if (!this.checked) await this.checkScale();
    await this.perform([{ type: 'pointerUp', button: 0 }]);
  }
}

/** Playwright's tap-only touchscreen, for browsers with touch but no CDP. A drag cannot be expressed. */
export class TouchscreenTouchBackend implements TouchBackend {
  readonly name = 'touchscreen';
  private pending: Point | null = null;
  constructor(private page: any) {}

  async down(x: number, y: number): Promise<void> { this.pending = [x, y]; }
  async move(_path: TouchSample[]): Promise<void> {
    throw new Error('this browser exposes taps but not touch travel, so a drag/slide puzzle cannot be ' +
      'driven on it. Use a Chromium-family browser (CDP touch dispatch) or an Appium driver.');
  }
  async up(x: number, y: number): Promise<void> {
    const at = this.pending ?? [x, y];
    this.pending = null;
    await this.page.touchscreen.tap(at[0], at[1]);
  }
}

export async function touchBackendFor(page: Page, driver?: any, transform?: TouchTransform): Promise<TouchBackend> {
  if (driver) {
    if (typeof driver.down === 'function' && typeof driver.up === 'function') return driver as TouchBackend;
    return new AppiumTouchBackend(driver, transform, page);
  }
  try {
    return await CdpTouchBackend.open(page);
  } catch (e) {
    if ((page as any).touchscreen) {
      log('no CDP session; falling back to tap-only touch dispatch');
      return new TouchscreenTouchBackend(page);
    }
    throw e;
  }
}

/** A finger on glass: no hover, touch events only, slower and more variable pauses. */
export class MobileHumanizer extends BaseHumanizer {
  readonly name: HumanizationMode = HumanizationMode.MOBILE;
  readonly hovers = false;
  // tap: measured human touch dwell clusters at 60-120ms. key: a soft keyboard is ~3x slower than a physical one.
  protected readonly pauses: PauseTable = {
    tap: [55, 130], between: [140, 320], grab: [90, 190], drop: [80, 170],
    probe: [70, 140], settle: [140, 300], key: [110, 320],
  };
  private backend: TouchBackend | null;
  private driver: any;
  private transform: TouchTransform | undefined;
  private frequency: number;
  private down = false;

  constructor(start: Point = [0, 0],
              options: { backend?: TouchBackend; driver?: any; transform?: TouchTransform; frequency?: number } = {}) {
    super(start);
    this.backend = options.backend ?? null;
    this.driver = options.driver;
    this.transform = options.transform;
    this.frequency = options.frequency ?? 90;
  }

  /** A solve that ended mid-gesture leaves a pointer down in the session's input state; lift it before the next one. */
  async reset(page: Page): Promise<void> {
    if (!this.down) return;
    try { await (await this.touch(page)).up(this.at[0], this.at[1]); } catch { /* a stale pointer must not fail a solve */ }
    this.down = false;
  }

  private async touch(page: Page): Promise<TouchBackend> {
    if (!this.backend) this.backend = await touchBackendFor(page, this.driver, this.transform);
    return this.backend;
  }

  async move(page: Page, to: Point): Promise<void> {
    const dest: Point = [Number(to[0]), Number(to[1])];
    if (this.down) {
      const [points, timings] = trajectory(this.at, dest, this.frequency);
      await (await this.touch(page)).move(points.map(([x, y], i) => [x, y, timings[i] - (i ? timings[i - 1] : 0)]));
    }
    this.at = dest;
  }

  async drift(page: Page, to: Point): Promise<void> {
    const dest: Point = [Number(to[0]), Number(to[1])];
    if (this.down) await (await this.touch(page)).move([[dest[0], dest[1], 0]]);
    this.at = dest;
  }

  async press(page: Page): Promise<void> {
    await (await this.touch(page)).down(this.at[0], this.at[1]);
    this.down = true;
  }

  async release(page: Page): Promise<void> {
    await (await this.touch(page)).up(this.at[0], this.at[1]);
    this.down = false;
  }

  /** A tap whose contact patch wobbles a pixel while held; a motionless tap is a synthetic one. */
  async click(page: Page, to: Point): Promise<void> {
    await this.move(page, to);
    await this.press(page);
    const held = this.pauseMs(PauseKind.TAP);
    await delay(held / 2);
    try {
      await (await this.touch(page)).move([[this.at[0] + gauss(0.9), this.at[1] + gauss(0.9), 0]]);
    } catch { /* a tap-only backend cannot wobble; the tap still lands */ }
    await delay(held / 2);
    await this.release(page);
  }

  /** Clears through the element: there is no Control key on a phone and no `page.keyboard` on Appium. */
  async typeText(page: Page, field: PlaywrightElementHandle, text: string): Promise<boolean> {
    const f = field as any;
    for (const [name, arg] of [['clear', undefined], ['fill', '']] as const) {
      if (typeof f?.[name] !== 'function') continue;
      try { await f[name](arg); break; } catch { /* an uncleared box is recoverable */ }
    }
    for (const ch of text) {
      try {
        if (typeof f?.sendKeys === 'function') await f.sendKeys(ch);
        else await page.keyboard.type(ch);
      } catch (e) {
        log(`could not type into the captcha field: ${e}`);
        return false;
      }
      await this.pause(PauseKind.KEY);
    }
    return true;
  }
}

/**
 * No humanisation: one move per gesture and a single fill. Fast, and detectable. It still moves before
 * it presses, because a click with no preceding move fails on the vendors that require a hover state first.
 */
export class NullHumanizer extends BaseHumanizer {
  readonly name: HumanizationMode = HumanizationMode.NONE;
  readonly hovers = false;
  protected readonly pauses: PauseTable = {};

  async move(page: Page, to: Point): Promise<void> {
    if (samePoint(this.at, to)) return;
    this.at = [Number(to[0]), Number(to[1])];
    try {
      await page.mouse.move(this.at[0], this.at[1]);
    } catch (e) {
      if (closedError(e)) log('could not move mouse; page or session closed');
    }
  }

  async press(page: Page): Promise<void> { await page.mouse.down(); }
  async release(page: Page): Promise<void> { await page.mouse.up(); }

  async typeText(page: Page, field: PlaywrightElementHandle, text: string): Promise<boolean> {
    try { await (field as any).fill(text); return true; } catch { /* fall through to the keyboard */ }
    try { await page.keyboard.press('Control+A'); } catch { /* optional */ }
    try {
      await page.keyboard.type(text);
      return true;
    } catch (e) {
      log(`could not type into the captcha field: ${e}`);
      return false;
    }
  }
}

export const MODES: readonly HumanizationMode[] = Object.values(HumanizationMode);

export interface HumanizerOptions {
  humanization?: HumanizationMode;
  humanizer?: Humanizer;
  touchDriver?: any;
  touchTransform?: TouchTransform;
  startingMousePosition?: { x: number; y: number };
}

/**
 * `config.humanizer`, else `config.humanization`, else CAPTCHA_HUMANIZATION, else mouse. The env var loses
 * to code, the opposite of the model settings, on purpose: an env var flipping a desktop solve to touch
 * dispatch would break every one of them silently.
 */
export function resolveHumanizer(config: HumanizerOptions = {}): Humanizer {
  if (config.humanizer) return config.humanizer;
  const raw = (config.humanization ?? process.env.CAPTCHA_HUMANIZATION ?? HumanizationMode.MOUSE).toString().trim().toLowerCase();
  if (!isOneOf(HumanizationMode, raw)) {
    throw new Error(`unknown humanization mode '${raw}'; expected one of ${MODES.join(', ')}, ` +
      'or pass your own object as CaptchaKrakenConfig.humanizer');
  }
  const p = config.startingMousePosition;
  const start: Point = p ? [p.x, p.y] : [0, 0];
  if (raw === HumanizationMode.MOBILE) return new MobileHumanizer(start, { driver: config.touchDriver, transform: config.touchTransform });
  if (raw === HumanizationMode.NONE) return new NullHumanizer(start);
  return new MouseHumanizer(start);
}
