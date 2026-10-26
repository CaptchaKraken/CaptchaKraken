"""Track the part of a slide captcha that the handle moves, and say where to put the handle next.

The model names three points: the handle, a point on what the handle moves, and where that point belongs. This
module turns them into a closed loop without knowing anything about the vendor: no selector, no handle-to-piece
ratio, no assumption about whether the handle slides the piece or turns it.

1. `segment` finds WHAT moves: optical flow from the shot at the press to the shot after a small probe, kept only
   where it agrees with the flow back, split into connected parts. Flow spreads across flat ground, so one part can
   hold the piece AND the knob below it: each part is cut, under each distinct motion in it, to the pixels that
   motion carries exactly onto the probe, and split into bodies cored on pixels that actually changed. The body
   under the model's point is the object; without one, the largest body that is not the handle.
2. The probe also says HOW the handle drives it: a SLIDE (a shift) or a TURN (about a pivot it fits). A handle does
   one or the other, and fitting both from a short probe lets a half-degree of noise grow into a ten-degree turn by
   the far end of the track.
3. `measure` finds where the object is now: template matching over its own mask near the prediction, then the exact
   warp scored to a fraction of a pixel, so a busy board or an animated badge elsewhere cannot pull it.
4. `plan` fits the motion as a straight line in the handle's travel and picks the travel that brings the model's
   point closest to its goal.

All coordinates are SHOT pixels; the caller converts to CSS with its own device scale.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple, Union

import cv2
import numpy as np

Image = Union[str, np.ndarray]
Point = Tuple[float, float]
# (theta in degrees, tx, ty) about the object's centroid c0: p' = R(theta)(p - c0) + c0 + t. Positive theta turns
# clockwise on screen, since image y points down.
Params = Tuple[float, float, float]
Offset = Union[float, Sequence[float]]

SLIDE = "slide"
TURN = "turn"

# Below this a pixel is still: DIS flow on a static textured board stays well under it.
_MOVING_PX = 0.5
# Forward-backward disagreement allowed, absolute and as a fraction of the motion: what fails it is ground the
# object covered or uncovered, which has no counterpart in the other shot.
_FB_ABS_PX = 0.8
_FB_REL = 0.25
# Grey levels within which carrying a pixel with the object's own motion must reproduce the probe for the pixel to
# be the object's. DIS spreads the object's flow several pixels onto the ground around it and the backward flow
# agrees, so only the pixels can say which side of the edge they are on. Comparing against standing still does not
# work: a smooth piece hardly changes when it moves, and an edge running along the motion not at all. Both shots
# are smoothed first, because a page composited at a fraction of a pixel softens the object's sharpest edge.
# Measured on the test boards: 95-98% of the piece, plus up to 4% featureless ground hugging its edge, which looks
# the same carried or still and so cannot be told apart by any pixel.
_CARRY_GREY = 6.0
_CARRY_SMOOTH = 1.0
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
# How far off its rail (px) a slid object may be read: the line through rest and the probe, which is all a handle on
# a track can do to it. Room for the sub-pixel jitter of a real page, not for a second motion.
_RAIL_SLACK = 2.0


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


# ── images and masks ─────────────────────────────────────────────────────────


def _gray(img: Image) -> np.ndarray:
    a = cv2.imread(img, cv2.IMREAD_COLOR) if isinstance(img, str) else img
    if a is None:
        raise TrackingError(f"unreadable image: {img}")
    if a.ndim == 3:
        a = cv2.cvtColor(a, cv2.COLOR_BGR2GRAY)
    return np.ascontiguousarray(a, dtype=np.uint8)


def _pair(first: Image, other: Image) -> Tuple[np.ndarray, np.ndarray]:
    a, b = _gray(first), _gray(other)
    if a.shape != b.shape:
        raise TrackingError(f"shots differ in size: {a.shape} vs {b.shape}")
    return a, b


def _centroid(mask: np.ndarray) -> Point:
    m = cv2.moments(mask.astype(np.uint8), binaryImage=True)
    return m["m10"] / m["m00"], m["m01"] / m["m00"]


def _fill(part: np.ndarray) -> np.ndarray:
    """The part with its holes filled: a turning disc's centre barely moves and a flat patch carries no flow."""
    contours, _ = cv2.findContours(part.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    out = np.zeros(part.shape, np.uint8)
    cv2.drawContours(out, contours, -1, 1, thickness=cv2.FILLED)
    return out


def _outline(part: np.ndarray) -> np.ndarray:
    contours, _ = cv2.findContours(part.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    return max(contours, key=len)


def _carried(a: np.ndarray, b: np.ndarray, part: np.ndarray, params: Params, c0: Point,
             min_area: float, along: Optional[Tuple[float, float]] = None) -> np.ndarray:
    """The pixels around `part` that the object's own motion (`params` about `c0`) carries onto the probe.

    `along`, a slide's shift: what changed is joined along it (`_spans`) before the unchanged ground is trimmed.
    """
    h, w = a.shape
    grow = cv2.dilate(part.astype(np.uint8), np.ones((7, 7), np.uint8)) > 0
    landed = cv2.warpAffine(b.astype(np.float32), _rigid(params, c0), (w, h),
                            flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP, borderMode=cv2.BORDER_REPLICATE)
    move = np.abs(cv2.GaussianBlur(landed, (0, 0), _CARRY_SMOOTH)
                  - cv2.GaussianBlur(a.astype(np.float32), (0, 0), _CARRY_SMOOTH))
    explained = grow & (move < _CARRY_GREY)
    # Ground that happens to match itself one shift along leaves thin threads, never a body.
    keep = cv2.morphologyEx(explained.astype(np.uint8), cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
    n, labels, stats, _ = cv2.connectedComponentsWithStats(keep, connectivity=8)
    ours = [i for i in range(1, n) if (part & (labels == i)).sum() > 0.5 * stats[i, cv2.CC_STAT_AREA]]
    keep = cv2.morphologyEx(np.isin(labels, ours).astype(np.uint8), cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    # The opening also shaves the object's rim, its sharpest edge; take back the rim pixels the motion explains.
    keep = keep | (cv2.dilate(keep, np.ones((3, 3), np.uint8)).astype(bool) & explained).astype(np.uint8)
    # Ground the shot shows unchanged is explained by standing still as well as by the motion: it is the object's
    # only where it lies within reach of what changed, or inside its outline.
    still = np.abs(cv2.GaussianBlur(b.astype(np.float32), (0, 0), _CARRY_SMOOTH)
                   - cv2.GaussianBlur(a.astype(np.float32), (0, 0), _CARRY_SMOOTH))
    core = keep.astype(bool) & (still >= _CARRY_GREY)
    if along is not None:
        core = _spans(core, keep, along)
    core = cv2.morphologyEx(core.astype(np.uint8), cv2.MORPH_CLOSE, np.ones((_CORE_CLOSE, _CORE_CLOSE), np.uint8))
    reach = cv2.distanceTransform((core == 0).astype(np.uint8), cv2.DIST_L2, 3) <= _CORE_REACH
    keep = _fill((keep.astype(bool) & reach | core.astype(bool)).astype(np.uint8))
    if keep.sum() < min_area:
        raise TrackingError("the moving part has no texture or edge that its own motion explains")
    return keep


# ── what moves ───────────────────────────────────────────────────────────────


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
    hist = cv2.GaussianBlur(hist.astype(np.float32), (3, 3), 0)
    peaks = (hist == cv2.dilate(hist, np.ones((5, 5), np.uint8))) & (hist >= _MODE_SHARE * hist.max())
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
    h, w = core.shape
    turn = cv2.getRotationMatrix2D((w / 2, h / 2), math.degrees(math.atan2(shift[1], shift[0])), 1.0)
    side = int(math.ceil(math.hypot(h, w)))
    turn[:, 2] += (side - w) / 2, (side - h) / 2
    flat = [cv2.warpAffine(m.astype(np.uint8), turn, (side, side), flags=cv2.INTER_NEAREST) > 0 for m in (core, cut)]
    c, k = flat
    run = np.cumsum(np.diff(np.pad(k, ((0, 0), (1, 0))).astype(np.int8), axis=1) == 1, axis=1) * k
    out = np.zeros_like(c)
    for y in np.nonzero(c.any(axis=1))[0]:
        for r in np.unique(run[y][c[y]]):
            xs = np.nonzero(c[y] & (run[y] == r))[0]
            out[y, xs[0]:xs[-1] + 1] = True
    back = cv2.warpAffine(out.astype(np.uint8), turn, (w, h), flags=cv2.INTER_NEAREST | cv2.WARP_INVERSE_MAP)
    return core.astype(bool) | ((back > 0) & cut.astype(bool))


def _split(a: np.ndarray, b: np.ndarray, cut: np.ndarray, min_area: float,
           shift: Optional[Tuple[float, float]] = None) -> List[np.ndarray]:
    """The separate bodies in a cut, which flat ground may join.

    Featureless ground is explained by ANY motion, the object's included, so it passes the pixel test and can bridge
    a piece to the knob under it. Only pixels that changed between the shots are evidence of a body: each body is
    cored on those, joined along a slide's motion (`_spans`), and keeps the explained ground within reach of its own
    core and nearer to it than to any other.
    """
    changed = np.abs(cv2.GaussianBlur(b.astype(np.float32), (0, 0), _CARRY_SMOOTH)
                     - cv2.GaussianBlur(a.astype(np.float32), (0, 0), _CARRY_SMOOTH)) >= _CARRY_GREY
    core = cut.astype(bool) & changed
    if shift is not None:
        core = _spans(core, cut, shift)
    core = cv2.morphologyEx(core.astype(np.uint8), cv2.MORPH_CLOSE, np.ones((_CORE_CLOSE, _CORE_CLOSE), np.uint8))
    n, labels, stats, _ = cv2.connectedComponentsWithStats(_fill(core), connectivity=8)
    cores = [labels == i for i in range(1, n) if stats[i, cv2.CC_STAT_AREA] >= min_area]
    if not cores:
        return []
    dist = np.stack([cv2.distanceTransform((~c).astype(np.uint8), cv2.DIST_L2, 3) for c in cores])
    owner = dist.argmin(axis=0)
    near = dist.min(axis=0) <= _CORE_REACH
    out = []
    for i in range(len(cores)):
        body = _fill(((cut.astype(bool) & near & (owner == i)) | cores[i]).astype(np.uint8))
        if body.sum() >= min_area:
            out.append(body)
    return out


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
    inner = cv2.erode(_fill(part), np.ones((9, 9), np.uint8)).astype(bool) & (moving > 0)
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
        g = cv2.GaussianBlur(a.astype(np.float32), (0, 0), 1.0)
        edge = cv2.Sobel(g, cv2.CV_32F, 1, 0) ** 2 + cv2.Sobel(g, cv2.CV_32F, 0, 1) ** 2
        kind, angles = SLIDE, None
        guesses = [(0.0, tx, ty) for tx, ty in _flow_modes(fwd[inner], edge[inner])]

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


def segment(first: Image, probe: Image, seed: Optional[Point] = None, handle: Optional[Point] = None) -> Segment:
    """The object the probe moved, in `first` coordinates, and how the handle drives it.

    With `seed`, the body under it (or nearest to it, within reach). Without one, the largest body that is not the
    handle: what a generation-2 answer, which names only the goal, has to settle for.
    """
    a, b = _pair(first, probe)
    h, w = a.shape
    dis = cv2.DISOpticalFlow_create(cv2.DISOPTICAL_FLOW_PRESET_MEDIUM)
    fwd = dis.calc(a, b, None)
    bwd = dis.calc(b, a, None)
    ys, xs = np.mgrid[0:h, 0:w].astype(np.float32)
    back = cv2.remap(bwd, xs + fwd[..., 0], ys + fwd[..., 1], cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
    mag = np.hypot(fwd[..., 0], fwd[..., 1])
    fb = np.hypot(fwd[..., 0] + back[..., 0], fwd[..., 1] + back[..., 1])
    moving = ((mag > _MOVING_PX) & (fb < np.maximum(_FB_ABS_PX, _FB_REL * mag))).astype(np.uint8)
    moving = cv2.morphologyEx(moving, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    moving = cv2.morphologyEx(moving, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))

    n, labels, stats, _ = cv2.connectedComponentsWithStats(moving, connectivity=8)
    min_area = max(_MIN_PART_PX, _MIN_PART_FRACTION * h * w)
    parts = [i for i in range(1, n) if stats[i, cv2.CC_STAT_AREA] >= min_area]
    if not parts:
        raise TrackingError("nothing moved between the press and the probe")

    def label_at(p: Optional[Point]) -> int:
        if p is None:
            return 0
        x, y = int(round(p[0])), int(round(p[1]))
        return int(labels[y, x]) if 0 <= x < w and 0 <= y < h else 0

    if seed is not None:
        pick = label_at(seed) if label_at(seed) in parts else 0
        if not pick:
            reach = max(_SEED_REACH_MIN_PX, _SEED_REACH_FRACTION * min(h, w))
            inside = {i: cv2.pointPolygonTest(_outline(labels == i), (float(seed[0]), float(seed[1])), True)
                      for i in parts}
            near = max(inside, key=inside.get)
            if -inside[near] > reach:
                raise TrackingError(f"nothing moved within {reach:.0f}px of the point on the object "
                                    f"({seed[0]:.0f}, {seed[1]:.0f}); the nearest moving part is "
                                    f"{-inside[near]:.0f}px away")
            pick = near
        candidates = [pick]
    else:
        # Every part, the handle's own included: see `_bodies` for why the piece can share it.
        candidates = sorted(parts, key=lambda i: -stats[i, cv2.CC_STAT_AREA])

    found: List[Tuple[np.ndarray, Params, str, Point]] = []
    why: Optional[TrackingError] = None
    for pick in candidates:
        try:
            found += _bodies(a, b, fwd, moving, labels == pick, xs, ys, min_area)
        except TrackingError as exc:
            why = why or exc
    held = _near_handle(handle, h, w)
    if seed is not None:
        if not found:
            raise why or TrackingError("the moving part has no texture or edge that its own motion explains")
        # The body under the model's point, else the nearest: it read the piece off a shot before the press.
        sx, sy = float(seed[0]), float(seed[1])
        mask, exact, kind, c_part = max(found, key=lambda f: cv2.pointPolygonTest(_outline(f[0]), (sx, sy), True))
    else:
        carried = [f for f in found if not (held is not None and (f[0].astype(bool) & held).any())]
        if not carried:
            if why is not None and not found:
                raise why
            raise TrackingError("only the handle moved; nothing it carries was seen")
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

    grabbed = handle is not None and bool(cv2.dilate(mask, np.ones((5, 5), np.uint8))[
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
    h, w = a.shape
    smooth = cv2.GaussianBlur(a.astype(np.float32), (0, 0), _CARRY_SMOOTH)
    along = cv2.warpAffine(smooth, _rigid(params, c0), (w, h), flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP,
                           borderMode=cv2.BORDER_REPLICATE)
    changed = np.abs(cv2.GaussianBlur(b.astype(np.float32), (0, 0), _CARRY_SMOOTH) - smooth) >= _CARRY_GREY
    # The mask's outermost pixel is ground the fill and the reach keep for the object's extent, nearly always; one
    # deeper is the object's own rim, which on a flat face is the only detail it has.
    body = cv2.erode(mask.astype(np.uint8), np.ones((3, 3), np.uint8)).astype(bool)
    proven = (body & changed & (np.abs(along - smooth) >= _CARRY_GREY)).astype(np.uint8)
    if proven.sum() < min_area:
        raise TrackingError("the probe moved the object too little to show which pixels are its own")
    return proven


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
    a match off it is something else in the picture that resembles it.
    """
    if seg.kind != SLIDE or seg.grabbed:
        return None
    n = math.hypot(seg.probe[1], seg.probe[2])
    return (seg.probe[1] / n, seg.probe[2] / n) if n > 0 else None


def _angles(centre: float, reach: float) -> List[float]:
    n = max(1, int(math.ceil(reach / _TURN_STEP)))
    return [centre + _TURN_STEP * i for i in range(-n, n + 1)]


def _peak(res: np.ndarray) -> Tuple[float, float, float]:
    """The score map's best point to a fraction of a pixel (a parabola through each axis), and its score."""
    _, score, _, (x, y) = cv2.minMaxLoc(res)

    def vertex(lo: float, mid: float, hi: float) -> float:
        den = lo - 2 * mid + hi
        return 0.0 if den >= 0 else max(-0.5, min(0.5, 0.5 * (lo - hi) / den))

    dx = vertex(res[y, x - 1], res[y, x], res[y, x + 1]) if 0 < x < res.shape[1] - 1 else 0.0
    dy = vertex(res[y - 1, x], res[y, x], res[y + 1, x]) if 0 < y < res.shape[0] - 1 else 0.0
    return x + dx, y + dy, float(score)


def _match(a: np.ndarray, b: np.ndarray, mask: np.ndarray, c0: Point, p: Params,
           reach: int, rail: Optional[Tuple[float, float]] = None) -> Optional[Tuple[Params, float]]:
    """The object carried by `p`, matched against `b` within `reach` pixels: the shift that best seats it.

    `rail`, a unit direction: only shifts within `_RAIL_SLACK` of the line through no shift along it are read.
    """
    h, w = a.shape
    m = _rigid(p, c0)
    warped = cv2.warpAffine(a, m, (w, h), flags=cv2.INTER_LINEAR)
    wmask = cv2.warpAffine(mask.astype(np.uint8) * 255, m, (w, h), flags=cv2.INTER_NEAREST)
    ys, xs = np.nonzero(wmask)
    if len(xs) < _MIN_PART_PX:
        return None
    x1, y1, x2, y2 = int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1
    sx1, sy1, sx2, sy2 = max(0, x1 - reach), max(0, y1 - reach), min(w, x2 + reach), min(h, y2 + reach)
    if sx2 - sx1 < x2 - x1 or sy2 - sy1 < y2 - y1:
        return None
    res = cv2.matchTemplate(b[sy1:sy2, sx1:sx2], warped[y1:y2, x1:x2], cv2.TM_CCOEFF_NORMED,
                            mask=wmask[y1:y2, x1:x2])
    res = np.nan_to_num(res, nan=-1.0, posinf=-1.0, neginf=-1.0)
    if rail is not None:
        ry, rx = np.mgrid[0:res.shape[0], 0:res.shape[1]].astype(np.float32)
        off = np.abs((p[1] + sx1 + rx - x1) * rail[1] - (p[2] + sy1 + ry - y1) * rail[0])
        res[off > _RAIL_SLACK] = -1.0
    px, py, score = _peak(res)
    return (float(p[0]), float(p[1] + sx1 + px - x1), float(p[2] + sy1 + py - y1)), float(score)


def _score(a: np.ndarray, b: np.ndarray, mask: np.ndarray, c0: Point, p: Params) -> float:
    """Zero-mean correlation of the object carried exactly by `p` against `b`, over the object only."""
    h, w = a.shape
    m = _rigid(p, c0)
    x1, y1, x2, y2 = _box(cv2.transform(_corners(mask), m).reshape(-1, 2), w, h)
    if x2 - x1 < 3 or y2 - y1 < 3:
        return -1.0
    shift = m.copy()
    shift[:, 2] -= (x1, y1)
    warped = cv2.warpAffine(a.astype(np.float32), shift, (x2 - x1, y2 - y1), flags=cv2.INTER_LINEAR)
    inside = cv2.warpAffine(mask.astype(np.float32), shift, (x2 - x1, y2 - y1), flags=cv2.INTER_LINEAR) > 0.99
    if inside.sum() < _MIN_PART_PX:
        return -1.0
    u, v = warped[inside], b[y1:y2, x1:x2].astype(np.float32)[inside]
    u, v = u - u.mean(), v - v.mean()
    den = math.sqrt(float((u * u).sum() * (v * v).sum()))
    return float((u * v).sum() / den) if den > 0 else -1.0


def _corners(mask: np.ndarray) -> np.ndarray:
    ys, xs = np.nonzero(mask)
    x1, y1, x2, y2 = xs.min(), ys.min(), xs.max() + 1, ys.max() + 1
    return np.float32([[x1, y1], [x2, y1], [x1, y2], [x2, y2]]).reshape(-1, 1, 2)


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
            angles: Optional[Sequence[float]], pivot: Optional[Point] = None,
            rail: Optional[Tuple[float, float]] = None) -> Tuple[Params, float]:
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
    found = [(c, _match(a, b, mask, c0, c, int(math.ceil(reach_px if angles is None or pivot is None else 2)), rail))
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
    again = _match(a, b, mask, c0, best, 2, rail)
    if again is not None:
        best, score = again
    return _polish(a, b, mask, c0, best, pivot)


def _share(sa: np.ndarray, sb: np.ndarray, sil: np.ndarray, box: Tuple[int, int, int, int], dx: float,
           dy: float) -> float:
    """The share of the pixels `sil` (in `box`) that land within `_CARRY_GREY` of `sb` shifted by (dx, dy), in
    smoothed grey; -1 when the shift takes them out of the shot."""
    x1, y1, x2, y2 = box
    h, w = sb.shape
    m = np.float32([[1, 0, x1 + dx], [0, 1, y1 + dy]])
    if x1 + dx < 0 or y1 + dy < 0 or x2 + dx > w or y2 + dy > h:
        return -1.0
    there = cv2.warpAffine(sb, m, (x2 - x1, y2 - y1), flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP)
    return float((np.abs(there - sa[y1:y2, x1:x2])[sil] < _CARRY_GREY).mean())


def _along_rail(a: np.ndarray, b: np.ndarray, seg: Segment, guess: Params, reach: float,
                rail: Tuple[float, float]) -> Tuple[Params, float]:
    """Where a piece on a rail is: its face slid along the line, scored by the share of it that lands on its own
    value, then the sub-pixel read off the proven pixels' correlation.

    The face is the proven pixels and the mask's interior, two pixels clear of its rim, where the smoothing reaches
    no ground. Correlation is the wrong question at range for a piece whose face is flat: with nothing inside to
    vary, the rim decides it, and correlation normalizes away the one thing that tells a flat face from any other
    flat ground, its grey. On GeeTest the seat scored 0.26-0.5 against a plateau of decoys at 0.49 along a white
    phone screen; the share is 0.88 there. Within a pixel of the seat the edges' correlation is the sharper of the
    two.
    """
    sa = cv2.GaussianBlur(a.astype(np.float32), (0, 0), _SHARE_SMOOTH)
    sb = cv2.GaussianBlur(b.astype(np.float32), (0, 0), _SHARE_SMOOTH)
    face = seg.proven.astype(bool) | cv2.erode(seg.mask.astype(np.uint8), np.ones((5, 5), np.uint8)).astype(bool)
    ys, xs = np.nonzero(face)
    box = (int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1)
    sil = face[box[1]:box[3], box[0]:box[2]]
    n = int(math.ceil(reach))
    along = [(guess[1] + k * rail[0], guess[2] + k * rail[1]) for k in range(-n, n + 1)]
    scores = [_share(sa, sb, sil, box, dx, dy) for dx, dy in along]
    i = int(np.argmax(scores))
    if scores[i] < 0:
        raise TrackingError("the object left the shot")
    params, _ = _locate(a, b, seg.proven, seg.centroid, (0.0, *along[i]), 1.0, None, None, rail)
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
    seg = segment(first, probe, seed, handle)
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
