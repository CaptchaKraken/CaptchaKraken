// Every capture is one unclipped viewport screenshot, cropped here. A clipped capture — an element screenshot, or
// `page.screenshot({ clip })` — makes a headed Chromium repaint the page at the clip's size for that frame, and the
// user watches the page flash and jump on every poll and every burst frame. Mirror of
// python/tests/test_a_capture_never_clips_the_page.py.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import zlib from 'node:zlib';

import { CaptchaKrakenSolver, isStaleHandleError } from './solver';
import { cropPng, enclosingRect } from './png';

/** Every pixel distinct, so a crop off by one pixel anywhere cannot match. */
const pixel = (x: number, y: number): number[] => [x % 256, y % 256, (x >> 8) * 16 + (y >> 8)];

function paeth(a: number, b: number, c: number): number {
  const p = a + b - c;
  const [pa, pb, pc] = [Math.abs(p - a), Math.abs(p - b), Math.abs(p - c)];
  return pa <= pb && pa <= pc ? a : pb <= pc ? b : c;
}

/** An RGB PNG whose rows cycle through all five filter types, so the decoder is checked against each of them. */
function viewportPng(width: number, height: number): Buffer {
  const bpp = 3;
  const rows = Array.from({ length: height }, (_, y) => Buffer.from(Array.from({ length: width }, (_, x) => pixel(x, y)).flat()));
  const filtered = rows.flatMap((row, y) => {
    const up = y ? rows[y - 1] : Buffer.alloc(row.length);
    const filter = y % 5;
    const out = Buffer.alloc(row.length);
    for (let i = 0; i < row.length; i++) {
      const left = i >= bpp ? row[i - bpp] : 0;
      const corner = i >= bpp ? up[i - bpp] : 0;
      const predict = [0, left, up[i], (left + up[i]) >> 1, paeth(left, up[i], corner)][filter];
      out[i] = (row[i] - predict) & 0xff;
    }
    return [Buffer.from([filter]), out];
  });
  const chunk = (type: string, data: Buffer) => {
    const head = Buffer.alloc(8);
    head.writeUInt32BE(data.length, 0);
    head.write(type, 4, 'latin1');
    return Buffer.concat([head, data, Buffer.alloc(4)]);   // the decoder does not check CRCs
  };
  const ihdr = Buffer.alloc(13);
  ihdr.writeUInt32BE(width, 0);
  ihdr.writeUInt32BE(height, 4);
  ihdr[8] = 8;
  ihdr[9] = 2;
  return Buffer.concat([Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]), chunk('IHDR', ihdr),
    chunk('IDAT', zlib.deflateSync(Buffer.concat(filtered))), chunk('IEND', Buffer.alloc(0))]);
}

/** Decode an unfiltered (filter 0 on every row) RGB PNG, which is what cropPng writes. */
function readCrop(png: Buffer): { width: number; height: number; px: (x: number, y: number) => number[] } {
  const width = png.readUInt32BE(16);
  const height = png.readUInt32BE(20);
  const idat = png.subarray(33 + 8, 33 + 8 + png.readUInt32BE(33));
  const raw = zlib.inflateSync(idat);
  const stride = width * 3 + 1;
  return { width, height, px: (x, y) => [...raw.subarray(y * stride + 1 + x * 3, y * stride + 1 + x * 3 + 3)] };
}

for (const dpr of [1, 2]) {
  test(`the crop is the element's whole pixels at the capture's scale (dpr ${dpr})`, () => {
    const png = viewportPng(160 * dpr, 120 * dpr);
    const rect = enclosingRect({ x: 37.5, y: 61.25, width: 101.3, height: 41.6 });
    assert.deepEqual(rect, { x: 37, y: 61, width: 102, height: 42 }, "not the rect Playwright's element screenshot clips to");
    const crop = readCrop(cropPng(png, rect, 160));
    assert.deepEqual([crop.width, crop.height], [102 * dpr, 42 * dpr]);
    for (const [x, y] of [[0, 0], [crop.width - 1, 0], [0, crop.height - 1], [crop.width - 1, crop.height - 1], [17, 9]]) {
      assert.deepEqual(crop.px(x, y), pixel(37 * dpr + x, 61 * dpr + y), `pixel (${x}, ${y})`);
    }
  });
}

function rig(opts: { viewport?: { width: number; height: number } | null;
                     inner?: { width: number; height: number; scale?: number };
                     dpr?: number; box: any; scrolledTo?: any }) {
  const shots: any[] = [];
  const view = opts.viewport ?? opts.inner!;
  const page: any = {
    viewportSize: () => opts.viewport ?? null,
    // A real window always answers; when nothing says otherwise its layout is the viewport.
    evaluate: async () => opts.inner ?? opts.viewport,
    screenshot: async (o: any) => { shots.push(o); return viewportPng(view.width * (opts.dpr ?? 1), view.height * (opts.dpr ?? 1)); },
  };
  const el: any = {
    box: opts.box,
    scrolls: 0,
    elementShots: 0,
    boundingBox: async () => el.box,
    scrollIntoViewIfNeeded: async () => { el.scrolls++; el.box = opts.scrolledTo ?? el.box; },
    screenshot: async ({ path: p }: { path: string }) => { el.elementShots++; fs.writeFileSync(p, viewportPng(4, 4)); },
  };
  const solver: any = new CaptchaKrakenSolver({});
  solver.page = page;
  const out = path.join(fs.mkdtempSync(path.join(os.tmpdir(), 'ck_capture_')), 'shot.png');
  return { solver, page, el, shots, out };
}

for (const animations of ['disabled', 'allow'] as const) {
  test(`every capture is one viewport shot with no clip (animations ${animations})`, async () => {
    const { solver, el, shots, out } = rig({ viewport: { width: 160, height: 120 }, dpr: 2, box: { x: 10, y: 20, width: 50, height: 25 } });
    await solver.shot(el, out, 1234, animations);
    assert.deepEqual(shots, [{ timeout: 1234, animations }], 'the capture was not one unclipped viewport screenshot');
    assert.equal(el.elementShots, 0, 'the element photographed itself, which repaints the page');
    const crop = readCrop(fs.readFileSync(out));
    assert.deepEqual([crop.width, crop.height], [100, 50], 'the crop lost the device pixel ratio');
  });
}

test('an element below the fold is scrolled in once, not per shot', async () => {
  const { solver, el, shots, out } = rig({ viewport: { width: 160, height: 120 }, box: { x: 10, y: 900, width: 50, height: 25 },
    scrolledTo: { x: 10, y: 40, width: 50, height: 25 } });
  for (let i = 0; i < 3; i++) await solver.shot(el, out);
  assert.equal(el.scrolls, 1);
  assert.equal(shots.length, 3);
  assert.equal(el.elementShots, 0);
});

test('an element bigger than the viewport photographs itself', async () => {
  const { solver, el, shots, out } = rig({ viewport: { width: 160, height: 120 }, box: { x: 0, y: 0, width: 200, height: 20 } });
  await solver.shot(el, out);
  assert.equal(el.elementShots, 1);
  assert.equal(shots.length, 0);
  assert.equal(el.scrolls, 0);
});

test('a mobile layout zoomed out to fit photographs the element', async () => {
  // Pixel 7 on a desktop page: a 412px device, a 981px layout shown at 0.42. The box speaks layout pixels and the
  // capture does not, so a crop scaled by the device width cut the board out of the wrong place.
  const { solver, el, shots, out } = rig({ viewport: { width: 412, height: 839 },
    inner: { width: 981, height: 1996, scale: 0.42 }, box: { x: 0, y: 0, width: 320, height: 257 } });
  await solver.shot(el, out);
  assert.equal(el.elementShots, 1);
  assert.equal(shots.length, 0);
});

test('a context without a viewport asks the window', async () => {
  const { solver, el, out } = rig({ viewport: null, inner: { width: 80, height: 60 }, box: { x: 0, y: 0, width: 30, height: 20 } });
  await solver.shot(el, out);
  const crop = readCrop(fs.readFileSync(out));
  assert.deepEqual([crop.width, crop.height], [30, 20]);
});

test('an element with no box reads as a stale handle', async () => {
  const { solver, el, out } = rig({ viewport: { width: 160, height: 120 }, box: null });
  await assert.rejects(() => solver.shot(el, out), (e: Error) => isStaleHandleError(e.message));
});
