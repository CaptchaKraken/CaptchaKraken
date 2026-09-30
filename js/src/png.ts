/**
 * Cutting a rectangle out of a PNG, with nothing but node:zlib. The driver photographs the whole viewport and crops
 * the widget out of it here, because a clipped browser capture makes a headed Chromium repaint the page.
 */
import zlib from 'node:zlib';

/** Whole CSS pixels, in viewport coordinates. */
export interface CaptureRect {
  x: number;
  y: number;
  width: number;
  height: number;
}

/** The whole pixels a bounding box covers: the rect Playwright's element screenshot clips to. */
export function enclosingRect(box: { x: number; y: number; width: number; height: number }): CaptureRect {
  const x = Math.floor(box.x + 1e-3);
  const y = Math.floor(box.y + 1e-3);
  return { x, y, width: Math.ceil(box.x + box.width - 1e-3) - x, height: Math.ceil(box.y + box.height - 1e-3) - y };
}

const SIGNATURE = Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]);
const CHANNELS: Record<number, number> = { 0: 1, 2: 3, 3: 1, 4: 2, 6: 4 };
// Chunks the pixels cannot be read without: the palette and its transparency, for a colour-type-3 image.
const CARRIED = new Set(['PLTE', 'tRNS']);

const CRC_TABLE = Array.from({ length: 256 }, (_, n) => {
  let c = n;
  for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
  return c >>> 0;
});

function crc32(buf: Buffer): number {
  let c = 0xffffffff;
  for (const byte of buf) c = CRC_TABLE[(c ^ byte) & 0xff] ^ (c >>> 8);
  return (c ^ 0xffffffff) >>> 0;
}

function chunk(type: string, data: Buffer): Buffer {
  const head = Buffer.alloc(8);
  head.writeUInt32BE(data.length, 0);
  head.write(type, 4, 'latin1');
  const crc = Buffer.alloc(4);
  crc.writeUInt32BE(crc32(Buffer.concat([head.subarray(4), data])), 0);
  return Buffer.concat([head, data, crc]);
}

function paeth(a: number, b: number, c: number): number {
  const p = a + b - c;
  const pa = Math.abs(p - a);
  const pb = Math.abs(p - b);
  const pc = Math.abs(p - c);
  return pa <= pb && pa <= pc ? a : pb <= pc ? b : c;
}

/** Undo the per-row filters of rows [0, rows); a row's filter reads the row above, so the rows above a crop are decoded too. */
function unfilter(raw: Buffer, rows: number, stride: number, bpp: number): Buffer[] {
  const out: Buffer[] = [];
  let prev = Buffer.alloc(stride);
  for (let y = 0; y < rows; y++) {
    const at = y * (stride + 1);
    const filter = raw[at];
    const line = raw.subarray(at + 1, at + 1 + stride);
    const cur = Buffer.alloc(stride);
    for (let i = 0; i < stride; i++) {
      const left = i >= bpp ? cur[i - bpp] : 0;
      const up = prev[i];
      const predict = filter === 0 ? 0
        : filter === 1 ? left
        : filter === 2 ? up
        : filter === 3 ? (left + up) >> 1
        : filter === 4 ? paeth(left, up, i >= bpp ? prev[i - bpp] : 0)
        : NaN;
      if (Number.isNaN(predict)) throw new Error(`PNG row ${y} has unknown filter type ${filter}`);
      cur[i] = (line[i] + predict) & 0xff;
    }
    out.push(cur);
    prev = cur;
  }
  return out;
}

/** Cut `rect` out of a viewport capture `cssWidth` CSS pixels wide, at the capture's own device pixel ratio. */
export function cropPng(png: Buffer, rect: CaptureRect, cssWidth: number): Buffer {
  if (!png.subarray(0, 8).equals(SIGNATURE)) throw new Error('not a PNG');
  let ihdr: Buffer | null = null;
  const idat: Buffer[] = [];
  const carried: Buffer[] = [];
  for (let at = 8; at < png.length;) {
    const length = png.readUInt32BE(at);
    const type = png.toString('latin1', at + 4, at + 8);
    const data = png.subarray(at + 8, at + 8 + length);
    if (type === 'IHDR') ihdr = data;
    else if (type === 'IDAT') idat.push(data);
    else if (CARRIED.has(type)) carried.push(chunk(type, data));
    at += 12 + length;
  }
  if (!ihdr) throw new Error('PNG has no IHDR');
  const width = ihdr.readUInt32BE(0);
  const bitDepth = ihdr[8];
  const colorType = ihdr[9];
  const channels = CHANNELS[colorType];
  if (!channels || bitDepth < 8 || ihdr[12] !== 0) {
    throw new Error(`unsupported PNG: colour type ${colorType}, bit depth ${bitDepth}, interlace ${ihdr[12]}`);
  }
  const bpp = channels * (bitDepth / 8);
  const scale = width / cssWidth;
  const x1 = Math.round(rect.x * scale);
  const y1 = Math.round(rect.y * scale);
  const x2 = Math.round((rect.x + rect.width) * scale);
  const y2 = Math.round((rect.y + rect.height) * scale);
  const rows = unfilter(zlib.inflateSync(Buffer.concat(idat)), y2, width * bpp, bpp);
  const cropped = Buffer.concat(rows.slice(y1).flatMap((row) => [Buffer.from([0]), row.subarray(x1 * bpp, x2 * bpp)]));
  const header = Buffer.from(ihdr);
  header.writeUInt32BE(x2 - x1, 0);
  header.writeUInt32BE(y2 - y1, 4);
  return Buffer.concat([
    SIGNATURE, chunk('IHDR', header), ...carried, chunk('IDAT', zlib.deflateSync(cropped, { level: 1 })), chunk('IEND', Buffer.alloc(0)),
  ]);
}
