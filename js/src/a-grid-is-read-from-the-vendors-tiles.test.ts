// A reCAPTCHA grid's cells come from the challenge frame's own tiles, not from the picture.
//
// The client used to find the lattice in the screenshot with an element detector. It has none now: each
// `td.rc-imageselect-tile` has a box in page pixels, and that box less the iframe's corner, scaled by the
// screenshot's size over the iframe's, is the cell on the screenshot. Twin of the Python test of the same name.
import assert from 'node:assert/strict';
import { mkdtempSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';
import { CaptchaKrakenSolver } from './solver';

const IFRAME = { x: 300, y: 50, width: 400, height: 580 };
/** A 3x3 board of 100px tiles, 4px apart, under a 120px banner, in iframe pixels. */
const TILES = Array.from({ length: 9 }, (_, i) => [10 + (i % 3) * 104, 120 + Math.floor(i / 3) * 104, 100, 100]);

/** Just the header `readPngDimensions` reads. */
function shot(w: number, h: number): string {
  const buf = Buffer.alloc(24);
  Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a, 0, 0, 0, 13, 0x49, 0x48, 0x44, 0x52]).copy(buf);
  buf.writeUInt32BE(w, 16);
  buf.writeUInt32BE(h, 20);
  const path = join(mkdtempSync(join(tmpdir(), 'ck-grid-')), 'board.png');
  writeFileSync(path, buf);
  return path;
}

function iframe(tiles: number[][] | null, seen: string[] = []) {
  const frame = tiles && {
    locator: (sel: string) => {
      seen.push(sel);
      return {
        all: async () => tiles.map(([x, y, width, height]) => ({
          elementHandle: async () => ({ boundingBox: async () => ({ x: IFRAME.x + x, y: IFRAME.y + y, width, height }) }),
        })),
      };
    },
  };
  return { contentFrame: async () => frame, boundingBox: async () => IFRAME };
}

const domGrid = (el: unknown, path: string) => (new CaptchaKrakenSolver() as any).domGrid(el, path);

test('tiles scale onto a 2x screenshot', async () => {
  const seen: string[] = [];
  const boxes = await domGrid(iframe(TILES, seen), shot(800, 1160));
  assert.deepEqual(boxes, TILES.map(([x, y, w, h]) => [2 * x, 2 * y, 2 * (x + w), 2 * (y + h)]));
  assert.deepEqual(seen, ['td.rc-imageselect-tile']);
});

test('tiles land unscaled on a 1x screenshot', async () => {
  assert.deepEqual(await domGrid(iframe(TILES), shot(400, 580)), TILES.map(([x, y, w, h]) => [x, y, x + w, y + h]));
});

test('fewer than four tiles, or no frame, is no grid', async () => {
  assert.equal(await domGrid(iframe(TILES.slice(0, 3)), shot(400, 580)), null);
  assert.equal(await domGrid(iframe(null), shot(400, 580)), null);
});
