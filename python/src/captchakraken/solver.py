"""Image in, actions out: grid detection plus the model, for one still or one keyframe set."""

import math
import os
import sys
import tempfile
from pathlib import Path
from typing import Any, List, Optional, Sequence, Tuple, Union

from PIL import Image

from .action_types import (CaptchaAction, ClickAction, DoneAction, DragAction, HoldAction, RefreshAction, TypeAction,
                           WaitAction)
from .kinds import ActionKind, PixelAnswerKind, PromptFamily, RetryMode, Vendor
from .planner import ActionPlanner
from .tool_calls.find_checkbox import find_checkbox
from .tool_calls.find_grid import detect_selected_cells, find_grid, get_numbered_grid_overlay

DEBUG = os.getenv("CAPTCHA_DEBUG", "0") == "1"
# ~1.2% ≈ ±6px on a 512px challenge.
_PIXEL_BOX_HALF = float(os.getenv("CAPTCHA_PIXEL_BOX_HALF", "0.012"))

# The only cell counts a trained grid puzzle has, and which of them each named vendor ships. UNKNOWN stays
# permissive in both directions: the driver reports it for GeeTest and Prosopo, and the offline grader defaults
# to it, so narrowing it would silently stop scoring reCAPTCHA 4x4 in evaluation.
GRID_CELL_SHAPES = {9: (3, 3), 16: (4, 4)}
VENDOR_GRID_CELLS: dict[Vendor, frozenset[int]] = {Vendor.HCAPTCHA: frozenset({9}), Vendor.RECAPTCHA: frozenset({9, 16})}
# Every true grid measures 0.000 cells out of true; the nearest false lattice measured 0.128.
_GRID_REGULARITY_TOL = 0.02


def _debug(message: str) -> None:
    if DEBUG:
        print(f"[Solver] {message}", file=sys.stderr)


class UnsupportedCaptchaError(Exception):
    pass


def _lattice_irregularity(grid_boxes) -> Optional[float]:
    """How far the cells stray from a regular lattice, in cells; None when not a square count."""
    boxes = [tuple(b) for b in grid_boxes]
    n = len(boxes)
    k = int(round(math.sqrt(n))) if n else 0
    if k < 2 or k * k != n:
        return None
    widths = [b[2] - b[0] for b in boxes]
    heights = [b[3] - b[1] for b in boxes]
    mid_w, mid_h = sorted(widths)[n // 2], sorted(heights)[n // 2]
    if mid_w <= 0 or mid_h <= 0:
        return None
    rows = [boxes[i * k:(i + 1) * k] for i in range(k)]
    cols = [[boxes[r * k + c] for r in range(k)] for c in range(k)]
    row_skew = max(max(b[1] for b in r) - min(b[1] for b in r) for r in rows) / mid_h
    col_skew = max(max(b[0] for b in c) - min(b[0] for b in c) for c in cols) / mid_w
    size_spread = max((max(widths) - min(widths)) / mid_w, (max(heights) - min(heights)) / mid_h)
    return max(row_skew, col_skew, size_spread)


def _grid_dims(n_cells: int, puzzle_source: Vendor = Vendor.UNKNOWN):
    shape = GRID_CELL_SHAPES.get(n_cells)
    allowed = VENDOR_GRID_CELLS.get(Vendor(puzzle_source))
    return None if shape is None or (allowed is not None and n_cells not in allowed) else shape


class CaptchaSolver:
    def __init__(self, model: Optional[str] = None, provider: str = "captchaKrakenApi",
                 api_key: Optional[str] = None, expert: Optional[PromptFamily] = None):
        self.planner = ActionPlanner(model=model, api_key=api_key, expert=expert)
        self._image_size: Optional[Tuple[int, int]] = None
        self._temp_files: List[str] = []

    def __del__(self):
        for f in self._temp_files:
            try:
                os.unlink(f)
            except OSError:
                pass

    def solve(self, media_path: str, instruction: str = "", puzzle_source: Vendor = Vendor.UNKNOWN,
              retry_mode: Optional[RetryMode] = None, text_mode: bool = False) -> Union[CaptchaAction, List[CaptchaAction]]:
        # String defaults stay: the public signature is pinned by contract.json. A bad value raises here.
        puzzle_source, retry_mode = Vendor(puzzle_source), None if retry_mode is None else RetryMode(retry_mode)
        media_path = str(Path(media_path).resolve())
        if not os.path.exists(media_path):
            raise FileNotFoundError(f"Media not found: {media_path}")
        image_path = self._materialize_image(media_path)
        img_w, img_h = self._image_size

        if text_mode:
            # A typed captcha's boxed glyphs are exactly the lattice find_grid looks for, so skip it.
            try:
                actions = self._solve_pixel(image_path, text_mode=True)
            except ValueError as exc:
                raise UnsupportedCaptchaError(str(exc)) from exc
            if actions:
                return actions
            raise UnsupportedCaptchaError("Could not read the text captcha")

        # The animated path never runs find_grid: it false-positives on the header and footer bands of hCaptcha's click puzzles.
        grid_boxes = find_grid(image_path)
        dims = _grid_dims(len(grid_boxes), puzzle_source) if grid_boxes else None
        if grid_boxes and dims and self._is_real_grid(image_path, grid_boxes):
            return self._solve_grid(image_path, grid_boxes, dims[0], dims[1], retry_mode=retry_mode)
        if grid_boxes:
            _debug(f"find_grid returned {len(grid_boxes)} cells; not solving as a grid")

        if img_h < 400:
            checkbox = find_checkbox(image_path)
            if checkbox:
                x, y, w, h = checkbox
                return ClickAction(action=ActionKind.CLICK,
                                   target_bounding_boxes=[[x / img_w, y / img_h, (x + w) / img_w, (y + h) / img_h]])

        actions = self._solve_pixel(image_path)
        if actions:
            return actions
        raise UnsupportedCaptchaError("Cannot solve this kind of captcha")

    def solve_keyframes(self, keyframe_paths: Sequence[str]) -> List[CaptchaAction]:
        """Solve an animated challenge from its keyframes, in model order (frame 1 first)."""
        paths = [str(p) for p in keyframe_paths]
        if not paths:
            raise UnsupportedCaptchaError("no keyframes to solve from")
        with Image.open(paths[0]) as im:
            self._image_size = im.size
        try:
            raw = self.planner.get_keyframe_actions(paths)
        except ValueError as exc:
            raise UnsupportedCaptchaError(str(exc)) from exc
        actions = self._to_actions(raw, keyframe_paths=paths)
        if actions:
            return actions
        raise UnsupportedCaptchaError("Cannot solve this animated captcha")

    def _solve_pixel(self, image_path: str, text_mode: bool = False) -> List[CaptchaAction]:
        return self._to_actions(self.planner.get_pixel_actions(image_path, text_mode=text_mode))

    def _to_actions(self, raw_actions: List[dict],
                    keyframe_paths: Optional[Sequence[str]] = None) -> List[CaptchaAction]:
        """Normalised 0-1 points become small boxes; a slide is a drag with no source."""
        r = _PIXEL_BOX_HALF

        def box(cx: float, cy: float) -> List[float]:
            return [min(max(v, 0.0), 1.0) for v in (cx - r, cy - r, cx + r, cy + r)]

        def wait_for(a: dict) -> dict:
            # An out-of-range frame is dropped, not clamped: clamping a 7 to 6 would invent an intent.
            frame = a.get("frame")
            if not keyframe_paths or not isinstance(frame, int) or not 1 <= frame <= len(keyframe_paths):
                return {}
            return {"frame": frame, "await_keyframe": str(keyframe_paths[frame - 1])}

        out: List[CaptchaAction] = []
        for a in raw_actions:
            kind = PixelAnswerKind(a["kind"])
            if kind == PixelAnswerKind.CLICK:
                boxes = [box(x, y) for (x, y) in a.get("points", [])]
                # Only generation 3 sends an empty click, and it means nothing on the board matches: submit as is.
                out.append(ClickAction(action=ActionKind.CLICK, target_bounding_boxes=boxes, **wait_for(a)) if boxes
                           else DoneAction(action=ActionKind.DONE))
            elif kind in (PixelAnswerKind.DRAG, PixelAnswerKind.SLIDE):
                src = box(*a["src"]) if kind == PixelAnswerKind.DRAG else None
                out.append(DragAction(action=ActionKind.DRAG, source_bounding_box=src,
                                      target_bounding_box=box(*a["dst"]), **wait_for(a)))
            elif kind == PixelAnswerKind.TYPE:
                out.append(TypeAction(action=ActionKind.TYPE, text=a["text"]))
            elif kind == PixelAnswerKind.HOLD and a.get("points"):
                out.append(HoldAction(action=ActionKind.HOLD, target_bounding_box=box(*a["points"][0])))
            elif kind == PixelAnswerKind.REFRESH:
                points = a.get("points")
                out.append(RefreshAction(action=ActionKind.REFRESH,
                                         target_bounding_box=box(*points[0]) if points else None))
        return out

    def solveVideo(self, *args, **kwargs):
        return self.solve(*args, **kwargs)

    def _materialize_image(self, media_path: str) -> str:
        """A PNG path for `media_path`; a video contributes its first frame."""
        if any(media_path.lower().endswith(ext) for ext in (".mp4", ".gif", ".avi", ".webm")):
            import cv2

            cap = cv2.VideoCapture(media_path)
            ok, frame = cap.read()
            cap.release()
            if not ok:
                raise ValueError(f"Could not read video frame from {media_path}")
            self._image_size = (frame.shape[1], frame.shape[0])
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tf:
                cv2.imwrite(tf.name, frame)
                self._temp_files.append(tf.name)
                return tf.name
        with Image.open(media_path) as img:
            self._image_size = img.size
        return media_path

    def _is_real_grid(self, image_path: str, grid_boxes: List[Tuple[int, int, int, int]]) -> bool:
        """Reject a lattice that is sheared, a sprite board on one background, or a flat image."""
        irregularity = _lattice_irregularity(grid_boxes)
        if irregularity is not None and irregularity > _GRID_REGULARITY_TOL:
            _debug(f"_is_real_grid: cells are {irregularity:.3f} of a cell out of true → reject")
            return False
        try:
            import cv2
            import numpy as np

            img = cv2.imread(image_path)
            if img is None:
                return True
            rois = [img[y1:y2, x1:x2].reshape(-1, 3) for (x1, y1, x2, y2) in grid_boxes
                    if x2 > x1 and y2 > y1 and img[y1:y2, x1:x2].size]
            if not rois:
                return False
            # Real tiles are independent photographs; a sprite board shares one colour behind every cell.
            if len(rois) >= 4 and float(np.mean(np.std(np.array([np.median(r, axis=0) for r in rois]), axis=0))) < 6.0:
                _debug("_is_real_grid: every cell shares one background colour → reject")
                return False
            if float(np.mean([np.mean(np.std(r, axis=0)) for r in rois])) < 25.0:
                _debug("_is_real_grid: overall mean stddev too low → reject")
                return False
            return True
        except Exception as e:
            _debug(f"_is_real_grid check errored ({e}); accepting grid.")
            return True

    def _cells_of(self, click: dict, grid_boxes: List[Tuple[int, int, int, int]]) -> List[int]:
        """The 1-based cells a generation-3 click names: its ids when any is a cell, else where its points land."""
        n = len(grid_boxes)
        ids = [i for i in click.get("ids", []) if 1 <= i <= n]
        if not ids:
            img_w, img_h = self._image_size
            ids = [c for c in (next((k + 1 for k, (x1, y1, x2, y2) in enumerate(grid_boxes)
                                     if x1 <= x * img_w <= x2 and y1 <= y * img_h <= y2), None)
                               for (x, y) in click.get("points", [])) if c is not None]
        return list(dict.fromkeys(ids))

    def _solve_grid(self, image_path: str, grid_boxes: List[Tuple[int, int, int, int]], rows: int, cols: int,
                    retry_mode: Optional[RetryMode] = None) -> Union[CaptchaAction, List[CaptchaAction]]:
        try:
            cv_selected, cv_loading = detect_selected_cells(image_path, grid_boxes)
        except Exception as e:
            _debug(f"detect_selected_cells failed: {e}")
            cv_selected, cv_loading = [], []

        # Every cell is numbered, exactly as the training overlays were; CV state is filtered after.
        with tempfile.NamedTemporaryFile(suffix=os.path.splitext(image_path)[1] or ".png", delete=False) as tf:
            overlay_path = tf.name
        self._temp_files.append(overlay_path)
        get_numbered_grid_overlay(image_path, grid_boxes, output_path=overlay_path)
        if self.planner.prompts.general is not None:
            raw = self.planner.get_general_actions(overlay_path)
            if not raw:
                raise UnsupportedCaptchaError("the model's answer to the grid could not be read")
            if raw[0]["kind"] != PixelAnswerKind.CLICK:
                return self._to_actions(raw)
            selected = self._cells_of(raw[0], grid_boxes)
        else:
            selected = self.planner.get_grid_selection(overlay_path, rows=rows, cols=cols, retry_mode=retry_mode)

        final = []
        for n in selected:
            try:
                v = int(n)
            except (TypeError, ValueError):
                continue
            if 1 <= v <= len(grid_boxes) and v not in cv_selected and v not in cv_loading:
                final.append(v)
        if not final:
            return WaitAction(action=ActionKind.WAIT, duration_ms=1000) if cv_loading else DoneAction(action=ActionKind.DONE)
        img_w, img_h = self._image_size
        return ClickAction(action=ActionKind.CLICK, target_bounding_boxes=[
            [x1 / img_w, y1 / img_h, x2 / img_w, y2 / img_h] for (x1, y1, x2, y2) in (grid_boxes[v - 1] for v in final)])


def solve_captcha(media_path: str, instruction: str = "", *, puzzle_source: Vendor = Vendor.UNKNOWN,
                  retry_mode: Optional[RetryMode] = None, text_mode: bool = False, **kwargs: Any) -> Any:
    # Solve arguments are spelled out because `**kwargs` go to the constructor: `text_mode=True` once raised
    # TypeError there, which made a static distorted-text image unsolvable through the public entry point.
    return CaptchaSolver(**kwargs).solve(media_path, instruction, puzzle_source=puzzle_source,
                                         retry_mode=retry_mode, text_mode=text_mode)
