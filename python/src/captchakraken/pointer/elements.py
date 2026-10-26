"""Detector output -> the numbered elements a board is shown with.

An element is {"class", "box": [x0, y0, x1, y1], "score", "mask": ((x, y), bool
array)} in board pixels; the mask is cropped to its own extent and placed at
(x, y), as `detector.Detector.detect` returns it. Numbers are 1-based in reading
order (rows of ~12 px, then left to right), so a grid's cells number row-major.

`element_at` is the inverse question training asks: which numbered element does
a gold point land on? That decides the id a slot is trained to give.
"""
from __future__ import annotations

from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

from .layout import MAX_ELEMENTS

#: Detector classes that are numbered. `grid` is acted on through its cells, and
#: `click_area` is the well a free click lands in: it holds every point on the
#: board and so names none of them. The detector's `submit` is a button.
NUMBERED = ("cell", "item", "draggable", "drop_target", "slider", "button", "text_input")
RENAME = {"submit": "button"}
#: A point this close to an element's mask (px) still lands on it: anti-aliased edges.
EDGE_PX = 3
#: Detections below this score are not shown. A spare outline costs the model one
#: more option to reject; a missing one cannot be chosen at all.
MIN_SCORE = 0.5


#: A cell whose box overlaps a piece's or slot's this much (IoU) IS that piece or
#: slot: a drag grid labels every position as both.
SAME_PLACE_IOU = 0.6


def number(dets: Sequence[Dict], min_score: float = MIN_SCORE,
           limit: Optional[int] = MAX_ELEMENTS) -> List[Dict]:
    """Detector output -> the numbered elements, in reading order, at most `limit`
    (None: all, to count a board that has too many). A cell that a piece, slot
    or item fills is numbered once, as that element: it is one place to act
    on, and the specific class says what is there."""
    els = []
    for d in dets:
        cls = RENAME.get(d["class"], d["class"])
        if cls in NUMBERED and d["score"] >= min_score:
            els.append({**d, "class": cls})
    filled = [e["box"] for e in els if e["class"] in ("item", "draggable", "drop_target")]
    els = [e for e in els if e["class"] != "cell" or all(_iou(e["box"], b) < SAME_PLACE_IOU for b in filled)]
    els.sort(key=lambda d: (round(((d["box"][1] + d["box"][3]) / 2) / 12),
                            (d["box"][0] + d["box"][2]) / 2))
    return els[:limit]


#: Two detections on neighbouring frames are one element when their boxes overlap
#: this much (IoU) and their class agrees. A sprite moving under ~1/3 of its width
#: a frame stays linked; a clip's frames are 0.1-0.5 s apart.
TRACK_IOU = 0.3


def _iou(a: Sequence[float], b: Sequence[float]) -> float:
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def track(per_frame: Sequence[Sequence[Dict]]) -> List[Dict]:
    """A video's per-frame numbered elements -> its elements across the clip.

    Each track is {"class", "frames": [element | None, ...]} (one entry per frame),
    linked greedily frame to frame by box IoU >= TRACK_IOU within a class; a track
    that misses a frame can be picked up again on the next (a fading sprite dips
    under the score cut for a frame). Tracks are numbered in reading order of
    where each first appears, then by that frame, so an element keeps ONE number
    for the whole clip and the static parts of a board number as a still would."""
    n = len(per_frame)
    tracks: List[Dict] = []
    for f, els in enumerate(per_frame):
        free = list(range(len(els)))
        pairs = []
        for t, tr in enumerate(tracks):
            last = next((tr["frames"][g] for g in range(f - 1, max(-1, f - 3), -1)
                         if tr["frames"][g] is not None), None)
            if last is None:
                continue
            for i in free:
                if els[i]["class"] == tr["class"]:
                    v = _iou(last["box"], els[i]["box"])
                    if v >= TRACK_IOU:
                        pairs.append((v, t, i))
        used_t, used_i = set(), set()
        for v, t, i in sorted(pairs, reverse=True):
            if t in used_t or i in used_i:
                continue
            tracks[t]["frames"][f] = els[i]
            used_t.add(t)
            used_i.add(i)
        for i in free:
            if i not in used_i:
                tr = {"class": els[i]["class"], "frames": [None] * n}
                tr["frames"][f] = els[i]
                tracks.append(tr)

    def first(tr):
        f = next(g for g, e in enumerate(tr["frames"]) if e is not None)
        b = tr["frames"][f]["box"]
        return (round(((b[1] + b[3]) / 2) / 12), (b[0] + b[2]) / 2, f)

    return sorted(tracks, key=first)[:MAX_ELEMENTS]


def moment_frame(moment: int, n_frames: int) -> int:
    """The frame a video moment's elements are read on: the first of its pair
    (the processor merges frames 2m and 2m+1 into moment m)."""
    return min(2 * moment, n_frames - 1)


def on_frame(tracks: Sequence[Dict], f: int) -> List[Optional[Dict]]:
    """Frame `f`'s elements, indexed by track (None where a track is absent), so
    `element_at` over it answers with the TRACK's index."""
    return [tr["frames"][f] for tr in tracks]


def scale(els: Sequence[Dict], fx: float, fy: float) -> List[Dict]:
    """Elements detected on one size of a board, moved onto another (fx, fy = new/old)."""
    import cv2
    out = []
    for e in els:
        (x, y), m = e["mask"]
        x0, y0 = int(round(x * fx)), int(round(y * fy))
        w, h = max(1, int(round(m.shape[1] * fx))), max(1, int(round(m.shape[0] * fy)))
        mm = (cv2.resize(m.astype(np.uint8), (w, h), interpolation=cv2.INTER_NEAREST) > 0
              if m.size else np.zeros((0, 0), bool))
        b = e["box"]
        out.append({**e, "box": [b[0] * fx, b[1] * fy, b[2] * fx, b[3] * fy], "mask": ((x0, y0), mm)})
    return out


def _solid(mask) -> Tuple[Tuple[int, int], np.ndarray]:
    """The mask with its enclosed holes filled (a ring's centre is ON the ring) and
    grown by EDGE_PX. An open gap (a chain's break) is not enclosed, so it stays out."""
    import cv2
    (x, y), m = mask
    m = np.pad(m.astype(np.uint8), EDGE_PX + 1)
    filled = m.copy()
    ff = np.zeros((m.shape[0] + 2, m.shape[1] + 2), np.uint8)
    cv2.floodFill(filled, ff, (0, 0), 1)
    m = m | (filled == 0)
    k = np.ones((2 * EDGE_PX + 1, 2 * EDGE_PX + 1), np.uint8)
    m = cv2.dilate(m.astype(np.uint8), k) > 0
    return (x - EDGE_PX - 1, y - EDGE_PX - 1), m


def element_at(pt: Sequence[float], size: Tuple[int, int], els: Sequence[Dict]) -> Optional[int]:
    """0-based index of the smallest element (by mask area) whose mask holds the
    0-1000 point `pt` on a board of `size`, or None. A None in `els` (a track
    absent from this frame, `on_frame`) holds nothing but keeps its index."""
    x = int(round(pt[0] * size[0] / 1000.0))
    y = int(round(pt[1] * size[1] / 1000.0))
    best, area = None, None
    for i, e in enumerate(els):
        if e is None or not e["mask"][1].size:
            continue
        (mx, my), m = _solid(e["mask"])
        if 0 <= y - my < m.shape[0] and 0 <= x - mx < m.shape[1] and m[y - my, x - mx]:
            a = int(e["mask"][1].sum())
            if area is None or a < area:
                best, area = i, a
    return best


def ids_for(answer: Dict, size: Tuple[int, int], els: Sequence[Optional[Dict]]) -> Dict:
    """`answer` (generation 3's shape, 0-1000 points) with the 1-based number of
    the element under each point beside it: `ids` for clicks, `from_id`/`to_id`
    for drags, `handle_id` for a slide. A point on no element gets None, and a
    board with no elements gets no ids at all. `els` is what the board was shown
    with (a video's: `on_frame` of the answer's moment)."""
    if not any(e is not None for e in els):
        return answer
    def n(p):
        i = element_at(p, size, els)
        return None if i is None else i + 1
    out = dict(answer)
    if out.get("points") is not None:
        out["ids"] = [n(p) for p in out["points"]]
    if out.get("drags") is not None:
        out["drags"] = [{**d, "from_id": n(d["from"]), "to_id": n(d["to"])} for d in out["drags"]]
    if out.get("handle") is not None:
        out["handle_id"] = n(out["handle"])
    return out
