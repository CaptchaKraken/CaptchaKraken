"""A photo is not a selection badge: pixel counts alone reported 74 phantoms over 3051 fresh corners, each a correct
tile silently dropped from the model's answer. Requiring the white within 2px of the teal hull leaves 15 while
still finding all 1200 rendered badges in both drawings; the reCAPTCHA chip measured clean and is unchanged.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from PIL import Image, ImageDraw

from captchakraken.tool_calls.find_grid import (
    _has_badge,
    _has_hcaptcha_check,
    detect_selected_cells,
    find_grid,
)

BADGE_RGB = (15, 117, 188)
PATCH = (28, 29)
#: Drawn this many times larger and shrunk, so edges are anti-aliased the way a browser paints them.
AA = 4


def _photo_patch(color=(90, 120, 150)) -> np.ndarray:
    return np.full((*PATCH, 3), color, dtype=np.uint8)


def _antialiased(patch: np.ndarray, draw) -> np.ndarray:
    h, w = patch.shape[:2]
    big = Image.fromarray(patch).resize((w * AA, h * AA), Image.NEAREST)
    draw(ImageDraw.Draw(big), lambda v: v * AA + AA // 2)
    return np.asarray(big.resize((w, h), Image.LANCZOS))


def _draw_badge(patch: np.ndarray, diameter: int, style: str) -> np.ndarray:
    """The disc anti-aliased; the white glyph at full strength, as the vendor's 1px strokes are."""
    r = diameter // 2
    cx, cy = patch.shape[1] - r - 2, r + 2
    white = (255, 255, 255)

    def disc(d, s, **kw):
        d.ellipse([s(cx - r), s(cy - r), s(cx + r), s(cy + r)], **kw)
    out = _antialiased(patch, lambda d, s: disc(d, s, fill=BADGE_RGB))
    if style == "ringed":
        out = _antialiased(out, lambda d, s: disc(d, s, outline=white, width=max(1, diameter // 8) * AA))
    im = Image.fromarray(out)
    d = ImageDraw.Draw(im)
    if style == "ringed":
        t, o = max(1, diameter // 7), max(1, r // 2)
        d.line([cx - o, cy - o, cx + o, cy + o], fill=white, width=t)
        d.line([cx - o, cy + o, cx + o, cy - o], fill=white, width=t)
    else:
        t = max(1, diameter // 6)
        d.line([cx - r // 2, cy, cx - r // 6, cy + r // 2], fill=white, width=t)
        d.line([cx - r // 6, cy + r // 2, cx + r // 2, cy - r // 2], fill=white, width=t)
    return np.asarray(im)


@pytest.mark.parametrize("style", ["filled", "ringed"])
@pytest.mark.parametrize("diameter", [10, 12, 14, 16])
def test_a_real_mark_is_still_found(style, diameter):
    assert _has_hcaptcha_check(_draw_badge(_photo_patch(), diameter, style)) is True


def test_sky_over_here_and_something_white_over_there_is_not_a_mark():
    patch = _photo_patch()
    patch[:, :16] = (60, 140, 210)
    patch[:, 24:] = (240, 240, 240)
    assert _has_hcaptcha_check(patch) is False


def test_teal_and_white_that_merely_share_a_corner_is_not_a_mark():
    patch = _photo_patch()
    patch[0:6, 0:6] = (40, 130, 200)
    patch[20:, 20:] = (255, 255, 255)
    assert _has_hcaptcha_check(patch) is False


def test_the_recaptcha_corner_chip_is_unaffected():
    patch = _antialiased(np.full((52, 52, 3), (90, 120, 150), dtype=np.uint8),
                         lambda d, s: d.ellipse([s(1), s(1), s(23), s(23)], fill=(27, 115, 232)))
    assert _has_badge(patch, (27, 115, 232)) is True
    assert _has_badge(_photo_patch(), (27, 115, 232)) is False


_CORPUS = Path(os.environ.get("CAPTCHA_GRID_CORPUS") or "/nonexistent")
_PHANTOM_BUDGET = 0.012


@pytest.mark.skipif(not _CORPUS.is_dir(), reason=f"grid corpus not present at {_CORPUS}")
def test_fresh_boards_report_almost_no_selections():
    """The budget is a ratchet set so the previous release fails it (2026-09-06: this tree 1.13%, origin/main 1.41%); re-record both arms on one corpus, only ever downward."""
    tiles = phantoms = 0
    offenders = []
    for path in sorted(_CORPUS.glob("*.png")):
        boxes = find_grid(str(path))
        if not boxes:
            continue
        selected, _ = detect_selected_cells(str(path), boxes)
        tiles += len(boxes)
        phantoms += len(selected)
        if selected:
            offenders.append(f"{path.name}: {selected}")
    if not tiles:
        pytest.skip("no grid detected anywhere in the corpus")
    rate = phantoms / tiles
    assert rate <= _PHANTOM_BUDGET, (
        f"{phantoms} phantom selections over {tiles} tiles of fresh boards "
        f"({rate:.2%} > {_PHANTOM_BUDGET:.2%}). Each one is a tile the solver "
        f"will refuse to click:\n  " + "\n  ".join(offenders)
    )
