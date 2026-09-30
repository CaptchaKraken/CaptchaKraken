export interface BoundingBoxRect {
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface ViewportSize {
  width: number;
  height: number;
}

export interface PlaywrightElementHandle {
  screenshot(options?: { path?: string; timeout?: number; animations?: 'disabled' | 'allow' }): Promise<Buffer>;

  contentFrame(): Promise<PlaywrightFrame | null>;

  boundingBox(): Promise<BoundingBoxRect | null>;

  scrollIntoViewIfNeeded(options?: { timeout?: number }): Promise<void>;

  getAttribute(name: string): Promise<string | null>;

  isVisible(): Promise<boolean>;

  textContent(): Promise<string | null>;

  inputValue(): Promise<string>;

  evaluate<R>(pageFunction: (element: Element) => R): Promise<R>;
}

/** The subset of Playwright's Locator the driver needs. `filter({ visible })` is Playwright 1.51+. */
export interface PlaywrightLocator {
  locator(selector: string): PlaywrightLocator;

  filter(options: { visible?: boolean }): PlaywrightLocator;

  all(): Promise<PlaywrightLocator[]>;

  count(): Promise<number>;

  elementHandle(options?: { timeout?: number }): Promise<PlaywrightElementHandle | null>;
}

/** Anything selectors can be run inside: a page, a frame, or the locator of an inline widget. */
export interface PlaywrightScope {
  locator(selector: string): PlaywrightLocator;
}

export interface PlaywrightFrame extends PlaywrightScope {
  waitForSelector(
    selector: string,
    options?: { state?: 'attached' | 'detached' | 'visible' | 'hidden'; timeout?: number },
  ): Promise<PlaywrightElementHandle | null>;

  waitForFunction(
    pageFunction: Function | string,
    arg?: any,
    options?: { timeout?: number; polling?: number | 'raf' },
  ): Promise<unknown>;
}

/** A network response as Playwright and Puppeteer both shape it. */
export interface PlaywrightResponse {
  url(): string;
  status(): number;
  text(): Promise<string>;
}

/**
 * Structural on purpose: the package depends on no browser library, and the version skew between
 * playwright, patchright and camoufox-js makes a nominal import the wrong one for someone.
 */
export interface PlaywrightPage extends PlaywrightScope {
  mouse: {
    move(x: number, y: number, options?: { steps?: number }): Promise<void>;
    down(options?: { button?: 'left' | 'right' | 'middle'; clickCount?: number }): Promise<void>;
    up(options?: { button?: 'left' | 'right' | 'middle'; clickCount?: number }): Promise<void>;
  };

  /** `type` is called per character by the humanizer; a constant `delay` would itself be a signal. */
  keyboard: {
    type(text: string, options?: { delay?: number }): Promise<void>;
    press(key: string, options?: { delay?: number }): Promise<void>;
  };

  waitForTimeout(timeout: number): Promise<void>;

  waitForSelector(
    selector: string,
    options?: { state?: 'attached' | 'detached' | 'visible' | 'hidden'; timeout?: number },
  ): Promise<PlaywrightElementHandle | null>;

  viewportSize(): ViewportSize | null;

  /** Optional: the mouse humanizer asks the window for its size when `viewportSize()` is null (camoufox). */
  evaluate?<R>(pageFunction: () => R): Promise<R>;

  context?(): { newCDPSession(page: PlaywrightPage): Promise<any> };

  touchscreen?: {
    tap(x: number, y: number): Promise<void>;
  };

  isClosed?(): boolean;

  /** Optional: where the vendor's own verdict is read. Without it every round is judged by the DOM. */
  on?(event: 'response', listener: (response: PlaywrightResponse) => void): unknown;

  off?(event: 'response', listener: (response: PlaywrightResponse) => void): unknown;

  /** Optional: its hostname names the site on hosted requests. */
  url?(): string;
}

export type Page = PlaywrightPage;
