"""Track the part of a slide captcha that the handle moves, and say where to put the handle next.

The model names three points: the handle, a point on what the handle moves, and where that point belongs. This
module turns them into a closed loop without knowing anything about the vendor: no selector, no handle-to-piece
ratio, no assumption about whether the handle slides the piece or turns it.

1. `segment` finds WHAT moves: optical flow from the shot at the press to the shot after a small probe, kept only
   where it agrees with the flow back, split into connected parts. Flow spreads across flat ground, so one part can
   hold the piece AND the knob below it: each part is cut, under each distinct motion in it, to the pixels that
   motion carries exactly onto the probe, and split into bodies cored on pixels that actually changed. The body
   under the model's point is the object; without one, the largest body that is not the handle. Flow cannot follow a
   piece that looks like the ground it moves over, so around the model's point every small shift is also tested
   directly, and the body the best one explains is a candidate too.
2. The probe also says HOW the handle drives it: a SLIDE (a shift) or a TURN (about a pivot it fits). A handle does
   one or the other, and fitting both from a short probe lets a half-degree of noise grow into a ten-degree turn by
   the far end of the track.
3. `measure` finds where the object is now. A piece on a rail is looked for only along its rail through rest, level
   unless the probe rose by more than it can be read to, by the share of its face that lands on its own value, ties
   broken by the prediction; anything else by template matching over its own mask near the prediction. Either way
   the exact warp is then scored to a fraction of a pixel, so a busy board or an animated badge elsewhere cannot
   pull it.
4. `plan` fits the motion as a straight line in the handle's travel and picks the travel that brings the model's
   point closest to its goal.

All coordinates are SHOT pixels; the caller converts to CSS with its own device scale.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple, Union

import numpy as np
from PIL import Image as PILImage
from scipy import fft, ndimage

Image = Union[str, np.ndarray]
Point = Tuple[float, float]
# (theta in degrees, tx, ty) about the object's centroid c0: p' = R(theta)(p - c0) + c0 + t. Positive theta turns
# clockwise on screen, since image y points down.
Params = Tuple[float, float, float]
Offset = Union[float, Sequence[float]]

SLIDE = "slide"
TURN = "turn"

# Below this a pixel is still: the flow (`_dense_flow`) on a static textured board stays well under it.
_MOVING_PX = 0.5
# Forward-backward disagreement allowed, absolute and as a fraction of the motion: what fails it is ground the
# object covered or uncovered, which has no counterpart in the other shot.
_FB_ABS_PX = 0.8
_FB_REL = 0.25
# Grey levels within which carrying a pixel with the object's own motion must reproduce the probe for the pixel to
# be the object's. Dense flow spreads the object's flow several pixels onto the ground around it and the backward flow
# agrees, so only the pixels can say which side of the edge they are on. Comparing against standing still does not
# work: a smooth piece hardly changes when it moves, and an edge running along the motion not at all. Both shots
# are smoothed first, because a page composited at a fraction of a pixel softens the object's sharpest edge.
# Measured on the test boards: 95-98% of the piece, plus up to 4% featureless ground hugging its edge, which looks
# the same carried or still and so cannot be told apart by any pixel.
_CARRY_GREY = 6.0
_CARRY_SMOOTH = 1.0
# The dense flow (`_dense_flow`) is fitted on the pyramid level whose short side is the first at or under
# `_FLOW_SIDE` px, so a device-scale shot is followed at the same detail as a plain one; coarser levels, down to
# `_FLOW_MIN_SIDE`, catch motion larger than the window. Each pixel's motion is fitted over a Gaussian window
# (sigma, px of the level) in `_FLOW_PASSES` passes per level, damped by `_FLOW_DAMP` (grey^2 per px^2) so that flat
# ground, which shows no motion, keeps what the level above gave it.
_FLOW_SIDE = 200
_FLOW_MIN_SIDE = 24
_FLOW_WINDOW = 2.0
_FLOW_PASSES = 3
_FLOW_DAMP = 1.0
# A part smaller than this is flow noise on an edge, not something the handle moves.
_MIN_PART_PX = 25
_MIN_PART_FRACTION = 1e-4
# How far the model's point may sit outside every moving part and still name the nearest one: it reads the piece
# off a screenshot taken before the press, and some widgets nudge the piece when it is grabbed.
_SEED_REACH_FRACTION = 0.06
_SEED_REACH_MIN_PX = 8.0
# Below this correlation the transform does not describe the object any more: report it lost, never a position.
_MIN_CORRELATION = 0.6
# The same for a piece on a rail, read by the share of its face (`_along_rail`) that lands within `_CARRY_GREY` of its
# own value: measured 0.07-0.12 where a piece left, 0.54-0.97 on it. It says lost, not which of two places: the best
# point along the rail is the reading, and on a flat face its neighbours a few pixels off score up to 0.85.
_MIN_SHARE = 0.4
# The smoothing that share is read through (sigma, px): enough to forgive a page's sub-pixel resampling, not so much
# that a flat piece's one-pixel rim, its only mark over ground of its own tone, is averaged into that ground.
_SHARE_SMOOTH = 0.5
# Peaks along a rail whose share is within this of the best are a tie the picture cannot break - a white piece over
# a white screen peaks at 0.73-0.76 all along 36 px of it (GeeTest) - and the motion's prediction breaks it instead.
_SHARE_TIE = 0.05
# The angle grid a turn is searched on, in degrees; the score's peak is interpolated between its points.
_TURN_STEP = 1.0
# The distinct shifts tried within one moving part: histogram bin (px), the share of the strongest peak another must
# reach to count, and how many are tried.
_MODE_BIN = 0.5
_MODE_SHARE = 0.15
_MODE_MAX = 3
# A body's core is the pixels that changed AND its motion explains, closed across gaps this wide (px); it keeps the
# explained ground within this reach of the core (px), the antialiased rim and the featureless ground hugging it.
_CORE_CLOSE = 5
_CORE_REACH = 2.0
# Passes of mask <-> motion refinement at most; each grows the mask by at most the pixel test's 3 px reach.
_REFINE_MAX = 8
# A seeded slide's motion searched directly (`_slid_at`): over this share of the shot's short side around the point,
# for shifts up to this share of it (at least 16 px) - a probe of 8 px at a handle ratio of up to 1.8 is 15.
_SLID_WINDOW = 0.15
_SLID_SHIFT = 0.08
# How well a probe's shift is read (px). A probe that rose or fell by less moved along x as the handle did: GeeTest's
# 8 px probe read 0.21 px of rise on a level rail, which carried along a probe-angled line put the seat 4.6 px off it
# by 170 px of travel, where a decoy was taken.
_PROBE_PRECISION = 0.5


class TrackingError(ValueError):
    """The object could not be found or followed; the message says which and why."""


@dataclass
class Segment:
    mask: np.ndarray            # uint8 0/1, the object in `first` coordinates
    centroid: Point             # c0, the point Params are taken about
    grabbed: bool               # the press is ON the object: the pointer carries it, in two dimensions
    kind: str                   # SLIDE or TURN: how the handle drives it
    pivot: Point                # the centre a TURN goes round; the centroid for a SLIDE
    probe: Params               # first -> probe, refined
    proven: np.ndarray          # uint8 0/1, the part of `mask` the probe proved is the object's: what is matched


@dataclass
class Sample:
    s: float
    params: Params


# ── geometry ─────────────────────────────────────────────────────────────────


def _rigid(params: Params, c0: Point) -> np.ndarray:
    """The 2x3 forward matrix of `params` about `c0`."""
    th, tx, ty = params
    r = math.radians(th)
    rot = np.array([[math.cos(r), -math.sin(r)], [math.sin(r), math.cos(r)]])
    b = np.array(c0) - rot @ np.array(c0) + np.array([tx, ty])
    return np.hstack([rot, b.reshape(2, 1)])


def _params_of(m: np.ndarray, c0: Point) -> Params:
    moved = m[:, :2] @ np.array(c0) + m[:, 2]
    return math.degrees(math.atan2(m[1, 0], m[0, 0])), float(moved[0] - c0[0]), float(moved[1] - c0[1])


def transform_point(params: Params, c0: Point, p: Point) -> Point:
    m = _rigid(params, c0)
    q = m[:, :2] @ np.array(p, dtype=float) + m[:, 2]
    return float(q[0]), float(q[1])


def _turn_about(theta: float, pivot: Point, c0: Point) -> Params:
    """A turn of `theta` about `pivot`, written about `c0`."""
    r = math.radians(theta)
    rot = np.array([[math.cos(r), -math.sin(r)], [math.sin(r), math.cos(r)]])
    t = (rot - np.eye(2)) @ (np.array(c0) - np.array(pivot))
    return theta, float(t[0]), float(t[1])


def _kabsch(src: np.ndarray, dst: np.ndarray, c0: Point) -> Params:
    """Best rigid fit of point pairs, as params about `c0`."""
    cs, cd = src.mean(axis=0), dst.mean(axis=0)
    h = (src - cs).T @ (dst - cd)
    th = math.atan2(h[0, 1] - h[1, 0], h[0, 0] + h[1, 1])
    rot = np.array([[math.cos(th), -math.sin(th)], [math.sin(th), math.cos(th)]])
    t = cd - np.array(c0) - rot @ (cs - np.array(c0))
    return math.degrees(th), float(t[0]), float(t[1])


def _inverse(m: np.ndarray) -> np.ndarray:
    """The 2x3 matrix that undoes `m`; a pure shift stays one exactly, which `_warp` reads off slices."""
    (p, q), (u, v) = m[:, :2]
    det = p * v - q * u
    inv = np.array([[v, -q], [-u, p]]) / det
    return np.hstack([inv, -(inv @ m[:, 2])[:, None]])


def _from(m: np.ndarray, x0: int, y0: int) -> np.ndarray:
    """`m` for a crop whose top-left is (x0, y0): its output pixel (x, y) is the shot's (x + x0, y + y0)."""
    out = m.astype(float)
    out[:, 2] += m[:, :2] @ np.array([x0, y0], dtype=float)
    return out


# ── images and masks ─────────────────────────────────────────────────────────


def _gray(img: Image) -> np.ndarray:
    """A shot as 8-bit grey: a path is read from disk, an array is taken as BGR, the order the drivers' own
    renders use. Both convert with the same BT.601 weights."""
    if isinstance(img, str):
        try:
            with PILImage.open(img) as f:
                return np.asarray(f.convert("L"), dtype=np.uint8)
        except OSError as exc:
            raise TrackingError(f"unreadable image: {img}") from exc
    a = np.asarray(img)
    if a.ndim == 3:
        a = np.rint(a[..., :3].astype(np.float32) @ np.float32([0.114, 0.587, 0.299]))
    return np.ascontiguousarray(a, dtype=np.uint8)


def _smooth(img: np.ndarray, sigma: float) -> np.ndarray:
    return ndimage.gaussian_filter(img.astype(np.float32), sigma, mode="mirror")


def _warp(img: np.ndarray, m: np.ndarray, shape: Tuple[int, int], order: int = 1,
          mode: str = "constant") -> np.ndarray:
    """`img` sampled at `m` applied to every output pixel: out(x, y) = img(m (x, y, 1)), as float32. Outside the
    image is 0 (`constant`) or the nearest edge pixel (`nearest`); `order` 1 is bilinear, 0 the nearest pixel. A
    third axis, if any, is channels warped alike.

    Sampled by hand rather than through `scipy.ndimage.affine_transform`, which is several times slower at the
    sizes the loop warps hundreds of times per look.
    """
    h, w = shape
    hi, wi = img.shape[:2]
    if m[0, 0] == 1 and m[1, 1] == 1 and m[0, 1] == 0 and m[1, 0] == 0:
        tx, ty = (math.floor(t + 0.5) if order == 0 else t for t in m[:, 2])
        ix, iy = math.floor(tx), math.floor(ty)
        if ix >= 0 and iy >= 0 and ix + w + 1 <= wi and iy + h + 1 <= hi:
            # A shift that stays inside the image is a blend of four slices.
            part = img[iy:iy + h + 1, ix:ix + w + 1].astype(np.float32)
            fx, fy = np.float32(tx - ix), np.float32(ty - iy)
            rows = part[:, :w] * (1 - fx) + part[:, 1:] * fx
            return rows[:h] * (1 - fy) + rows[1:] * fy
    xs, ys = np.arange(w, dtype=np.float64), np.arange(h, dtype=np.float64)[:, None]
    x, y = m[0, 0] * xs + m[0, 1] * ys + m[0, 2], m[1, 0] * xs + m[1, 1] * ys + m[1, 2]
    if order == 0:
        xi, yi = np.floor(x + 0.5).astype(np.intp), np.floor(y + 0.5).astype(np.intp)
        out = img[np.clip(yi, 0, hi - 1), np.clip(xi, 0, wi - 1)].astype(np.float32)
        if mode == "constant":
            out[(xi < 0) | (xi >= wi) | (yi < 0) | (yi >= hi)] = 0
        return out
    if mode == "nearest":
        x, y = np.clip(x, 0, wi - 1), np.clip(y, 0, hi - 1)
    else:
        x, y = np.clip(x, -1, wi), np.clip(y, -1, hi)
    x0, y0 = np.floor(x), np.floor(y)
    # Only the part of the image the samples read is copied, with a pixel of border all round (two after) so every
    # corner a sample reads exists: the edge's own value, or 0 past the image.
    cx, cy = max(int(x0.min()), 0), max(int(y0.min()), 0)
    src = img[cy:min(int(y0.max()) + 2, hi), cx:min(int(x0.max()) + 2, wi)].astype(np.float32)
    border = ((1, 2), (1, 2)) + ((0, 0),) * (src.ndim - 2)
    pad = np.pad(src, border, mode="edge") if mode == "nearest" else np.pad(src, border)
    fx, fy = ((v - v0).astype(np.float32).reshape(v.shape + (1,) * (src.ndim - 2)) for v, v0 in ((x, x0), (y, y0)))
    stride = src.shape[1] + 3
    i = (y0.astype(np.intp) - cy + 1) * stride + x0.astype(np.intp) - cx + 1
    flat = pad.reshape((-1,) + src.shape[2:])
    top = flat.take(i, axis=0) * (1 - fx) + flat.take(i + 1, axis=0) * fx
    bottom = flat.take(i + stride, axis=0) * (1 - fx) + flat.take(i + stride + 1, axis=0) * fx
    return top * (1 - fy) + bottom * fy


# Every step that tests pixels near a mask works on the mask's box grown by this (px): past the smoothing's reach
# (4 sigma of `_CARRY_SMOOTH`) and every closing's, so the crop gives exactly what the whole shot would.
_MARGIN = 8


def _region(mask: np.ndarray, margin: int = _MARGIN) -> Tuple[slice, slice]:
    """The rows and columns of `mask`'s bounding box grown by `margin`, within the shot."""
    rows, cols = np.flatnonzero(mask.any(axis=1)), np.flatnonzero(mask.any(axis=0))
    h, w = mask.shape
    return (slice(max(int(rows[0]) - margin, 0), min(int(rows[-1]) + 1 + margin, h)),
            slice(max(int(cols[0]) - margin, 0), min(int(cols[-1]) + 1 + margin, w)))


def _paste(crop: np.ndarray, at: Tuple[slice, slice], shape: Tuple[int, int]) -> np.ndarray:
    out = np.zeros(shape, crop.dtype)
    out[at] = crop
    return out


def _grow(mask: np.ndarray, size: int) -> np.ndarray:
    """Dilation by a `size` square; the border adds nothing."""
    return ndimage.maximum_filter(mask.astype(np.uint8), size, mode="nearest")


def _shrink(mask: np.ndarray, size: int) -> np.ndarray:
    """Erosion by a `size` square; the border removes nothing."""
    return ndimage.minimum_filter(mask.astype(np.uint8), size, mode="nearest")


def _open(mask: np.ndarray, size: int) -> np.ndarray:
    return _grow(_shrink(mask, size), size)


def _close(mask: np.ndarray, size: int) -> np.ndarray:
    return _shrink(_grow(mask, size), size)


_EIGHT = np.ones((3, 3), bool)


def _components(mask: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    """8-connected parts: the label image and each label's area (label 0 is the background)."""
    labels, _ = ndimage.label(mask, structure=_EIGHT)
    return labels, np.bincount(labels.ravel())


def _within(mask: np.ndarray, radius: float) -> np.ndarray:
    """The pixels within `radius` (Euclidean, px) of `mask`."""
    r = int(math.floor(radius))
    yy, xx = np.mgrid[-r:r + 1, -r:r + 1]
    return ndimage.binary_dilation(mask.astype(bool), xx * xx + yy * yy <= radius * radius)


def _pair(first: Image, other: Image) -> Tuple[np.ndarray, np.ndarray]:
    a, b = _gray(first), _gray(other)
    if a.shape != b.shape:
        raise TrackingError(f"shots differ in size: {a.shape} vs {b.shape}")
    return a, b


def _centroid(mask: np.ndarray) -> Point:
    ys, xs = np.nonzero(mask)
    return float(xs.mean()), float(ys.mean())


def _fill(part: np.ndarray) -> np.ndarray:
    """The part with its holes filled: a turning disc's centre barely moves and a flat patch carries no flow.

    A hole is ground the part encloses, 4-connected as ground next to an 8-connected part is; labelling it once is
    much faster than `binary_fill_holes`' repeated dilation.
    """
    ground, _ = ndimage.label(np.pad(~part.astype(bool), 1, constant_values=True))
    return (ground[1:-1, 1:-1] != ground[0, 0]).astype(np.uint8)


def _inside(part: np.ndarray, p: Point) -> float:
    """How far `p` lies inside the outline of `part`'s largest piece (px): negative outside it.

    The outline runs through the centres of the piece's rim pixels, those with a background pixel beside them.
    """
    labels, areas = _components(part)
    largest = labels == int(np.argmax(areas[1:])) + 1
    at = _region(largest, 1)
    piece = _fill(largest[at]).astype(bool)
    ys, xs = np.nonzero(piece & ~ndimage.binary_erosion(piece, border_value=1))
    ys, xs = ys + at[0].start, xs + at[1].start
    d = float(np.sqrt(((xs - p[0]) ** 2 + (ys - p[1]) ** 2).min()))
    x, y = int(round(p[0])) - at[1].start, int(round(p[1])) - at[0].start
    on = 0 <= y < piece.shape[0] and 0 <= x < piece.shape[1] and piece[y, x]
    return d if on else -d


def _carried(a: np.ndarray, b: np.ndarray, part: np.ndarray, params: Params, c0: Point,
             min_area: float, along: Optional[Tuple[float, float]] = None) -> np.ndarray:
    """The pixels around `part` that the object's own motion (`params` about `c0`) carries onto the probe.

    `along`, a slide's shift: what changed is joined along it (`_spans`) before the unchanged ground is trimmed.
    """
    shape = a.shape
    at = _region(part, 3 + _MARGIN)     # 3: the reach of the 7x7 grow below
    landed = _warp(b, _from(_rigid(params, c0), at[1].start, at[0].start), a[at].shape, mode="nearest")
    a, b, part = a[at], b[at], part[at]
    grow = _grow(part, 7) > 0
    sa = _smooth(a, _CARRY_SMOOTH)
    explained = grow & (np.abs(_smooth(landed, _CARRY_SMOOTH) - sa) < _CARRY_GREY)
    # Ground that happens to match itself one shift along leaves thin threads, never a body.
    labels, areas = _components(_open(explained, 5))
    hits = np.bincount(labels[part.astype(bool)], minlength=len(areas))
    ours = [i for i in range(1, len(areas)) if hits[i] > 0.5 * areas[i]]
    keep = _close(np.isin(labels, ours), 5)
    # The opening also shaves the object's rim, its sharpest edge; take back the rim pixels the motion explains.
    keep = keep | (_grow(keep, 3).astype(bool) & explained).astype(np.uint8)
    # Ground the shot shows unchanged is explained by standing still as well as by the motion: it is the object's
    # only where it lies within reach of what changed, or inside its outline.
    core = keep.astype(bool) & (np.abs(_smooth(b, _CARRY_SMOOTH) - sa) >= _CARRY_GREY)
    if along is not None:
        core = _spans(core, keep, along)
    core = _close(core, _CORE_CLOSE)
    keep = _fill(keep.astype(bool) & _within(core, _CORE_REACH) | core.astype(bool))
    if keep.sum() < min_area:
        raise TrackingError("the moving part has no texture or edge that its own motion explains")
    return _paste(keep, at, shape)


# ── what moves ───────────────────────────────────────────────────────────────


def _dense_flow(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Where each pixel of `a` went in `b`, as an (h, w, 2) field of (dx, dy) in shot pixels: pyramidal Lucas-Kanade.

    Each level starts from the motion of the level above, doubled, and refines it by fitting, over a Gaussian
    window, the one shift that best lays `b` back on `a`.
    """
    pa, pb = [a.astype(np.float32)], [b.astype(np.float32)]
    while min(pa[-1].shape) // 2 >= _FLOW_MIN_SIDE:
        pa.append(_smooth(pa[-1], 1.0)[::2, ::2])
        pb.append(_smooth(pb[-1], 1.0)[::2, ::2])
    finest = next(i for i, level in enumerate(pa) if min(level.shape) <= _FLOW_SIDE or i == len(pa) - 1)
    flow = np.zeros(pa[-1].shape + (2,), np.float32)
    for la, lb in reversed(list(zip(pa, pb))[finest:]):
        flow = _upsampled(flow, la.shape)
        h, w = la.shape
        ys, xs = np.mgrid[0:h, 0:w].astype(np.float32)
        ga_y, ga_x = np.gradient(la)
        for _ in range(_FLOW_PASSES):
            lw = ndimage.map_coordinates(lb, [ys + flow[..., 1], xs + flow[..., 0]], order=1, mode="nearest")
            gw_y, gw_x = np.gradient(lw)
            gx, gy, gt = 0.5 * (ga_x + gw_x), 0.5 * (ga_y + gw_y), lw - la
            sxx, syy = _smooth(gx * gx, _FLOW_WINDOW) + _FLOW_DAMP, _smooth(gy * gy, _FLOW_WINDOW) + _FLOW_DAMP
            sxy, sxt, syt = (_smooth(v, _FLOW_WINDOW) for v in (gx * gy, gx * gt, gy * gt))
            det = sxx * syy - sxy * sxy
            flow[..., 0] -= (syy * sxt - sxy * syt) / det
            flow[..., 1] -= (sxx * syt - sxy * sxt) / det
    return _upsampled(flow, a.shape)


def _upsampled(flow: np.ndarray, shape: Tuple[int, int]) -> np.ndarray:
    """A flow field resampled to `shape`, its vectors scaled with it."""
    if flow.shape[:2] == tuple(shape):
        return flow
    k = shape[1] / flow.shape[1]
    zoom = (shape[0] / flow.shape[0], k)
    return k * np.stack([ndimage.zoom(flow[..., i], zoom, order=1, mode="nearest", grid_mode=True)
                         for i in (0, 1)], axis=-1).astype(np.float32)


def _near_handle(handle: Optional[Point], h: int, w: int) -> Optional[np.ndarray]:
    """The few pixels around the press point, or None without one."""
    if handle is None:
        return None
    out = np.zeros((h, w), bool)
    x, y = min(max(int(round(handle[0])), 0), w - 1), min(max(int(round(handle[1])), 0), h - 1)
    out[max(y - 2, 0):y + 3, max(x - 2, 0):x + 3] = True
    return out


def _flow_modes(flow: np.ndarray, weight: np.ndarray) -> List[Tuple[float, float]]:
    """The distinct shifts in a part's flow, strongest first, counted where the picture has an edge to show them.

    Flat ground carries no evidence of motion, only flow smoothed across it, so it is weighted by its gradient: zero.
    A piece and the knob under it move by different amounts unless the handle drives the piece 1:1, and each shows
    as its own peak.
    """
    lo = np.floor(flow.min(axis=0)) - _MODE_BIN
    hi = np.ceil(flow.max(axis=0)) + _MODE_BIN
    bins = [max(1, int((hi[i] - lo[i]) / _MODE_BIN)) for i in (0, 1)]
    hist, ex, ey = np.histogram2d(flow[:, 0], flow[:, 1], bins=bins, range=[[lo[0], hi[0]], [lo[1], hi[1]]],
                                  weights=weight)
    for axis in (0, 1):
        hist = ndimage.correlate1d(hist, [0.25, 0.5, 0.25], axis=axis, mode="mirror")
    peaks = (hist == ndimage.maximum_filter(hist, 5, mode="nearest")) & (hist >= _MODE_SHARE * hist.max())
    ix, iy = np.nonzero(peaks)
    order = np.argsort(-hist[ix, iy])[:_MODE_MAX]
    return [(float((ex[i] + ex[i + 1]) / 2), float((ey[j] + ey[j + 1]) / 2)) for i, j in zip(ix[order], iy[order])]


def _spans(core: np.ndarray, cut: np.ndarray, shift: Tuple[float, float]) -> np.ndarray:
    """`core` joined across the cut along the motion: each run of the cut in the motion's direction filled from its
    first core pixel to its last.

    Moved along its length, a flat body changes only at its leading and trailing edges, which face each other along
    the motion across its own unchanged middle. Ground bridging two bodies lies across the motion from them instead,
    so this joins the halves of one body and never two bodies.
    """
    if not cut.any():
        return core.astype(bool)
    at = _region(cut, 1)
    shape = core.shape
    core, cut = core[at], cut[at]
    h, w = core.shape
    # The turn that lays the motion along +x, centred in a square that holds the whole cut at any angle.
    phi = math.atan2(shift[1], shift[0])
    rot = np.array([[math.cos(phi), math.sin(phi)], [-math.sin(phi), math.cos(phi)]])
    side = int(math.ceil(math.hypot(h, w)))
    turn = np.hstack([rot, (np.array([side / 2, side / 2]) - rot @ np.array([w / 2, h / 2]))[:, None]])
    c, k = (_warp(m, _inverse(turn), (side, side), order=0) > 0 for m in (core, cut))
    run = np.cumsum(np.diff(np.pad(k, ((0, 0), (1, 0))).astype(np.int8), axis=1) == 1, axis=1) * k
    out = np.zeros_like(c)
    for y in np.nonzero(c.any(axis=1))[0]:
        for r in np.unique(run[y][c[y]]):
            xs = np.nonzero(c[y] & (run[y] == r))[0]
            out[y, xs[0]:xs[-1] + 1] = True
    back = _warp(out, turn, (h, w), order=0)
    return _paste(core.astype(bool) | ((back > 0) & cut.astype(bool)), at, shape)


def _split(a: np.ndarray, b: np.ndarray, cut: np.ndarray, min_area: float,
           shift: Optional[Tuple[float, float]] = None) -> List[np.ndarray]:
    """The separate bodies in a cut, which flat ground may join.

    Featureless ground is explained by ANY motion, the object's included, so it passes the pixel test and can bridge
    a piece to the knob under it. Only pixels that changed between the shots are evidence of a body: each body is
    cored on those, joined along a slide's motion (`_spans`), and keeps the explained ground within reach of its own
    core and nearer to it than to any other.
    """
    at = _region(cut)
    shape = cut.shape
    a, b, cut = a[at], b[at], cut[at]
    changed = np.abs(_smooth(b, _CARRY_SMOOTH) - _smooth(a, _CARRY_SMOOTH)) >= _CARRY_GREY
    core = cut.astype(bool) & changed
    if shift is not None:
        core = _spans(core, cut, shift)
    labels, areas = _components(_fill(_close(core, _CORE_CLOSE)))
    cores = [labels == i for i in range(1, len(areas)) if areas[i] >= min_area]
    if not cores:
        return []
    dist = np.stack([ndimage.distance_transform_edt(~c) for c in cores])
    owner = dist.argmin(axis=0)
    near = dist.min(axis=0) <= _CORE_REACH
    bodies = [_fill((cut.astype(bool) & near & (owner == i)) | cores[i]) for i in range(len(cores))]
    return [_paste(body, at, shape) for body in bodies if body.sum() >= min_area]


def _bodies(a: np.ndarray, b: np.ndarray, fwd: np.ndarray, moving: np.ndarray, part: np.ndarray, xs: np.ndarray,
            ys: np.ndarray, min_area: float) -> List[Tuple[np.ndarray, Params, str, Point]]:
    """Every rigid body in one moving part: `(mask, params about its centroid, SLIDE or TURN, centroid)`.

    A part is what the FLOW joined, and flow spreads across flat ground: a piece resting just above its track comes
    out joined to the knob below it, though the pixels between them never changed. So each distinct motion in the
    part is tried, the part is cut to the pixels that motion carries exactly onto the probe, and what is left is
    split into the bodies it holds, each then measured on its own.
    """
    # The flow's own part has leaked onto still ground, and the flow is smoothed toward zero at its edge: the
    # interior alone says how it moved, to a tenth of a pixel.
    inner = _shrink(_fill(part), 9).astype(bool) & (moving > 0)
    if inner.sum() < min_area:
        inner = part & (moving > 0)
    src = np.stack([xs[inner], ys[inner]], axis=1)
    c_part = _centroid(part)
    rough = _kabsch(src, src + fwd[inner], c_part)

    # How far the turn moves the object's pixels against how far it shifts them: a handle does one or the other,
    # and the probe is the only evidence of which.
    radius = float(np.sqrt(((src - np.array(c_part)) ** 2).sum(axis=1).mean()))
    if radius * abs(math.radians(rough[0])) > math.hypot(rough[1], rough[2]):
        kind, angles, guesses = TURN, _angles(rough[0], 3.0), [rough]
    else:
        g = _smooth(a, 1.0)
        edge = ndimage.sobel(g, axis=1, mode="mirror") ** 2 + ndimage.sobel(g, axis=0, mode="mirror") ** 2
        kind, angles = SLIDE, None
        guesses = [(0.0, tx, ty) for tx, ty in _flow_modes(fwd[inner], edge[inner])]
    return _refined(a, b, part, inner, c_part, guesses, kind, angles, min_area)


def _refined(a: np.ndarray, b: np.ndarray, part: np.ndarray, inner: np.ndarray, c_part: Point,
             guesses: Sequence[Params], kind: str, angles: Optional[List[float]],
             min_area: float) -> List[Tuple[np.ndarray, Params, str, Point]]:
    """The bodies `part` holds under each guessed motion, each mask and motion refined against the other."""
    out: List[Tuple[np.ndarray, Params, str, Point]] = []
    for guess in guesses:
        # The pixel test needs the motion to a fraction of a pixel or every sharp edge fails it; the mask and the
        # motion then sharpen each other.
        try:
            exact, _ = _locate(a, b, inner.astype(np.uint8), c_part, guess, 3.0, angles)
            cut = _carried(a, b, part, exact, c_part, min_area, exact[1:] if kind == SLIDE else None)
        except TrackingError:
            continue
        for mask in _split(a, b, cut, min_area, exact[1:] if kind == SLIDE else None):
            c = _centroid(mask)
            params = _params_of(_rigid(exact, c_part), c)
            try:
                # Each pass reaches a few pixels past the last mask, so a body the flow covered only in part
                # takes several to come out whole; it stops when a pass adds nothing.
                for _ in range(_REFINE_MAX):
                    params, _ = _locate(a, b, mask, c, params, 3.0, angles and _angles(params[0], 2.0))
                    grown = _carried(a, b, mask, params, c, min_area, params[1:] if kind == SLIDE else None)
                    settled = bool((grown == mask).all())
                    mask = grown
                    if settled:
                        break
            except TrackingError:
                continue
            out.append((mask, params, kind, c))
    if not out:
        raise TrackingError("the moving part has no texture or edge that its own motion explains")
    return out


def _slid_at(a: np.ndarray, b: np.ndarray, seed: Point, min_area: float) -> List[Tuple[np.ndarray, Params, str, Point]]:
    """The body under `seed` found by its motion alone: every whole-pixel shift within reach tried around the point,
    the one that explains the most pixels the probe changed taken, and the part it explains refined like a flow part.

    Dense flow needs the object to look unlike the ground it moves over. A piece cut from the photo it rests on, or
    a pale piece on pale ground, does not: the flow there failed its own forward-backward check almost everywhere
    (Tencent and GeeTest, seed 6), and no part was left at the point. Testing the rigid motion itself asks only that
    the pixels the probe changed be explained, which a piece's edges always are.
    """
    h, w = a.shape
    reach, reach_t = int(_SLID_WINDOW * min(h, w)), max(16, int(_SLID_SHIFT * min(h, w)))
    x, y = int(round(seed[0])), int(round(seed[1]))
    x0, x1 = max(reach_t, x - reach), min(w - reach_t, x + reach)
    y0, y1 = max(reach_t, y - reach), min(h - reach_t, y + reach)
    if x1 - x0 < 3 or y1 - y0 < 3:
        return []
    sa, sb = _smooth(a, _CARRY_SMOOTH), _smooth(b, _CARRY_SMOOTH)
    here = sa[y0:y1, x0:x1]
    changed = np.abs(sb[y0:y1, x0:x1] - here) >= _CARRY_GREY
    best, shift = 0, (0, 0)
    for ty in range(-reach_t, reach_t + 1):
        for tx in range(-reach_t, reach_t + 1):
            if tx or ty:
                n = int((changed & (np.abs(sb[y0 + ty:y1 + ty, x0 + tx:x1 + tx] - here) < _CARRY_GREY)).sum())
                if n > best:
                    best, shift = n, (tx, ty)
    if best < min_area:
        return []
    tx, ty = shift
    explained = np.zeros((h, w), np.uint8)
    explained[y0:y1, x0:x1] = changed & (np.abs(sb[y0 + ty:y1 + ty, x0 + tx:x1 + tx] - here) < _CARRY_GREY)
    labels, areas = _components(_close(explained, _CORE_CLOSE))
    dist = {i: _inside(labels == i, seed) for i in range(1, len(areas)) if areas[i] >= min_area}
    if not dist:
        return []
    part = _fill((labels == max(dist, key=dist.get)).astype(np.uint8)).astype(bool)
    try:
        return _refined(a, b, part, part, _centroid(part), [(0.0, float(tx), float(ty))], SLIDE, None, min_area)
    except TrackingError:
        return []


def segment(first: Image, probe: Image, seed: Optional[Point] = None, handle: Optional[Point] = None,
            goal: Optional[Point] = None) -> Segment:
    """The object the probe moved, in `first` coordinates, and how the handle drives it.

    With `seed`, the body under it (or nearest to it, within reach), from the flow's parts or found by its motion
    alone (`_slid_at`). Without one, the largest body that is not the handle: what a generation-2 answer, which
    names only the goal, has to settle for. That answer still says where the piece rests: the driver slides the
    handle along x, so a piece it moves onto `goal` starts on the goal's row, and with `goal` the bodies are looked
    for along that row too and only one on it is taken.
    """
    a, b = _pair(first, probe)
    h, w = a.shape
    fwd, bwd = _dense_flow(a, b), _dense_flow(b, a)
    ys, xs = np.mgrid[0:h, 0:w].astype(np.float32)
    at = [ys + fwd[..., 1], xs + fwd[..., 0]]
    back = np.stack([ndimage.map_coordinates(bwd[..., i], at, order=1, mode="nearest") for i in (0, 1)], axis=-1)
    mag = np.hypot(fwd[..., 0], fwd[..., 1])
    fb = np.hypot(fwd[..., 0] + back[..., 0], fwd[..., 1] + back[..., 1])
    moving = _close(_open((mag > _MOVING_PX) & (fb < np.maximum(_FB_ABS_PX, _FB_REL * mag)), 3), 5)

    labels, areas = _components(moving)
    min_area = max(_MIN_PART_PX, _MIN_PART_FRACTION * h * w)
    parts = [i for i in range(1, len(areas)) if areas[i] >= min_area]
    if not parts and seed is None and goal is None:
        raise TrackingError("nothing moved between the press and the probe")

    def label_at(p: Optional[Point]) -> int:
        if p is None:
            return 0
        x, y = int(round(p[0])), int(round(p[1]))
        return int(labels[y, x]) if 0 <= x < w and 0 <= y < h else 0

    reach = max(_SEED_REACH_MIN_PX, _SEED_REACH_FRACTION * min(h, w))
    if seed is not None:
        pick = label_at(seed) if label_at(seed) in parts else 0
        if not pick and parts:
            inside = {i: _inside(labels == i, seed) for i in parts}
            near = max(inside, key=inside.get)
            pick = near if -inside[near] <= reach else 0
        candidates = [pick] if pick else []
    else:
        # Every part, the handle's own included: see `_bodies` for why the piece can share it.
        candidates = sorted(parts, key=lambda i: -areas[i])

    found: List[Tuple[np.ndarray, Params, str, Point]] = []
    why: Optional[TrackingError] = None
    for pick in candidates:
        try:
            found += _bodies(a, b, fwd, moving, labels == pick, xs, ys, min_area)
        except TrackingError as exc:
            why = why or exc
    held = _near_handle(handle, h, w)
    if seed is not None:
        # Flow cannot follow a piece that looks like the ground it moves over; its motion, tested directly, can.
        found += _slid_at(a, b, seed, min_area)
        if not found:
            raise why or TrackingError(f"nothing moved within {reach:.0f}px of the point on the object "
                                       f"({seed[0]:.0f}, {seed[1]:.0f})")
        # The body under the model's point, else the nearest: it read the piece off a shot before the press.
        sx, sy = float(seed[0]), float(seed[1])
        mask, exact, kind, c_part = max(found, key=lambda f: _inside(f[0], (sx, sy)))
        off = -_inside(mask, (sx, sy))
        if off > reach:
            raise TrackingError(f"nothing moved within {reach:.0f}px of the point on the object "
                                f"({sx:.0f}, {sy:.0f}); the nearest moving body is {off:.0f}px away")
    else:
        if goal is not None:
            # Flow misses a piece that looks like the ground it moves over (see `_slid_at`); its row is known.
            step = max(1, int(_SLID_WINDOW * min(h, w)))
            for x in range(step, w - step + 1, step):
                found += _slid_at(a, b, (float(x), float(goal[1])), min_area)
        carried = [f for f in found if not (held is not None and (f[0].astype(bool) & held).any())]
        if goal is not None:
            carried = [f for f in carried if np.abs(np.nonzero(f[0])[0] - goal[1]).min() <= reach]
        if not carried:
            if why is not None and not found:
                raise why
            raise TrackingError("only the handle moved; nothing it carries was seen" if goal is None else
                                f"nothing that moved, but the handle, rests on the goal's row (y {goal[1]:.0f})")
        mask, exact, kind, c_part = max(carried, key=lambda f: int(f[0].sum()))
    c0 = _centroid(mask)
    exact = _params_of(_rigid(exact, c_part), c0)
    if kind == TURN:
        r = math.radians(exact[0])
        rot = np.array([[math.cos(r), -math.sin(r)], [math.sin(r), math.cos(r)]])
        # p' = R(p - c0) + c0 + t turns about the pivot q where (I - R)(q - c0) = t.
        q = np.array(c0) + np.linalg.solve(np.eye(2) - rot, np.array(exact[1:]))
        pivot = (float(q[0]), float(q[1]))
    else:
        pivot = c0

    grabbed = handle is not None and bool(_grow(mask, 5)[
        min(max(int(round(handle[1])), 0), h - 1), min(max(int(round(handle[0])), 0), w - 1)])
    probe, _ = _locate(a, b, mask, c0, exact, 3.0, _angles(exact[0], 2.0) if kind == TURN else None)
    return Segment(mask=mask, centroid=c0, grabbed=grabbed, kind=kind, pivot=pivot, probe=probe,
                   proven=_proven(a, b, mask, probe, c0, min_area))


def _proven(a: np.ndarray, b: np.ndarray, mask: np.ndarray, params: Params, c0: Point, min_area: float) -> np.ndarray:
    """The pixels of `mask` the probe can tell from the ground: those unlike the pixel one motion along.

    Where the picture is the same one motion along, the object moving and the ground staying put draw the same probe,
    so the mask's flat rim and any flat ground it swallowed are unproven. They are the object's extent (the fill
    needs them) but not its appearance: matched against a later shot, after the object has left that ground, a
    swallowed patch of dark cow is a template the object no longer carries.
    """
    at = _region(mask)
    smooth = _smooth(a, _CARRY_SMOOTH)
    along = _warp(smooth, _from(_rigid(params, c0), at[1].start, at[0].start), smooth[at].shape, mode="nearest")
    changed = np.abs(_smooth(b[at], _CARRY_SMOOTH) - smooth[at]) >= _CARRY_GREY
    # The mask's outermost pixel is ground the fill and the reach keep for the object's extent, nearly always; one
    # deeper is the object's own rim, which on a flat face is the only detail it has.
    body = _shrink(mask[at], 3).astype(bool)
    proven = (body & changed & (np.abs(along - smooth[at]) >= _CARRY_GREY)).astype(np.uint8)
    if proven.sum() < min_area:
        raise TrackingError("the probe moved the object too little to show which pixels are its own")
    return _paste(proven, at, a.shape)


# ── where it is now ──────────────────────────────────────────────────────────


def _turns(seg: Segment) -> bool:
    return seg.kind == TURN and not seg.grabbed


def _constrain(seg: Segment, p: Params) -> Params:
    """`p` reduced to the one motion the handle produces: a SLIDE never turns, a TURN never leaves its pivot."""
    if _turns(seg):
        return _turn_about(p[0], seg.pivot, seg.centroid)
    return 0.0, p[1], p[2]


def _rail(seg: Segment) -> Optional[Tuple[float, float]]:
    """The direction a SLIDE the handle drives along its track can move, as the probe showed it; None otherwise.

    A carried piece goes wherever the pointer does, and a turn has no line; a piece on a rail has only this one, so
    a match off it is something else in the picture that resembles it. The driver moves the handle along x, so the
    rail is x unless the probe rose or fell by more than it can be read to: a short probe's own noise, carried down
    the whole track, would put the far end of the rail pixels off the piece.
    """
    if seg.kind != SLIDE or seg.grabbed:
        return None
    n = math.hypot(seg.probe[1], seg.probe[2])
    if n == 0:
        return None
    if abs(seg.probe[2]) <= _PROBE_PRECISION:
        return (math.copysign(1.0, seg.probe[1]), 0.0)
    return (seg.probe[1] / n, seg.probe[2] / n)


def _angles(centre: float, reach: float) -> List[float]:
    n = max(1, int(math.ceil(reach / _TURN_STEP)))
    return [centre + _TURN_STEP * i for i in range(-n, n + 1)]


def _peak(res: np.ndarray) -> Tuple[float, float, float]:
    """The score map's best point to a fraction of a pixel (a parabola through each axis), and its score."""
    y, x = np.unravel_index(int(np.argmax(res)), res.shape)
    score = res[y, x]

    def vertex(lo: float, mid: float, hi: float) -> float:
        den = lo - 2 * mid + hi
        return 0.0 if den >= 0 else max(-0.5, min(0.5, 0.5 * (lo - hi) / den))

    dx = vertex(res[y, x - 1], res[y, x], res[y, x + 1]) if 0 < x < res.shape[1] - 1 else 0.0
    dy = vertex(res[y - 1, x], res[y, x], res[y + 1, x]) if 0 < y < res.shape[0] - 1 else 0.0
    return x + dx, y + dy, float(score)


def _match(a: np.ndarray, b: np.ndarray, mask: np.ndarray, c0: Point, p: Params,
           reach: int) -> Optional[Tuple[Params, float]]:
    """The object carried by `p`, matched against `b` within `reach` pixels: the shift that best seats it."""
    h, w = a.shape
    m = _rigid(p, c0)
    bx1, by1, bx2, by2 = _box(_corners(mask) @ m[:, :2].T + m[:, 2], w, h)
    if bx2 <= bx1 or by2 <= by1:
        return None
    # Only the box the carried mask can land in is warped; the template is its tight bounds within that.
    back = _from(_inverse(m), bx1, by1)
    wmask = _warp(mask, back, (by2 - by1, bx2 - bx1), order=0) > 0
    ys, xs = np.nonzero(wmask)
    if len(xs) < _MIN_PART_PX:
        return None
    warped = np.rint(_warp(a, back, wmask.shape))
    xs, ys = xs + bx1, ys + by1
    x1, y1, x2, y2 = int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1
    sx1, sy1, sx2, sy2 = max(0, x1 - reach), max(0, y1 - reach), min(w, x2 + reach), min(h, y2 + reach)
    if sx2 - sx1 < x2 - x1 or sy2 - sy1 < y2 - y1:
        return None
    tight = (slice(y1 - by1, y2 - by1), slice(x1 - bx1, x2 - bx1))
    px, py, score = _peak(_correlation(b[sy1:sy2, sx1:sx2], warped[tight], wmask[tight]))
    return (float(p[0]), float(p[1] + sx1 + px - x1), float(p[2] + sy1 + py - y1)), float(score)


def _correlation(img: np.ndarray, templ: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """Zero-mean normalized correlation of `templ` over `mask` at every place it fits in `img`; -1 where the window
    is flat and has no correlation.

    All three sums are of whole grey levels over a 0/1 mask, so they are whole numbers: rounding the FFT's results
    makes them exact, and a flat window's variance exactly zero rather than rounding noise that scores as a match.
    """
    i, t, m = img.astype(np.float64), templ.astype(np.float64), mask.astype(np.float64)
    n = m.sum()
    (ih, iw), (th, tw) = i.shape, t.shape
    shape = (fft.next_fast_len(ih + th - 1, real=True), fft.next_fast_len(iw + tw - 1, real=True))
    f_i, f_ii, f_m, f_tm = (fft.rfft2(x, shape) for x in (i, i * i, m[::-1, ::-1], (t * m)[::-1, ::-1]))

    def window(f: np.ndarray) -> np.ndarray:
        return np.rint(fft.irfft2(f, shape)[th - 1:ih, tw - 1:iw])

    s_i, s_ii, s_ti = window(f_i * f_m), window(f_ii * f_m), window(f_i * f_tm)
    s_t = float((t * m).sum())
    var_t = float((t * t * m).sum()) - s_t * s_t / n
    den = np.sqrt(np.maximum(var_t * (s_ii - s_i * s_i / n), 0.0))
    return np.where(den > 0, (s_ti - s_t * s_i / n) / np.where(den > 0, den, 1.0), -1.0)


def _score(a: np.ndarray, b: np.ndarray, mask: np.ndarray, c0: Point, p: Params) -> float:
    """Zero-mean correlation of the object carried exactly by `p` against `b`, over the object only."""
    h, w = a.shape
    m = _rigid(p, c0)
    x1, y1, x2, y2 = _box(_corners(mask) @ m[:, :2].T + m[:, 2], w, h)
    if x2 - x1 < 3 or y2 - y1 < 3:
        return -1.0
    shift = m.copy()
    shift[:, 2] -= (x1, y1)
    # Only the object's own box is read: outside it the mask is 0, and no pixel there is scored.
    at = _region(mask, 1)
    back = _inverse(shift)
    back[:, 2] -= (at[1].start, at[0].start)
    both = _warp(np.dstack([a[at], mask[at]]), back, (y2 - y1, x2 - x1))
    warped, inside = both[..., 0], both[..., 1] > 0.99
    if inside.sum() < _MIN_PART_PX:
        return -1.0
    u, v = warped[inside], b[y1:y2, x1:x2].astype(np.float32)[inside]
    u, v = u - u.mean(), v - v.mean()
    den = math.sqrt(float((u * u).sum() * (v * v).sum()))
    return float((u * v).sum() / den) if den > 0 else -1.0


def _corners(mask: np.ndarray) -> np.ndarray:
    rows, cols = _region(mask, 0)
    x1, y1, x2, y2 = cols.start, rows.start, cols.stop, rows.stop
    return np.float64([[x1, y1], [x2, y1], [x1, y2], [x2, y2]])


def _box(pts: np.ndarray, w: int, h: int) -> Tuple[int, int, int, int]:
    x1, y1 = np.floor(pts.min(axis=0)).astype(int) - 1
    x2, y2 = np.ceil(pts.max(axis=0)).astype(int) + 2
    return max(0, x1), max(0, y1), min(w, x2), min(h, y2)


def _polish(a: np.ndarray, b: np.ndarray, mask: np.ndarray, c0: Point, p: Params,
            pivot: Optional[Point]) -> Tuple[Params, float]:
    """The last fraction of a pixel (and of a degree), read from the exact warp's own score on a quarter grid.

    A template match can only shift whole pixels and guess between them; scoring the object warped by sub-pixel
    amounts asks the question directly, one axis at a time, with a parabola through the best quarter.
    """
    def at(q: List[float]) -> Params:
        return _turn_about(q[0], pivot, c0) if pivot is not None else (q[0], q[1], q[2])

    q = [p[0], p[1], p[2]]
    axes = [0] if pivot is not None else ([0, 1, 2] if p[0] else [1, 2])
    best = _score(a, b, mask, c0, at(q))
    for _ in range(2):
        for ax in axes:
            step = 0.25
            vals = []
            for k in (-2, -1, 0, 1, 2):
                trial = list(q)
                trial[ax] += k * step
                vals.append(_score(a, b, mask, c0, at(trial)))
            k = int(np.argmax(vals))
            off = (k - 2) * step
            if 0 < k < 4:
                lo, mid, hi = vals[k - 1], vals[k], vals[k + 1]
                den = lo - 2 * mid + hi
                if den < 0:
                    off += step * max(-0.5, min(0.5, 0.5 * (lo - hi) / den))
            trial = list(q)
            trial[ax] += off
            got = _score(a, b, mask, c0, at(trial))
            if got >= best:
                q, best = trial, got
    return at(q), best


def _locate(a: np.ndarray, b: np.ndarray, mask: np.ndarray, c0: Point, guess: Params, reach_px: float,
            angles: Optional[Sequence[float]], pivot: Optional[Point] = None) -> Tuple[Params, float]:
    """Where the object is in `b`: masked template matching near `guess`, to a tenth of a pixel.

    Matching, not a gradient method: it searches the whole window, so it cannot drift along an edge the way masked
    ECC did (a third of a pixel off the track by its second step). `angles` searches a turn too, about `pivot` when
    given; its sub-degree comes from the scores either side of the best angle. `_polish` then reads the last fraction
    off the exact warp, because the parabola that reads a peak between whole pixels is biased toward the nearest.
    """
    if angles is None:
        cands = [(0.0, guess[1], guess[2])]
    elif pivot is None:
        cands = [(float(th), guess[1], guess[2]) for th in angles]
    else:
        cands = [_turn_about(float(th), pivot, c0) for th in angles]
    found = [(c, _match(a, b, mask, c0, c, int(math.ceil(reach_px if angles is None or pivot is None else 2))))
             for c in cands]
    scored = [(c, f) for c, f in found if f is not None]
    if not scored:
        raise TrackingError("the object left the shot")
    i = int(np.argmax([f[1] for _, f in scored]))
    best, score = scored[i][1]
    if angles is not None and 0 < i < len(scored) - 1:
        lo, hi = scored[i - 1][1][1], scored[i + 1][1][1]
        den = lo - 2 * score + hi
        if den < 0:
            th = best[0] + _TURN_STEP * max(-0.5, min(0.5, 0.5 * (lo - hi) / den))
            best = _turn_about(th, pivot, c0) if pivot is not None else (th, best[1], best[2])
            best, score = _match(a, b, mask, c0, best, 2) or (best, score)
    again = _match(a, b, mask, c0, best, 2)
    if again is not None:
        best, score = again
    return _polish(a, b, mask, c0, best, pivot)


def _share(sa: np.ndarray, sb: np.ndarray, sil: np.ndarray, box: Tuple[int, int, int, int], dx: float,
           dy: float) -> float:
    """The share of the pixels `sil` (in `box`) that land within `_CARRY_GREY` of `sb` shifted by (dx, dy), in
    smoothed grey; -1 when the shift takes them out of the shot."""
    x1, y1, x2, y2 = box
    h, w = sb.shape
    if x1 + dx < 0 or y1 + dy < 0 or x2 + dx > w or y2 + dy > h:
        return -1.0
    there = _warp(sb, np.array([[1.0, 0.0, x1 + dx], [0.0, 1.0, y1 + dy]]), (y2 - y1, x2 - x1))
    return float((np.abs(there - sa[y1:y2, x1:x2])[sil] < _CARRY_GREY).mean())


def _along_rail(a: np.ndarray, b: np.ndarray, seg: Segment, guess: Params, reach: float,
                rail: Tuple[float, float]) -> Tuple[Params, float]:
    """Where a piece on a rail is: its face slid along the line, scored by the share of it that lands on its own
    value, then the sub-pixel read off the proven pixels' correlation.

    The face is the proven pixels and the mask's interior, two pixels clear of its rim, where the smoothing reaches
    no ground. Correlation is the wrong question at range for a piece whose face is flat: with nothing inside to
    vary, the rim decides it, and correlation normalizes away the one thing that tells a flat face from any other
    flat ground, its grey. On GeeTest the seat scored 0.26-0.5 against a plateau of decoys at 0.49 along a white
    phone screen; the share is 0.88 there. Where its peaks tie along a stretch of ground the shade of the face, the
    peak nearest `guess` is taken (`_SHARE_TIE`). Within a pixel of the seat the edges' correlation is the sharper
    of the two.
    """
    sa, sb = _smooth(a, _SHARE_SMOOTH), _smooth(b, _SHARE_SMOOTH)
    face = seg.proven.astype(bool) | _shrink(seg.mask, 5).astype(bool)
    ys, xs = np.nonzero(face)
    box = (int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1)
    sil = face[box[1]:box[3], box[0]:box[2]]
    n = int(math.ceil(reach))
    # The rail runs through rest, not through the guess: a guess extrapolated from the probe carries the probe's
    # own error, which on GeeTest's long track put the line 4.5 px above the seat.
    t = guess[1] * rail[0] + guess[2] * rail[1]
    along = [((t + k) * rail[0], (t + k) * rail[1]) for k in range(-n, n + 1)]
    scores = np.array([_share(sa, sb, sil, box, dx, dy) for dx, dy in along])
    if scores.max() < 0:
        raise TrackingError("the object left the shot")
    # A peak is the best place within two pixels of itself; a slope beside the true peak never is.
    peaks = np.nonzero(scores >= np.array([scores[max(0, k - 2):k + 3].max() for k in range(len(scores))]))[0]
    tied = peaks[scores[peaks] >= scores.max() - _SHARE_TIE]
    i = int(tied[np.argmin(np.abs(tied - n))])
    params, _ = _locate(a, b, seg.proven, seg.centroid, (0.0, *along[i]), 1.0, None)
    if math.hypot(params[1] - along[i][0], params[2] - along[i][1]) > 1.5:
        params = (0.0, *along[i])
    return params, max(scores[i], _share(sa, sb, sil, box, params[1], params[2]))


def measure(first: Image, current: Image, seg: Segment, guess: Optional[Params] = None,
            reach_px: Optional[float] = None, reach_deg: Optional[float] = None) -> Tuple[Params, float]:
    """The transform `first` -> `current` of the segmented object, and the match's confidence: the correlation, or
    for a piece on a rail the share of it that lands where it was (`_along_rail`).

    Raises TrackingError below `_MIN_CORRELATION` (`_MIN_SHARE`): the object is gone, covered, or redrawn, and a
    position read off a poor match would steer the handle by a guess.
    """
    a, b = _pair(first, current)
    g = _constrain(seg, guess or (0.0, 0.0, 0.0))
    rp = reach_px if reach_px is not None else max(15.0, 0.3 * math.hypot(g[1], g[2]))
    rd = reach_deg if reach_deg is not None else max(4.0, 0.3 * abs(g[0]))
    rail = _rail(seg)
    if rail is not None:
        params, share = _along_rail(a, b, seg, g, rp, rail)
        if share < _MIN_SHARE:
            raise TrackingError(f"lost the object: at best {share:.0%} of it lands where it was")
        return params, share
    params, corr = _locate(a, b, seg.proven, seg.centroid, g, rp, _angles(g[0], rd) if _turns(seg) else None,
                           seg.pivot if _turns(seg) else None)
    if corr < _MIN_CORRELATION:
        raise TrackingError(f"lost the object: its best match correlates {corr:.2f}")
    return params, corr


# ── where to put the handle ──────────────────────────────────────────────────


def _model(samples: Sequence[Sample], seg: Segment) -> Callable[[np.ndarray], List[Params]]:
    """The motion as a line in travel s, weighted toward the latest samples: a vendor's ratio can bend, and the
    newest readings are the ones taken nearest the goal. The press itself (s=0, no motion) is always a sample."""
    turn = seg.kind == TURN
    pts = [Sample(0.0, (0.0, 0.0, 0.0)), *samples]
    s = np.array([p.s for p in pts], dtype=float)
    q = np.array([[p.params[0]] if turn else list(p.params[1:]) for p in pts], dtype=float)
    wts = 4.0 ** np.arange(len(pts))
    if len(pts) == 2 or np.ptp(s) < 1e-6:
        a0 = np.zeros(q.shape[1])
        k = (wts[:, None] * s[:, None] * q).sum(0) / max(float((wts * s * s).sum()), 1e-9)
    else:
        x = np.stack([np.ones_like(s), s], axis=1) * np.sqrt(wts)[:, None]
        (a0, k), *_ = np.linalg.lstsq(x, q * np.sqrt(wts)[:, None], rcond=None)

    def at(travel: np.ndarray) -> List[Params]:
        v = a0[None, :] + np.asarray(travel, dtype=float)[:, None] * k[None, :]
        if turn:
            return [_turn_about(float(th), seg.pivot, seg.centroid) for th in v[:, 0]]
        return [(0.0, float(tx), float(ty)) for tx, ty in v]

    return at


def predict(samples: Sequence[Sample], seg: Segment, s: float) -> Params:
    return _model(samples, seg)(np.array([s]))[0]


def plan(samples: Sequence[Sample], seg: Segment, point: Point, goal: Point, bounds: Tuple[float, float]) -> float:
    """The handle travel, within `bounds`, whose predicted motion puts `point` nearest `goal`."""
    travel = np.arange(float(bounds[0]), float(bounds[1]) + 0.25, 0.25)
    pos = np.array([transform_point(p, seg.centroid, point) for p in _model(samples, seg)(travel)])
    return float(travel[int(np.argmin(np.hypot(pos[:, 0] - goal[0], pos[:, 1] - goal[1])))])


def _same(x: Image, y: Image) -> bool:
    return x is y or (isinstance(x, str) and isinstance(y, str) and x == y)


def slide_step(first: Image, probe: Image, current: Image, *, probe_s: Offset, s: Offset, goal: Point,
               seed: Optional[Point] = None, handle: Optional[Point] = None,
               bounds: Optional[Tuple[float, float]] = None, history: Sequence[Dict[str, Any]] = (),
               tol: float = 2.0) -> Dict[str, Any]:
    """One look of the closed loop: where the object's point is now, and where the handle should go next.

    `probe_s` and `s` are the handle's offsets from the press for the probe and the current shot: a number (travel
    along the track) or, once `grabbed` has come back true, an [dx, dy] pair. `history` is the `observation` each
    earlier call returned, oldest first, excluding the probe. `done` means stop moving: the point is within `tol`, or
    no travel inside `bounds` brings it closer; `error` says which. Raises TrackingError when the object cannot be
    found or followed.
    """
    seg = segment(first, probe, seed, handle, goal)
    point = seed if seed is not None else seg.centroid
    a = _gray(first)

    if seg.grabbed:
        at = np.array(s if isinstance(s, (list, tuple)) else (s, 0.0), dtype=float)
        # A carried piece follows the pointer, so the pointer's own offset is the guess.
        params, corr = measure(first, current, seg, guess=(0.0, float(at[0]), float(at[1])))
        pos = transform_point(params, seg.centroid, point)
        err = (goal[0] - pos[0], goal[1] - pos[1])
        dist = math.hypot(*err)
        return {"pos": list(pos), "params": list(params), "error": dist, "grabbed": True, "kind": SLIDE,
                "next": [float(at[0] + err[0]), float(at[1] + err[1])], "done": dist <= tol, "correlation": corr,
                "observation": {"s": [float(v) for v in at], "params": list(params)}}

    ps = float(probe_s[0] if isinstance(probe_s, (list, tuple)) else probe_s)
    cur = float(s[0] if isinstance(s, (list, tuple)) else s)
    samples = [Sample(ps, seg.probe)] + [Sample(float(e["s"]), tuple(float(v) for v in e["params"])) for e in history]
    if _same(current, probe):
        params, corr = measure(first, probe, seg, guess=seg.probe, reach_px=2.0, reach_deg=1.0)
    else:
        params, corr = measure(first, current, seg, guess=predict(samples, seg, cur))
        samples.append(Sample(cur, params))
    pos = transform_point(params, seg.centroid, point)
    dist = math.hypot(goal[0] - pos[0], goal[1] - pos[1])
    width = float(a.shape[1])
    nxt = cur if dist <= tol else plan(samples, seg, point, goal, bounds if bounds is not None else (-width, width))
    return {"pos": list(pos), "params": list(params), "error": dist, "grabbed": False, "kind": seg.kind,
            "next": nxt, "done": dist <= tol or abs(nxt - cur) < 0.5, "correlation": corr,
            "observation": {"s": cur, "params": list(params)}}
