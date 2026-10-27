"""Follow a press-and-hold widget's fill, and say when to let go.

The model names three points: what to press, where the fill starts and where it should be released. Holding makes
something grow from `start` toward `end` (a bar filling, a ring closing along its chord, a pill colouring in), so
the shot at the press and a later shot differ along that line up to the fill's leading edge, and nowhere past it.

`fill_step` reads one look: the leading edge in pixels along start->end, and whether to release now. Nothing about
the widget is read from its DOM, and nothing is kept between calls: the caller passes back what earlier looks
returned, so the CLI worker can serve the JS port the same way.

All coordinates are SHOT pixels; the caller converts to CSS with its own device scale.
"""

from __future__ import annotations

import math
from typing import Any, Dict, Optional, Sequence, Tuple, Union

import cv2
import numpy as np

Image = Union[str, np.ndarray]
Point = Tuple[float, float]

# A pixel the fill has reached differs from the press in at least one channel by this much; a re-composited page
# shot jitters by a few levels at edges, and the 3x3 blur takes most of that out.
_CHANGED = 24.0
# Half-width of the band read across the line: the model's points are a few pixels off the bar's axis.
_BAND_PX = 2
# The edge is the furthest changed sample whose last _RUN_PX samples are mostly changed: a lone flicker past the
# fill (a cursor, a badge) is not the fill.
_RUN_PX = 6
_RUN_SHARE = 0.6
# Read this far past `end` too, so a fill that overshot between looks is seen as past, not as stalled at it.
_PAST = 0.15


# A timed release is aimed this long after the predicted arrival. Early and late do not cost the same: when `end` is
# where the fill stops (HUMAN's pill, a ring closing) the widget completes on its own and a release a few ms early
# starts it over, while a late one is free; on a mark mid-bar this is a few pixels of the mark's tolerance.
_LATE_S = 0.06
# The pace is fitted over this many looks: two alone turn a pixel of edge noise on a slow fill into a release a
# whole tolerance off, and a widget that eases changes pace over more than a few.
_PACE_LOOKS = 4


class FillError(ValueError):
    """The line cannot be read: a degenerate segment or shots of different sizes."""


def _rgb(img: Image) -> np.ndarray:
    a = cv2.imread(img, cv2.IMREAD_COLOR) if isinstance(img, str) else np.asarray(img)
    if a is None:
        raise FillError(f"cannot read {img!r}")
    if a.ndim == 2:
        a = np.repeat(a[..., None], 3, axis=2)
    return cv2.GaussianBlur(a[..., :3].astype(np.float32), (3, 3), 0)


def profile(first: Image, current: Image, start: Point, end: Point) -> Tuple[np.ndarray, float]:
    """How much each pixel step along start->end (and _PAST beyond) changed since the press, and the line's length."""
    a, b = _rgb(first), _rgb(current)
    if a.shape != b.shape:
        raise FillError(f"shots differ in size: {a.shape[:2]} vs {b.shape[:2]}")
    h, w = a.shape[:2]
    (x0, y0), (x1, y1) = (float(v) for v in start), (float(v) for v in end)
    length = math.hypot(x1 - x0, y1 - y0)
    if length < 2.0:
        raise FillError("the fill's start and end are the same point")
    ux, uy = (x1 - x0) / length, (y1 - y0) / length
    steps = np.arange(int(math.ceil(length * (1 + _PAST))) + 1, dtype=np.float32)
    diff = np.abs(a - b).max(axis=2)
    across = []
    for o in range(-_BAND_PX, _BAND_PX + 1):
        xs = np.clip(np.round(x0 + steps * ux - o * uy), 0, w - 1).astype(int)
        ys = np.clip(np.round(y0 + steps * uy + o * ux), 0, h - 1).astype(int)
        across.append(diff[ys, xs])
    # The median across the band: the bar's edge running along one side of the line is not the fill.
    return np.median(np.stack(across), axis=0), length


def _solid(changes: np.ndarray) -> np.ndarray:
    """The changed steps whose last _RUN_PX steps are mostly changed too."""
    on = changes > _CHANGED
    run = np.convolve(on.astype(np.float32), np.ones(_RUN_PX, np.float32), mode="full")[:len(on)]
    count = np.minimum(np.arange(1, len(on) + 1), _RUN_PX)
    return on & (run / count >= _RUN_SHARE)


def leading_edge(changes: np.ndarray) -> Optional[float]:
    """The furthest step the fill has reached, or None when nothing along the line has changed."""
    idx = np.flatnonzero(_solid(changes))
    return float(idx[-1]) if len(idx) else None


def trailing_edge(changes: np.ndarray) -> Optional[float]:
    """Where the fill was when the reference was shot: the changed run starts there, because what had already filled
    by then looks the same in both shots."""
    idx = np.flatnonzero(_solid(changes[::-1]))
    return float(len(changes) - 1 - idx[-1]) if len(idx) else None


def _pace(looks: Sequence[Tuple[float, float]]) -> Optional[float]:
    """Pixels per second, least squares over (t, edge) looks; None from fewer than two."""
    if len(looks) < 2:
        return None
    ts, es = np.array(looks, dtype=np.float64).T
    if np.ptp(ts) <= 0:
        return None
    return float(np.polyfit(ts, es, 1)[0])


def fill_step(first: Image, current: Image, *, start: Point, end: Point, t: float,
              history: Sequence[Dict[str, Any]] = (), poll_s: float = 0.25, tol: float = 2.0,
              first_t: Optional[float] = None) -> Dict[str, Any]:
    """One look at a held widget: how far its fill has come, and whether to release it now.

    `t` is the caller's clock (seconds) when this shot was taken and `history` the `observation` of each earlier
    look, oldest first; `first_t` is when `first` was shot, which gives the first look a pace of its own (see
    `trailing_edge`) so a mark close to the start is not passed while two looks are gathered. `release` is true once the edge is within `tol` of `end` or past it, or when at its measured
    pace the fill reaches `end` before the next look, `poll_s` away. `release_in` is then how long after `t` to let
    go, a little after the arrival (`_LATE_S`): releasing on the look instead lands up to a whole look's travel past
    the mark, and a fast fill covers more than a mark's tolerance in one.
    """
    changes, length = profile(first, current, start, end)
    edge = leading_edge(changes)
    obs = {"t": float(t), "edge": edge}
    out: Dict[str, Any] = {"edge": edge, "length": length, "observation": obs, "release": False, "release_in": None,
                           "speed": None}
    if edge is None:
        return out
    short = length - edge
    seen = [(float(o["t"]), float(o["edge"])) for o in history if o.get("edge") is not None and float(o["t"]) < t]
    back = trailing_edge(changes) if first_t is not None and float(first_t) < t else None
    if back is not None and back < edge and all(float(first_t) < ts for ts, _ in seen):
        seen = [(float(first_t), back)] + seen
    out["speed"] = _pace(seen[-(_PACE_LOOKS - 1):] + [(t, edge)])
    if short <= tol:
        out["release"], out["release_in"] = True, 0.0
    elif out["speed"] and out["speed"] > 0 and short / out["speed"] <= poll_s:
        out["release"], out["release_in"] = True, short / out["speed"] + _LATE_S
    return out
