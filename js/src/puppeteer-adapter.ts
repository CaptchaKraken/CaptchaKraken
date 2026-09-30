import {
  PlaywrightPage,
  PlaywrightFrame,
  PlaywrightElementHandle,
  PlaywrightLocator,
  PlaywrightResponse,
  BoundingBoxRect,
  ViewportSize,
} from './playwright-types';

interface PuppeteerSelectorState {
  state?: 'attached' | 'detached' | 'visible' | 'hidden';
  timeout?: number;
}
interface PuppeteerElementHandle {
  screenshot(options?: { path?: string }): Promise<unknown>;
  contentFrame(): Promise<PuppeteerFrame | null>;
  boundingBox(): Promise<BoundingBoxRect | null>;
  scrollIntoView(): Promise<void>;
  isVisible(): Promise<boolean>;
  evaluate(pageFunction: (el: any, ...args: any[]) => any, ...args: any[]): Promise<any>;
  $$(selector: string): Promise<PuppeteerElementHandle[]>;
}
interface PuppeteerFrame {
  $$(selector: string): Promise<PuppeteerElementHandle[]>;
  waitForSelector(selector: string, options?: any): Promise<PuppeteerElementHandle | null>;
  waitForFunction(pageFunction: Function | string, options?: any, ...args: any[]): Promise<unknown>;
}
interface PuppeteerPage {
  mouse: {
    move(x: number, y: number, options?: { steps?: number }): Promise<void>;
    down(options?: any): Promise<void>;
    up(options?: any): Promise<void>;
  };
  keyboard: {
    type(text: string, options?: { delay?: number }): Promise<void>;
    press(key: string, options?: any): Promise<void>;
    down(key: string, options?: any): Promise<void>;
    up(key: string): Promise<void>;
  };
  waitForSelector(selector: string, options?: any): Promise<PuppeteerElementHandle | null>;
  viewport(): ViewportSize | null;
  evaluate<R>(pageFunction: () => R): Promise<R>;
  $$(selector: string): Promise<PuppeteerElementHandle[]>;
  isClosed(): boolean;
  evaluate(pageFunction: () => any): Promise<any>;
  on(event: 'response', listener: (response: PlaywrightResponse) => void): unknown;
  off(event: 'response', listener: (response: PlaywrightResponse) => void): unknown;
  url(): string;
}

function toPuppeteerSelectorOptions(options?: PuppeteerSelectorState): any {
  if (!options) return undefined;
  const { state, timeout } = options;
  const out: any = {};
  if (timeout !== undefined) out.timeout = timeout;
  if (state === 'visible') out.visible = true;
  else if (state === 'hidden') out.hidden = true;

  return out;
}

/** Puppeteer's own Locator has no `all()`, `count()` or visibility filter, so a Playwright-shaped one is built over `$$`. */
function locatorOver(resolve: () => Promise<PuppeteerElementHandle[]>): PlaywrightLocator {
  return {
    locator: (selector) => locatorOver(async () => (await Promise.all((await resolve()).map((h) => h.$$(selector)))).flat()),
    filter: ({ visible }) => locatorOver(async () => {
      const found = await resolve();
      const shown = await Promise.all(found.map((h) => (visible === undefined ? true : h.isVisible().then((v) => v === visible))));
      return found.filter((_, i) => shown[i]);
    }),
    all: async () => (await resolve()).map((h) => locatorOver(async () => [h])),
    count: async () => (await resolve()).length,
    elementHandle: async () => wrapHandle((await resolve())[0] ?? null),
  };
}

function wrapHandle(h: PuppeteerElementHandle | null): PlaywrightElementHandle | null {
  if (!h) return null;
  return {
    screenshot: (options) => h.screenshot(options) as Promise<Buffer>,
    contentFrame: async () => wrapFrame(await h.contentFrame()),
    boundingBox: () => h.boundingBox(),
    scrollIntoViewIfNeeded: () => h.scrollIntoView(),
    getAttribute: (name) => h.evaluate((el: Element, n: string) => el.getAttribute(n), name),
    isVisible: () => h.isVisible(),
    textContent: () => h.evaluate((el: Element) => el.textContent),
    inputValue: () => h.evaluate((el: any) => (typeof el.value === 'string' ? el.value : '')),
    evaluate: (pageFunction) => h.evaluate(pageFunction),
  };
}

function wrapFrame(f: PuppeteerFrame | null): PlaywrightFrame | null {
  if (!f) return null;
  return {
    locator: (selector) => locatorOver(() => f.$$(selector)),
    waitForSelector: async (selector, options) =>
      wrapHandle(await f.waitForSelector(selector, toPuppeteerSelectorOptions(options))),
    waitForFunction: (pageFunction, arg, options) =>

      f.waitForFunction(pageFunction as any, options, arg),
  };
}

export function fromPuppeteer(page: PuppeteerPage): PlaywrightPage {
  return {
    mouse: {
      move: (x, y, options) => page.mouse.move(x, y, options),
      down: (options) => page.mouse.down(options),
      up: (options) => page.mouse.up(options),
    },
    keyboard: {
      type: (text, options) => page.keyboard.type(text, options),

      // Puppeteer has no 'Control+A' combo syntax; the solver speaks Playwright and this side translates.
      press: async (key) => {
        const parts = key.split('+');
        const target = parts.pop() as string;
        for (const mod of parts) await page.keyboard.down(mod);
        await page.keyboard.press(target);
        for (const mod of parts.reverse()) await page.keyboard.up(mod);
      },
    },
    waitForTimeout: (timeout) => new Promise<void>((resolve) => setTimeout(resolve, timeout)),
    waitForSelector: async (selector, options) =>
      wrapHandle(await page.waitForSelector(selector, toPuppeteerSelectorOptions(options))),
    viewportSize: () => page.viewport(),
    evaluate: (pageFunction) => page.evaluate(pageFunction),
    locator: (selector) => locatorOver(() => page.$$(selector)),
    // Forwarded explicitly: without it the watcher polls a dead page forever.
    isClosed: () => page.isClosed(),
    // Puppeteer's HTTPResponse already has Playwright's url/status/text, so the listener passes straight through.
    on: (event, listener) => page.on(event, listener),
    off: (event, listener) => page.off(event, listener),
    url: () => page.url(),
  };
}
