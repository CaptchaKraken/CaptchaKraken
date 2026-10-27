"""Turn a recorded captcha clip into the frames the model watches as video.

Models on prompt generation 3 and later see an animated captcha through the video pathway rather than as
numbered stills: every two consecutive frames share one temporal patch, so motion reaches the vision encoder
directly. The frames travel as a JPEG sequence (`data:video/jpeg;base64,f0,f1,...`), so no codec is involved
and the server does not resample them. The model labels its answer with the time printed before a frame
pair (`"t": 1.3`), and `time_to_index` turns that back into the recorded frame the driver waits for.

A verbatim port of the module the model was trained with: if this copy trimmed, sampled or sized a clip
differently, the time the model answers with would name a different moment than the one it watched.
"""
from __future__ import annotations

import base64
import math
from dataclasses import dataclass, field
from typing import List, Optional, Sequence, Tuple

import cv2
import numpy as np

#: Bump when the cutting LOGIC changes in a way the constants below do not show;
#: cached frame sets carry it and are re-cut on mismatch (`clips.materialize_video`).
CUT_VERSION = 3
FPS = 5.0
MAX_FRAMES = 32
JPEG_QUALITY = 90
SIZE_FACTOR = 64
TEMPORAL_PATCH = 2
LOOP_RATIO = 0.5
LOOP_MIN_PERIOD_S = 0.6


@dataclass
class ClipVideo:
    frames: List[np.ndarray]
    source_indices: List[int]
    source_fps: float
    period: Optional[int] = None
    fps: float = FPS
    timestamps: List[float] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.timestamps:
            self.timestamps = pair_timestamps(len(self.frames), self.fps)


def frame_size(height: int, width: int, max_pixels: int) -> Tuple[int, int]:
    """(H, W): multiples of SIZE_FACTOR, area <= max_pixels.

    The largest such frame whose aspect is within ~10% of the clip's; the closest
    aspect only when none is. Most area first, because a 64-grid rarely hits the
    exact aspect and a perfect-aspect frame half the size is a worse picture.
    """
    aspect = height / width
    cands = [(h, w) for h in range(SIZE_FACTOR, 4097, SIZE_FACTOR)
             for w in range(SIZE_FACTOR, 4097, SIZE_FACTOR) if h * w <= max_pixels]
    if not cands:
        return SIZE_FACTOR, SIZE_FACTOR
    err = {c: abs(math.log((c[0] / c[1]) / aspect)) for c in cands}
    close = [c for c in cands if err[c] <= 0.1]
    if close:
        return max(close, key=lambda c: (c[0] * c[1], -err[c]))
    return min(cands, key=lambda c: (err[c], -c[0] * c[1]))


def find_period(frames: Sequence[np.ndarray], source_fps: float) -> Optional[int]:
    """The period P (in source frames) at which the WHOLE clip repeats, or None.

    The frame is split into 8x8 blocks. For every block that moves, frames P apart
    must differ by less than LOOP_RATIO of what neighbouring frames differ by in
    that block. Requiring every moving block (not the frame average) matters: one
    object out of step with the others means the clip does NOT loop, and trimming
    it would lose that object's other phase. A false "no loop" only costs tokens.
    """
    blocks = 8
    g = np.stack([cv2.resize(cv2.cvtColor(f, cv2.COLOR_BGR2GRAY), (128, 128)).astype(np.float32)
                  for f in frames])
    n = len(g)

    def per_block(d: np.ndarray) -> np.ndarray:
        return d.reshape(d.shape[0], blocks, 128 // blocks, blocks, 128 // blocks).mean((2, 4)).mean(0)

    step = per_block(np.abs(np.diff(g, axis=0)))
    active = step > max(0.25 * float(step.max()), 0.3)
    if not active.any():
        return None
    best_p, best_r = None, LOOP_RATIO
    for p in range(max(2, int(round(LOOP_MIN_PERIOD_S * source_fps))), n - 2):
        r = float((per_block(np.abs(g[p:] - g[:-p]))[active] / step[active]).max())
        if r < best_r:
            best_p, best_r = p, r
    return best_p


def pair_timestamps(n_frames: int, fps: float = FPS) -> List[float]:
    """The `<x.x seconds>` Qwen prints before each frame pair, as floats."""
    n = n_frames + (n_frames % TEMPORAL_PATCH)
    return [round((2 * k + 0.5) / fps, 1) for k in range(n // TEMPORAL_PATCH)]


def sample_indices(n_source: int, source_fps: float, period: Optional[int]) -> List[int]:
    window = period if period else n_source
    step = source_fps / FPS
    idx = [int(round(i * step)) for i in range(int(math.floor((window - 1) / step)) + 1)]
    idx = [i for i in idx if i < window] or [0]
    if len(idx) > MAX_FRAMES:
        idx = [int(round(x)) for x in np.linspace(0, window - 1, MAX_FRAMES)]
    if len(idx) % TEMPORAL_PATCH:
        nxt = min(idx[-1] + max(1, int(round(step))), n_source - 1)
        idx.append(nxt)
    return idx


def clip_video(frames: Sequence[np.ndarray], source_fps: float, *, max_pixels: int) -> ClipVideo:
    """The frames the model watches, resized and in order, plus where each came from."""
    if not frames:
        raise ValueError("empty clip")
    source_fps = float(source_fps) if source_fps and source_fps > 0 else 10.0
    period = find_period(frames, source_fps) if len(frames) > 4 else None
    idx = sample_indices(len(frames), source_fps, period)
    h, w = frame_size(frames[0].shape[0], frames[0].shape[1], max_pixels)
    out = [cv2.resize(frames[i], (w, h), interpolation=cv2.INTER_AREA) for i in idx]
    return ClipVideo(frames=out, source_indices=idx, source_fps=source_fps, period=period)


def encode_jpeg(frame: np.ndarray) -> bytes:
    ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
    if not ok:
        raise ValueError("jpeg encode failed")
    return buf.tobytes()


def data_url(clip: ClipVideo) -> str:
    """vLLM's `video_url` for this clip: a JPEG sequence, no container, no codec."""
    return "data:video/jpeg;base64," + ",".join(
        base64.b64encode(encode_jpeg(f)).decode("ascii") for f in clip.frames)


def media_io_kwargs(fps: float = FPS) -> dict:
    """What vLLM must be started with (`--media-io-kwargs`) to read data_url() as sent."""
    return {"video": {"num_frames": -1, "fps": fps}}


def time_to_index(clip: ClipVideo, t: float) -> int:
    """The SOURCE frame a `"t"` answer names: the first frame of the nearest pair."""
    k = min(range(len(clip.timestamps)), key=lambda i: abs(clip.timestamps[i] - float(t)))
    j = min(TEMPORAL_PATCH * k, len(clip.source_indices) - 1)
    return clip.source_indices[j]


def index_to_time(clip: ClipVideo, source_index: int) -> float:
    """The `"t"` that names a source frame: the FIRST pair lying wholly at or after it.

    A label names the first moment the answer is known and clear, so it rounds
    FORWARD by whole pairs, never to the nearest pair. Nearest put the bee's last
    landing (frame 47) on a pair still showing the bee in flight. A frame outside
    the kept loop is folded back into it first; a frame after the last pair takes
    the last pair.
    """
    s = int(source_index)
    if clip.period:
        s %= clip.period
    idx = clip.source_indices
    for k, ts in enumerate(clip.timestamps):
        pair = idx[TEMPORAL_PATCH * k:TEMPORAL_PATCH * (k + 1)]
        if pair and min(pair) >= s:
            return ts
    return clip.timestamps[-1]
