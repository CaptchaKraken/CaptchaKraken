"""Reduce a recorded clip to the few frames the model is shown.

Ported from the training-side extractor; the model answers with a frame NUMBER into this slicing, so a
divergence names a picture that does not exist (see TRIBAL_KNOWLEDGE.md). `region_box` / `region_diff_ratio`
are also the driver's wait-for-state gate, with the same box the label was chosen with.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import cv2
import numpy as np

from .kinds import KeyframeMode


DEFAULT_MAX_KEYFRAMES = 6

# Measured over 20 real clips: same picture <= 0.000067, smallest real state change >= 0.004282. The old 0.005
# sat ABOVE that change and collapsed ssqr8 to one still; it was calibrated on 64x64 fixtures.
DEFAULT_STEADY_RATIO = 0.001

# Licenses `cycle`'s collapse, where being generous discards the middle of a clip; deliberately not scaled
# with steady_ratio, and never applied to steady_screens (GeeTest svg screens are 0.005 apart).
DEFAULT_DISTINCT_RATIO = 0.02

# A hold is a deliberate resting state, not a frame that repeated mid-animation: 3 frames @ 10 fps ~ 0.3 s.
DEFAULT_MIN_HOLD_FRAMES = 3

# A 3-state cycle is ~0.9 held, a cross-fade ~0.0; the gap is wide.
DEFAULT_MIN_STEADY_COVERAGE = 0.5

# The one pixel threshold shared with every other movement check in the project.
_PIXEL_DELTA = 30

# One constant for both choosing the label's frame and the live wait: the two must ask the same question.
MATCH_REGION_HALF = 0.06

# Looser than steady_ratio: the live page carries antialiasing and cursor artefacts a keyframe does not.
MATCH_REGION_TOLERANCE = 0.05

MANIFEST_NAME = "keyframes.json"
KEYFRAME_DIR_NAME = "keyframes"


@dataclass(frozen=True)
class KeyframeParams:
    """Recorded in the manifest so a threshold change re-cuts a set instead of silently mixing two slicings."""

    max_keyframes: int = DEFAULT_MAX_KEYFRAMES
    steady_ratio: float = DEFAULT_STEADY_RATIO
    distinct_ratio: float = DEFAULT_DISTINCT_RATIO
    min_hold_frames: int = DEFAULT_MIN_HOLD_FRAMES
    min_steady_coverage: float = DEFAULT_MIN_STEADY_COVERAGE
    dedupe: bool = True

    def as_dict(self) -> Dict[str, Any]:
        return {
            "max_keyframes": self.max_keyframes,
            "steady_ratio": self.steady_ratio,
            "distinct_ratio": self.distinct_ratio,
            "min_hold_frames": self.min_hold_frames,
            "min_steady_coverage": self.min_steady_coverage,
            "dedupe": self.dedupe,
        }


@dataclass
class Keyframe:
    """`number` is 1-based and is what the model returns as `frame`; `source_index` keeps the provenance."""

    number: int
    source_index: int
    timestamp_ms: float
    image: Optional[np.ndarray] = None


@dataclass
class KeyframeSet:
    mode: KeyframeMode
    keyframes: List[Keyframe]
    source_frames: int
    fps: float
    params: KeyframeParams = field(default_factory=KeyframeParams)
    frame_states: List[int] = field(default_factory=list)
    # Independent of `mode`: EVEN says recurrence could not be proved from one burst, this says how many
    # screens the board sits on. Reading `mode` for that put the driver's wait off on 100% of real animated captchas.
    steady_screens: int = 0

    def __len__(self) -> int:
        return len(self.keyframes)

    def manifest(self, *, stem: str, filenames: Sequence[str]) -> Dict[str, Any]:
        return {
            "stem": stem,
            "mode": self.mode,
            "steady_screens": self.steady_screens,
            "fps": self.fps,
            "source_frames": self.source_frames,
            "params": self.params.as_dict(),
            "keyframes": [
                {
                    "number": kf.number,
                    "file": name,
                    "source_index": kf.source_index,
                    "timestamp_ms": round(kf.timestamp_ms, 1),
                }
                for kf, name in zip(self.keyframes, filenames)
            ],
        }


def region_box(
    size_wh: Tuple[int, int],
    point_norm: Tuple[float, float],
    half: float = MATCH_REGION_HALF,
) -> Tuple[int, int, int, int]:
    """Never empty: a comparison over no pixels reads as a perfect match and the gate would open on any state."""
    w, h = int(size_wh[0]), int(size_wh[1])
    cx, cy = float(point_norm[0]) * w, float(point_norm[1]) * h
    rx, ry = max(1.0, half * w), max(1.0, half * h)
    x1 = max(0, min(w - 1, int(round(cx - rx))))
    y1 = max(0, min(h - 1, int(round(cy - ry))))
    x2 = max(x1 + 1, min(w, int(round(cx + rx))))
    y2 = max(y1 + 1, min(h, int(round(cy + ry))))
    return x1, y1, x2, y2


def region_diff_ratio(
    a: np.ndarray, b: np.ndarray, box: Optional[Tuple[int, int, int, int]] = None
) -> float:
    if a is None or b is None or a.shape != b.shape:
        return 1.0
    if box is None:
        return frame_diff_ratio(a, b)
    x1, y1, x2, y2 = box
    return frame_diff_ratio(a[y1:y2, x1:x2], b[y1:y2, x1:x2])


def frame_diff_ratio(a: np.ndarray, b: np.ndarray) -> float:
    if a is None or b is None:
        return 1.0
    if a.shape != b.shape:
        return 1.0
    diff = cv2.absdiff(a, b)
    if diff.ndim == 3:
        diff = cv2.cvtColor(diff, cv2.COLOR_BGR2GRAY)
    _, thr = cv2.threshold(diff, _PIXEL_DELTA, 255, cv2.THRESH_BINARY)
    h, w = thr.shape[:2]
    if h * w == 0:
        return 1.0
    return cv2.countNonZero(thr) / float(h * w)



def _anchor_runs(frames: Sequence[np.ndarray], steady_ratio: float) -> List[Tuple[int, int]]:
    """Anchored on the run's first frame: a slow pan has every consecutive diff under the threshold."""
    runs: List[Tuple[int, int]] = []
    i = 0
    n = len(frames)
    while i < n:
        j = i
        while j + 1 < n and frame_diff_ratio(frames[i], frames[j + 1]) <= steady_ratio:
            j += 1
        runs.append((i, j))
        i = j + 1
    return runs


def _medoid(frames: Sequence[np.ndarray], indices: Sequence[int]) -> int:
    if len(indices) <= 2:
        return indices[0]
    best_idx, best_cost = indices[0], float("inf")
    for a in indices:
        cost = sum(frame_diff_ratio(frames[a], frames[b]) for b in indices if b != a)
        if cost < best_cost:
            best_idx, best_cost = a, cost
    return best_idx


def _even_indices(n: int, count: int) -> List[int]:
    if n <= count:
        return list(range(n))
    if count <= 1:
        return [0]
    out = [int(round(k * (n - 1) / (count - 1))) for k in range(count)]
    seen: List[int] = []
    for i in out:
        if i not in seen:
            seen.append(i)
    return seen


def _distinct_indices(
    frames: Sequence[np.ndarray], candidates: Sequence[int], params: KeyframeParams
) -> List[int]:
    """Drop repeats, then backfill: a duplicate makes the `frame` label ambiguous, a silently unanswerable question.

    Safer than a better cycle detector (a 2px/frame pan and a real 3-state board score alike on every path
    statistic tried); the backfill exists because symza holds nine screens and six samples found four.
    """
    kept: List[int] = []

    def is_new(i: int) -> bool:
        return not any(
            frame_diff_ratio(frames[i], frames[k]) <= params.steady_ratio for k in kept
        )

    for i in candidates:
        if is_new(i):
            kept.append(i)
    if len(kept) < params.max_keyframes:
        for i in range(len(frames)):
            if len(kept) >= params.max_keyframes:
                break
            if i not in kept and is_new(i):
                kept.append(i)
    return sorted(kept)


def _steady_screens(
    frames: Sequence[np.ndarray], params: KeyframeParams
) -> Optional[Tuple[List[Tuple[int, int]], List[int], List[int]]]:
    n = len(frames)
    runs = _anchor_runs(frames, params.steady_ratio)
    holds = [(s, e) for (s, e) in runs if (e - s + 1) >= params.min_hold_frames]
    if not holds:
        return None

    covered = sum(e - s + 1 for s, e in holds)
    if covered / float(n) < params.min_steady_coverage:
        return None

    state_reps: List[int] = []
    hold_state: List[int] = []
    for s, e in holds:
        rep = _medoid(frames, list(range(s, e + 1)))
        for k, existing in enumerate(state_reps):
            if frame_diff_ratio(frames[rep], frames[existing]) <= params.steady_ratio:
                hold_state.append(k)
                break
        else:
            if len(state_reps) >= params.max_keyframes:
                return None
            state_reps.append(rep)
            hold_state.append(len(state_reps) - 1)

    if len(state_reps) < 1:
        return None

    # No distinct_ratio here: the merge above already separated states by the measured noise floor.
    return holds, state_reps, hold_state


def steady_screens(frames: Sequence[np.ndarray], params: KeyframeParams) -> int:
    got = _steady_screens(frames, params)
    return len(got[1]) if got else 0


def _detect_cycle(
    frames: Sequence[np.ndarray], params: KeyframeParams
) -> Optional[Tuple[List[int], List[int]]]:
    n = len(frames)
    got = _steady_screens(frames, params)
    if got is None:
        return None
    holds, state_reps, hold_state = got

    # A cycle REVISITS. Equal counts is a one-way progression: a slow fade also decomposes into 2 long holds
    # (verified), and collapsing that to 2 frames discards the middle of the clip.
    if len(holds) <= len(state_reps) and len(state_reps) > 1:
        return None

    for a in range(len(state_reps)):
        for b in range(a + 1, len(state_reps)):
            if frame_diff_ratio(frames[state_reps[a]], frames[state_reps[b]]) < params.distinct_ratio:
                return None

    per_frame = [-1] * n
    for (s, e), state in zip(holds, hold_state):
        for i in range(s, e + 1):
            per_frame[i] = state
    return state_reps, per_frame


def _drop_smeared(
    frames: Sequence[np.ndarray], indices: Sequence[int], params: KeyframeParams
) -> List[int]:
    """Drop a sample caught mid-swap when both neighbouring holds are already kept.

    Not a pixel diff: snapping to the nearest hold turned [0, 16, 39] into [0, 16] on six clips, and a
    distinct_ratio test cut an hCaptcha tile-flip from 6 stills to 3 (two boards differ by one tile).
    """
    runs = _anchor_runs(frames, params.steady_ratio)
    holds = [(s, e) for (s, e) in runs if (e - s + 1) >= params.min_hold_frames]
    if not holds:
        return list(indices)

    state_of_hold: List[int] = []
    reps: List[int] = []
    for start, end in holds:
        rep = _medoid(frames, list(range(start, end + 1)))
        for k, existing in enumerate(reps):
            if frame_diff_ratio(frames[rep], frames[existing]) <= params.steady_ratio:
                state_of_hold.append(k)
                break
        else:
            reps.append(rep)
            state_of_hold.append(len(reps) - 1)

    def hold_of(i: int) -> Optional[int]:
        for k, (s, e) in enumerate(holds):
            if s <= i <= e:
                return k
        return None

    covered = {state_of_hold[h] for h in (hold_of(i) for i in indices)
               if h is not None}
    kept: List[int] = []
    for i in indices:
        if hold_of(i) is not None:
            kept.append(i)
            continue
        before = max((k for k, (s, e) in enumerate(holds) if e < i), default=None)
        after = min((k for k, (s, e) in enumerate(holds) if s > i), default=None)
        if before is not None and after is not None \
                and state_of_hold[before] in covered \
                and state_of_hold[after] in covered:
            continue
        kept.append(i)
    return kept


def extract_keyframes(
    frames: Sequence[np.ndarray],
    *,
    fps: float = 10.0,
    params: Optional[KeyframeParams] = None,
) -> KeyframeSet:
    if not frames:
        raise ValueError("no frames to extract keyframes from")
    p = params or KeyframeParams()
    n = len(frames)

    def _ms(i: int) -> float:
        return (i / fps) * 1000.0 if fps > 0 else 0.0

    cycle = _detect_cycle(frames, p)
    if cycle is not None:
        reps, per_frame = cycle
        mode = KeyframeMode.STATIC if len(reps) == 1 else KeyframeMode.CYCLE
        return KeyframeSet(
            steady_screens=len(reps),
            mode=mode,
            keyframes=[
                Keyframe(number=k + 1, source_index=idx, timestamp_ms=_ms(idx),
                         image=frames[idx])
                for k, idx in enumerate(reps)
            ],
            source_frames=n,
            fps=fps,
            params=p,
            frame_states=per_frame,
        )

    indices = _even_indices(n, p.max_keyframes)
    # Before dedup so a smear does not spend budget, and after because the backfill re-picks smears
    # (measured: filtering only before returned [0, 10, 12, 21, 25] with 10 and 21 the two smears).
    indices = _drop_smeared(frames, indices, p)
    if p.dedupe:
        indices = _distinct_indices(frames, indices, p)
        indices = _drop_smeared(frames, indices, p)
    return KeyframeSet(
        steady_screens=steady_screens(frames, p),
        mode=KeyframeMode.EVEN,
        keyframes=[
            Keyframe(number=k + 1, source_index=idx, timestamp_ms=_ms(idx),
                     image=frames[idx])
            for k, idx in enumerate(indices)
        ],
        source_frames=n,
        fps=fps,
        params=p,
    )




def _frame_filename(number: int) -> str:
    """Zero-padded because readers sort by name."""
    return f"frame_{number:02d}.png"


def write_keyframes(
    kfset: KeyframeSet, out_dir: str | os.PathLike, *, stem: str
) -> List[Path]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    # A re-slice from 6 to 3 would otherwise leave frame_04..06 for a glob to hand the model.
    for stale in out.glob("frame_*.png"):
        stale.unlink()

    paths: List[Path] = []
    names: List[str] = []
    for kf in kfset.keyframes:
        name = _frame_filename(kf.number)
        target = out / name
        if kf.image is None:
            raise ValueError(f"keyframe {kf.number} has no image to write")
        cv2.imwrite(str(target), kf.image)
        paths.append(target)
        names.append(name)

    with (out / MANIFEST_NAME).open("w") as f:
        json.dump(kfset.manifest(stem=stem, filenames=names), f, indent=2)
    return paths


def number_for_source_index(kfset: KeyframeSet, source_index: int) -> int:
    """The keyframe a given source frame belongs to (1-based), by POSITION.

    Exact in cycle mode (the frame's own state), else the nearest keyframe in time. A transition
    frame (state -1) has no state of its own, so where the pixels are at hand, matching by
    appearance around the action point is the better question.
    """
    if not kfset.keyframes:
        raise ValueError("keyframe set is empty")
    if kfset.mode == KeyframeMode.CYCLE and 0 <= source_index < len(kfset.frame_states):
        state = kfset.frame_states[source_index]
        if state >= 0:
            return state + 1
    return min(kfset.keyframes, key=lambda k: abs(k.source_index - source_index)).number



