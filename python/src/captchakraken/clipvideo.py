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
import io
import math
from dataclasses import dataclass, field
from typing import List, Optional, Sequence, Tuple

import numpy as np
from PIL import Image

from .keyframes import to_gray

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
    g = np.stack([resize_linear(to_gray(f), 128, 128).astype(np.float32) for f in frames])
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
    out = [resize_area(frames[i], w, h) for i in idx]
    return ClipVideo(frames=out, source_indices=idx, source_fps=source_fps, period=period)


# The resizes below reproduce OpenCV's uint8 INTER_LINEAR and INTER_AREA bit for bit, because the model was
# trained on frames OpenCV cut: the same pixels in means the same period found and the same picture watched.

def _linear_taps(src: int, dst: int, area: bool,
                 clamp: bool) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Along one axis: the two source pixels each output pixel blends, and their 11-bit weights.

    `area` is INTER_AREA's upscaling rule. Only the horizontal pass clamps its weight at the edges; the vertical
    pass blends the clamped edge row with itself, whose rounded weights need not sum to 2048.
    """
    inv = dst / src
    d = np.arange(dst)
    if area:
        s = np.floor(d * (1.0 / inv)).astype(np.int64)
        f = ((d + 1) - (s + 1) * inv).astype(np.float32)
        f = np.where(f <= 0, np.float32(0), f - np.floor(f))
    else:
        f = ((d + 0.5) * (1.0 / inv) - 0.5).astype(np.float32)
        s = np.floor(f).astype(np.int64)
        f = f - s.astype(np.float32)
    if clamp:
        edge = (s < 0) | (s >= src - 1)
        f[edge] = 0
        s = np.clip(s, 0, src - 1)
    w1 = np.rint(f * np.float32(2048)).astype(np.int32)
    w0 = np.rint((np.float32(1) - f) * np.float32(2048)).astype(np.int32)
    return np.clip(s, 0, src - 1), np.clip(s + 1, 0, src - 1), w0, w1


def resize_linear(img: np.ndarray, w: int, h: int, area: bool = False) -> np.ndarray:
    """A uint8 image resized to (w, h) by OpenCV's fixed-point bilinear, with its SIMD rounding."""
    x0, x1, a0, a1 = _linear_taps(img.shape[1], w, area, clamp=True)
    y0, y1, b0, b1 = _linear_taps(img.shape[0], h, area, clamp=False)
    across = (slice(None),) + (None,) * (img.ndim - 2)
    down = (slice(None),) + (None,) * (img.ndim - 1)
    s = img.astype(np.int32)
    row = (np.take(s, x0, 1) * a0[across] + np.take(s, x1, 1) * a1[across]) >> 4
    out = (((np.take(row, y0, 0) * b0[down]) >> 16) + ((np.take(row, y1, 0) * b1[down]) >> 16) + 2) >> 2
    return out.astype(np.uint8)


def _area_taps(src: int, dst: int) -> Tuple[np.ndarray, np.ndarray]:
    """Along one axis: the source pixels each output pixel averages and their float32 weights, in
    OpenCV's order (padded with zero weights), since float32 sums depend on it."""
    scale = src / dst
    taps = []
    for d in range(dst):
        f1 = d * scale
        f2 = f1 + scale
        s2 = min(math.floor(f2), src - 1)
        s1 = min(math.ceil(f1), s2)
        cell = min(scale, src - f1)
        t = [(s1 - 1, (s1 - f1) / cell)] if s1 - f1 > 1e-3 else []
        t += [(x, 1 / cell) for x in range(s1, s2)]
        t += [(s2, min(min(f2 - s2, 1.0), cell) / cell)] if f2 - s2 > 1e-3 else []
        taps.append(t)
    k = max(map(len, taps))
    idx = np.array([[x for x, _ in t] + [0] * (k - len(t)) for t in taps])
    wt = np.array([[a for _, a in t] + [0.0] * (k - len(t)) for t in taps], dtype=np.float32)
    return idx, wt


def _area_pass(img: np.ndarray, axis: int, dst: int) -> np.ndarray:
    idx, wt = _area_taps(img.shape[axis], dst)
    shape = [1] * img.ndim
    shape[axis] = dst
    out = np.take(img, idx[:, 0], axis) * wt[:, 0].reshape(shape)
    for j in range(1, idx.shape[1]):
        out = out + np.take(img, idx[:, j], axis) * wt[:, j].reshape(shape)
    return out


def resize_area(img: np.ndarray, w: int, h: int) -> np.ndarray:
    """A uint8 image resized to (w, h) as OpenCV's INTER_AREA does it: a box average shrinking, bilinear growing."""
    H, W = img.shape[:2]
    if w > W or h > H:
        return resize_linear(img, w, h, area=True)
    if W % w == 0 and H % h == 0:
        sx, sy = W // w, H // h
        s = img.astype(np.int64).reshape(h, sy, w, sx, *img.shape[2:]).sum((1, 3))
        if (sx, sy) == (2, 2):
            return ((s + 2) >> 2).astype(np.uint8)
        return np.rint(s.astype(np.float32) * np.float32(1 / (sx * sy))).astype(np.uint8)
    out = _area_pass(_area_pass(img.astype(np.float32), 1, w), 0, h)
    return np.clip(np.rint(out), 0, 255).astype(np.uint8)


def encode_jpeg(frame: np.ndarray) -> bytes:
    """A BGR frame as JPEG at JPEG_QUALITY with 4:2:0 chroma, the settings the model was trained on."""
    buf = io.BytesIO()
    Image.fromarray(frame[..., ::-1]).save(buf, "JPEG", quality=JPEG_QUALITY, subsampling=2)
    return buf.getvalue()


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
