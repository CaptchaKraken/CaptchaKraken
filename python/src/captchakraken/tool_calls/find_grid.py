import cv2
import numpy as np
import os
import tempfile
from dataclasses import dataclass
from typing import List, Tuple, Optional
from ..kinds import LabelPosition
from ..overlay import add_overlays_to_image

# Grid detection: trace every gutter as a consistent-colour walk, cluster the traces, form an evenly spaced
# lattice, then gate it on structure and on cell content. The colour comb and seal test are the second cue
# (see _comb_lines and TRIBAL_KNOWLEDGE.md). Every threshold below is measured; each gate has a test named for it.

COLOR_TOL = 10.0
# Tolerates JPEG and lighting jitter along a real gutter; a real tile edge is far beyond it.
CONT_TOL = 14.0
CONT_TOL2 = CONT_TOL * CONT_TOL
# Gate on L alone: a gutter's L span is ~3 while grass drifts ~32, and a/b are JPEG chroma noise that CIE76
# over-weights (it wrongly dropped real tinted-grey gutters).
SEED_L_TOL = 6.0
# A gutter never jumps between consecutive pixels (|dL| <= ~2); grass jumps up to ~16.
STEP_L_TOL = 4.0
MIN_RUN = 10
# No longer a hard reject: a white gutter adjacent to white tile content reads as one band far thicker.
MAX_THICKNESS = 14
PERP_SCAN = 60
# On a miss, look this far perpendicular for the gutter colour before calling it a wall; ~3px tolerates ~25 deg.
PERP_REFIND = 3
# How far the walk tolerances widen per unit of measured noise; 0 restores the fixed thresholds exactly.
NOISE_GAIN = 2.0
MAX_PERP_JUMP = 6.0
MERGE_PX = 8.0
MERGE_ANGLE = 0.07
MIN_CELL = 36
# Fractions of the cell PITCH, not pixels: hCaptcha gutters are ~13px median, so a fixed offset probed gutter
# against gutter and read zero contrast.
FLANK_PITCH_FRACS = (0.18, 0.26, 0.34, 0.42)
# Per grid and as a MEAN of both flanks: under `min` the lowest true hCaptcha grid scored 2.7 against false
# positives at 9.0, under mean 17.4 against 18.0/14.1. 18.1 clears both but sits 0.3 under a real reCAPTCHA 4x4.
GRID_FLANK_MIN_DE = 16.0
LINE_STD_TOL = 7.0
STEP = 1
SLANT_CAP = 0.47
SUPPORT_FRAC = 0.42
TERM_FRAC = 0.30
# A gutter spans the full image so a central band seeds it; narrowing from 0.46 cut trace attempts ~25%.
MAX_SEED_FRAC = 0.34
EDGE_MARGIN = 0.02
GRID_COLOR_TOL = 8.0
GRID_THICK_TOL = 4.0
GRID_ANGLE_TOL = 0.09
# Real grids share one gutter colour across both axes; photo "grids" pair an H edge of one colour with a V edge of another.
XAXIS_COLOR_TOL = 6.0
LATTICE_TOL = 0.18
MAX_OFF_LATTICE = 1
EVEN_TOL = 0.18
# Measured floor over 2239 real grids is 0.348. Deliberately not 0.33: that also catches one observed video
# false positive at 0.322 but leaves 5% headroom, buying a false-positive fix with a future missed grid.
MIN_IMAGE_AREA_COVERAGE = 0.30
# Applied to the EMITTED cells: the line check cannot see degenerate boxes built from near-duplicate lines.
CELL_REGULARITY_TOL = 0.12
MIN_GRID_DIM = 3
# A true internal line has perpendicular gutters running ~a full cell past it on both sides; a frame line does not.
CORROB_FRAC = 0.9
GRID_OVERSHOOT = 0.35
FULL_SPAN_MARGIN = 0.5
MIN_GRID_COVERAGE = 0.72
CELL_INSET = 0.22
# A flat region (white wall, sky, watermark haze) has "cells" the same colour as its "gutters".
CELL_DIVERGE_TOL = 12.0
CELL_DIVERGE_FRAC = 0.6
# Real-grid gutters measure color_std ~0-2; textured-photo pseudo-gutters run ~3-6.
CLEAN_GUTTER_STD = 2.3
# Only when the gutters are clean: a painted-gutter grid with sky tiles legitimately has fewer content cells.
CELL_DIVERGE_FRAC_CLEAN = 0.42
# A gutter's ridge run covers >= 0.88 of the scan, content fragments p90 ~0.35; drops ~95% of dead seeds (~73% of walk steps).
SEED_RUN_FRAC = 0.5
SEED_DECIMATE = 2
CLEAN_LATTICE_STD = 2.0
MAX_VIRTUAL_FRAC = 0.5
MAX_VIRTUAL_NODES = 2
# Per corroborated internal line a candidate leaves out, so a 4x4's [r1,r2,r3] is not dropped to [r2,r3].
UNUSED_LINE_PENALTY = 400.0
VIRTUAL_NODE_PENALTY = 600.0
# Outweighs the virtual-node penalty so a completed 4x4 beats the 3-row subset whose gutters run a cell past the border.
SPAN_FIT_PENALTY = 900.0
# hCaptcha's V gutters reach the submit bar (~0.65 cell) without implying another cell.
MISSING_LINE_FRAC = 0.8
# Real grids are inset ~60-120px; a gutter reaching the image edge is bleeding into a margin, not a cell.
EDGE_BLEED_PX = 6
# Count clusters, not lines: the plateau on the real corpus is 17..23; at 24 a textured drag puzzle becomes a false positive.
OFF_LATTICE_CLUSTER_PX = 20
MAX_OFF_LATTICE_CLEAN = 1
# Tight on purpose: on the failing 4x4s the gutter is pure white (L 100.0) against sky at L 95-97.
COMB_TOL = 3.0
# The scan band crosses the vendor's header/footer chrome, which costs a true gutter ~8% of its scan.
COMB_COVER = 0.9
# Taking the strictly contiguous run reported a full-width 520px gutter as a 43px stub (JPEG ringing).
COMB_GAP = 8
# Not zero: a blank canvas seals every lattice and its cells read exactly 0.0; a 4x4 of open sky reads 2.3-11.2.
SEALED_DIVERGE_TOL = 2.0
# Real 4x4s over unbroken sky measure 6.x-7.1; at 8.0 two stayed undetected. Free on the FP side (16 at 6/7/8 alike).
SEALED_FLANK_MIN_DE = 6.0
GRID_SEAL_MIN = 0.85
# Above UNUSED_LINE_PENALTY, or a candidate that swallowed a half-width sky belt outscores the true lattice.
UNSEALED_PENALTY = 700.0
# Real comb blocks are 2-12px; chrome bands 19-83.
COMB_MAX_THICK = MAX_THICKNESS
OFF_LATTICE_CLEAN_STD = 2.6


@dataclass
class PotentialGridLine:
    orientation: str
    angle: float
    thickness: float
    start: Tuple[float, float]
    end: Tuple[float, float]
    color_lab: np.ndarray
    color_std: float
    midline_pos: float
    support: int


def _de(a, b):
    d = a - b
    return float(np.sqrt(np.dot(d, d)))


def _de2(a, b):
    d0 = a[0] - b[0]; d1 = a[1] - b[1]; d2 = a[2] - b[2]
    return d0 * d0 + d1 * d1 + d2 * d2


def _line_extent(line):
    if line.orientation == 'h':
        return abs(line.end[0] - line.start[0])
    return abs(line.end[1] - line.start[1])


def _cell_divergences(lab, boxes, gutter_color):
    h, w = lab.shape[:2]
    out = []
    for (x1, y1, x2, y2) in boxes:
        bw, bh = x2 - x1, y2 - y1
        ix1 = int(x1 + CELL_INSET * bw); ix2 = int(x2 - CELL_INSET * bw)
        iy1 = int(y1 + CELL_INSET * bh); iy2 = int(y2 - CELL_INSET * bh)
        ix1 = max(0, min(w - 1, ix1)); ix2 = max(ix1 + 1, min(w, ix2))
        iy1 = max(0, min(h - 1, iy1)); iy2 = max(iy1 + 1, min(h, iy2))
        patch = lab[iy1:iy2, ix1:ix2].reshape(-1, 3)
        if patch.shape[0] == 0:
            out.append(0.0); continue
        mean = patch.mean(axis=0)
        out.append(_de(mean, gutter_color))
    return out


def _cells_have_content(lab, boxes, rows, cols, gutter_lines, sealed=False):
    """The false-positive killer. Not every row must have content: a reCAPTCHA 4x4's top row can reach into the header."""
    if lab is None:
        return True
    gutter_color = np.mean([l.color_lab for l in gutter_lines], axis=0)
    divs = _cell_divergences(lab, boxes, gutter_color)
    if not divs or len(divs) != rows * cols:
        return False
    gutter_std = float(np.mean([l.color_std for l in gutter_lines]))
    frac = CELL_DIVERGE_FRAC_CLEAN if gutter_std < CLEAN_GUTTER_STD else CELL_DIVERGE_FRAC
    tol = SEALED_DIVERGE_TOL if sealed else CELL_DIVERGE_TOL
    return sum(1 for d in divs if d > tol) >= frac * len(divs)


# OKLab scaled onto CIELAB units so every tuned constant keeps its meaning.
_OK_L_SCALE = 100.0
_OK_AB_SCALE = 300.0

_OK_M1 = np.array([[0.4122214708, 0.5363325363, 0.0514459929],
                   [0.2119034982, 0.6806995451, 0.1073969566],
                   [0.0883024619, 0.2817188376, 0.6299787005]], dtype=np.float32)
_OK_M2 = np.array([[0.2104542553, 0.7936177850, -0.0040720468],
                   [1.9779984951, -2.4285922050, 0.4505937099],
                   [0.0259040371, 0.7827717662, -0.8086757660]], dtype=np.float32)

_SRGB_TO_LINEAR = np.where(
    np.arange(256, dtype=np.float32) / 255.0 <= 0.04045,
    (np.arange(256, dtype=np.float32) / 255.0) / 12.92,
    (((np.arange(256, dtype=np.float32) / 255.0) + 0.055) / 1.055) ** 2.4,
).astype(np.float32)


def _to_lab(img_bgr):
    """OKLab: CIE76 over-weights a/b, which is why the walk gates on L alone. ~2-3ms against find_grid's ~53ms; a GPU was rejected."""
    rgb_lin = _SRGB_TO_LINEAR[img_bgr[:, :, ::-1]]
    lms = rgb_lin @ _OK_M1.T
    np.cbrt(lms, out=lms)
    ok = lms @ _OK_M2.T
    ok[:, :, 0] *= _OK_L_SCALE
    ok[:, :, 1] *= _OK_AB_SCALE
    ok[:, :, 2] *= _OK_AB_SCALE
    return ok


def _runlength(same, axis):
    s = same.astype(np.int32)
    out = np.zeros_like(s)
    if axis == 1:
        out[:, 0] = s[:, 0]
        for j in range(1, s.shape[1]):
            out[:, j] = (out[:, j - 1] + 1) * s[:, j]
    else:
        out[0, :] = s[0, :]
        for i in range(1, s.shape[0]):
            out[i, :] = (out[i - 1, :] + 1) * s[i, :]
    return out


def _build_ridge_map(lab, axis):
    h, w = lab.shape[:2]
    if axis == 1:
        diff = lab[:, 1:, :] - lab[:, :-1, :]
        de = np.sqrt(np.sum(diff * diff, axis=2))
        same = np.concatenate([np.zeros((h, 1), bool), de < COLOR_TOL], axis=1)
        run = _runlength(same, 1)
        end_ok = run >= (MIN_RUN - 1)
        ridge = end_ok.copy()
        for j in range(w - 2, -1, -1):
            ridge[:, j] |= ridge[:, j + 1] & same[:, j + 1]
    else:
        diff = lab[1:, :, :] - lab[:-1, :, :]
        de = np.sqrt(np.sum(diff * diff, axis=2))
        same = np.concatenate([np.zeros((1, w), bool), de < COLOR_TOL], axis=0)
        run = _runlength(same, 0)
        end_ok = run >= (MIN_RUN - 1)
        ridge = end_ok.copy()
        for i in range(h - 2, -1, -1):
            ridge[i, :] |= ridge[i + 1, :] & same[i + 1, :]
    return ridge




def _seed_thickness(lab, axis, cx, cy, ref):
    h, w = lab.shape[:2]
    ix, iy = int(round(cx)), int(round(cy))
    if not (0 <= iy < h and 0 <= ix < w):
        return 1.0
    up = dn = 0
    if axis == 1:
        i = iy - 1
        while i >= 0 and up < PERP_SCAN and _de2(lab[i, ix], ref) <= COLOR_TOL ** 2:
            up += 1; i -= 1
        i = iy + 1
        while i < h and dn < PERP_SCAN and _de2(lab[i, ix], ref) <= COLOR_TOL ** 2:
            dn += 1; i += 1
    else:
        i = ix - 1
        while i >= 0 and up < PERP_SCAN and _de2(lab[iy, i], ref) <= COLOR_TOL ** 2:
            up += 1; i -= 1
        i = ix + 1
        while i < w and dn < PERP_SCAN and _de2(lab[iy, i], ref) <= COLOR_TOL ** 2:
            dn += 1; i += 1
    return float(up + dn + 1)


def _split_runs(sorted_idx):
    sorted_idx = np.asarray(sorted_idx)
    if sorted_idx.size == 0:
        return []
    breaks = np.where(np.diff(sorted_idx) > 1)[0] + 1
    return np.split(sorted_idx, breaks)


def _batch_gather(lab, axis, along_i, perp_i):
    if axis == 1:
        return lab[perp_i, along_i]
    return lab[along_i, perp_i]


def image_noise(lab):
    """p90 lightness step between adjacent BRIGHT pixels: ~0 for a compositor-painted gutter, higher after JPEG or rescaling."""
    L = lab[:, :, 0]
    bright = L > 85
    dh = np.abs(np.diff(L, axis=1)); mh = bright[:, :-1] & bright[:, 1:]
    dv = np.abs(np.diff(L, axis=0)); mv = bright[:-1, :] & bright[1:, :]
    vals = np.concatenate([dh[mh], dv[mv]])
    if vals.size < 100:
        return 0.0
    return float(np.percentile(vals, 90))


def walk_tolerances(noise):
    """Scaled, not raised: a flat SEED_L/STEP_L of 10/8 drops a pristine sample and 14/12 drops four."""
    return (SEED_L_TOL + NOISE_GAIN * noise,
            STEP_L_TOL + NOISE_GAIN * noise,
            (CONT_TOL + NOISE_GAIN * noise) ** 2)


def _batch_accept(pix, seed_L, prev_L, line_color, tols):
    seed_tol, step_tol, cont_tol2 = tols
    L = pix[:, 0]
    d0 = pix[:, 0] - line_color[:, 0]
    d1 = pix[:, 1] - line_color[:, 1]
    d2 = pix[:, 2] - line_color[:, 2]
    de2 = d0 * d0 + d1 * d1 + d2 * d2
    return ((np.abs(L - seed_L) <= seed_tol)
            & (np.abs(L - prev_L) <= step_tol)
            & (de2 <= cont_tol2))


def _walk_dir(lab, axis, along_seed, perp_seed, seed_ref, direction, tols):
    h, w = lab.shape[:2]
    N = along_seed.shape[0]
    along_max = (w - 1) if axis == 1 else (h - 1)
    perp_max = (h - 1) if axis == 1 else (w - 1)
    seed_L = seed_ref[:, 0]

    perp = perp_seed.astype(np.float64).copy()
    along = along_seed.astype(np.float64).copy()
    prev_L = seed_L.copy()
    line_color = seed_ref.astype(np.float64).copy()
    line_n = np.ones(N, dtype=np.float64)
    last_along = along_seed.astype(np.float64).copy()
    last_perp = perp_seed.astype(np.float64).copy()
    support = np.zeros(N, dtype=np.int64)
    active = np.ones(N, dtype=bool)

    while active.any():
        ai = np.where(active)[0]
        al = along[ai] + direction * STEP
        in_b = (al >= 0) & (al <= along_max)
        if not in_b.all():
            active[ai[~in_b]] = False
            keep = in_b
            ai = ai[keep]; al = al[keep]
            if ai.size == 0:
                break
        pe = perp[ai]
        ali = al.astype(np.intp); pei = pe.astype(np.intp)
        pix = _batch_gather(lab, axis, ali, pei)
        ok = _batch_accept(pix, seed_L[ai], prev_L[ai], line_color[ai], tols)

        new_perp = pe.copy()
        new_pix = pix.copy()
        accepted = ok.copy()

        if not ok.all():
            still = ~ok
            for d in range(1, PERP_REFIND + 1):
                for s in (-1, +1):
                    sid = np.where(still)[0]
                    if sid.size == 0:
                        break
                    cand_pe = pe[sid] + s * d
                    inb = (cand_pe >= 0) & (cand_pe <= perp_max)
                    sid = sid[inb]; cand_pe = cand_pe[inb]
                    if sid.size == 0:
                        continue
                    cpx = _batch_gather(lab, axis, al[sid].astype(np.intp),
                                        cand_pe.astype(np.intp))
                    passc = _batch_accept(cpx, seed_L[ai[sid]],
                                          prev_L[ai[sid]], line_color[ai[sid]], tols)
                    hit = sid[passc]
                    if hit.size:
                        new_perp[hit] = cand_pe[passc]
                        new_pix[hit] = cpx[passc]
                        accepted[hit] = True
                        still[hit] = False
                if not still.any():
                    break

        adv = np.where(accepted)[0]
        if adv.size:
            gid = ai[adv]
            ln = line_n[gid]
            line_color[gid] = (line_color[gid] * ln[:, None] + new_pix[adv]) / (ln[:, None] + 1)
            line_n[gid] = ln + 1
            prev_L[gid] = new_pix[adv, 0]
            perp[gid] = new_perp[adv]
            along[gid] = al[adv]
            last_perp[gid] = new_perp[adv]
            last_along[gid] = al[adv]
            support[gid] += 1
        active[ai[~accepted]] = False

    return last_along, last_perp, support


def _walk_batch(lab, axis, along_seed, perp_seed, seed_ref, tols):
    fa, fp, ns_f = _walk_dir(lab, axis, along_seed, perp_seed, seed_ref, +1, tols)
    ba, bp, ns_b = _walk_dir(lab, axis, along_seed, perp_seed, seed_ref, -1, tols)
    a_hi = np.maximum(along_seed.astype(np.float64), fa)
    a_lo = np.minimum(along_seed.astype(np.float64), ba)
    return a_lo, a_hi, bp, fp, ns_f + ns_b




def _principal_dir_2d(centered):
    cxx = float(np.dot(centered[:, 0], centered[:, 0]))
    cyy = float(np.dot(centered[:, 1], centered[:, 1]))
    cxy = float(np.dot(centered[:, 0], centered[:, 1]))
    tr = cxx + cyy
    det = cxx * cyy - cxy * cxy
    disc = max(0.0, (tr * tr) / 4.0 - det)
    lam = tr / 2.0 + np.sqrt(disc)
    if abs(cxy) > 1e-9:
        v = np.array([lam - cyy, cxy], dtype=np.float64)
    elif cxx >= cyy:
        v = np.array([1.0, 0.0])
    else:
        v = np.array([0.0, 1.0])
    n = np.hypot(*v)
    return v / n if n > 1e-9 else np.array([1.0, 0.0])


def _collect_seeds(lab, axis, ridge, c_lo, c_hi, span):
    h, w = lab.shape[:2]
    lo, hi = int(span * (0.5 - MAX_SEED_FRAC)), int(span * (0.5 + MAX_SEED_FRAC))
    scan_w = c_hi - c_lo
    along_s, perp_s = [], []
    for c in range(lo, hi + 1, SEED_DECIMATE):
        if axis == 1:
            runs = _split_runs(np.where(ridge[c, c_lo:c_hi])[0] + c_lo)
        else:
            runs = _split_runs(np.where(ridge[c_lo:c_hi, c])[0] + c_lo)
        for run in runs:
            if len(run) < MIN_RUN or len(run) < SEED_RUN_FRAC * scan_w:
                continue
            chosen = None
            mid = len(run) // 2
            for idx in [mid, int(len(run) * 0.25), int(len(run) * 0.75)]:
                if 0 <= idx < len(run):
                    a = float(run[idx])
                    if axis == 1:
                        sx, sy = a, float(c)
                    else:
                        sx, sy = float(c), a
                    if 0 <= int(sy + 0.5) < h and 0 <= int(sx + 0.5) < w:
                        chosen = a; break
            if chosen is None:
                continue
            along_s.append(chosen)
            perp_s.append(float(c))
    if not along_s:
        return (np.empty(0), np.empty(0), np.empty((0, 3)))
    along_seed = np.array(along_s, dtype=np.float64)
    perp_seed = np.array(perp_s, dtype=np.float64)
    if axis == 1:
        seed_ref = lab[perp_seed.astype(np.intp), along_seed.astype(np.intp)].astype(np.float64)
    else:
        seed_ref = lab[along_seed.astype(np.intp), perp_seed.astype(np.intp)].astype(np.float64)
    return along_seed, perp_seed, seed_ref


def _trace_lines(lab, axis, seed_bias, tols=None):
    h, w = lab.shape[:2]
    if tols is None:
        tols = walk_tolerances(image_noise(lab))
    ridge = _build_ridge_map(lab, axis)
    if axis == 1:
        span = h; c_lo, c_hi = int(w * 0.2), int(w * 0.8)
    else:
        span = w; c_lo, c_hi = int(h * 0.2), int(h * 0.8)
    along_seed, perp_seed, seed_ref = _collect_seeds(lab, axis, ridge, c_lo, c_hi, span)
    if along_seed.size == 0:
        return []
    a_lo, a_hi, perp_lo, perp_hi, support = _walk_batch(lab, axis, along_seed, perp_seed, seed_ref, tols)

    full = w if axis == 1 else h
    lines = []
    for i in range(along_seed.size):
        if support[i] < MIN_RUN:
            continue
        span_i = a_hi[i] - a_lo[i]
        if span_i < SUPPORT_FRAC * full:
            continue
        if axis == 1:
            pts = np.array([(along_seed[i], perp_seed[i]),
                            (a_lo[i], perp_lo[i]), (a_hi[i], perp_hi[i])], dtype=np.float64)
        else:
            pts = np.array([(perp_seed[i], along_seed[i]),
                            (perp_lo[i], a_lo[i]), (perp_hi[i], a_hi[i])], dtype=np.float64)
        mean = pts.mean(axis=0)
        dv = _principal_dir_2d(pts - mean)
        if axis == 1:
            ang = np.arctan2(dv[1], dv[0])
            if abs(ang) > np.pi / 2:
                ang -= np.copysign(np.pi, ang)
            slant = np.tan(ang)
            midline = mean[1] + slant * (w / 2.0 - mean[0])
        else:
            ang = np.arctan2(dv[0], dv[1])
            if abs(ang) > np.pi / 2:
                ang -= np.copysign(np.pi, ang)
            slant = np.tan(ang)
            midline = mean[0] + slant * (h / 2.0 - mean[1])
        if abs(slant) > SLANT_CAP:
            continue
        a0 = a_lo[i]; a1 = a_hi[i]
        aa = np.arange(a0, a1 + 1, 3.0)
        if axis == 1:
            xs = aa; ys = midline + slant * (xs - w / 2.0)
        else:
            ys = aa; xs = midline + slant * (ys - h / 2.0)
        jx = np.round(xs).astype(np.intp); jy = np.round(ys).astype(np.intp)
        inb = (jy >= 0) & (jy < h) & (jx >= 0) & (jx < w)
        if not inb.any():
            continue
        cols = lab[jy[inb], jx[inb]].astype(np.float64)
        color_std = float(np.mean(np.std(cols, axis=0)))
        if color_std > LINE_STD_TOL:
            continue
        if axis == 1:
            start = (a0, midline + slant * (a0 - w / 2.0))
            end = (a1, midline + slant * (a1 - w / 2.0))
        else:
            start = (midline + slant * (a0 - h / 2.0), a0)
            end = (midline + slant * (a1 - h / 2.0), a1)
        lines.append(PotentialGridLine(
            orientation='h' if axis == 1 else 'v',
            angle=float(ang), thickness=0.0,
            start=start, end=end,
            color_lab=cols.mean(axis=0), color_std=color_std,
            midline_pos=float(midline), support=int(support[i]),
        ))
    return _merge_lines(lines)


def _merge_lines(lines):
    """Cluster by position only: angle-gating left noisy fragments of one gutter as separate near-duplicates."""
    if not lines:
        return []
    lines = sorted(lines, key=lambda l: l.midline_pos)
    merged = []
    cur = [lines[0]]
    for ln in lines[1:]:
        if abs(ln.midline_pos - cur[-1].midline_pos) < MERGE_PX:
            cur.append(ln)
        else:
            merged.append(_pick(cur)); cur = [ln]
    merged.append(_pick(cur))
    return merged


def _pick(group):
    """Position is the support-weighted mean; colour comes from the cleanest member of comparable support.

    The longest trace is often seeded at the gutter's edge and runs along tile content (ice_cream4: 11px off,
    std 2.80 vs 0.55-0.80 on-centre, 2026-08-11); nearest-to-centre swapped a 0.00 trace for a 3.43 one on rhitt.
    """
    best = max(group, key=lambda l: l.support)
    wsum = sum(l.support for l in group)
    centre = sum(l.midline_pos * l.support for l in group) / wsum
    strong = [l for l in group if l.support >= 0.5 * best.support] or group
    cleanest = min(strong, key=lambda l: (l.color_std, abs(l.midline_pos - centre)))
    best.midline_pos = centre
    best.support = max(l.support for l in group)
    best.color_lab = cleanest.color_lab
    best.color_std = cleanest.color_std
    return best


def _comb_lines(lab, axis, color):
    """Second cue: full-span lines every pixel of which is the gutter colour the tracer already proved is painted.

    The local walk loses a gutter whose neighbours are nearly its colour (rrv7m: gutters at 103/200/297 came
    back as 66/96/215). Axis-aligned by construction, so tilted grids stay the tracer's.
    """
    h, w = lab.shape[:2]
    d = lab - color
    m = (d * d).sum(axis=2) < COMB_TOL * COMB_TOL
    if axis == 1:
        lo, hi = int(w * (0.5 - MAX_SEED_FRAC)), int(w * (0.5 + MAX_SEED_FRAC))
        cov = m[:, lo:hi].mean(axis=1)
    else:
        lo, hi = int(h * (0.5 - MAX_SEED_FRAC)), int(h * (0.5 + MAX_SEED_FRAC))
        cov = m[lo:hi, :].mean(axis=0)
    mid = (lo + hi) // 2
    total = h if axis == 1 else w
    out = []
    for blk in _split_runs(np.where(cov >= COMB_COVER)[0]):
        if len(blk) > COMB_MAX_THICK:
            continue
        pos = float(blk.mean())
        # The page margin is the gutter colour too; left in, it corroborates every line on the other axis and a 3x3 reads as 4x3.
        if not (total * EDGE_MARGIN < pos < total * (1 - EDGE_MARGIN)):
            continue
        i = int(round(pos))
        along = m[i] if axis == 1 else m[:, i]
        idx = np.where(along)[0]
        grp = (np.split(idx, np.where(np.diff(idx) > COMB_GAP)[0] + 1)
               if idx.size else [])
        run = next((r for r in grp if r[0] <= mid <= r[-1]), None)
        if run is None or len(run) < MIN_RUN:
            continue
        a, b = float(run[0]), float(run[-1])
        cols = (lab[i, run] if axis == 1 else lab[run, i]).astype(np.float64)
        out.append(PotentialGridLine(
            orientation='h' if axis == 1 else 'v', angle=0.0,
            thickness=float(len(blk)),
            start=(a, pos) if axis == 1 else (pos, a),
            end=(b, pos) if axis == 1 else (pos, b),
            color_lab=cols.mean(axis=0),
            color_std=float(np.mean(np.std(cols, axis=0))),
            midline_pos=pos, support=int(len(run))))
    return out


def _comb_axis(lines, comb):
    """The comb wins on position only; extent comes from the longer trace (a comb extent stops at the first off-colour stretch)."""
    out, used = [], set()
    for c in comb:
        near = [l for l in lines if abs(l.midline_pos - c.midline_pos) < MERGE_PX]
        best = max(near, key=_line_extent, default=None)
        if best is not None and _line_extent(best) > _line_extent(c):
            best.midline_pos = c.midline_pos
            c = best
        used.update(id(l) for l in near)
        out.append(c)
    return sorted(out + [l for l in lines if id(l) not in used],
                  key=lambda l: l.midline_pos)


def _add_comb_lines(lab, h_lines, v_lines):
    """Colour is the median of the clean traces of BOTH axes, so a starved axis is rescued by the other's evidence."""
    clean = [l for l in h_lines + v_lines if l.color_std < CLEAN_LATTICE_STD]
    if not clean:
        return h_lines, v_lines
    color = np.median(np.array([l.color_lab for l in clean]), axis=0)
    return (_comb_axis(h_lines, _comb_lines(lab, 1, color)),
            _comb_axis(v_lines, _comb_lines(lab, 0, color)))


def _generate_grid(rows, cols, hs, vs, hd, vd, h, w, slant):
    mid_x, mid_y = w / 2, h / 2
    y_bounds = [hs[0] - hd] + list(hs) + [hs[-1] + hd]
    x_bounds = [vs[0] - vd] + list(vs) + [vs[-1] + vd]
    grid_boxes = []
    s2 = slant * slant
    denom = 1 + s2
    for i in range(len(y_bounds) - 1):
        for j in range(len(x_bounds) - 1):
            corners = []
            for y_i in [y_bounds[i], y_bounds[i + 1]]:
                for x_j in [x_bounds[j], x_bounds[j + 1]]:
                    cy = (y_i + slant * (x_j - mid_x) + s2 * mid_y) / denom
                    cx = x_j - slant * (cy - mid_y)
                    corners.append((cx, cy))
            pts = np.array(corners, dtype=np.float32)
            x1, y1 = np.min(pts, axis=0)
            x2, y2 = np.max(pts, axis=0)
            x1_c, y1_c = int(max(0, min(w, x1))), int(max(0, min(h, y1)))
            x2_c, y2_c = int(max(0, min(w, x2))), int(max(0, min(h, y2)))
            if x2_c > x1_c and y2_c > y1_c:
                grid_boxes.append((x1_c, y1_c, x2_c, y2_c))
    return grid_boxes if len(grid_boxes) == rows * cols else None


def _internal(lines, total):
    return [l for l in lines
            if total * EDGE_MARGIN < l.midline_pos < total * (1 - EDGE_MARGIN)]


def _boxes_are_regular(boxes, rows, cols):
    """The last word on geometry: an observed false positive had column pitches [1, 1, 151, 1, 1, 151, 1, 1].

    Edges come from ONE row / ONE column: the union of every box's edge invents a 1px phantom separator from
    inter-row rounding on any slant, which rejected 101 real hCaptcha grids.
    """
    if not boxes or rows < 1 or cols < 1:
        return False

    if len(boxes) < rows * cols:
        return False
    col_edges = [boxes[c][0] for c in range(cols)]
    row_edges = [boxes[r * cols][1] for r in range(rows)]
    for edges in (col_edges, row_edges):
        if len(edges) < 2:
            continue
        pitches = np.diff(np.array(sorted(edges), dtype=np.float64))
        if np.any(pitches < MIN_CELL):
            return False
        mp = float(np.median(pitches))
        if np.any(np.abs(pitches - mp) > CELL_REGULARITY_TOL * mp):
            return False

    widths = np.array([b[2] - b[0] for b in boxes], dtype=np.float64)
    heights = np.array([b[3] - b[1] for b in boxes], dtype=np.float64)
    if widths.size == 0 or heights.size == 0:
        return False
    mw, mh = float(np.median(widths)), float(np.median(heights))
    if mw < MIN_CELL or mh < MIN_CELL:
        return False
    if np.any(np.abs(widths - mw) > CELL_REGULARITY_TOL * mw):
        return False
    if np.any(np.abs(heights - mh) > CELL_REGULARITY_TOL * mh):
        return False
    return True


def _even_spacing_ok(positions, total):
    p = sorted(positions)
    gaps = [p[i + 1] - p[i] for i in range(len(p) - 1)]
    pitch = float(np.median(gaps))
    if pitch < MIN_CELL:
        return False, pitch
    for g in gaps:
        if abs(g - pitch) > EVEN_TOL * pitch:
            return False, pitch
    if (p[0] - pitch) < -GRID_OVERSHOOT * pitch:
        return False, pitch
    if (p[-1] + pitch) > total + GRID_OVERSHOOT * pitch:
        return False, pitch
    return True, pitch


def _flank_contrast(lab, line, pitch):
    """Median over the line of the mean of both flanks' distance to the line colour: does this separator separate anything?"""
    h, w = lab.shape[:2]
    (x0, y0), (x1, y1) = line.start, line.end
    if line.orientation == 'h':
        xs = np.arange(min(x0, x1), max(x0, x1) + 1, 3.0)
        ys = line.midline_pos + np.tan(line.angle) * (xs - w / 2.0)
    else:
        ys = np.arange(min(y0, y1), max(y0, y1) + 1, 3.0)
        xs = line.midline_pos + np.tan(line.angle) * (ys - h / 2.0)
    jx = np.round(xs).astype(np.intp); jy = np.round(ys).astype(np.intp)
    ok = (jx >= 0) & (jx < w) & (jy >= 0) & (jy < h)
    if ok.sum() < 3:
        return 0.0
    jx, jy = jx[ok], jy[ok]
    d_lo = d_hi = None
    for fr in FLANK_PITCH_FRACS:
        fo = max(3, int(round(fr * pitch)))
        if line.orientation == 'h':
            a = lab[np.clip(jy - fo, 0, h - 1), jx]; b = lab[np.clip(jy + fo, 0, h - 1), jx]
        else:
            a = lab[jy, np.clip(jx - fo, 0, w - 1)]; b = lab[jy, np.clip(jx + fo, 0, w - 1)]
        da = np.sqrt(np.sum((a.astype(np.float64) - line.color_lab) ** 2, axis=1))
        db = np.sqrt(np.sum((b.astype(np.float64) - line.color_lab) ** 2, axis=1))
        d_lo = da if d_lo is None else np.maximum(d_lo, da)
        d_hi = db if d_hi is None else np.maximum(d_hi, db)
    return float(np.median((d_lo + d_hi) / 2.0))


def _seal_fraction(lab, color, orientation, pos, angle, lo, hi):
    """Share of the CANDIDATE's extent along which the line is the gutter colour: the same line seals a 3x3 and fails a 4x4."""
    h, w = lab.shape[:2]
    a = np.arange(max(0.0, lo), min(float(w if orientation == 'h' else h), hi), 2.0)
    if a.size < 3:
        return 0.0
    t = np.tan(angle)
    if orientation == 'h':
        xs, ys = a, pos + t * (a - w / 2.0)
    else:
        ys, xs = a, pos + t * (a - h / 2.0)
    jx = np.round(xs).astype(np.intp); jy = np.round(ys).astype(np.intp)
    ok = (jx >= 0) & (jx < w) & (jy >= 0) & (jy < h)
    if ok.sum() < 3:
        return 0.0
    d = lab[jy[ok], jx[ok]].astype(np.float64) - color
    return float(((d * d).sum(axis=1) < COMB_TOL * COMB_TOL).mean())


def _line_span_perp(line):
    if line.orientation == 'h':
        return (min(line.start[0], line.end[0]), max(line.start[0], line.end[0]))
    return (min(line.start[1], line.end[1]), max(line.start[1], line.end[1]))


def _corroborate(lines, perp_lines, total):
    lines = sorted(_internal(lines, total), key=lambda l: l.midline_pos)
    perp = sorted(perp_lines, key=lambda l: l.midline_pos)
    if len(lines) < 2:
        return lines
    pos = [l.midline_pos for l in lines]
    gaps = np.diff(pos)
    # Pitch over gaps that could be a cell: comb-reported footer bands took the median from 87 to 55.8 and detection
    # 20/20 -> 5/20. The guard below still reads the RAW median: filtering first skipped the perpendicular rescue
    # and cost a 4x4 its fourth row (ttvu9: raw 34.5, filtered 80.9, perpendicular 97.0).
    raw_cell = float(np.median(gaps)) if len(gaps) else 0.0
    cell_gaps = [g for g in gaps if g >= MIN_CELL]
    cell = float(np.median(cell_gaps)) if cell_gaps else 0.0
    if raw_cell < MIN_CELL:
        pgaps = np.diff([l.midline_pos for l in perp])
        cell = float(np.median(pgaps)) if len(pgaps) else 0.0
        if cell < MIN_CELL:
            return lines
    need = CORROB_FRAC * cell
    kept = []
    for l in lines:
        p = l.midline_pos
        n_ok = 0
        for q in perp:
            lo, hi = _line_span_perp(q)
            if (p - lo) >= need and (hi - p) >= need:
                n_ok += 1
        if n_ok >= 2:
            kept.append(l)
    return kept if len(kept) >= 2 else lines


def _complete_one_run(positions, grp, pitch, total):
    real = sorted(positions)
    sub_pitches = [pitch]
    for k in (2, 3):
        sp = pitch / k
        if sp >= MIN_CELL:
            sub_pitches.append(sp)
    bases = []
    seen_runs = set()
    for tp in sub_pitches:
        filled = [real[0]]
        interior_virtual = 0
        ok = True
        for a, b in zip(real, real[1:]):
            m = int(round((b - a) / tp))
            if m < 1 or abs((b - a) - m * tp) > EVEN_TOL * tp:
                ok = False
                break
            for j in range(1, m):
                filled.append(a + j * (b - a) / m)
                interior_virtual += 1
            filled.append(b)
        if not ok:
            continue
        kf = tuple(round(x) for x in filled)
        if kf in seen_runs:
            continue
        seen_runs.add(kf)
        bases.append((list(filled), interior_virtual))
    out = []
    for base, ivirt in bases:
        bp = (base[-1] - base[0]) / (len(base) - 1) if len(base) > 1 else pitch
        for lo_add in (0, 1):
            for hi_add in (0, 1):
                nv = ivirt + lo_add + hi_add
                if nv == 0 or nv > MAX_VIRTUAL_NODES:
                    continue
                run = list(base)
                if lo_add:
                    run.insert(0, run[0] - bp)
                if hi_add:
                    run.append(run[-1] + bp)
                dim = len(run) + 1
                if dim < MIN_GRID_DIM or dim > 6:
                    continue
                if nv > MAX_VIRTUAL_FRAC * len(run):
                    continue
                out.append((run, nv))
    return out


def _completed_candidates(lines, total, real_cand):
    """Lattice completion for a missing sky-bordered gutter; only clean painted anchors, never arbitrary clean pairs."""
    out = {}
    seen = set()
    for dim, runs in real_cand.items():
        for positions, _score, pitch, grp in runs:
            if any(l.color_std >= CLEAN_LATTICE_STD for l in grp):
                continue
            for run, n_virtual in _complete_one_run(positions, grp, pitch, total):
                run = sorted(run)
                cdim = len(run) + 1
                ok, fpitch = _even_spacing_ok(run, total)
                if not ok:
                    continue
                key = (cdim, tuple(round(p) for p in run))
                if key in seen:
                    continue
                seen.add(key)
                ang_pen = max(l.angle for l in grp) - min(l.angle for l in grp)
                center_off = abs((run[0] + run[-1]) / 2 - total / 2) / total
                scale_err = abs(fpitch - total / cdim) / total
                score = (center_off * 1000 + scale_err * 500 + ang_pen * 200
                         + n_virtual * VIRTUAL_NODE_PENALTY)
                out.setdefault(cdim, []).append((run, score, fpitch, grp))
    return out


def _axis_candidates(lines, total):
    lines = sorted(_internal(lines, total), key=lambda l: l.midline_pos)
    n = len(lines)
    cand = {}
    seen = set()
    for i in range(n):
        for j in range(i + 1, n):
            pitch0 = lines[j].midline_pos - lines[i].midline_pos
            if pitch0 < MIN_CELL:
                continue
            run_idx = [i, j]
            pos = lines[j].midline_pos
            jj = j
            while True:
                target = pos + pitch0
                best_k = None; best_d = EVEN_TOL * pitch0
                for k in range(jj + 1, n):
                    d = abs(lines[k].midline_pos - target)
                    if d < best_d:
                        best_d = d; best_k = k
                    if lines[k].midline_pos - target > EVEN_TOL * pitch0:
                        break
                if best_k is None:
                    break
                run_idx.append(best_k)
                pos = lines[best_k].midline_pos
                jj = best_k
            # Every prefix, not just the maximal run: the last line may be a geetest/prosopo panel border.
            for end in range(2, len(run_idx) + 1):
                sub = run_idx[:end]
                positions = [lines[r].midline_pos for r in sub]
                ok, pitch = _even_spacing_ok(positions, total)
                if not ok:
                    continue
                grp = [lines[r] for r in sub]
                dim = len(sub) + 1
                if dim < MIN_GRID_DIM:
                    continue
                key = (dim, tuple(round(p) for p in positions))
                if key in seen:
                    continue
                seen.add(key)
                ang_pen = max(l.angle for l in grp) - min(l.angle for l in grp)
                center_off = abs((positions[0] + positions[-1]) / 2 - total / 2) / total
                scale_err = abs(pitch - total / dim) / total
                score = center_off * 1000 + scale_err * 500 + ang_pen * 200
                cand.setdefault(dim, []).append((positions, score, pitch, grp))
    for dim, comps in _completed_candidates(lines, total, dict(cand)).items():
        bucket = cand.setdefault(dim, [])
        existing = {tuple(round(p) for p in c[0]) for c in bucket}
        for c in comps:
            kpos = tuple(round(p) for p in c[0])
            if kpos not in existing:
                bucket.append(c)
                existing.add(kpos)
    for k in cand:
        cand[k].sort(key=lambda x: x[1])
    return cand


# How near a cell's midpoint a detected gutter must sit, as a fraction of the pitch, to say the cell is two cells.
HALVED_CELL_TOL = 0.12


def _halves_a_finer_lattice(positions, pitch, kept_lines):
    """True when a detected gutter splits EVERY cell of this axis down its middle.

    Tall tiles fail the square-cell gate as themselves, but every other gutter spaces cells two tiles wide that
    pass it, so a 6x3 board read as a 3x3 of tile pairs.
    """
    if not positions or pitch <= 0:
        return False
    lines = sorted(positions)
    mids = ([lines[0] - pitch / 2.0] + [(a + b) / 2.0 for a, b in zip(lines, lines[1:])]
            + [lines[-1] + pitch / 2.0])
    tol = HALVED_CELL_TOL * pitch
    return all(any(abs(l.midline_pos - m) <= tol for l in kept_lines) for m in mids)


def extract_grid_from_lines(h_lines, v_lines, h, w, lab=None):
    """Every colour gate is RELATIVE, so a grid of any uniform border colour is detectable."""
    h_keep = _corroborate(h_lines, v_lines, h)
    v_keep = _corroborate(v_lines, h_lines, w)
    h_keep_int = _internal(h_keep, h)
    v_keep_int = _internal(v_keep, w)
    # One painted reference colour for every seal test (the one the comb looked for), so answers cache across candidates.
    clean = [l for l in h_lines + v_lines if l.color_std < CLEAN_LATTICE_STD]
    seal_col = np.median(np.array([l.color_lab for l in clean]), axis=0) if clean else None
    seal_cache = {}

    def sealed(orientation, pos, angle, lo, hi):
        if lab is None or seal_col is None:
            return True
        k = (orientation, round(pos), round(angle, 3), int(lo), int(hi))
        if k not in seal_cache:
            seal_cache[k] = (_seal_fraction(lab, seal_col, orientation, pos, angle,
                                            lo, hi) >= GRID_SEAL_MIN)
        return seal_cache[k]
    h_cand = _axis_candidates(h_keep, h)
    v_cand = _axis_candidates(v_keep, w)
    best = None
    best_score = float('inf')
    for rows in sorted(h_cand):
        if rows < MIN_GRID_DIM:
            continue
        for cols in sorted(v_cand):
            if cols < MIN_GRID_DIM:
                continue
            for hpos, hsc, hd, hlns in h_cand[rows][:25]:
                for vpos, vsc, vd, vlns in v_cand[cols][:25]:
                    s_diff = abs(hd - vd) / max(hd, vd)
                    if s_diff > 0.22:
                        continue
                    h_min = (cols - FULL_SPAN_MARGIN) * vd
                    v_min = (rows - FULL_SPAN_MARGIN) * hd
                    if (min(_line_extent(l) for l in hlns) < h_min
                            or min(_line_extent(l) for l in vlns) < v_min):
                        continue
                    alll = hlns + vlns
                    ccols = np.array([l.color_lab for l in alll])
                    avg = ccols.mean(axis=0)
                    de = np.sqrt(np.sum((ccols - avg) ** 2, axis=1))
                    if np.max(de) > GRID_COLOR_TOL:
                        continue
                    h_ang = np.mean([l.angle for l in hlns])
                    v_ang = np.mean([l.angle for l in vlns])
                    if abs(h_ang + v_ang) > GRID_ANGLE_TOL:
                        continue
                    h_col = np.mean([l.color_lab for l in hlns], axis=0)
                    v_col = np.mean([l.color_lab for l in vlns], axis=0)
                    if _de(h_col, v_col) > XAXIS_COLOR_TOL:
                        continue
                    if (_halves_a_finer_lattice(vpos, vd, v_keep_int)
                            or _halves_a_finer_lattice(hpos, hd, h_keep_int)):
                        continue
                    slant = np.tan(h_ang)
                    ang_inc = abs(h_ang + v_ang) * 200
                    hsorted = sorted(hpos); vsorted = sorted(vpos)
                    row_top, row_bot = hsorted[0] - hd, hsorted[-1] + hd
                    col_lft, col_rgt = vsorted[0] - vd, vsorted[-1] + vd
                    vy = [_line_span_perp(l) for l in vlns]
                    hx = [_line_span_perp(l) for l in hlns]
                    vy_lo = float(np.median([s[0] for s in vy]))
                    vy_hi = float(np.median([s[1] for s in vy]))
                    hx_lo = float(np.median([s[0] for s in hx]))
                    hx_hi = float(np.median([s[1] for s in hx]))
                    v_top_edge = vy_lo <= EDGE_BLEED_PX
                    v_bot_edge = vy_hi >= h - EDGE_BLEED_PX
                    h_lft_edge = hx_lo <= EDGE_BLEED_PX
                    h_rgt_edge = hx_hi >= w - EDGE_BLEED_PX
                    # A one-sided edge bleed (hCaptcha's white footer) is not a missing row; a grid that fills an axis reaches both edges.
                    def _missing(uncov, pitch, bleed):
                        if bleed:
                            return 0.0
                        f = uncov / pitch
                        return f if f >= MISSING_LINE_FRAC else 0.0
                    span_pen = SPAN_FIT_PENALTY * (
                        _missing(max(0.0, row_top - vy_lo), hd, v_top_edge and not v_bot_edge)
                        + _missing(max(0.0, vy_hi - row_bot), hd, v_bot_edge and not v_top_edge)
                        + _missing(max(0.0, col_lft - hx_lo), vd, h_lft_edge and not h_rgt_edge)
                        + _missing(max(0.0, hx_hi - col_rgt), vd, h_rgt_edge and not h_lft_edge))
                    def _seal(orientation, pos, angle):
                        return sealed(orientation, pos, angle,
                                      *((col_lft, col_rgt) if orientation == 'h'
                                        else (row_top, row_bot)))
                    unsealed = sum(1 for l in alll
                                   if not _seal(l.orientation, l.midline_pos, l.angle))
                    # Refund the invention charge for INTERIOR nodes the image seals (a missed gutter, not a guess): without it
                    # the true 4x4 on every sky-backed reCAPTCHA lost by ~470. Extrapolated nodes seal trivially on a white
                    # margin and refunding them turned a correct 3x3 into a 3x4.
                    def _confirm(pos, lns, orientation, angle):
                        if len(lns) < 2:
                            return 0
                        lo = min(l.midline_pos for l in lns)
                        hi = max(l.midline_pos for l in lns)
                        return sum(1 for p in pos
                                   if lo < p < hi
                                   and all(abs(p - l.midline_pos) >= 1.0 for l in lns)
                                   and _seal(orientation, p, angle))
                    confirmed = (_confirm(hpos, hlns, 'h', h_ang)
                                 + _confirm(vpos, vlns, 'v', v_ang))
                    # Only SEALED lines count as unused: the comb hands over clean sky belts that are not cell boundaries.
                    chosen = {id(l) for l in alll}
                    unused = (sum(1 for l in h_keep_int if id(l) not in chosen
                                  and _seal('h', l.midline_pos, l.angle))
                              + sum(1 for l in v_keep_int if id(l) not in chosen
                                    and _seal('v', l.midline_pos, l.angle)))
                    score = (hsc + vsc + s_diff * 1000 + abs(slant) * 500
                             + unused * UNUSED_LINE_PENALTY + ang_inc + span_pen
                             + unsealed * UNSEALED_PENALTY
                             - confirmed * VIRTUAL_NODE_PENALTY)
                    if score < best_score:
                        # Content gate IN the loop so a rejected over-count lets a smaller valid candidate win.
                        boxes = _generate_grid(rows, cols, hpos, vpos, hd, vd, h, w, slant)
                        if boxes and _cells_have_content(lab, boxes, rows, cols,
                                                         hlns + vlns, unsealed == 0):
                            best_score = score
                            best = (boxes, rows, cols, slant, avg,
                                    sorted(hpos), hd, sorted(vpos), vd, hlns + vlns,
                                    unsealed == 0)
    if best is None:
        return None, None, None
    (boxes, rows, cols, slant, gutter_color, hpos, hd, vpos, vd, chosen_lns,
     fully_sealed) = best
    grid_gutters_clean = (float(np.mean([l.color_std for l in chosen_lns]))
                          < CLEAN_GUTTER_STD) if chosen_lns else False
    def _off_lattice(lines, total, anchors, pitch, orientation, ext):
        """Same-colour lines off the pitch inside the grid's own span; the textured-photo false-positive killer."""
        off_pos = []
        clean_skipped = 0
        lo, hi = anchors[0], anchors[-1]
        for l in _internal(lines, total):
            if not (lo - LATTICE_TOL * pitch <= l.midline_pos <= hi + LATTICE_TOL * pitch):
                continue
            if _de(l.color_lab, gutter_color) > GRID_COLOR_TOL:
                continue
            # Gutter-coloured for only part of the width divides nothing; three such belts once rejected a correct 4x4.
            if not sealed(orientation, l.midline_pos, l.angle, *ext):
                continue
            off = min(abs((l.midline_pos - anchors[0]) - round((l.midline_pos - anchors[0]) / pitch) * pitch),
                      abs((l.midline_pos - anchors[-1]) - round((l.midline_pos - anchors[-1]) / pitch) * pitch))
            if off > LATTICE_TOL * pitch:
                # On a proven clean grid forgive a few clean strays (a horizon, a UI rule); noisy strays always count.
                if (grid_gutters_clean and l.color_std < OFF_LATTICE_CLEAN_STD
                        and clean_skipped < MAX_OFF_LATTICE_CLEAN):
                    clean_skipped += 1
                    continue
                off_pos.append(l.midline_pos)
        off_pos.sort()
        return sum(1 for i, p in enumerate(off_pos)
                   if i == 0 or p - off_pos[i - 1] > OFF_LATTICE_CLUSTER_PX)
    rows_ext = (hpos[0] - hd, hpos[-1] + hd)
    cols_ext = (vpos[0] - vd, vpos[-1] + vd)
    if (_off_lattice(h_lines, h, hpos, hd, 'h', cols_ext) > MAX_OFF_LATTICE
            or _off_lattice(v_lines, w, vpos, vd, 'v', rows_ext) > MAX_OFF_LATTICE):
        return None, None, None
    if not _boxes_are_regular(boxes, rows, cols):
        return None, None, None
    # On the chosen grid only: as a per-line filter it deleted the strays the off-lattice gate counts (FP 2 -> 4 -> 6).
    if lab is not None:
        if float(np.median([_flank_contrast(lab, l, hd if l.orientation == 'h' else vd)
                            for l in chosen_lns])) < (SEALED_FLANK_MIN_DE if fully_sealed
                                                      else GRID_FLANK_MIN_DE):
            return None, None, None
    x0 = min(b[0] for b in boxes); x1 = max(b[2] for b in boxes)
    y0 = min(b[1] for b in boxes); y1 = max(b[3] for b in boxes)
    if (x1 - x0) * (y1 - y0) < MIN_IMAGE_AREA_COVERAGE * w * h:
        return None, None, None
    return boxes, (rows, cols), slant


def _detect_grid(image_path, seed_bias=0.0):
    img = cv2.imread(image_path)
    if img is None:
        return None
    h, w = img.shape[:2]
    lab = _to_lab(img)
    tols = walk_tolerances(image_noise(lab))
    h_lines = _trace_lines(lab, axis=1, seed_bias=seed_bias, tols=tols)
    v_lines = _trace_lines(lab, axis=0, seed_bias=-seed_bias, tols=tols)
    # Both axes traced before either is judged: the comb takes its colour from whichever axis found a clean line.
    h_lines, v_lines = _add_comb_lines(lab, h_lines, v_lines)
    if len(_internal(h_lines, h)) < 2 or len(_internal(v_lines, w)) < 2:
        return None
    boxes, dims, slant = extract_grid_from_lines(h_lines, v_lines, h, w, lab=lab)
    return boxes


def find_grid(image_path: str, slant_to_try: Optional[float] = None) -> Optional[List[Tuple[int, int, int, int]]]:
    seed_bias = float(slant_to_try) if slant_to_try is not None else 0.0
    return _detect_grid(image_path, seed_bias=seed_bias)


def detect_selected_cells(image_path, grid_boxes):
    img = cv2.imread(image_path)
    if img is None: return [], []
    sel, ld = [], []
    recap_blue = (27, 115, 232)
    hcap_blue = (188, 117, 15)
    for i, box in enumerate(grid_boxes):
        cell = img[box[1]:box[3], box[0]:box[2]]
        if cell.size == 0: continue

        h_cell, w_cell = cell.shape[:2]
        tl = cell[0:int(h_cell * 0.4), 0:int(w_cell * 0.4)]
        if tl.size > 0 and _has_badge(tl, recap_blue):
            sel.append(i + 1)
            continue
        tr = cell[0:max(8, int(h_cell * 0.22)), int(w_cell * 0.78):]
        if tr.size > 0 and _has_hcaptcha_check(tr):
            sel.append(i + 1)
            continue

        cntr = cell[int(h_cell * 0.3):int(h_cell * 0.7), int(w_cell * 0.3):int(w_cell * 0.7)]
        if cntr.size > 0 and _is_loading(cntr, recap_blue):
            ld.append(i + 1)
    return sel, ld


def _crop_cell(image_path, grid_boxes, cell_number):
    img = cv2.imread(image_path)
    if img is None:
        return None
    if cell_number < 1 or cell_number > len(grid_boxes):
        return None
    x1, y1, x2, y2 = grid_boxes[cell_number - 1]
    cell = img[y1:y2, x1:x2]
    return cell if cell.size else None

def is_empty_cell(image_path, grid_boxes, cell_number,
                  white_frac=0.97, l_thresh=92.0, chroma_thresh=6.0):
    cell = _crop_cell(image_path, grid_boxes, cell_number)
    if cell is None:
        return False
    lab = cv2.cvtColor(cell, cv2.COLOR_BGR2LAB).astype(np.float32)
    L = lab[:, :, 0] * (100.0 / 255.0)
    a = lab[:, :, 1] - 128.0
    b = lab[:, :, 2] - 128.0
    chroma = np.sqrt(a * a + b * b)
    white = (L > l_thresh) & (chroma < chroma_thresh)
    return float(white.mean()) >= white_frac

def is_cell_opacity_changing(image_path_a, image_path_b, grid_boxes,
                             cell_number, change_thresh=0.02):
    a = _crop_cell(image_path_a, grid_boxes, cell_number)
    b = _crop_cell(image_path_b, grid_boxes, cell_number)
    if a is None or b is None or a.shape != b.shape:
        return False
    diff = cv2.absdiff(a, b)
    gray = cv2.cvtColor(diff, cv2.COLOR_BGR2GRAY)
    _, thr = cv2.threshold(gray, 30, 255, cv2.THRESH_BINARY)
    ratio = cv2.countNonZero(thr) / (thr.shape[0] * thr.shape[1])
    return ratio > change_thresh


# Two, not zero: the ringed rendering draws the white on the rim and fragments the teal. At 4px the phantom rate doubles for ~1 point of recall.
_HCAPTCHA_GLYPH_SLACK_PX = 2.0


def _has_hcaptcha_check(roi):
    """The white glyph must BELONG to the teal mark: pixel counts alone called blue sky with a white pole a selection (74 phantoms over 3051 corners)."""
    if roi is None or roi.size == 0:
        return False
    flat = roi.reshape(-1, 3).astype(np.int32)
    # Deliberately loose: pinning the badge colour to a delta-E costs more real badges than it saves phantoms.
    teal = (
        (flat[:, 0] > 120)
        & (flat[:, 1] > 80)
        & (flat[:, 2] < 80)
        & (flat[:, 0] - flat[:, 2] > 60)
    )
    white = (flat[:, 0] > 220) & (flat[:, 1] > 220) & (flat[:, 2] > 220)
    if int(teal.sum()) < 8 or int(white.sum()) < 2:
        return False

    h, w = roi.shape[:2]
    # Close first: the glyph cuts the disc into pieces, and the largest blob must be the whole mark.
    mask = cv2.morphologyEx(
        teal.reshape(h, w).astype(np.uint8) * 255, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8)
    )
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return False
    hull = cv2.convexHull(max(contours, key=cv2.contourArea))
    ys, xs = np.nonzero(white.reshape(h, w))
    inside = sum(
        1
        for y, x in zip(ys, xs)
        if cv2.pointPolygonTest(hull, (float(x), float(y)), True) >= -_HCAPTCHA_GLYPH_SLACK_PX
    )
    return inside >= 2


def _has_badge(roi, rgb):
    mask = _create_delta_e_mask(roi, rgb, 8.0)
    if cv2.countNonZero(mask) <= roi.size * 0.003: return False

    contours, _ = cv2.findContours(cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((3,3), np.uint8)), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours: return False
    cnt = max(contours, key=cv2.contourArea)
    hull = cv2.convexHull(cnt)
    area, perim = cv2.contourArea(hull), cv2.arcLength(hull, True)

    if perim == 0 or (4*np.pi*area/(perim*perim)) < 0.8: return False

    M = cv2.moments(hull)
    if M["m00"] == 0 or (M["m10"]/M["m00"]) > roi.shape[1]*0.7 or (M["m01"]/M["m00"]) > roi.shape[0]*0.7: return False
    return True

def _is_loading(roi, rgb):
    mask = _create_delta_e_mask(roi, rgb, 12.0)
    return 0.05 < (cv2.countNonZero(mask) / (roi.shape[0]*roi.shape[1])) < 0.6 if roi.size > 0 else False

def _create_delta_e_mask(img, rgb, thr):
    t_lab = cv2.cvtColor(np.array([[[rgb[2], rgb[1], rgb[0]]]], dtype=np.uint8), cv2.COLOR_BGR2LAB)[0, 0]
    diff = cv2.cvtColor(img, cv2.COLOR_BGR2LAB).astype(np.float32) - t_lab.astype(np.float32)
    return (np.sqrt(np.sum(diff**2, axis=2)) <= thr).astype(np.uint8)*255

def get_numbered_grid_overlay(image_path, grid_boxes, output_path=None):
    ov = [{"bbox": [b[0], b[1], b[2]-b[0], b[3]-b[1]], "number": i+1, "color": "#FF0000", "box_style": "solid"} for i, b in enumerate(grid_boxes)]
    if output_path is None:
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tf: output_path = tf.name
    add_overlays_to_image(image_path, ov, output_path=output_path, label_position=LabelPosition.TOP_RIGHT)
    return output_path
