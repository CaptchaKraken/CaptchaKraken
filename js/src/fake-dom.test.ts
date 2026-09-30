// A locator-shaped fake DOM for driver tests. Nodes name the selectors they answer to, so no test carries its own CSS matcher.
import { test } from 'node:test';
import assert from 'node:assert/strict';

import type { BoundingBoxRect, PlaywrightElementHandle, PlaywrightFrame, PlaywrightLocator } from './playwright-types';
import { WIDGET_PROBES } from './selectors';

export interface FakeNode {
  /** Every selector this node answers to, matched by exact string per comma-separated part. */
  matches: string[];
  visible?: boolean;
  text?: string;
  value?: string;
  /** `undefined` is a plain 100x40 box; `null` is a node the page will not measure. */
  box?: BoundingBoxRect | null;
  /** boundingBox throws, as a handle that detached mid-read does. */
  throws?: boolean;
  /** The content document, when the node is an iframe. */
  frame?: FakeNode[];
  children?: FakeNode[];
}

export interface FakeHandle extends PlaywrightElementHandle {
  node: FakeNode;
}

interface Options {
  /** Selectors this adapter rejects, at query time, the way a real one does. */
  unparsable?: string[];
}

/**
 * For tests about what the driver does with a picture rather than how it takes one: each fake element photographs
 * itself. The viewport capture has tests of its own.
 */
export function photographsItself<T>(solver: T): T {
  (solver as any).shot = (el: PlaywrightElementHandle, path: string, timeout?: number, animations?: 'disabled' | 'allow') =>
    el.screenshot({ path, timeout, animations });
  return solver;
}

const parts = (selector: string): string[] => (selector.startsWith('xpath=') ? [selector] : selector.split(',').map((s) => s.trim()));

function handleOf(node: FakeNode, opts: Options): FakeHandle {
  return {
    node,
    isVisible: async () => node.visible !== false,
    textContent: async () => node.text ?? '',
    inputValue: async () => node.value ?? '',
    getAttribute: async () => null,
    boundingBox: async () => {
      if (node.throws) throw new Error('detached mid-read');
      return node.box === undefined ? { x: 0, y: 0, width: 100, height: 40 } : node.box;
    },
    contentFrame: async () => (node.frame ? fakeDom(node.frame, opts) : null),
    scrollIntoViewIfNeeded: async () => {},
    screenshot: async () => Buffer.alloc(0),
    evaluate: async (fn) => fn(node as unknown as Element),
  };
}

const select = (nodes: FakeNode[], selector: string, opts: Options): FakeNode[] => {
  if (opts.unparsable?.includes(selector)) throw new Error(`cannot parse ${selector}`);
  return parts(selector).flatMap((part) => nodes.filter((n) => n.matches.includes(part)));
};

function locatorOf(resolve: () => FakeNode[], opts: Options): PlaywrightLocator {
  return {
    locator: (selector) => locatorOf(() => select(resolve().flatMap((n) => n.children ?? []), selector, opts), opts),
    filter: ({ visible }) => locatorOf(() => resolve().filter((n) => visible === undefined || (n.visible !== false) === visible), opts),
    all: async () => resolve().map((n) => locatorOf(() => [n], opts)),
    count: async () => resolve().length,
    elementHandle: async () => {
      const [first] = resolve();
      return first ? handleOf(first, opts) : null;
    },
  };
}

/** A page or frame holding `nodes`. Cast it to `Page` where a test drives the solver with it. */
export function fakeDom(nodes: FakeNode[], opts: Options = {}): PlaywrightFrame {
  return {
    locator: (selector) => locatorOf(() => select(nodes, selector, opts), opts),
    waitForSelector: async () => null,
    waitForFunction: async () => true,
  };
}

/** The host-page iframe selectors an element with this `src` answers to, the way a CSS engine would read them. */
export function iframeMatches(src: string): string[] {
  const wants = (sel: string) => [...sel.matchAll(/\[src\*="([^"]+)"\]/g)].map((m) => m[1]);
  return WIDGET_PROBES.map((p) => p.selector).filter((sel) => {
    if (!sel.startsWith('iframe[src')) return false;
    const [positive, negative = ''] = sel.split(':not(');
    return wants(positive).every((s) => src.includes(s)) && wants(negative).every((s) => !src.includes(s));
  });
}

test('the fake honours the visibility filter and rejects at query time, not construction', async () => {
  const dom = fakeDom([{ matches: ['.a'], visible: false }, { matches: ['.a'] }], { unparsable: ['bad'] });
  assert.equal(await dom.locator('.a').count(), 2);
  assert.equal((await dom.locator('.a').filter({ visible: true }).all()).length, 1);
  const lazy = dom.locator('bad');
  await assert.rejects(() => lazy.all());
  assert.equal(await fakeDom([{ matches: ['.a'], children: [{ matches: ['.b'] }] }]).locator('.a').locator('.b').count(), 1);
});

test('iframe selectors are read off the src the way the vendors serve them', () => {
  assert.deepEqual(iframeMatches('https://www.google.com/recaptcha/api2/anchor?k=6Le&size=invisible'), []);
  assert.deepEqual(iframeMatches('https://www.google.com/recaptcha/api2/anchor?k=6Le'), ['iframe[src*="recaptcha/api2/anchor"]:not([src*="size=invisible"])']);
});
