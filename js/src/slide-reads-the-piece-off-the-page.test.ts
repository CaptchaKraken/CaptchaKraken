// The pixel diff sees the vacated left edge inset ~17px while the right edge is sharp, and every one of fourteen refused drags undershot;
// the DOM piece is read first and the diff stays as the fallback.
import { test } from 'node:test';
import assert from 'node:assert/strict';

import { CaptchaKrakenSolver } from './solver';
import { photographsItself } from './fake-dom.test';

const BOX = { x: 0, y: 0, width: 340, height: 400 };

const TARGET = 245;
const TRUE_PIECE_W = 80;

const DIFF_PIECE_W = 63;

async function runSlide({ pieceInDom }: { pieceInDom: boolean }) {
  const s: any = photographsItself(new CaptchaKrakenSolver({}));
  const moves: number[] = [];
  let handleX = 40;
  const pieceStartCentre = TRUE_PIECE_W / 2;

  const pieceCentreNow = () => pieceStartCentre + (handleX - 40);

  s.findControl = async (_scope: any, sels: ReadonlyArray<string>) => {
    if (sels.some((x) => x.includes('slider') || x.includes('btn') || x.includes('handle'))) {
      return { boundingBox: async () => ({ x: handleX - 25, y: 300, width: 50, height: 40 }) };
    }
    if (!pieceInDom) return null;
    return {
      boundingBox: async () => ({
        x: pieceCentreNow() - TRUE_PIECE_W / 2, y: 100,
        width: TRUE_PIECE_W, height: TRUE_PIECE_W,
      }),
    };
  };

  s.measurePieceBox = async () => (pieceInDom ? {
    x: pieceCentreNow() - TRUE_PIECE_W / 2, y: 100,
    width: TRUE_PIECE_W, height: TRUE_PIECE_W,
  } : null);
  s.shotScale = () => 1;
  s.move = async () => {};
  s.performSmoothMove = async (_p: any, x: number) => { handleX = x; moves.push(x); };
  s.human = { press: async () => {}, release: async () => {}, pause: async () => {}, drag: async () => {} };

  const LEFT_INSET = TRUE_PIECE_W - DIFF_PIECE_W;
  s.trackPiece = async () => {
    const origLeft = pieceStartCentre - TRUE_PIECE_W / 2;

    return {
      bbox: [origLeft + LEFT_INSET, 0, pieceCentreNow() + TRUE_PIECE_W / 2, TRUE_PIECE_W],
      piece: null,
    };
  };

  const element = { screenshot: async () => {} };
  await s.executeSlide(
    {} as any, element as any, {} as any,
    { action: 'drag', target_bounding_box: [TARGET / BOX.width, 0.4, TARGET / BOX.width, 0.5] } as any,
    BOX,
  );
  return { finalPieceCentre: pieceCentreNow(), moves };
}

test('with the piece in the DOM the drag lands on the notch', async () => {
  const { finalPieceCentre } = await runSlide({ pieceInDom: true });
  const err = finalPieceCentre - TARGET;
  assert.ok(
    Math.abs(err) <= 2,
    `should seat within the notch, landed ${err.toFixed(1)}px off`,
  );
});

test('the diff-only path is what undershoots, and is still the fallback', async () => {
  const { finalPieceCentre } = await runSlide({ pieceInDom: false });
  const err = finalPieceCentre - TARGET;
  assert.ok(err < -4, `expected the known undershoot, got ${err.toFixed(1)}px`);
  assert.ok(
    Math.abs(err - -(TRUE_PIECE_W - DIFF_PIECE_W) / 2) < 1.5,
    `the undershoot should be half the width error (${(TRUE_PIECE_W - DIFF_PIECE_W) / 2}px), got ${(-err).toFixed(1)}px`,
  );
});
