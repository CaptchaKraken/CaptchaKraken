"""A board's grid of tiles, and the state of each tile.

`find_grid` asks the element detector (`pointer.detector`) for the board's grid
and the cells inside it, and returns the cells in reading order when they make
a whole lattice. The detector was trained on every vendor's boards, grids and
not-grids alike, so a board of cards, a sprite sheet or a keyframe of moving
tiles is simply not a `grid` to it.

The rest reads pixels inside cells the grid has already given: a vendor's
"selected" mark, a tile still loading, an empty slot, a tile fading in.
"""

from __future__ import annotations

import tempfile
from typing import List, Optional, Sequence, Tuple

import numpy as np
from PIL import Image
from scipy import ndimage

from ..kinds import LabelPosition
from ..overlay import add_overlays_to_image

Box = Tuple[int, int, int, int]

#: Below these the detector is guessing: measured on real captures, every true
#: grid and its cells score above them and no not-grid board's grid does.
GRID_MIN_SCORE = 0.5
CELL_MIN_SCORE = 0.5
#: A row starts where a cell's top sits more than this share of a cell below the row's.
ROW_BREAK = 0.5
#: A tile is a cell whatever else it looks like: a flat-coloured tile can read as a
#: jigsaw piece (`draggable`) or an `item`. Inside the grid, one the size of the
#: cells (within this share) that no cell box already covers fills its slot.
TILE_CLASSES = ("draggable", "item")
TILE_SIZE_TOL = 0.25


def _iou(a: Sequence[float], b: Sequence[float]) -> float:
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def _with_tiles(cells: List[List[float]], tiles: List[List[float]]) -> List[List[float]]:
    """`cells` plus every tile the size of a cell that no cell (or tile already taken) overlaps."""
    if not cells:
        return cells
    w = float(np.median([c[2] - c[0] for c in cells]))
    h = float(np.median([c[3] - c[1] for c in cells]))
    out = list(cells)
    for t in tiles:
        if abs((t[2] - t[0]) - w) <= TILE_SIZE_TOL * w and abs((t[3] - t[1]) - h) <= TILE_SIZE_TOL * h \
                and all(_iou(t, c) < 0.3 for c in out):
            out.append(t)
    return out


def _cells_in(grid: Sequence[float], cells: List[List[float]]) -> List[List[float]]:
    x0, y0, x1, y1 = grid
    return [c for c in cells if x0 <= (c[0] + c[2]) / 2 <= x1 and y0 <= (c[1] + c[3]) / 2 <= y1]


def _rows(cells: List[List[float]]) -> List[List[List[float]]]:
    """Cells grouped into rows, top to bottom, each row left to right."""
    h = float(np.median([c[3] - c[1] for c in cells]))
    rows: List[List[List[float]]] = []
    for c in sorted(cells, key=lambda c: c[1]):
        if rows and c[1] - rows[-1][0][1] <= ROW_BREAK * h:
            rows[-1].append(c)
        else:
            rows.append([c])
    return [sorted(r, key=lambda c: c[0]) for r in rows]


def find_grid(image_path: str) -> Optional[List[Box]]:
    """The cells of the board's grid in reading order, as (x0, y0, x1, y1) pixels;
    None when the board has no grid, or its cells do not form whole rows of one length."""
    from ..pointer.detector import detect_file

    dets = detect_file(image_path)
    grids = [d for d in dets if d["class"] == "grid" and d["score"] >= GRID_MIN_SCORE]
    if not grids:
        return None
    grid = max(grids, key=lambda d: d["score"])["box"]
    cells = _cells_in(grid, [d["box"] for d in dets if d["class"] == "cell" and d["score"] >= CELL_MIN_SCORE])
    cells = _with_tiles(cells, _cells_in(grid, [d["box"] for d in dets
                                                if d["class"] in TILE_CLASSES and d["score"] >= CELL_MIN_SCORE]))
    if len(cells) < 4:
        return None
    rows = _rows(cells)
    if len(rows) < 2 or len({len(r) for r in rows}) != 1 or len(rows[0]) < 2:
        return None
    return [tuple(int(round(v)) for v in c) for r in rows for c in r]


# ── colour ──────────────────────────────────────────────────────────────

def _read_rgb(image_path: str) -> Optional[np.ndarray]:
    try:
        with Image.open(image_path) as im:
            return np.asarray(im.convert("RGB"))
    except OSError:
        return None


def _lab8(rgb: np.ndarray) -> np.ndarray:
    """CIELAB (D65) on the 8-bit scale the cell thresholds were measured on:
    L x 255/100, a and b offset by 128."""
    c = rgb.astype(np.float32) / 255.0
    lin = np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)
    xyz = lin @ np.array([[0.412453, 0.357580, 0.180423],
                          [0.212671, 0.715160, 0.072169],
                          [0.019334, 0.119193, 0.950227]], np.float32).T
    xyz /= np.array([0.950456, 1.0, 1.088754], np.float32)
    f = np.where(xyz > 0.008856, np.cbrt(xyz), 7.787 * xyz + 16.0 / 116.0)
    L = np.where(xyz[..., 1] > 0.008856, 116.0 * f[..., 1] - 16.0, 903.3 * xyz[..., 1])
    a = 500.0 * (f[..., 0] - f[..., 1]) + 128.0
    b = 200.0 * (f[..., 1] - f[..., 2]) + 128.0
    return np.stack([L * 255.0 / 100.0, a, b], axis=-1)


def _delta_e_mask(rgb: np.ndarray, colour: Tuple[int, int, int], thr: float) -> np.ndarray:
    target = _lab8(np.array([[colour]], np.uint8))[0, 0]
    return np.sqrt(np.sum((_lab8(rgb) - target) ** 2, axis=2)) <= thr


# ── shapes ──────────────────────────────────────────────────────────────

def _close(mask: np.ndarray) -> np.ndarray:
    """A 3x3 closing that neither grows nor eats the image border."""
    s = np.ones((3, 3), bool)
    return ndimage.binary_erosion(ndimage.binary_dilation(mask, s, border_value=0), s, border_value=1)


def _largest_blob(mask: np.ndarray) -> Optional[np.ndarray]:
    """(x, y) of every pixel of the 8-connected component whose outline encloses
    the most area, or None. The outline runs through boundary pixel centres, so
    by Pick's theorem it encloses (filled pixels - boundary pixels / 2 - 1): two
    blobs of nearly equal size are ranked as their outlines rank them."""
    lab, n = ndimage.label(mask, structure=np.ones((3, 3), bool))
    if not n:
        return None
    best, best_area = 0, -np.inf
    for i, sl in enumerate(ndimage.find_objects(lab), 1):
        filled = np.pad(ndimage.binary_fill_holes(lab[sl] == i), 1)
        boundary = filled & ~ndimage.binary_erosion(filled, border_value=0)
        area = int(filled.sum()) - int(boundary.sum()) / 2 - 1
        if area > best_area:
            best, best_area = i, area
    ys, xs = np.nonzero(lab == best)
    return np.stack([xs, ys], axis=1).astype(np.float64)


def _cross(u: np.ndarray, v: np.ndarray) -> float:
    return float(u[0] * v[1] - u[1] * v[0])


def _hull(points: np.ndarray) -> np.ndarray:
    """Convex hull of pixel centres, counter-clockwise (Andrew's monotone chain)."""
    pts = np.unique(points, axis=0)
    if len(pts) < 3:
        return pts

    def half(seq):
        out: List[np.ndarray] = []
        for p in seq:
            while len(out) >= 2 and _cross(out[-1] - out[-2], p - out[-2]) <= 0:
                out.pop()
            out.append(p)
        return out
    lower, upper = half(pts), half(pts[::-1])
    return np.array(lower[:-1] + upper[:-1])


def _area_perimeter_centroid(poly: np.ndarray) -> Tuple[float, float, Tuple[float, float]]:
    if len(poly) < 3:
        return 0.0, 0.0, ((float(poly[:, 0].mean()), float(poly[:, 1].mean())) if len(poly) else (0.0, 0.0))
    x, y = poly[:, 0], poly[:, 1]
    xn, yn = np.roll(x, -1), np.roll(y, -1)
    cross = x * yn - xn * y
    a2 = float(cross.sum())
    perim = float(np.hypot(xn - x, yn - y).sum())
    if a2 == 0:
        return 0.0, perim, (float(x.mean()), float(y.mean()))
    return abs(a2) / 2, perim, (float(((x + xn) * cross).sum() / (3 * a2)), float(((y + yn) * cross).sum() / (3 * a2)))


def _distance_outside(poly: np.ndarray, pts: np.ndarray) -> np.ndarray:
    """0 for points inside the convex polygon (counter-clockwise), else the distance to its boundary."""
    if len(poly) < 3:
        return np.full(len(pts), np.inf)
    a, b = poly, np.roll(poly, -1, axis=0)
    ab = b - a
    ap = pts[:, None, :] - a[None]
    inside = np.all(ab[None, :, 0] * ap[..., 1] - ab[None, :, 1] * ap[..., 0] >= 0, axis=1)
    t = np.clip(np.einsum("nkd,kd->nk", ap, ab) / np.maximum(np.einsum("kd,kd->k", ab, ab), 1e-9), 0, 1)
    d = np.min(np.linalg.norm(ap - t[..., None] * ab[None], axis=2), axis=1)
    return np.where(inside, 0.0, d)


# ── per-cell state ──────────────────────────────────────────────────────

_RECAPTCHA_BLUE = (27, 115, 232)
# Two, not zero: the ringed rendering draws the white on the rim and fragments the teal. At 4px the phantom rate doubles for ~1 point of recall.
_HCAPTCHA_GLYPH_SLACK_PX = 2.0


def detect_selected_cells(image_path, grid_boxes):
    """([selected], [loading]) 1-based cells: reCAPTCHA's blue tick badge or hCaptcha's
    teal check marks a selection, reCAPTCHA's blue spinner a tile still loading."""
    img = _read_rgb(image_path)
    if img is None:
        return [], []
    sel, ld = [], []
    for i, box in enumerate(grid_boxes):
        cell = img[box[1]:box[3], box[0]:box[2]]
        if cell.size == 0:
            continue
        h_cell, w_cell = cell.shape[:2]
        tl = cell[0:int(h_cell * 0.4), 0:int(w_cell * 0.4)]
        if tl.size > 0 and _has_badge(tl, _RECAPTCHA_BLUE):
            sel.append(i + 1)
            continue
        tr = cell[0:max(8, int(h_cell * 0.22)), int(w_cell * 0.78):]
        if tr.size > 0 and _has_hcaptcha_check(tr):
            sel.append(i + 1)
            continue
        cntr = cell[int(h_cell * 0.3):int(h_cell * 0.7), int(w_cell * 0.3):int(w_cell * 0.7)]
        if cntr.size > 0 and _is_loading(cntr, _RECAPTCHA_BLUE):
            ld.append(i + 1)
    return sel, ld


def _crop_cell(image_path, grid_boxes, cell_number) -> Optional[np.ndarray]:
    img = _read_rgb(image_path)
    if img is None or cell_number < 1 or cell_number > len(grid_boxes):
        return None
    x1, y1, x2, y2 = grid_boxes[cell_number - 1]
    cell = img[y1:y2, x1:x2]
    return cell if cell.size else None


def is_empty_cell(image_path, grid_boxes, cell_number,
                  white_frac=0.97, l_thresh=92.0, chroma_thresh=6.0):
    cell = _crop_cell(image_path, grid_boxes, cell_number)
    if cell is None:
        return False
    lab = _lab8(cell)
    L = lab[:, :, 0] * (100.0 / 255.0)
    chroma = np.hypot(lab[:, :, 1] - 128.0, lab[:, :, 2] - 128.0)
    white = (L > l_thresh) & (chroma < chroma_thresh)
    return float(white.mean()) >= white_frac


def is_cell_opacity_changing(image_path_a, image_path_b, grid_boxes,
                             cell_number, change_thresh=0.02):
    a = _crop_cell(image_path_a, grid_boxes, cell_number)
    b = _crop_cell(image_path_b, grid_boxes, cell_number)
    if a is None or b is None or a.shape != b.shape:
        return False
    diff = np.abs(a.astype(np.int16) - b.astype(np.int16)).astype(np.float32)
    grey = diff @ np.array([0.299, 0.587, 0.114], np.float32)
    return float((grey > 30).mean()) > change_thresh


def _has_hcaptcha_check(roi):
    """The white glyph must BELONG to the teal mark: pixel counts alone called blue sky with a white pole a selection (74 phantoms over 3051 corners)."""
    if roi is None or roi.size == 0:
        return False
    px = roi.astype(np.int32)
    r, g, b = px[..., 0], px[..., 1], px[..., 2]
    # Deliberately loose: pinning the badge colour to a delta-E costs more real badges than it saves phantoms.
    teal = (b > 120) & (g > 80) & (r < 80) & (b - r > 60)
    white = (r > 220) & (g > 220) & (b > 220)
    if int(teal.sum()) < 8 or int(white.sum()) < 2:
        return False
    # Close first: the glyph cuts the disc into pieces, and the largest blob must be the whole mark.
    blob = _largest_blob(_close(teal))
    if blob is None:
        return False
    ys, xs = np.nonzero(white)
    near = _distance_outside(_hull(blob), np.stack([xs, ys], axis=1).astype(np.float64)) <= _HCAPTCHA_GLYPH_SLACK_PX
    return int(near.sum()) >= 2


def _has_badge(roi, rgb):
    mask = _delta_e_mask(roi, rgb, 8.0)
    if int(mask.sum()) <= roi.size * 0.003:
        return False
    blob = _largest_blob(_close(mask))
    if blob is None:
        return False
    area, perim, (cx, cy) = _area_perimeter_centroid(_hull(blob))
    if perim == 0 or (4 * np.pi * area / (perim * perim)) < 0.8:
        return False
    return not (area == 0 or cx > roi.shape[1] * 0.7 or cy > roi.shape[0] * 0.7)


def _is_loading(roi, rgb):
    if roi.size == 0:
        return False
    return 0.05 < float(_delta_e_mask(roi, rgb, 12.0).mean()) < 0.6


def get_numbered_grid_overlay(image_path, grid_boxes, output_path=None):
    ov = [{"bbox": [b[0], b[1], b[2] - b[0], b[3] - b[1]], "number": i + 1, "color": "#FF0000", "box_style": "solid"}
          for i, b in enumerate(grid_boxes)]
    if output_path is None:
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tf:
            output_path = tf.name
    add_overlays_to_image(image_path, ov, output_path=output_path, label_position=LabelPosition.TOP_RIGHT)
    return output_path
