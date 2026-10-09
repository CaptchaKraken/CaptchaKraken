"""Browser page driver: the Python mirror of js/src/solver.ts. Sync Playwright only."""

from __future__ import annotations

import hashlib
import io
import itertools
import json
import math
import os
import random
import re
import shutil
import sys
import tempfile
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import AbstractSet, Any, Callable, Dict, List, NamedTuple, Optional, Sequence, Set, Tuple

from . import planner
from .action_types import CaptchaAction
from .humanize import Humanizer, resolve as resolve_humanizer
from .kinds import (ActionKind, FrameRole, HumanizationMode, KeyframeMode, PauseKind, Phase, PromptFamily,
                    RecaptchaBanner, RetryMode, SettleVerdict, Vendor, Verdict)
from .selectors import (ACCEPTED_SELECTORS, PIECE_SELECTORS, RESPONSE_SELECTORS, SELECTORS, SLIDER_HANDLE_SELECTORS,
                        SUBMIT_SELECTORS, TEXT_INPUT_SELECTORS, TEXT_INPUT_VENDOR_SELECTORS, VENDORS, WIDGET_PROBES,
                        VendorSelectors, WidgetProbe)
from .solver import CaptchaSolver, UnsupportedCaptchaError
from .timing import PhaseBudget, timings_enabled
from .verdicts import RoundVerdict, VerdictLog

DEBUG = os.getenv("CAPTCHA_DEBUG", "0") == "1"
_SESSION_ENV = "CAPTCHA_KRAKEN_SESSION"
_VENDOR_ENV = "CAPTCHA_KRAKEN_VENDOR"
_SITE_ENV = "CAPTCHA_KRAKEN_SITE"
_WIDGET_HOST_ENV = "CAPTCHA_KRAKEN_WIDGET_HOST"
# How often a page that has not drawn its widget yet is looked at again.
_DETECTION_POLL_MS = 250


def _log(message: str) -> None:
    print(f"[captchakraken] {message}", flush=True)


def _debug(message: str) -> None:
    if DEBUG:
        print(f"[captchakraken:debug] {message}", flush=True)


def _delay(ms: float) -> None:
    if ms > 0:
        time.sleep(ms / 1000.0)


def _now() -> float:
    return time.monotonic() * 1000.0


def _tmp_png(prefix: str) -> str:
    fd, path = tempfile.mkstemp(prefix=f"{prefix}_", suffix=".png")
    os.close(fd)
    return path


def _unlink(path: Optional[str]) -> None:
    if path and os.path.exists(path):
        try:
            os.unlink(path)
        except OSError:
            pass


def _sha1(path: str) -> str:
    with open(path, "rb") as fh:
        return hashlib.sha1(fh.read()).hexdigest()


class CaptureRect(NamedTuple):
    """Whole CSS pixels, in viewport coordinates."""

    x: int
    y: int
    width: int
    height: int


def enclosing_rect(box: Dict[str, float]) -> CaptureRect:
    """The whole pixels a bounding box covers: the rect Playwright's element screenshot clips to."""
    x, y = math.floor(box["x"] + 1e-3), math.floor(box["y"] + 1e-3)
    return CaptureRect(x, y, math.ceil(box["x"] + box["width"] - 1e-3) - x,
                       math.ceil(box["y"] + box["height"] - 1e-3) - y)


def crop_png(png: bytes, rect: CaptureRect, css_width: float) -> bytes:
    """Cut `rect` out of a viewport capture `css_width` CSS pixels wide, at the capture's own device pixel ratio."""
    from PIL import Image

    with Image.open(io.BytesIO(png)) as img:
        scale = img.width / css_width
        out = io.BytesIO()
        img.crop((round(rect.x * scale), round(rect.y * scale), round((rect.x + rect.width) * scale),
                  round((rect.y + rect.height) * scale))).save(out, format="PNG", compress_level=1)
        return out.getvalue()


_VIEWPORT_JS = "() => ({ width: window.innerWidth, height: window.innerHeight })"
_FRAME_JS = ("() => ({ width: window.innerWidth, height: window.innerHeight,"
             " scale: window.visualViewport ? window.visualViewport.scale : 1 })")


def _viewport_of(page: Any) -> Dict[str, float]:
    """`viewport_size` is None on a context launched without one (camoufox), where only the window knows."""
    return page.viewport_size or page.evaluate(_VIEWPORT_JS)


def _layout_is_the_viewport(page: Any, view: Dict[str, float]) -> bool:
    """Does a viewport capture speak the bounding box's coordinates? Not on a page laid out wider than the device and zoomed out to fit, which is every mobile layout of a desktop page: there the box is in layout pixels and the capture is not."""
    frame = page.evaluate(_FRAME_JS)
    return abs(frame.get("scale", 1) - 1) < 1e-3 and abs(frame["width"] - view["width"]) <= 1


def _within(rect: CaptureRect, view: Dict[str, float]) -> bool:
    return rect.x >= 0 and rect.y >= 0 and rect.x + rect.width <= view["width"] and rect.y + rect.height <= view["height"]


def _off_board_point(box: Dict[str, float], at: Tuple[float, float],
                     view: Dict[str, float]) -> Optional[Tuple[float, float]]:
    """A point just outside the board, past the edge nearest the pointer, that is still inside the viewport."""
    x, y = at
    gap = 24 + random.random() * 40
    right, bottom = box["x"] + box["width"], box["y"] + box["height"]
    exits = sorted([(x - box["x"], (box["x"] - gap, y)), (right - x, (right + gap, y)),
                    (y - box["y"], (x, box["y"] - gap)), (bottom - y, (x, bottom + gap))])
    return next((p for _, p in exits if 0 <= p[0] < view["width"] and 0 <= p[1] < view["height"]), None)


class CaptchaSolveError(Exception):
    pass


class AnimatedChallengeError(CaptchaSolveError):
    pass


class UnsupportedChallengeError(CaptchaSolveError):
    pass


class NoCaptchaFoundError(CaptchaSolveError):
    pass


class PageClosedError(CaptchaSolveError):
    pass


class VendorBlockedError(CaptchaSolveError):
    """The vendor refused to serve this client at all, so no further round can succeed."""


#: `bounding box of captcha element` is in here because the JS port has always had it
#: (`isStaleHandleError`): a widget with no box has moved on under us — hCaptcha swapped rounds, GeeTest
#: closed on accept — and re-detecting is right where failing the attempt is not. Without it the Python
#: port turned an accepted board into a failed solve.
_STALE_HANDLE_RE = re.compile(
    r"Timeout .*exceeded|not visible|not attached|detached|bounding box of captcha element",
    re.IGNORECASE)
# A closed target is not a stale handle: retried as one, a dead page was re-detected three times and the
# error that finally escaped named whichever call ran last.
_CLOSED_TARGET_RE = re.compile(
    r"Target (?:page, context or browser )?(?:has been )?closed|Session closed", re.IGNORECASE)


def answer_needs_element_box(actions: Sequence[Any]) -> bool:
    """An allow-list of what needs nothing: the other direction raises instead of clicking at the origin.

    Takes actions in EITHER shape. The planner returns typed actions (`ClickAction`, `TypeAction`,
    `DoneAction`) and every other reader here goes through `_as_dict` first; this one called `.get` on
    them. It only runs when the element has no bounding box, which is what a widget that is CLOSING
    looks like — so a solve the vendor had just accepted ended as
    `AttributeError: 'ClickAction' object has no attribute 'get'` instead of as a success. Tier 3 saw
    it as a lost solve on five types.
    """
    return any(_as_dict(a).get("action") != ActionKind.DONE for a in actions if a is not None)


@dataclass
class SolveResult:
    is_solved: bool
    final_mouse_position: Tuple[float, float]
    token_usage: List[Dict[str, Any]] = field(default_factory=list)
    phases: Dict[str, float] = field(default_factory=dict)
    # What the vendor's own server answered, in order, for the vendors whose answer is readable.
    verdicts: List[RoundVerdict] = field(default_factory=list)


@dataclass
class _GridSession:
    grid_boxes: List[Sequence[int]]
    element_box: Dict[str, float]
    scale_x: float
    scale_y: float
    screenshot_w: int
    screenshot_h: int


# Mirrors the JS port: past the floor window, this many distinct screens still arriving is an animation
# even though no screen has come back yet.
BURST_ANIMATED_SCREENS = 6


def settle_verdict(samples, *, settle_frames: int, animated_after_ms: int,
                   motion_streak: int = 0) -> SettleVerdict:
    """The pixel-settle rule over `(elapsed_ms, moved)` polls.

    `motion_streak` exits early: rotating_obj_video changes every 133-171ms, and without it 4.5s went on
    proving that before a fresh 4s burst filmed it again.
    """
    still = moved = 0
    for elapsed_ms, did_move in samples:
        if did_move:
            still, moved = 0, moved + 1
            if elapsed_ms >= animated_after_ms or (motion_streak and moved >= motion_streak):
                return SettleVerdict.ANIMATED
        else:
            moved, still = 0, still + 1
            if still >= settle_frames:
                return SettleVerdict.SETTLED
    return SettleVerdict.TIMEOUT


def burst_hang_deadline_ms(cfg) -> float:
    return 3.0 * float(cfg.video_burst_max_ms) + 5_000.0


def measured_fps(frames: int, elapsed_ms: float, nominal_fps: float) -> float:
    if frames <= 0 or elapsed_ms <= 0:
        return float(nominal_fps)
    return frames / (elapsed_ms / 1000.0)


# Frame-diff thresholds; two screens of one board differ by ~0.0056, a different board by ~0.77.
# 0.002 sits above the 0.001 noise floor; reusing stale_frame_diff_threshold (0.02) was blind to GeeTest svg.
_MOVED_DURING_INFERENCE_DIFF = 0.002
_NOT_THIS_BOARD_DIFF = 0.5
_NOT_THIS_BOARD_POLLS = 3
# How long a control we hovered, pressed or typed into takes to stop repainting in reaction. A board read
# inside this window is wearing our own feedback, which is not a screen it ever showed by itself.
INPUT_SETTLE_MS = 400


@dataclass
class PageSolverConfig:
    humanization: Optional[HumanizationMode] = None
    humanizer: Optional[Humanizer] = None
    touch_driver: Optional[Any] = None
    touch_transform: Optional[Dict[str, Any]] = None
    starting_mouse_position: Optional[Tuple[float, float]] = None
    expert: Optional[PromptFamily] = None
    max_solve_loops: int = 6
    overall_solve_timeout_ms: int = 45_000
    # A page just navigated has often not drawn its widget; this long is spent looking before "no captcha" is
    # believed. It is not charged to overall_solve_timeout_ms, which starts when there is something to solve.
    detection_timeout_ms: int = 15_000
    # Repeats of one answer on one board before the solve ends; the first repeats are re-asked at a fresh sample.
    max_no_progress_rounds: int = 2
    # Deprecated and ignored since 3.2.0: a round that performed nothing goes straight on to the next.
    post_solve_delay_ms: int = 1_200
    post_solve_outcome_timeout_ms: int = 1_000
    post_solve_outcome_poll_ms: int = 75
    element_screenshot_timeout_ms: int = 8_000
    # Deprecated and ignored since 3.2.0: each of these failures now counts against max_solve_loops.
    max_unsupported_resolves: int = 3
    max_stale_element_retries: int = 3
    # The pause before a failed round is tried again.
    stale_element_backoff_ms: int = 900
    stale_frame_resolve_enabled: bool = True
    stale_frame_diff_threshold: float = 0.02
    max_stale_frame_resolves: int = 2
    settle_poll_ms: int = 220
    settle_frames: int = 2
    settle_timeout_ms: int = 9_000
    animated_challenge_after_ms: int = 4_500
    animated_motion_streak: int = 5
    settle_diff_threshold: float = 0.01
    post_submit_change_timeout_ms: int = 4_000
    video_solve_enabled: bool = True
    animated_probe_enabled: bool = True
    video_burst_duration_ms: int = 4_000
    video_burst_max_ms: int = 12_000
    # Safety ceiling on the film an animated board accumulates across rounds. It is meant to end with the
    # solve, not on this clock; frames are decoded images, so this bounds memory rather than the recording.
    video_film_max_ms: int = 120_000
    speculative_burst_enabled: bool = True
    video_burst_fps: int = 10
    # GeeTest svg dwells up to 2.7s a screen, so a 3-screen cycle is 8.1s; 6s gave up one screen short.
    keyframe_wait_timeout_ms: int = 9_000
    keyframe_wait_poll_ms: int = 120
    video_extra_inference_ms: int = 8_000
    hcaptcha_images_timeout_ms: int = 3_000
    grid_load_poll_interval_ms: int = 250
    grid_load_timeout_ms: int = 8_000
    board_paint_poll_ms: int = 180
    board_paint_timeout_ms: int = 2_500
    board_paint_floor: Optional[float] = None
    recaptcha_max_dynamic_rounds: int = 8
    recaptcha_fade_onset_grace_ms: int = 4_000
    recaptcha_dynamic_fade_poll_ms: int = 250
    recaptcha_dynamic_fade_wait_ms: int = 6_000
    recaptcha_tile_hover_enabled: bool = True
    slide_tolerance_px: float = 2.0
    slide_max_corrections: int = 3

    def video_budget_ms(self) -> int:
        return (self.video_burst_max_ms + self.keyframe_wait_timeout_ms
                + self.video_extra_inference_ms)


class Widget(NamedTuple):
    """What detection found: the handle to photograph, the locator to search inside, and which table entry named it."""

    element: Any
    at: Any
    vendor: Vendor
    role: FrameRole


# A named set rather than `== UNKNOWN`: naming a new vendor must not silently switch off typed-challenge
# detection for the text vendors and the animated probe for GeeTest and Tencent.
VENDORS_WITH_BESPOKE_HANDLING: frozenset[Vendor] = frozenset({Vendor.HCAPTCHA, Vendor.RECAPTCHA})

# Long enough to resolve a locator `all()` just returned, short enough that a widget gone in between reads as stale, not hung.
HANDLE_TIMEOUT_MS = 1000


def _visible(scope: Any, selectors: Sequence[str]) -> List[Any]:
    """Every visible match of `selectors`, in selector order. A selector this adapter can't parse is skipped, not fatal."""
    found: List[Any] = []
    for selector in selectors:
        try:
            found.extend(scope.locator(selector).filter(visible=True).all())
        except Exception:
            continue
    return found


def _handle_of(at: Any) -> Optional[Any]:
    try:
        return at.element_handle(timeout=HANDLE_TIMEOUT_MS)
    except Exception:
        return None


def _handles(ats: Sequence[Any]) -> List[Any]:
    return [h for h in map(_handle_of, ats) if h is not None]


def _frame_of(at: Any) -> Optional[Any]:
    handle = _handle_of(at)
    try:
        return handle.content_frame() if handle else None
    except Exception:
        return None


def _input_value(handle: Any) -> str:
    try:
        return str(handle.input_value() or "")
    except Exception:
        return ""


def _has_text(handle: Any) -> bool:
    try:
        return bool((handle.text_content() or "").strip())
    except Exception:
        return False


SLIDE_PIECE_MIN_PX = 3.0
SLIDE_PIECE_MAX_FRACTION = 0.6

# No prompt and no pictures both read as ready: waiting for `.prompt-text` to exist once paid the whole timeout
# before every board of a challenge that draws none (tower_stack: 18s a round, 2/2 -> 0/2).
_BOARD_IMAGES_READY_JS = """({ prompt, images }) => {
    const vis = (el) => !!el && el.getClientRects().length > 0
        && getComputedStyle(el).visibility !== 'hidden';
    const p = prompt && document.querySelector(prompt);
    if (p && !vis(p)) return false;
    return Array.from(document.querySelectorAll(images)).every((el) => {
        if (el instanceof HTMLImageElement) return el.complete && el.naturalWidth > 0;
        const bg = getComputedStyle(el).backgroundImage;
        return !!bg && bg !== 'none' && !/url\\(["']?["']?\\)/.test(bg);
    });
}"""
_RESOURCES_JS = """() => {
  const out = [];
  try { for (const e of performance.getEntriesByType('resource')) out.push(e.name); } catch (err) {}
  for (const el of document.querySelectorAll('script[src],iframe[src],link[href],img[src]')) {
    out.push(el.getAttribute('src') || el.getAttribute('href') || '');
  }
  return out;
}"""


class PageSolver:
    """Drives one Playwright-compatible `page` through a captcha. Reusable across solves."""

    def __init__(self, config: Optional[PageSolverConfig] = None,
                 solver: Optional[CaptchaSolver] = None, **solver_kwargs: Any) -> None:
        self.config = config or PageSolverConfig()
        if self.config.expert is not None:
            solver_kwargs.setdefault("expert", self.config.expert)
        self._solver = solver or CaptchaSolver(**solver_kwargs)
        self._human: Humanizer = resolve_humanizer(self.config)
        self._last_submit_frame_hash: Optional[str] = None
        self._deadline_ms: Optional[float] = None
        self._budget: Optional[PhaseBudget] = None
        self._animated_plan: Optional[Tuple[List[str], str, Any, Any]] = None
        self._film_frames: List[Any] = []
        self._film_ms: float = 0.0
        # The digests of every screen the film holds: what a later burst is checked against to answer
        # "is this still the same board?" — see `_record_keyframes`.
        self._film_digests: Set[str] = set()
        # Has this board EVER shown the same screen twice? A board that has not cannot prove it was replaced
        # and has no cycle left to find, so a re-ask neither re-films it at length nor throws its film away.
        self._film_cycled: bool = False
        self._verdicts: Optional[VerdictLog] = None
        # The page being solved: every capture is taken of its viewport. Set by `solve`.
        self._page: Any = None
        # When our last gesture ended; the board's reaction to it is never read as the board's own motion.
        self._last_input_ms: float = -math.inf
        self._reset_animated_state()

    @property
    def _last_mouse(self) -> Tuple[float, float]:
        return self._human.at

    @_last_mouse.setter
    def _last_mouse(self, at: Tuple[float, float]) -> None:
        self._human.at = (float(at[0]), float(at[1]))

    @contextmanager
    def _phase(self, name: Phase):
        if self._budget is None:
            yield
            return
        with self._budget.phase(name):
            yield

    @contextmanager
    def _gesture(self):
        """A pointer gesture, timed as MOUSE and remembered: see `INPUT_SETTLE_MS`."""
        try:
            with self._phase(Phase.MOUSE):
                yield
        finally:
            self._last_input_ms = _now()

    # ── per-solve state ──────────────────────────────────────────────────

    def _reset_animated_state(self) -> None:
        self._acted_on_board = False
        self._known_animated = False
        self._animated_probe_armed = False
        self._animated_probe_done = False
        self._video_budget_granted = False
        self._stop_animated_film()
        self._keyframe_mode: Optional[KeyframeMode] = None
        self._keyframe_steady_screens = 0
        self._last_answer_sig: Optional[str] = None
        self._no_progress_rounds = 0
        self._resample_level = 0
        self._apply_sampling()

    @staticmethod
    def _answer_signature(actions: Sequence[Any], retry_mode: Optional[RetryMode]) -> Optional[str]:
        """Keyed on retry mode: the missed-tiles answer legitimately overlaps the previous one."""
        try:
            parts = [(a.get("action"), _round_pts(a.get("target_bounding_boxes")),
                      _round_pts(a.get("target_bounding_box")), _round_pts(a.get("target_coordinates")),
                      _round_pts(a.get("source_bounding_box")), a.get("text"))
                     for a in map(_as_dict, actions)]
            return repr((retry_mode, parts))
        except Exception:
            return None

    def _note_answer(self, actions: Sequence[Any], retry_mode: Optional[RetryMode]) -> bool:
        """True when this answer already ran and changed nothing: resample, re-ask, and arm the probe."""
        sig = self._answer_signature(actions, retry_mode)
        if sig is not None and sig == self._last_answer_sig:
            self._no_progress_rounds += 1
            _log(f"[no-progress] the model returned the same answer again ({self._no_progress_rounds} in a row)")
            self._resample_level += 1
            self._apply_sampling()
            self._invalidate_animated_answer()
            self._arm_animated_probe()
            return True
        self._no_progress_rounds = 0
        self._last_answer_sig = sig
        return False

    def _bound_ask_to_the_budget(self) -> None:
        """Give the planner what is LEFT of the solve, so one ask cannot outlive the whole thing.

        A request in flight cannot be cancelled — `_check_deadline` is only read between steps — so the
        only thing that bounds it is the timeout it was sent with. Measured on the hosted endpoint: one
        ask hung and gave up after ~124s inside a 45s budget, and the attempt ran 143s.
        """
        target = getattr(self._solver, "planner", None)
        if target is None or self._deadline_ms is None:
            return
        left_s = (self._deadline_ms - _now()) / 1000.0
        target.request_timeout_s = max(planner.MIN_REQUEST_TIMEOUT_S,
                                       min(planner.DEFAULT_REQUEST_TIMEOUT_S, left_s))

    def _apply_sampling(self) -> None:
        target = getattr(self._solver, "planner", None)
        if target is None:
            return
        target.sampling = sampling = planner.sampling_for_level(self._resample_level)
        if sampling:
            _log(f"[resample] temperature {sampling['temperature']}, seed {sampling['seed']}")

    def _fresh_board(self) -> None:
        # ONE FILM, ONE BOARD — enforced where the board actually changes. The recorded answer describes the
        # board it was cut from, so replaying it here presses that board's coordinates onto this one: live, a
        # keyframe answer from an earlier board landed on hCaptcha's reference photo and then pressed Skip,
        # six rounds running.
        self._stop_animated_film()
        self._known_animated = False
        # Its own second look, but only once IT fails: an arm set on the previous board is evidence about that one.
        self._animated_probe_armed = False
        self._animated_probe_done = False
        self._resample_level = 0
        self._acted_on_board = False
        self._apply_sampling()

    def _check_deadline(self, where: str) -> None:
        # Called inside loops too: a camoufox session once ran ten minutes past a 120s timeout because only
        # the loop head checked.
        if self._deadline_ms is not None and _now() > self._deadline_ms:
            raise CaptchaSolveError(
                f"captcha solve exceeded overall_solve_timeout_ms "
                f"({self.config.overall_solve_timeout_ms}ms) during {where}")

    def _grant_video_budget(self) -> None:
        """The recording path buys its own budget once per solve."""
        cfg = self.config
        if cfg.video_solve_enabled and not self._video_budget_granted:
            self._video_budget_granted = True
            if self._deadline_ms is not None:
                self._deadline_ms += cfg.video_budget_ms()
                _log(f"[animated] +{cfg.video_budget_ms()}ms for the recording path")

    # ── the shared half, in-process ──────────────────────────────────────

    def _find_grid(self, image_path: str) -> Optional[List[Sequence[int]]]:
        from .tool_calls.find_grid import find_grid

        try:
            return find_grid(image_path)
        except Exception as exc:
            _debug(f"find_grid failed: {exc}")
            return None

    def _has_movement(self, path_a: str, path_b: str, threshold: float) -> bool:
        from .image_processor import ImageProcessor

        try:
            return bool(ImageProcessor.detect_movement(path_a, path_b, threshold))
        except Exception as exc:
            _debug(f"detect_movement failed: {exc}")
            return False

    def _grid_cell_states(self, path_a: str, path_b: str,
                          grid_boxes: Sequence[Sequence[int]]) -> Optional[Dict[str, List[int]]]:
        from .cli import grid_cell_states

        try:
            return grid_cell_states(path_a, path_b, list(grid_boxes))
        except Exception as exc:
            _debug(f"grid_cell_states failed: {exc}")
            return None

    def _board_painted(self, path: str) -> Optional[bool]:
        from .tool_calls.board_painted import board_is_painted

        try:
            return board_is_painted(path, self.config.board_paint_floor)["painted"]
        except Exception:
            return None

    def _ask(self, query: Callable[[], Any]) -> Tuple[List[CaptchaAction], List[Dict[str, Any]]]:
        """One model query; usage is read off the shared planner by delta."""
        p = self._solver.planner
        before = len(p.token_usage)
        actions = query()
        usage = [dict(u) for u in p.token_usage[before:]]
        return (actions if isinstance(actions, list) else [actions]), usage

    def _get_solution(self, image_path: str, puzzle_source: Vendor, retry_mode: Optional[RetryMode],
                      text_mode: bool = False):
        return self._ask(lambda: self._solver.solve(
            image_path, puzzle_source=puzzle_source, retry_mode=retry_mode, text_mode=text_mode))

    def _get_keyframe_solution(self, keyframe_paths: Sequence[str]):
        return self._ask(lambda: self._solver.solve_keyframes(keyframe_paths))

    # ── gestures ─────────────────────────────────────────────────────────

    def _smooth_move(self, page: Any, x: float, y: float) -> None:
        with self._gesture():
            self._human.move(page, (x, y))

    def _move_to_element(self, page: Any, element: Any, padding_percentage: float = 25.0) -> None:
        # Bounded: Playwright's default 30s stability wait hangs on an animating frame.
        try:
            element.scroll_into_view_if_needed(timeout=2_000)
        except TypeError:
            try:
                element.scroll_into_view_if_needed()
            except Exception:
                pass
        except Exception:
            pass
        box = element.bounding_box()
        if not box:
            raise CaptchaSolveError("element has no bounding box")
        pad = padding_percentage / 100.0
        self._smooth_move(
            page,
            box["x"] + box["width"] * (pad + random.random() * (1 - 2 * pad)),
            box["y"] + box["height"] * (pad + random.random() * (1 - 2 * pad)))

    def _move_and_click(self, page: Any, element: Any) -> None:
        self._move_to_element(page, element)
        with self._gesture():
            self._human.click(page, self._last_mouse)

    @staticmethod
    def _click_point_for(action: Dict[str, Any],
                         element_box: Dict[str, float]) -> Optional[Tuple[float, float]]:
        """Element-relative click point: a random spot inside the box, inset 10% off its border."""
        bbox = action.get("target_bounding_box")
        coords = action.get("target_coordinates")
        if bbox:
            x1, y1, x2, y2 = (float(v) for v in bbox)
            w, h = element_box["width"], element_box["height"]
            px, py = (x2 - x1) * w * 0.1, (y2 - y1) * h * 0.1
            return (x1 * w + px + random.random() * ((x2 - x1) * w - 2 * px),
                    y1 * h + py + random.random() * ((y2 - y1) * h - 2 * py))
        if coords:
            return float(coords[0]) * element_box["width"], float(coords[1]) * element_box["height"]
        return None

    def _execute_click(self, page: Any, action: Dict[str, Any], element_box: Dict[str, float],
                       element: Any = None, await_keyframe: Optional[str] = None) -> None:
        # Every gesture marks the board acted on so the speculative burst is never re-run over a touched board.
        self._acted_on_board = True
        rel = self._click_point_for(action, element_box)
        if rel is None:
            _log("click action without coordinates or bounding box; skipping")
            return
        at = (element_box["x"] + rel[0], element_box["y"] + rel[1])
        if await_keyframe:
            # Park on the target first, so only a mouse-down separates the right screen from the click.
            with self._gesture():
                self._human.move(page, at)
            self._wait_for_keyframe(element, await_keyframe,
                                    (rel[0] / element_box["width"], rel[1] / element_box["height"]))
        with self._gesture():
            self._human.click(page, at)

    def _click_when_frame_matches(self, page: Any, element: Any, action: Dict[str, Any],
                                  element_box: Dict[str, float], await_keyframe: str) -> None:
        self._execute_click(page, action, element_box, element, await_keyframe)

    def _execute_drag(self, page: Any, action: Dict[str, Any], element_box: Dict[str, float]) -> None:
        self._acted_on_board = True

        def center(bbox):
            return (element_box["x"] + (float(bbox[0]) + float(bbox[2])) / 2 * element_box["width"],
                    element_box["y"] + (float(bbox[1]) + float(bbox[3])) / 2 * element_box["height"])

        with self._gesture():
            self._human.drag(page, center(action["source_bounding_box"]), center(action["target_bounding_box"]))

    def _find_control(self, scope: Any, selectors: Sequence[str]) -> Optional[Any]:
        first = next(iter(_visible(scope, selectors)), None)
        return _handle_of(first) if first is not None else None

    def _measure_piece_box(self, scope: Any, widget_width: float) -> Optional[Dict[str, float]]:
        """The slider piece's box: the first visible match small enough to be a piece.

        Runs during detection, so it must not mark the board acted on: doing so once disabled the
        speculative burst on every slide solve.
        """
        for candidate in _handles(_visible(scope, PIECE_SELECTORS)):
            try:
                b = candidate.bounding_box()
            except Exception:
                continue
            if b and SLIDE_PIECE_MIN_PX <= b["width"] <= widget_width * SLIDE_PIECE_MAX_FRACTION:
                return b
        return None

    def _answer_box(self, scope: Any, at: Any = None) -> Optional[Any]:
        """The text box inside the widget, else a vendor-named one in its enclosing fieldset/form.

        Only vendor-named selectors widen: BotDetect's `.BDC_CaptchaDiv` is 280x50 and holds only the image,
        with `#captchaCode` in a sibling div. The generic tail there would take a login form's own box.
        """
        inside = self._find_control(scope, TEXT_INPUT_SELECTORS)
        if inside is not None or at is None:
            return inside
        around = (self._find_control(at.locator(f"xpath={axis}"), TEXT_INPUT_VENDOR_SELECTORS)
                  for axis in ("ancestor::fieldset[1]", "ancestor::form[1]"))
        return next((found for found in around if found is not None), None)

    def _execute_type(self, page: Any, scope: Any, action: Dict[str, Any], at: Any = None) -> bool:
        self._acted_on_board = True
        text = str(action.get("text") or "")
        field_el = text and self._answer_box(scope, at)
        if not field_el:
            _log("type action, but no text box in the widget; skipping")
            return False
        self._move_and_click(page, field_el)
        typed = self._human.type_text(page, field_el, text)
        self._last_input_ms = _now()
        if not typed:
            return False
        _log(f"typed {len(text)} character(s) into the captcha field")
        return True

    def _track_piece(self, element: Any, before: str, after: str, exclude: Sequence[float],
                     travel: float = 0.0) -> Optional[Dict[str, Any]]:
        from .tool_calls.track_piece import changed_bbox, locate_piece

        try:
            self._screenshot(element, after, timeout_ms=self.config.element_screenshot_timeout_ms)
            bbox = changed_bbox(before, after, exclude)
            if bbox is None:
                return None
            return {"bbox": bbox, "piece": locate_piece(before, after, travel, exclude)}
        except Exception as exc:
            _debug(f"track_piece failed: {exc}")
            return None

    @staticmethod
    def _shot_scale(shot: str, css_width: float) -> float:
        dims = _read_png_dimensions(shot)
        return dims[0] / css_width if dims and css_width > 0 else 1.0

    def _execute_slide(self, page: Any, element: Any, scope: Any, action: Dict[str, Any],
                       element_box: Dict[str, float]) -> bool:
        """Aim the handle at the slot once, then look and correct until the piece is home."""
        self._acted_on_board = True
        tb = action["target_bounding_box"]
        target_x = (float(tb[0]) + float(tb[2])) / 2 * element_box["width"]

        handle = self._find_control(scope, SLIDER_HANDLE_SELECTORS)
        if handle is None:
            piece = self._find_control(scope, PIECE_SELECTORS)
            box = piece and piece.bounding_box()
            if not box:
                _log("slide action, but the widget has neither a slider nor a draggable piece")
                return False
            target_y = (float(tb[1]) + float(tb[3])) / 2 * element_box["height"]
            with self._gesture():
                self._human.drag(page, (box["x"] + box["width"] / 2, box["y"] + box["height"] / 2),
                                 (element_box["x"] + target_x, element_box["y"] + target_y))
            return True

        hbox = handle.bounding_box()
        if not hbox:
            return False
        start_x, hold_y = hbox["x"] + hbox["width"] / 2, hbox["y"] + hbox["height"] / 2
        # Mask from the handle's band to the widget's bottom: the filled track moves too.
        pad = max(4.0, hbox["height"] * 0.35)
        band = [0.0, hbox["y"] - element_box["y"] - pad, element_box["width"], element_box["height"]]
        shots = [_tmp_png("slide") for _ in range(2)]
        try:
            self._move_to_element(page, handle, padding_percentage=30.0)
            self._human.press(page)
            self._human.pause(PauseKind.GRAB)
            self._screenshot(element, shots[0], timeout_ms=self.config.element_screenshot_timeout_ms)
            scale = self._shot_scale(shots[0], element_box["width"])
            exclude = [v * scale for v in band]

            def live_center():
                b = self._measure_piece_box(scope, element_box["width"])
                return None if b is None else b["x"] + b["width"] / 2.0 - element_box["x"]

            rest = live_center()
            offset = target_x - (start_x - element_box["x"] if rest is None else rest)
            self._smooth_move(page, start_x + offset, hold_y)

            widths: List[Tuple[float, float]] = []
            last_box = last_piece = None
            ratio, steered = 1.0, False
            for _ in range(self.config.slide_max_corrections):
                self._human.pause(PauseKind.PROBE)
                seen = self._track_piece(element, shots[0], shots[1], exclude, travel=offset * ratio * scale)
                if seen is not None:
                    box = seen["bbox"]
                    widths.append((offset, float(box[2] - box[0]) / scale))
                    last_box, last_piece = box, seen["piece"]
                piece_w, ratio = self._solve_slide_geometry(widths, element_box["width"])
                live = live_center()
                if live is not None:
                    center = live
                elif last_piece is not None:
                    center = last_piece["centre"] / scale
                elif last_box is not None and piece_w is not None:
                    center = last_box[2] / scale - piece_w / 2.0
                else:
                    continue
                steered = True
                error = target_x - center
                _debug(f"slider: center={center:.1f} target={target_x:.1f} error={error:+.1f} ratio={ratio:.3f}")
                if abs(error) <= self.config.slide_tolerance_px:
                    break
                offset += error / ratio
                self._smooth_move(page, start_x + offset, hold_y)
            if not steered:
                _log("slider: the piece never resolved on screen; released where the opening sweep put it")
            self._human.pause(PauseKind.SETTLE)
        finally:
            try:
                self._human.release(page)
            except Exception:
                pass
            self._last_input_ms = _now()
            for shot in shots:
                _unlink(shot)
        return True

    @staticmethod
    def _solve_slide_geometry(widths: Sequence[Tuple[float, float]],
                              widget_width: float) -> Tuple[Optional[float], float]:
        """Piece width and handle-to-piece ratio from `(offset, changed width)` readings.

        The widest-apart pair over a 16px spread: changed widths are ±1px, so the ratio error is ±0.13 at the
        floor and ±0.5 at 4px. An implausible ratio falls back to 1:1 (true of every vendor observed) rather
        than a 0.02 that sends the handle off the track and camoufox into a move that never returns.
        """
        if not widths:
            return None, 1.0
        piece_w, ratio = None, 1.0
        (o1, w1), (o2, w2) = min(widths, key=lambda m: m[0]), max(widths, key=lambda m: m[0])
        if o2 - o1 >= 16.0 and 0.2 <= (w2 - w1) / (o2 - o1) <= 3.0:
            ratio = (w2 - w1) / (o2 - o1)
            piece_w = w1 - ratio * o1
        if piece_w is None:
            o, w = widths[-1]
            piece_w = w - ratio * o
        if not (SLIDE_PIECE_MIN_PX <= piece_w <= widget_width * SLIDE_PIECE_MAX_FRACTION):
            return None, ratio
        return piece_w, ratio

    # ── detection ────────────────────────────────────────────────────────

    def _has_value(self, page: Any, selector: str) -> bool:
        """Any element at `selector` carrying a non-blank value; response fields are hidden, so no visibility filter."""
        try:
            fields = _handles(page.locator(selector).all())
        except Exception:
            return False
        return any(_input_value(f).strip() for f in fields)

    def _visible_with_text(self, scope: Any, selector: str) -> bool:
        """A visible match carrying text; an empty banner or prompt is a placeholder, not a signal."""
        return any(map(_has_text, _handles(_visible(scope, (selector,)))))

    def _checked_in(self, checkbox: Any, checked: str) -> bool:
        frame = _frame_of(checkbox)
        return bool(frame) and bool(_visible(frame, (checked,)))

    def has_interactive_widget_in_dom(self, page: Any) -> bool:
        """Is a widget in the DOM at all, rendered or not? Invisible reCAPTCHA is excluded by its selector.

        The inline vendors count: without them the JS port failed fast in under a second on every GeeTest/Yidun page.
        """
        def count(selector: str) -> int:
            try:
                return page.locator(selector).count()
            except Exception:
                return 0

        return any(count(p.selector) > 0 for p in WIDGET_PROBES)

    def detect_captcha(self, page: Any) -> Optional[Widget]:
        """Open challenges first, then unsolved checkboxes, then the inline vendors."""
        for probe in WIDGET_PROBES:
            at = next(iter(_visible(page, (probe.selector,))), None)
            if at is None or self._already_accepted(page, at, probe):
                continue
            element = _handle_of(at)
            return Widget(element, at, probe.vendor, probe.role) if element is not None else None
        return None

    def _already_accepted(self, page: Any, at: Any, probe: WidgetProbe) -> bool:
        """A checkbox the vendor has already accepted is not a captcha to solve."""
        s = SELECTORS[probe.vendor]
        if probe.role != FrameRole.CHECKBOX:
            return False
        return bool(s.response and self._has_value(page, s.response)) or bool(s.checked and self._checked_in(at, s.checked))

    def vendors_on_the_wire(self, page: Any) -> List[Vendor]:
        """Which vendors' code the page loaded. Resource timing, because a request listener would have to have been attached before navigation."""
        try:
            names = page.evaluate(_RESOURCES_JS)
        except Exception:
            return []
        blob = " ".join(str(n) for n in (names or []))
        return [vendor for vendor, s in VENDORS if any(h in blob for h in s.hosts)]

    def _unmatched_vendor_frames(self, page: Any) -> List[Vendor]:
        """Vendors showing a frame no selector names. Only asked once detection has found nothing, and a passive frame
        (an invisible badge) is not a widget, so what is left is markup the table no longer matches."""
        return [vendor for vendor, s in VENDORS if s.hosts and len(_visible(page, [f'iframe[src*="{h}"]' for h in s.hosts]))
                > len(_visible(page, s.passive))]

    def _no_widget_message(self, page: Any) -> str:
        base = f"no interactive captcha widget detected within {self.config.detection_timeout_ms}ms"
        loaded = self.vendors_on_the_wire(page)
        if not loaded:
            return (f"{base} (no vendor captcha code loaded on this page — likely reCAPTCHA v3 / "
                    "invisible, or a click-triggered challenge that has not been triggered)")
        framed = self._unmatched_vendor_frames(page)
        if framed:
            return (f"{base}, BUT {'/'.join(framed)} is showing a frame that matches nothing in SELECTORS. The "
                    "vendor's markup has changed — the table needs re-measuring against the vendor's current "
                    "markup, in both solver ports")
        return (f"{base}; {'/'.join(loaded)} code is loaded but drew no widget — the challenge may be invisible "
                "or not triggered yet, or an in-page widget's markup has changed")

    def _await_widget(self, page: Any) -> Tuple[Optional[Widget], float]:
        """A page that has not drawn its widget yet is looked at again until `detection_timeout_ms`, and the time
        spent is returned so the solve budget can start after it. Solving straight after `domcontentloaded` failed
        3/3 on a demo page whose frames arrived a moment later."""
        started = _now()
        widget = None
        with self._phase(Phase.DETECT):
            while (widget is None and _now() - started < self.config.detection_timeout_ms
                   and not self.is_captcha_solved(page)):
                _delay(_DETECTION_POLL_MS)
                widget = self.detect_captcha(page)
        return widget, _now() - started

    def _is_blocked(self, page: Any) -> bool:
        """The vendor showing its refusal screen: rate-limited or flagged, with no board to answer."""
        for probe in WIDGET_PROBES:
            blocked = SELECTORS[probe.vendor].blocked
            if probe.role != FrameRole.CHALLENGE or not blocked:
                continue
            at = next(iter(_visible(page, (probe.selector,))), None)
            frame = _frame_of(at) if at is not None else None
            if frame and any(self._visible_with_text(frame, selector) for selector in blocked):
                return True
        return False

    def _vendor_verdict(self) -> Optional[Verdict]:
        """What the vendor's server said since the last look: BLOCKED outranks everything, else the latest answer."""
        fresh = [v.verdict for v in (self._verdicts.fresh() if self._verdicts else ()) if v.verdict != Verdict.NEW_CHALLENGE]
        return Verdict.BLOCKED if Verdict.BLOCKED in fresh else (fresh[-1] if fresh else None)

    def is_captcha_solved(self, page: Any) -> bool:
        """The vendor's own done signal: a response token, a painted success state, or a checked box."""
        try:
            if any(self._has_value(page, s) for s in RESPONSE_SELECTORS) or _visible(page, ACCEPTED_SELECTORS):
                return True
            for probe in WIDGET_PROBES:
                checked = SELECTORS[probe.vendor].checked
                if probe.role != FrameRole.CHECKBOX or not checked:
                    continue
                at = next(iter(_visible(page, (probe.selector,))), None)
                if at is not None and self._checked_in(at, checked):
                    return True
        except Exception:
            pass
        return False

    def _is_challenge_freshly_rendered(self, page: Any) -> bool:
        """A next round has painted, as opposed to the answered frame animating closed."""
        try:
            for probe in WIDGET_PROBES:
                fresh = SELECTORS[probe.vendor].fresh
                if probe.role != FrameRole.CHALLENGE or not fresh:
                    continue
                at = next(iter(_visible(page, (probe.selector,))), None)
                element = _handle_of(at) if at is not None else None
                if element is None:
                    continue
                if self._last_submit_frame_hash and self._element_frame_hash(element) == self._last_submit_frame_hash:
                    continue
                frame = element.content_frame()
                if frame and self._visible_with_text(frame, fresh):
                    return True
        except Exception:
            pass
        return False

    @staticmethod
    def _banner_is_fatal_after_retry(kind: Optional[RecaptchaBanner]) -> bool:
        return kind in (RecaptchaBanner.SELECT_MORE, RecaptchaBanner.REJECTED)

    def _banner_kind(self, page: Any) -> Optional[RecaptchaBanner]:
        """Which verdict banner the open challenge shows; `dynamic-more` is the dynamic board's normal flow, not an error."""
        try:
            for probe in WIDGET_PROBES:
                banners = SELECTORS[probe.vendor].banners
                if probe.role != FrameRole.CHALLENGE or not banners:
                    continue
                at = next(iter(_visible(page, (probe.selector,))), None)
                frame = _frame_of(at) if at is not None else None
                if not frame:
                    continue
                shown = next((kind for selector, kind in banners if self._visible_with_text(frame, selector)), None)
                if shown is not None:
                    return shown
        except Exception:
            pass
        return None

    def _click_checkbox(self, page: Any, widget: Widget, frame: Any) -> None:
        """Tick the box and wait for what it opens. A checkbox is not a board: it is never polled, filmed or asked about.

        Treated as a board it cost 70 screenshots and three model calls in one measured solve, two of them answering
        the checkbox picture with a drag.
        """
        box = self._checkbox_box(frame, widget.vendor)
        if box is not None:
            self._move_to_element(page, box)
        else:
            self._smooth_move(page, *self._find_checkbox_on_screen(widget.element))
        self._human.pause(PauseKind.BETWEEN)
        with self._gesture():
            self._human.click(page, self._last_mouse)
        self._await_what_the_checkbox_opened(page)

    def _checkbox_box(self, frame: Any, vendor: Vendor) -> Optional[Any]:
        """The box in a checkbox frame once the frame has drawn it; None when the DOM cannot reach it.

        Turnstile's box is in a closed shadow root, and a frame can refuse access; both are found on screen instead.
        """
        box = SELECTORS[vendor].box
        if frame is None or not box:
            return None
        try:
            return frame.wait_for_selector(", ".join(box), state="visible", timeout=self.config.detection_timeout_ms)
        except Exception as exc:
            _log(f"[checkbox] the box is out of the DOM's reach ({str(exc).splitlines()[0]}); finding it on screen")
            return None

    def _find_checkbox_on_screen(self, element: Any) -> Tuple[float, float]:
        """One capture and OpenCV: a point inside the tick box, in page coordinates. No model is asked."""
        from .tool_calls.find_checkbox import find_checkbox

        box = element.bounding_box()
        if not box:
            raise CaptchaSolveError("could not get bounding box of captcha element")
        shot = _tmp_png("checkbox")
        try:
            with self._phase(Phase.SCREENSHOT):
                self._screenshot(element, shot, timeout_ms=self.config.element_screenshot_timeout_ms)
            found = find_checkbox(shot)
            scale = self._shot_scale(shot, box["width"])
        finally:
            _unlink(shot)
        if found is None:
            raise UnsupportedCaptchaError("the checkbox widget shows no tick box to click")
        x, y, w, h = (v / scale for v in found)
        return box["x"] + x + w * (0.3 + random.random() * 0.4), box["y"] + y + h * (0.3 + random.random() * 0.4)

    def _await_what_the_checkbox_opened(self, page: Any) -> None:
        """A clicked checkbox passes or opens a challenge, and both show in the DOM.

        Without this wait the next round found the same checkbox still up and clicked it again.
        """
        deadline = _now() + self.config.post_submit_change_timeout_ms
        with self._phase(Phase.AWAIT_NEXT_ROUND):
            while _now() < deadline and not self.is_captcha_solved(page):
                widget = self.detect_captcha(page)
                if widget is None or widget.role != FrameRole.CHECKBOX:
                    return
                _delay(self.config.post_solve_outcome_poll_ms)

    def _get_verify_button(self, scope: Any) -> Optional[Any]:
        return self._find_control(scope, SUBMIT_SELECTORS)

    # ── frames and polling ───────────────────────────────────────────────

    def _screenshot(self, element: Any, path: str, timeout_ms: Optional[int] = None,
                    animations: str = "disabled") -> None:
        """Every capture the driver takes: the whole viewport, cropped here to the element.

        Never a clipped capture. An element screenshot, or any `clip`, makes a headed Chromium repaint the page at
        the clip's size for that frame, which the user watches as the page flashing and jumping; a viewport
        capture repaints nothing, and measured twice as fast. Short timeout; `disabled` freezes CSS animation,
        so bursts and the keyframe gate pass `allow`.
        """
        timeout = 2_500 if timeout_ms is None else timeout_ms
        page = self._page
        view = _viewport_of(page)
        rect = self._rect_in_view(element, view) if _layout_is_the_viewport(page, view) else None
        if rect is None:
            # Bigger than the viewport, or a zoomed-out mobile layout: no viewport capture holds it in its own
            # coordinates, so the element photographs itself.
            element.screenshot(path=path, timeout=timeout, animations=animations)
            return
        png = crop_png(page.screenshot(timeout=timeout, animations=animations), rect, view["width"])
        with open(path, "wb") as fh:
            fh.write(png)

    @staticmethod
    def _rect_of(element: Any) -> CaptureRect:
        box = element.bounding_box()
        rect = enclosing_rect(box) if box else None
        if rect is None or rect.width <= 0 or rect.height <= 0:
            raise CaptchaSolveError("the element is not visible: it has no bounding box to photograph")
        return rect

    def _rect_in_view(self, element: Any, view: Dict[str, float]) -> Optional[CaptureRect]:
        """Where the element sits in the viewport, scrolled in when it is merely off screen; None when it cannot fit."""
        rect = self._rect_of(element)
        if rect.width > view["width"] or rect.height > view["height"]:
            return None
        if not _within(rect, view):
            element.scroll_into_view_if_needed(timeout=2_000)
            rect = self._rect_of(element)
        return rect if _within(rect, view) else None

    def _step_off_the_board(self, page: Any, element: Any) -> None:
        """Take the pointer off the board and let our own feedback fade before the board is judged still or animated.

        A hovered or pressed control repaints, and a board wearing our highlight read as motion: a still board
        was filmed as animated because of the Verify button under the cursor.
        """
        # Only a board we pointed at wears our feedback. One the vendor dealt under a resting pointer has
        # nothing of ours to fade, and stepping off it cost every round its own gesture and settle window.
        if not self._acted_on_board:
            return
        box = element.bounding_box()
        x, y = self._last_mouse
        if box and self._human.hovers and box["x"] <= x <= box["x"] + box["width"] and box["y"] <= y <= box["y"] + box["height"]:
            spot = _off_board_point(box, (x, y), _viewport_of(page))
            if spot is not None:
                self._smooth_move(page, *spot)
        _delay(self._last_input_ms + INPUT_SETTLE_MS - _now())

    def _element_frame_hash(self, element: Any) -> Optional[str]:
        path = _tmp_png("fh")
        try:
            self._screenshot(element, path)
            return _sha1(path)
        except Exception:
            return None
        finally:
            _unlink(path)

    def _poll(self, element: Any, timeout_ms: float, interval_ms: float,
              judge: Callable[[List[str], float], Any], where: str,
              before: Optional[Callable[[], None]] = None) -> Any:
        """Screenshot `element` every `interval_ms` until `judge(last_two_frames, elapsed_ms)` answers."""
        start = _now()
        frames: List[str] = []
        try:
            while _now() - start < timeout_ms:
                self._check_deadline(where)
                t0 = _now()
                if before is not None:
                    before()
                path = _tmp_png("poll")
                try:
                    self._screenshot(element, path)
                except Exception:
                    _unlink(path)
                    _delay(interval_ms)
                    continue
                frames.append(path)
                verdict = judge(frames, _now() - start)
                if verdict is not None:
                    return verdict
                if len(frames) > 1:
                    _unlink(frames.pop(0))
                _delay(interval_ms - (_now() - t0))
            return None
        finally:
            for path in frames:
                _unlink(path)

    def _wait_for_element_settled(self, element: Any) -> SettleVerdict:
        cfg = self.config
        samples: List[Tuple[float, bool]] = []

        def judge(frames, elapsed):
            if len(frames) < 2:
                return None
            samples.append((elapsed, self._has_movement(frames[0], frames[1], cfg.settle_diff_threshold)))
            verdict = settle_verdict(samples, settle_frames=cfg.settle_frames,
                                     animated_after_ms=cfg.animated_challenge_after_ms,
                                     motion_streak=cfg.animated_motion_streak)
            return None if verdict == SettleVerdict.TIMEOUT else verdict

        return self._poll(element, cfg.settle_timeout_ms, cfg.settle_poll_ms, judge,
                          "waiting for the challenge to settle") or SettleVerdict.TIMEOUT

    def _wait_for_grid_cells_loaded(self, element: Any) -> bool:
        cfg = self.config

        def judge(frames, _elapsed):
            if len(frames) < 2:
                return None
            boxes = self._find_grid(frames[1])
            states = boxes and self._grid_cell_states(frames[0], frames[1], boxes)
            return True if states and not states["empty"] and not states["changing"] and states["loaded"] else None

        return bool(self._poll(element, cfg.grid_load_timeout_ms, cfg.grid_load_poll_interval_ms,
                               judge, "waiting for grid cells to load"))

    def _wait_for_board_painted(self, element: Any) -> int:
        """A still board is not a loaded board: hold until the panel's centre carries structure."""
        cfg = self.config
        start = _now()
        painted = self._poll(element, cfg.board_paint_timeout_ms, cfg.board_paint_poll_ms,
                             lambda frames, _e: True if self._board_painted(frames[-1]) is not False else None,
                             "waiting for the board to paint")
        waited = int(_now() - start)
        if not painted:
            _log(f"[board] the widget never painted a puzzle in {cfg.board_paint_timeout_ms}ms")
        elif waited >= cfg.board_paint_poll_ms:
            _log(f"[board] waited {waited}ms for the widget to paint its puzzle")
        return waited

    def _wait_for_change_since(self, element: Any, since_hash: str) -> bool:
        start = _now()
        while _now() - start < self.config.post_submit_change_timeout_ms:
            current = self._element_frame_hash(element)
            if current and current != since_hash:
                return True
            _delay(self.config.settle_poll_ms)
        return False

    def _wait_for_board_images(self, frame: Any, selectors: VendorSelectors) -> None:
        """Best-effort: hold until the board's pictures have painted."""
        try:
            frame.wait_for_function(_BOARD_IMAGES_READY_JS, arg={"prompt": selectors.fresh or "", "images": ",".join(selectors.images)},
                                    timeout=self.config.hcaptcha_images_timeout_ms)
        except Exception:
            pass

    def _get_grid_boxes(self, element: Any) -> Optional[Dict[str, Any]]:
        path = _tmp_png("findgrid")
        try:
            self._screenshot(element, path, timeout_ms=self.config.element_screenshot_timeout_ms)
            boxes = self._find_grid(path)
            dims = _read_png_dimensions(path)
            if not boxes or len(boxes) not in (9, 16) or not dims:
                return None
            return {"boxes": [list(b) for b in boxes], "size": 4 if len(boxes) == 16 else 3,
                    "screenshot_w": dims[0], "screenshot_h": dims[1]}
        except Exception:
            return None
        finally:
            _unlink(path)

    def _frame_changed_since(self, element: Any, prior_path: str, threshold: float) -> bool:
        probe = _tmp_png("freshcheck")
        try:
            self._screenshot(element, probe)
            return self._has_movement(prior_path, probe, threshold)
        except Exception:
            return False
        finally:
            _unlink(probe)

    def _solve_frame_freshness_guarded(self, element: Any, initial_shot: str,
                                       run_query: Callable[[str], Tuple[List[CaptchaAction], List[Dict[str, Any]]]]):
        """Re-solve when the frame changed during inference; twice means the board cycles."""
        cfg = self.config
        owned: List[str] = []
        merged: List[Dict[str, Any]] = []
        try:
            current = initial_shot
            actions, usage = run_query(current)
            merged.extend(usage)
            if not cfg.stale_frame_resolve_enabled:
                return actions, merged
            if self._frame_changed_since(element, current, _MOVED_DURING_INFERENCE_DIFF):
                self._arm_animated_probe()
                _log("[freshness] the widget moved while the model was reading it")
            changes = 0
            for attempt in range(cfg.max_stale_frame_resolves):
                if not self._frame_changed_since(element, current, cfg.stale_frame_diff_threshold):
                    break
                changes += 1
                if changes >= 2:
                    self._arm_animated_probe()
                    _log("[freshness] the frame changed twice during inference — this board cycles")
                    return actions, merged
                self._wait_for_board_painted(element)
                fresh = _tmp_png("freshsolve")
                try:
                    self._screenshot(element, fresh)
                except Exception:
                    _unlink(fresh)
                    break
                owned.append(fresh)
                _log(f"[freshness] frame changed during inference (re-solve {attempt + 1}/{cfg.max_stale_frame_resolves})")
                current = fresh
                actions, usage = run_query(current)
                merged.extend(usage)
            return actions, merged
        finally:
            for path in owned:
                _unlink(path)

    # ── animated challenges ──────────────────────────────────────────────

    def _settle_or_animated(self, element: Any) -> bool:
        """Wait for the widget to settle; True routes the caller to the recording path."""
        if self._known_animated:
            return True
        with self._phase(Phase.SETTLE):
            verdict = self._wait_for_element_settled(element)
        animated = verdict == SettleVerdict.ANIMATED
        if not animated:
            # 'settled' is not proof of static; a repeated answer arms one recording to find out. The clip
            # that recording brings back is what decides — `_known_animated` is set from it, not from here.
            if not self._animated_probe_armed or self._animated_probe_done:
                return False
            self._animated_probe_done, self._animated_probe_armed = True, False
            _log("[animated] a second look at a board that did not solve as a still — recording it")
        self._known_animated = animated
        if not self.config.video_solve_enabled:
            raise AnimatedChallengeError("the challenge never settles and video_solve_enabled is off")
        if animated:
            _log("[animated] challenge is animated — solving it from keyframes")
        return True

    def _arm_animated_probe(self) -> None:
        if self.config.animated_probe_enabled and not self._animated_probe_done:
            self._animated_probe_armed = True

    def _should_speculate(self, puzzle_source: Vendor, text_mode: bool) -> bool:
        # reCAPTCHA is excluded: its dynamic 3x3 replaces tiles in place, so a burst would film a fade and call
        # it a cycle. A text round has nothing to film.
        cfg = self.config
        return (cfg.video_solve_enabled and cfg.speculative_burst_enabled and not self._acted_on_board
                and puzzle_source != Vendor.RECAPTCHA and not text_mode)

    def _burst(self, element: Any, known: AbstractSet[str] = frozenset(),
               max_ms: Optional[float] = None) -> Tuple[List[Any], List[str], bool, float, bool]:
        """Film the widget until a screen comes back (a cycle) or nothing new appears for a floor window.

        `known` is the screens an earlier burst of this solve already holds. One of them coming back proves
        the board was not replaced, and the film in hand already describes it, so there is nothing left to
        film — that exit is the difference between a re-ask costing a frame and costing a whole window.

        Returns `(frames, distinct_digests, moved, elapsed_ms, cycle_closed)`. `moved` is a closed cycle OR a board still
        producing new screens past the floor with more than BURST_ANIMATED_SCREENS seen: a continuous animation
        never repeats and never settles, so without that verdict it read as a still and was clicked as one.
        Both bounds are wall-clock. There is no "enough screens, stop" exit: both spellings were measured on
        number_with_highest_value_video and failed every seed either way.
        """
        import cv2

        cfg = self.config
        floor_ms = float(cfg.video_burst_duration_ms)
        max_ms = max(floor_ms, float(cfg.video_burst_max_ms if max_ms is None else max_ms))
        interval = 1.0 / max(1, int(cfg.video_burst_fps))
        frames: List[Any] = []
        order: List[str] = []
        last_digest: Optional[str] = None
        cycle_closed = False
        last_new_ms = 0.0
        shot = _tmp_png("burst")
        t0 = time.monotonic()
        next_at = t0
        hang_deadline = t0 * 1000.0 + burst_hang_deadline_ms(cfg)
        try:
            while (time.monotonic() - t0) * 1000.0 < max_ms:
                if time.monotonic() * 1000.0 > hang_deadline:
                    raise CaptchaSolveError(
                        f"the animated recording stalled: {len(frames)} frames in "
                        f"{burst_hang_deadline_ms(cfg):.0f}ms. The widget is not screenshotting.")
                img = None
                # A frame taken while the board still wears our last gesture is not a screen it showed by itself.
                if _now() - self._last_input_ms >= INPUT_SETTLE_MS:
                    try:
                        self._screenshot(element, shot, animations="allow")
                        img = cv2.imread(shot)
                    except Exception as exc:
                        _debug(f"burst frame failed: {exc}")
                if img is not None:
                    frames.append(img)
                    d = _sha1(shot)
                    if d in known:
                        _log("[animated] a screen the film already holds came back — the board is unchanged")
                        cycle_closed = True
                        if d not in order:
                            order.append(d)
                        break
                    if d != last_digest:
                        if d in order and len(order) >= 2:
                            cycle_closed = True
                        elif d not in order:
                            order.append(d)
                            last_new_ms = (time.monotonic() - t0) * 1000.0
                        last_digest = d
                elapsed_ms = (time.monotonic() - t0) * 1000.0
                if cycle_closed and elapsed_ms >= floor_ms:
                    _log(f"[animated] cycle closed after {elapsed_ms / 1000:.1f}s ({len(order)} screens)")
                    break
                if elapsed_ms >= floor_ms and elapsed_ms - last_new_ms >= floor_ms:
                    _log(f"[animated] no new screen for {floor_ms / 1000:.1f}s ({len(order)} seen) — settled")
                    break
                # Sleep to a fixed grid, not `interval - work`: per-frame overshoot would otherwise accumulate and a
                # loaded runner films fewer frames than the floor window holds. A stalled frame skips, not bunches.
                next_at = max(next_at + interval, time.monotonic())
                # END on the frame that would land past the ceiling rather than declining to sleep for it:
                # declining left the loop spinning at whatever rate the screenshots came back, which on a
                # ceiling that is not a whole number of intervals filmed thousands of junk frames into the
                # tail of the clip (measured: 2487 frames in a 150ms window).
                if (next_at - t0) * 1000.0 >= max_ms:
                    break
                wait = next_at - time.monotonic()
                if wait > 0:
                    time.sleep(wait)
        finally:
            _unlink(shot)
        elapsed_ms = (time.monotonic() - t0) * 1000.0
        animating = len(order) > BURST_ANIMATED_SCREENS and elapsed_ms - last_new_ms < floor_ms
        if cycle_closed:
            why = "a screen came back"
        elif animating:
            why = f"{len(order)} screens and still arriving — animating continuously"
        else:
            why = "no new screen for a full floor window — it moved once and settled"
        _log(f"[animated] burst verdict after {elapsed_ms / 1000:.1f}s: "
             f"{'ANIMATED' if cycle_closed or animating else 'still'} ({len(order)} screens; {why})")
        return frames, order, cycle_closed or animating, elapsed_ms, cycle_closed

    def _slice(self, frames: List[Any], burst_ms: float) -> Tuple[List[str], str]:
        """Cut a burst with the training-side slicer; the model answers with a frame number into it."""
        from .keyframes import extract_keyframes, write_keyframes

        kfset = extract_keyframes(frames, fps=measured_fps(len(frames), burst_ms, self.config.video_burst_fps))
        self._keyframe_mode = kfset.mode
        self._keyframe_steady_screens = kfset.steady_screens
        temp_dir = tempfile.mkdtemp(prefix="ck_keyframes_")
        paths = [str(p) for p in write_keyframes(kfset, temp_dir, stem="challenge")]
        _log(f"[animated] sliced to {len(paths)} keyframe(s) (mode={kfset.mode})")
        return paths, temp_dir

    def _record_keyframes(self, element: Any) -> Tuple[List[str], str, bool]:
        """Record the widget and return `(keyframe_paths, temp_dir, moved)`; the caller removes the dir.

        Frames stay in memory: the intermediate mp4 this used to write was mp4v, which the serving side may not decode.

        THE FILM IS NEVER THROWN AWAY MID-SOLVE. One burst can only show the model the screens that fell
        inside its window — measured, a 4s burst against a 5.3s cycle showed two screens of three — and the
        answer it produces is identical next round by construction, because sampling is greedy over the same
        frames. So a refused answer used to be re-pressed until the no-progress fence tripped. Every round
        now films ANOTHER chunk and slices the whole accumulation, so the next ask is a strictly better
        question: more repetitions for `_detect_cycle` to confirm, and, on a board that never repeats, the
        slicer's even picks spread across the whole solve rather than across four seconds.

        WHAT IT IS NOT IS A FILM OF TWO BOARDS. Accumulating across a board the vendor replaced is worse
        than not accumulating at all — six keyframes cut across both states describe neither, `_detect_cycle`
        gives up on the extra screens, and the frame the model names is one the widget will never show
        again. A screen coming back is the proof the board is the same one; nothing coming back restarts
        the film below.

        THE JS PORT FILMS CONTINUOUSLY AND THIS ONE CANNOT. There the recorder is an async loop on the same
        event loop, so it keeps filming through inference and through the verdict wait. Sync Playwright is
        thread-affine — `_speculate` says so where it hands only the HTTP call to a worker — so a background
        camera here would be a second thread touching the page, which Playwright forbids. Accumulating
        per-round chunks is the same contract with a sparser film: both ports re-ask a refused animated
        answer against strictly more of the board than the last ask saw.
        """
        cfg = self.config
        self._grant_video_budget()
        if self._deadline_ms is not None and self._deadline_ms - _now() < cfg.video_burst_duration_ms:
            raise CaptchaSolveError(
                f"only {self._deadline_ms - _now():.0f}ms of the {cfg.overall_solve_timeout_ms}ms solve "
                f"budget is left and an animated recording needs {cfg.video_burst_duration_ms}ms — not "
                "starting one that would be cut off mid-way. Raise overall_solve_timeout_ms or "
                "video_extra_inference_ms, or set video_solve_enabled=False.")
        # A board that has never repeated a screen has nothing further to show: another ceiling-long window
        # is more of the same animation, and three of them is most of the solve budget. Measured on the gate:
        # boards at 54.6s and 59.1s against a 49s ceiling, all of them boards that never repeat.
        reask = bool(self._film_frames)
        frames, order, moved, burst_ms, cycled = self._burst(
            element, known=self._film_digests,
            max_ms=float(cfg.video_burst_duration_ms) if reask and not self._film_cycled else None)
        if not frames:
            # Not a verdict about the board — a still photographs fine. A widget that would not screenshot for a
            # whole window is usually closing because the answer was accepted, so the loop asks before it counts
            # the round. A board proven animated keeps that verdict, and is filmed again rather than read as a still.
            raise AnimatedChallengeError("could not record the animated challenge (no frame screenshotted)")
        _log(f"[animated] recorded {len(frames)} frames in {burst_ms / 1000:.1f}s "
             f"({measured_fps(len(frames), burst_ms, cfg.video_burst_fps):.1f}fps)")
        # ONE FILM, ONE BOARD. A vendor that deals a fresh puzzle on a miss has replaced everything the film
        # holds, and keyframes cut across both name screens that no longer exist: the model answers with one
        # and the click waits out `keyframe_wait_timeout_ms` for a picture that is gone. Nothing coming back
        # is what says so, and the film restarts on the board that is actually there.
        # Cut ONLY on proof of a replacement: this burst repeated a screen, and none of what it repeated was
        # in the film. A board that never repeats cannot produce that proof either way and has not been
        # replaced — it has simply never repeated, and its film is the only record of it.
        if reask and cycled and not (self._film_digests & set(order)):
            _log("[animated] nothing the film holds came back — the board was replaced; the film restarts here")
            self._film_frames, self._film_ms, self._film_digests = [], 0.0, set()
        # The cap is a safety net on memory, not the working limit: frames are decoded images, and a board
        # that never settles would otherwise film for the whole solve budget.
        if self._film_ms < cfg.video_film_max_ms:
            self._film_frames.extend(frames)
            self._film_ms += burst_ms
            self._film_digests.update(order)
        self._film_cycled = self._film_cycled or cycled
        if len(self._film_frames) > len(frames):
            _log(f"[animated] slicing {len(self._film_frames)} frames filmed over "
                 f"{self._film_ms / 1000:.1f}s — every round of this board, not just this one")
        paths, temp_dir = self._slice(self._film_frames or frames, self._film_ms or burst_ms)
        return paths, temp_dir, moved

    def _speculate(self, element: Any, shot: str, puzzle_source: Vendor, retry_mode: Optional[RetryMode],
                   text_mode: bool) -> Tuple[List[CaptchaAction], List[Dict[str, Any]], Optional[str]]:
        """Ask the still and film the widget at once; `keyframe_dir` is None when the board is still.

        Only the HTTP request crosses to the worker thread: sync Playwright is thread-affine.
        """
        pool = ThreadPoolExecutor(max_workers=1)
        try:
            fut = pool.submit(self._get_solution, shot, puzzle_source, retry_mode, text_mode)
            with self._phase(Phase.BURST):
                frames, order, moved, burst_ms, _cycled = self._burst(element)
            if not moved:
                with self._phase(Phase.INFERENCE):
                    actions, usage = fut.result()
                if len(order) > 1:
                    # Moved once and settled: re-read the screen it came to rest on.
                    try:
                        self._screenshot(element, shot)
                        actions, extra = self._get_solution(shot, puzzle_source, retry_mode, text_mode)
                        usage = list(usage) + list(extra)
                    except Exception as exc:
                        _debug(f"settled re-read failed: {exc}")
                return actions, usage, None
            _log("[animated] the widget moved while the model was reading it — finishing the recording")
            self._known_animated = True
            fut.result()
            self._grant_video_budget()
            paths, keyframe_dir = self._slice(frames, burst_ms)
            with self._phase(Phase.INFERENCE):
                actions, usage = self._get_keyframe_solution(paths)
            self._animated_plan = (paths, keyframe_dir, actions, usage)
            return actions, usage, keyframe_dir
        finally:
            pool.shutdown(wait=True)

    def _invalidate_animated_answer(self) -> None:
        """Keep the frames and drop the answer, unless the clip has no steady screen to re-ask."""
        plan = self._animated_plan
        if plan is None or plan[2] is None:
            return
        if self._keyframe_steady_screens < 2:
            self._discard_animated_plan()
            self._keyframe_mode, self._keyframe_steady_screens = None, 0
            return
        self._animated_plan = (plan[0], plan[1], None, None)

    def _discard_animated_plan(self) -> None:
        """Drop the ANSWER, keep the film.

        An answer the widget refused is spent: reusing it presses the same wrong thing until the fence trips
        three rounds in, with half the budget unspent. The frames are the opposite — every chunk added makes
        the next ask a better question — so only a board that is GONE clears them, via `_stop_animated_film`.
        """
        plan = self._animated_plan
        self._animated_plan = None
        if plan and plan[1]:
            shutil.rmtree(plan[1], ignore_errors=True)

    def _stop_animated_film(self) -> None:
        """The board is gone: its film can never describe the next one."""
        self._discard_animated_plan()
        self._film_frames = []
        self._film_ms = 0.0
        self._film_digests = set()
        self._film_cycled = False

    def _answer_region_recurs(self, keyframe_path: str, ref: Any, box: Any) -> bool:
        """Does the chosen keyframe's answer area appear in a sibling keyframe of the same clip?"""
        import cv2

        from .keyframes import MATCH_REGION_TOLERANCE, region_diff_ratio

        folder, base = os.path.dirname(keyframe_path), os.path.basename(keyframe_path)
        prefix = re.sub(r"_\d+\.png$", "_", base, flags=re.IGNORECASE)
        if prefix == base:
            return False
        try:
            siblings = [os.path.join(folder, f) for f in sorted(os.listdir(folder))
                        if f.startswith(prefix) and f.lower().endswith(".png") and f != base]
        except OSError:
            return False
        for other in siblings:
            img = cv2.imread(other)
            if img is not None and img.shape == ref.shape and region_diff_ratio(ref, img, box) <= MATCH_REGION_TOLERANCE:
                return True
        return False

    def _wait_for_keyframe(self, element: Any, keyframe_path: str, point_norm: Tuple[float, float]) -> bool:
        """Hold until the widget looks like the keyframe around the action point, or the wait is spent."""
        import cv2

        from .keyframes import MATCH_REGION_TOLERANCE, region_box, region_diff_ratio

        ref = cv2.imread(keyframe_path)
        if ref is None:
            return False
        box = region_box(ref.shape[1::-1], point_norm)
        steady = self._keyframe_steady_screens >= 2
        if not steady and not self._answer_region_recurs(keyframe_path, ref, box):
            _log("[animated] the answer area is unique to the chosen frame; acting without waiting")
            return False
        cfg = self.config
        wait_ms = cfg.keyframe_wait_timeout_ms if steady else min(cfg.keyframe_wait_timeout_ms, cfg.video_burst_duration_ms)
        deadline = _now() + wait_ms
        probe = _tmp_png("kfwait")
        best, polls = 1.0, 0
        try:
            while _now() < deadline:
                self._check_deadline("waiting for the challenge keyframe")
                try:
                    self._screenshot(element, probe, animations="allow")
                    live = cv2.imread(probe)
                except Exception:
                    live = None
                if live is not None:
                    d = region_diff_ratio(ref, live, box)
                    best = min(best, d)
                    if d <= MATCH_REGION_TOLERANCE:
                        _log(f"[animated] widget matched the chosen keyframe (diff={d:.4f})")
                        return True
                    polls += 1
                    if polls >= _NOT_THIS_BOARD_POLLS and best > _NOT_THIS_BOARD_DIFF:
                        _log("[animated] the widget no longer resembles the recorded board")
                        self._stop_animated_film()
                        return False
                _delay(cfg.keyframe_wait_poll_ms)
        finally:
            _unlink(probe)
        self._stop_animated_film()
        _log(f"[animated] widget never matched the chosen keyframe within {wait_ms}ms (closest diff={best:.4f})")
        return False

    # ── reCAPTCHA 3x3 dynamic driver ─────────────────────────────────────

    def _cell_center_page(self, cell: int, session: _GridSession) -> Tuple[float, float]:
        x1, y1, x2, y2 = session.grid_boxes[cell - 1]
        return (session.element_box["x"] + (x1 + x2) / 2 * session.scale_x,
                session.element_box["y"] + (y1 + y2) / 2 * session.scale_y)

    def _hover_cell(self, page: Any, session: _GridSession, cell: int) -> None:
        if not self._human.hovers:
            return
        first = session.grid_boxes[0]
        cx, cy = self._cell_center_page(cell, session)
        self._smooth_move(page,
                          cx + (random.random() - 0.5) * (first[2] - first[0]) * session.scale_x * 0.4,
                          cy + (random.random() - 0.5) * (first[3] - first[1]) * session.scale_y * 0.4)

    @staticmethod
    def _bbox_to_cell(bbox: Sequence[float], grid_boxes: Sequence[Sequence[int]],
                      width: int, height: int) -> Optional[int]:
        cx = (float(bbox[0]) + float(bbox[2])) / 2 * width
        cy = (float(bbox[1]) + float(bbox[3])) / 2 * height
        for index, (x1, y1, x2, y2) in enumerate(grid_boxes):
            if x1 <= cx <= x2 and y1 <= cy <= y2:
                return index + 1
        return None

    @staticmethod
    def _order_by_priority(loading: Sequence[int], priority: Sequence[int]) -> List[int]:
        remaining = set(loading)
        ordered = [c for c in priority if c in remaining and not remaining.discard(c)]
        return ordered + sorted(remaining)

    def _hover_loop(self, page: Any, session: _GridSession, cells: Sequence[int]) -> Optional[Callable[[], None]]:
        if not cells:
            return None
        cycle = itertools.cycle(cells)

        def hover():
            try:
                self._hover_cell(page, session, next(cycle))
            except Exception:
                pass

        return hover

    def _watch_clicked_tiles(self, page: Any, element: Any, session: _GridSession,
                             priority: Sequence[int] = ()) -> Tuple[List[int], bool]:
        """`(loading, chipped)`: a chip means the photo was kept, a blank or fade means it is being swapped.

        A grace window, not a snapshot: reCAPTCHA holds a clicked tile selected for ~1-3s and only then blanks
        it. The chip is tested first, because a chip zooms the photo and reads as `changing` on the frame that
        shows it. `chipped` needs every clicked tile, since the two misreads cost differently: calling a
        swapping board finished submits half an answer, calling a chipped board unfinished costs one inference.
        """
        cfg = self.config
        watch = set(priority) or None

        def judge(frames, _elapsed):
            if len(frames) < 2:
                return None
            states = self._grid_cell_states(frames[0], frames[1], session.grid_boxes) or {}
            if priority and set(states.get("selected", [])).issuperset(priority):
                return [], True
            loading = sorted({c for c in states.get("empty", []) + states.get("changing", [])
                              if watch is None or c in watch})
            return (self._order_by_priority(loading, priority), False) if loading else None

        return self._poll(element, cfg.recaptcha_fade_onset_grace_ms, cfg.recaptcha_dynamic_fade_poll_ms,
                          judge, "watching for the tile refresh",
                          self._hover_loop(page, session, priority)) or ([], False)

    def _wait_for_any_clicked_tile_loaded(self, page: Any, element: Any, session: _GridSession,
                                          fading_cells: Sequence[int]) -> bool:
        if not fading_cells:
            return True
        cfg = self.config

        def judge(frames, _elapsed):
            if len(frames) < 2:
                return None
            states = self._grid_cell_states(frames[0], frames[1], session.grid_boxes)
            return True if states and any(c in states["loaded"] for c in fading_cells) else None

        hover = self._hover_loop(page, session, fading_cells) if cfg.recaptcha_tile_hover_enabled else None
        return bool(self._poll(element, cfg.recaptcha_dynamic_fade_wait_ms, cfg.recaptcha_dynamic_fade_poll_ms,
                               judge, "waiting for a tile to reload", hover))

    def _solve_recaptcha_grid(self, page: Any, element: Any, retry_mode: Optional[RetryMode],
                              grid: Dict[str, Any], element_box: Dict[str, float]) -> Tuple[bool, List[Dict[str, Any]]]:
        """Click, watch the clicked tiles, re-solve while they swap, submit on `done` or a chipped board."""
        cfg = self.config
        session = _GridSession(grid["boxes"], element_box,
                               element_box["width"] / grid["screenshot_w"],
                               element_box["height"] / grid["screenshot_h"],
                               grid["screenshot_w"], grid["screenshot_h"])
        clicked_order: List[int] = []
        performed = should_submit = False
        all_usage: List[Dict[str, Any]] = []
        pending_retry = retry_mode

        for round_index in range(1, cfg.recaptcha_max_dynamic_rounds + 1):
            self._check_deadline(f"recaptcha grid round {round_index}")
            if round_index > 1:
                with self._phase(Phase.GRID_LOAD):
                    self._wait_for_grid_cells_loaded(element)
            shot = _tmp_png("recap")
            try:
                with self._phase(Phase.SCREENSHOT):
                    self._screenshot(element, shot, timeout_ms=cfg.element_screenshot_timeout_ms)
                retry_for_round, pending_retry = pending_retry, None
                with self._phase(Phase.INFERENCE):
                    actions, usage = self._solve_frame_freshness_guarded(
                        element, shot, lambda p: self._get_solution(p, Vendor.RECAPTCHA, retry_for_round))
                all_usage.extend(usage)
                action = _as_dict(actions[0]) if actions else None
            finally:
                _unlink(shot)

            kind = (action or {}).get("action")
            if not action or kind == ActionKind.DONE:
                _log(f"[recaptcha-grid] round {round_index}: done; submitting.")
                should_submit = True
                break
            if kind == ActionKind.WAIT:
                with self._phase(Phase.FADE_WAIT):
                    loading, _ = self._watch_clicked_tiles(page, element, session, clicked_order)
                    self._wait_for_any_clicked_tile_loaded(page, element, session, loading)
                continue
            if kind != ActionKind.CLICK:
                _log(f"[recaptcha-grid] round {round_index}: unexpected action; re-solving.")
                continue
            bboxes = action.get("target_bounding_boxes") or (
                [action["target_bounding_box"]] if action.get("target_bounding_box") else [])
            if not bboxes:
                _delay(500)
                continue
            clicked_this_round: List[int] = []
            for bbox in bboxes:
                cell = self._bbox_to_cell(bbox, session.grid_boxes, session.screenshot_w, session.screenshot_h)
                self._execute_click(page, {"target_bounding_box": bbox}, element_box)
                if cell is not None:
                    clicked_order.append(cell)
                    clicked_this_round.append(cell)
                self._human.pause(PauseKind.BETWEEN)
            performed = True
            _log(f"[recaptcha-grid] round {round_index}: clicked cells {clicked_this_round}.")
            with self._phase(Phase.FADE_WAIT):
                loading, chipped = self._watch_clicked_tiles(page, element, session, clicked_this_round)
            if chipped or not loading:
                _log(f"[recaptcha-grid] round {round_index}: {'tiles chipped' if chipped else 'nothing loading'}; submitting.")
                should_submit = True
                break
            with self._phase(Phase.FADE_WAIT):
                self._wait_for_any_clicked_tile_loaded(page, element, session, loading)

        if should_submit:
            frame = element.content_frame()
            verify = frame and self._get_verify_button(frame)
            if verify:
                _log("[recaptcha-grid] clicking Verify to submit.")
                self._move_and_click(page, verify)
                performed = True
        return performed, all_usage

    # ── one pass over a rendered challenge ───────────────────────────────

    def _solve_single(self, page: Any, widget: Widget, retry_mode: Optional[RetryMode]) -> Tuple[bool, List[Dict[str, Any]]]:
        element, puzzle_source, role = widget.element, widget.vendor, widget.role
        os.environ[_VENDOR_ENV] = puzzle_source.value
        frame = element.content_frame()
        # The widget's own host comes from its iframe; an inline widget has none to report.
        widget_host = _hostname(frame) if frame else ""
        if widget_host:
            os.environ[_WIDGET_HOST_ENV] = widget_host
        else:
            os.environ.pop(_WIDGET_HOST_ENV, None)
        scope = frame or widget.at

        if role == FrameRole.CHECKBOX:
            self._click_checkbox(page, widget, frame)
            return True, []

        if frame and role == FrameRole.CHALLENGE and SELECTORS[puzzle_source].images:
            if self._last_submit_frame_hash:
                with self._phase(Phase.AWAIT_NEXT_ROUND):
                    self._wait_for_change_since(element, self._last_submit_frame_hash)
                self._last_submit_frame_hash = None
            with self._phase(Phase.HCAPTCHA_IMAGES):
                self._wait_for_board_images(frame, SELECTORS[puzzle_source])

        # THE TWO QUESTIONS BELOW ARE PUT TO A PAINTED BOARD. Which expert answers the round is read out of
        # the DOM and whether the board cycles is read off its motion, and a widget that has not drawn yet
        # has no text box to find and no motion but its own arrival.
        #
        # A reCAPTCHA board is asked NEITHER — it is never typed and never filmed — and it waits for its
        # board at the grid gate below, on the cells themselves. Waiting here as well put 0.8-1.8s in front
        # of that gate on every dynamic round, on the family with the tightest per-board budget.
        if puzzle_source != Vendor.RECAPTCHA:
            with self._phase(Phase.BOARD_PAINT):
                self._wait_for_board_painted(element)

        # Only the DOM can tell a typed captcha from a click puzzle; hCaptcha and reCAPTCHA never type.
        text_mode = puzzle_source not in VENDORS_WITH_BESPOKE_HANDLING and self._answer_box(scope, widget.at) is not None
        if text_mode:
            _log("widget has a text box; solving as a distorted-text captcha")

        # A reCAPTCHA board is read by its grid below, not filmed.
        filmable = puzzle_source != Vendor.RECAPTCHA and not text_mode
        if filmable and not self._known_animated:
            self._step_off_the_board(page, element)
        is_animated = filmable and self._settle_or_animated(element)
        # hCaptcha keeps its challenge iframe visible ~2s after the final submit; read as a fresh puzzle it burned ~18s.
        if role == FrameRole.CHALLENGE and self.is_captcha_solved(page):
            _log("solved while waiting for the next round; skipping inference.")
            return False, []

        if puzzle_source == Vendor.RECAPTCHA and role == FrameRole.CHALLENGE:
            with self._phase(Phase.GRID_LOAD):
                self._wait_for_grid_cells_loaded(element)
            grid = self._get_grid_boxes(element)
            if grid and grid["size"] == 3:
                element_box = element.bounding_box()
                if element_box:
                    return self._solve_recaptcha_grid(page, element, retry_mode, grid, element_box)

        # The board a reCAPTCHA round photographs, for the rounds that do not take the grid path above.
        if puzzle_source == Vendor.RECAPTCHA:
            with self._phase(Phase.BOARD_PAINT):
                self._wait_for_board_painted(element)

        shot = _tmp_png("captcha")
        performed = slid = answered = have_shot = False
        all_usage: List[Dict[str, Any]] = []
        keyframe_dir: Optional[str] = None
        try:
            if is_animated:
                if self._animated_plan is not None:
                    keyframes, keyframe_dir, actions, all_usage = self._animated_plan
                    reused = actions is not None
                    if not reused:
                        # Drop the ANSWER, keep the FRAMES — and the frames grow. Filming another chunk and
                        # re-slicing the accumulation puts a better question up; re-asking the same frames
                        # puts the same question up and gets the same answer back.
                        with self._phase(Phase.BURST):
                            keyframes, new_dir, moved = self._record_keyframes(element)
                        shutil.rmtree(keyframe_dir, ignore_errors=True)
                        keyframe_dir = new_dir
                        self._known_animated = self._known_animated or moved
                    _log("[animated] reusing the recorded answer" if reused
                         else "[animated] re-asking on a film a round longer")
                else:
                    reused = False
                    with self._phase(Phase.BURST):
                        keyframes, keyframe_dir, moved = self._record_keyframes(element)
                    self._known_animated = self._known_animated or moved
                # The clip answers the question the probe asked: a board that never moved is a still, and the
                # video expert can only answer a still with a frame number the widget will not take.
                if len(keyframes) < 2 or not self._known_animated:
                    _log("[animated] the recording shows a still board; solving it as a still")
                    is_animated = False
                    shutil.copyfile(keyframes[-1], shot)
                    have_shot = True
                    self._stop_animated_film()
                    shutil.rmtree(keyframe_dir, ignore_errors=True)
                    keyframe_dir = None
                elif not reused:
                    with self._phase(Phase.INFERENCE):
                        actions, all_usage = self._get_keyframe_solution(keyframes)
                    self._animated_plan = (keyframes, keyframe_dir, actions, all_usage)

            if not is_animated:
                if not have_shot:
                    with self._phase(Phase.SCREENSHOT):
                        self._screenshot(element, shot, timeout_ms=self.config.element_screenshot_timeout_ms)
                if self._should_speculate(puzzle_source, text_mode):
                    actions, all_usage, keyframe_dir = self._speculate(element, shot, puzzle_source, retry_mode, text_mode)
                    is_animated = keyframe_dir is not None
                else:
                    with self._phase(Phase.INFERENCE):
                        actions, all_usage = self._solve_frame_freshness_guarded(
                            element, shot,
                            lambda p: self._get_solution(p, puzzle_source, retry_mode, text_mode=text_mode))

            element_box = element.bounding_box()
            if not element_box and answer_needs_element_box(actions):
                # A WIDGET WITH NO BOX IS USUALLY A WIDGET THAT IS CLOSING, and it closes because the
                # answer was accepted. Asking costs one call; not asking cost the solve — measured on
                # 2026-09-17, five types graded `solved: true` on the board and then ended the attempt
                # here, which Tier 3 reports as an answer the board would have taken, reported failed.
                if self.is_captcha_solved(page):
                    _log("the widget has no box because it is closing on a solved board; finishing.")
                    return False, all_usage
                raise CaptchaSolveError("could not get bounding box of captcha element")

            _log("[answer] " + json.dumps({"actions": [_as_dict(a) for a in actions]}, default=str))
            # A repeated answer is not re-performed: the widget already refused it, and every extra press is
            # behaviour a vendor scores. Re-asking with a fresh sample or a recording is the round's only move.
            # `_note_answer` drops the refused animated answer on its way through, so the next round re-asks.
            if self._note_answer(actions, retry_mode):
                return False, all_usage
            _log(f"executing {len(actions)} action(s)")

            for raw_action in actions:
                self._check_deadline("action execution")
                action = _as_dict(raw_action)
                kind = action.get("action")
                await_kf = action.get("await_keyframe")
                if kind == ActionKind.CLICK:
                    bboxes = action.get("target_bounding_boxes") or (
                        [action["target_bounding_box"]] if action.get("target_bounding_box") else [])
                    if not bboxes and not action.get("target_coordinates"):
                        _log("click action has no bboxes or coordinates; skipping")
                        continue
                    for bbox in bboxes or [None]:
                        one = {"target_bounding_box": bbox} if bbox else action
                        self._execute_click(page, one, element_box, element, await_kf)
                        if bbox:
                            self._human.pause(PauseKind.BETWEEN)
                    performed = answered = True
                elif kind == ActionKind.DRAG and not action.get("source_bounding_box"):
                    if self._execute_slide(page, element, scope, action, element_box):
                        performed = slid = True
                elif kind == ActionKind.DRAG:
                    if await_kf:
                        self._wait_for_keyframe(element, await_kf, _bbox_center(action["source_bounding_box"]))
                    self._execute_drag(page, action, element_box)
                    performed = answered = True
                elif kind == ActionKind.TYPE:
                    if self._execute_type(page, scope, action, widget.at):
                        performed = answered = True
                elif kind == ActionKind.WAIT:
                    duration = int(action.get("duration_ms") or 0)
                    if duration > 0:
                        _delay(duration)
                        performed = True

            # A slide submits itself on release, and any Verify found afterwards belongs to the host page and would
            # submit the guarded form while the verdict is in flight. An empty or `done` plan still presses Verify/Skip.
            verify_button = self._get_verify_button(scope) if frame or not slid else None
            if not slid and (answered or not performed) and verify_button:
                _log(f"clicking Verify to submit ({puzzle_source}).")
                self._move_and_click(page, verify_button)
                performed = True
                self._last_submit_frame_hash = self._element_frame_hash(element)
        finally:
            _unlink(shot)
            held = self._animated_plan[1] if self._animated_plan else None
            if keyframe_dir and keyframe_dir != held:
                shutil.rmtree(keyframe_dir, ignore_errors=True)
        return performed, all_usage

    # ── public entry point ───────────────────────────────────────────────

    def watch(self, page: Any, **options: Any) -> "CaptchaWatcher":
        """A watcher over `page`; `.run()` blocks, `.poll_once()` is cooperative."""
        from .watcher import CaptchaWatcher

        return CaptchaWatcher(solver=self, page=page, **options)

    def solve(self, page: Any) -> SolveResult:
        start = _now()
        usage: List[Dict[str, Any]] = []
        self._last_submit_frame_hash = None
        self._deadline_ms = start + self.config.overall_solve_timeout_ms
        self._page = page
        self._human.reset(page)
        self._reset_animated_state()
        self._budget = PhaseBudget()
        self._verdicts = None
        # One session id per solve groups its inference rounds into one billable attempt; vendor and site say
        # where it was, and are set as they become known.
        previous = {name: os.environ.get(name) for name in (_SESSION_ENV, _VENDOR_ENV, _SITE_ENV, _WIDGET_HOST_ENV)}
        session_id = os.environ[_SESSION_ENV] = str(uuid.uuid4())
        os.environ.pop(_VENDOR_ENV, None)
        os.environ.pop(_SITE_ENV, None)
        os.environ.pop(_WIDGET_HOST_ENV, None)
        site = _hostname(page)
        if site:
            os.environ[_SITE_ENV] = site
        solved = False
        try:
            result = self._solve_impl(page, start, usage)
            result.phases = dict(self._budget.totals, total=self._budget.elapsed_ms())
            solved = bool(result.is_solved)
            return result
        finally:
            if timings_enabled():
                print(self._budget.report(), file=sys.stderr)
            self._deadline_ms = None
            if self._verdicts is not None:
                self._verdicts.close()
            # The vendor's own verdict when it was readable; the DOM's done-signal only when it was not.
            said = self._verdicts.decisive() if self._verdicts is not None else None
            try:
                # On by default: it is the only way a hosted account's failures can be found at all.
                self._solver.planner.report_outcome(session_id, solved if said is None else said == Verdict.ACCEPTED)
            except Exception as exc:
                _log(f"[outcome] could not report: {exc}")
            for name, value in previous.items():
                if value is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = value

    def _solve_impl(self, page: Any, start: float, usage: List[Dict[str, Any]]) -> SolveResult:
        """Give up only when the vendor refuses to serve us, or when every one of `max_solve_loops` has been spent.

        Any other failed round — a stale handle, an unusable or repeated answer, a board that would not film —
        counts one loop, pauses, and goes again.
        """
        cfg = self.config
        pending_retry_mode: Optional[RetryMode] = None
        has_interacted = False
        last_failure: Optional[CaptchaSolveError] = None
        verdicts = self._verdicts = VerdictLog(page)

        def done() -> SolveResult:
            return SolveResult(True, self._last_mouse, _aggregate(usage), verdicts=list(verdicts.verdicts))

        def blocked(how: str) -> VendorBlockedError:
            return VendorBlockedError(f"the vendor refused to serve this client ({how}); no further round can succeed")

        def again(failure: CaptchaSolveError, *, in_transition: bool = False) -> None:
            """Count the loop. Only a widget caught mid-transition is worth waiting out; a refused or repeated
            answer changed nothing on the page, and pausing after it only spends the solve's budget."""
            nonlocal last_failure
            last_failure = failure
            _log(f"{failure}; counting this loop and going again")
            if in_transition:
                _delay(cfg.stale_element_backoff_ms)

        for attempt in range(1, cfg.max_solve_loops + 1):
            # A round that failed arms the second look only while its board is still up. A board the vendor has
            # replaced (`_fresh_board` clears `_acted_on_board`) has failed nothing yet, and arming it anyway
            # filmed every still board after a solve's first miss: 4-8s each, a 41.8s session became 49s.
            if attempt >= 2 and self._acted_on_board:
                self._arm_animated_probe()
            self._bound_ask_to_the_budget()
            # The deadline, not the bare config: a recording extends it once per solve (`_grant_video_budget`), and
            # a loop head reading only overall_solve_timeout_ms quit video solves at 45s with 29s still granted.
            deadline = self._deadline_ms if self._deadline_ms is not None else start + cfg.overall_solve_timeout_ms
            if _now() > deadline:
                granted = deadline - start - cfg.overall_solve_timeout_ms
                raise CaptchaSolveError(
                    f"captcha solve timed out after {deadline - start:.0f}ms (attempt {attempt}/{cfg.max_solve_loops})"
                    + (f", including {granted:.0f}ms granted for recording an animated challenge" if granted > 0 else ""))
            said = self._vendor_verdict()
            if said == Verdict.ACCEPTED:
                _log("[verdict] the vendor accepted the answer; finishing.")
                return done()
            if said == Verdict.BLOCKED:
                raise blocked("its server answered 429")
            if has_interacted and self.is_captcha_solved(page):
                _log("captcha reports solved; finishing.")
                return done()

            with self._phase(Phase.DETECT):
                widget = self.detect_captcha(page)
            if not widget:
                # A widget that vanished right after the vendor refused the answer was not solved.
                if has_interacted and verdicts.decisive() != Verdict.REJECTED:
                    _log("no supported captcha remains after interaction; considering solved.")
                    return done()
                widget, waited = self._await_widget(page)
                # The budget is for solving; the page drawing its widget is not charged to it.
                start += waited
                if self._deadline_ms is not None:
                    self._deadline_ms += waited
                if widget is None:
                    if self.is_captcha_solved(page):
                        _log("captcha already satisfied; nothing to solve.")
                        return done()
                    if has_interacted:
                        raise CaptchaSolveError(f"the vendor rejected the last answer and its widget did not come "
                                                f"back within {cfg.detection_timeout_ms}ms")
                    raise NoCaptchaFoundError(self._no_widget_message(page))

            _log(f"--- captcha solve loop {attempt}/{cfg.max_solve_loops} ---")
            retry_mode, pending_retry_mode = pending_retry_mode, None
            try:
                did_interact, round_usage = self._solve_single(page, widget, retry_mode)
            except UnsupportedCaptchaError as unsupported:
                # The model had nothing usable for this board. The next round re-asks, often of a board the
                # vendor has replaced.
                again(UnsupportedChallengeError(f"cannot solve this kind of captcha — {unsupported}"))
                continue
            except AnimatedChallengeError as animated:
                if not cfg.video_solve_enabled:
                    raise
                # A widget that will not screenshot is usually one that is closing, because the answer was
                # accepted: measured, a vendor that deals several boards lost four attempts to exactly this, each
                # after its first board came back graded solved.
                if has_interacted and self.is_captcha_solved(page):
                    _log("nothing left to film because the board was accepted; finishing.")
                    return done()
                again(animated, in_transition=True)
                continue
            except Exception as exc:
                message = str(exc)
                closed = bool(_CLOSED_TARGET_RE.search(message))
                if not (closed or _STALE_HANDLE_RE.search(message)):
                    raise
                # The handle most often went stale because the answer was accepted.
                try:
                    if has_interacted and self.is_captcha_solved(page):
                        _log("captcha reports solved; finishing.")
                        return done()
                except Exception:
                    pass
                if closed:
                    raise PageClosedError(
                        "the page, context or browser closed mid-solve"
                        + (", after the answer had been submitted but before the vendor's verdict could be read — "
                           "the solve may in fact have succeeded" if has_interacted else "")) from exc
                again(CaptchaSolveError(f"the challenge handle went stale ({message.splitlines()[0]})"), in_transition=True)
                continue

            has_interacted = has_interacted or did_interact
            usage.extend(round_usage)

            # One polled wait per round: the vendor's verdict, the widget going away, or a fresh board. The flat
            # sleep it replaced observed nothing and cost 1200-1500ms per finished round. A round that performed
            # nothing gave the page nothing to react to, so it looks once and goes on: waiting there cost every
            # refused or repeated answer the full window.
            window_ms = cfg.post_solve_outcome_timeout_ms if did_interact else 0
            deadline = _now() + window_ms
            t0 = time.perf_counter()
            solved = False
            said = None
            widget_gone = 0
            looked = False
            while not looked or _now() < deadline:
                looked = True
                said = self._vendor_verdict() or said
                if said in (Verdict.ACCEPTED, Verdict.BLOCKED):
                    solved = said == Verdict.ACCEPTED
                    break
                if self.is_captcha_solved(page):
                    solved = True
                    break
                widget_gone = widget_gone + 1 if said != Verdict.REJECTED and self.detect_captcha(page) is None else 0
                if widget_gone >= 2:
                    solved = True
                    break
                if self._is_challenge_freshly_rendered(page):
                    self._fresh_board()
                    break
                _delay(cfg.post_solve_outcome_poll_ms)
            verdict_ms = (time.perf_counter() - t0) * 1000.0
            if self._budget is not None:
                self._budget.add(Phase.AWAIT_VERDICT if did_interact else Phase.POST_SUBMIT_DELAY, verdict_ms)
            if solved:
                _log(f"[verdict] success signal arrived after {verdict_ms:.0f}ms")
                return done()
            if said == Verdict.BLOCKED:
                raise blocked("its server answered 429")
            if self._is_blocked(page):
                raise blocked("it is showing its try-again-later screen")
            if said == Verdict.REJECTED:
                _log(f"[verdict] the vendor rejected the answer after {verdict_ms:.0f}ms")

            if self._banner_is_fatal_after_retry(self._banner_kind(page)):
                _log("reCAPTCHA under-selection error; the next round asks for the missed tiles.")
                pending_retry_mode = RetryMode.MISSED_TILES

            if said != Verdict.REJECTED and not self.detect_captcha(page):
                return done()
            if self._no_progress_rounds:
                stuck = CaptchaSolveError(f"no progress: the model returned the same answer "
                                          f"{self._no_progress_rounds + 1} times running")
                # A board answered the same way after every resample is one the model cannot read: measured, no
                # solve ever followed a third identical answer, and each further round cost the board 3-7s.
                if self._no_progress_rounds >= cfg.max_no_progress_rounds:
                    raise stuck
                again(stuck)
            elif not did_interact:
                # An answer with nothing to execute is not proof the page is stuck; on an animated board it is
                # what a still expert returns when the board is not a still, so the next round takes a second look.
                if cfg.video_solve_enabled:
                    self._arm_animated_probe()
                again(CaptchaSolveError("the solver performed no interactions this round"))

        if isinstance(last_failure, UnsupportedChallengeError):
            raise UnsupportedChallengeError(f"{last_failure} (after {cfg.max_solve_loops} solve loops)")
        raise CaptchaSolveError(f"captcha still detected after {cfg.max_solve_loops} solve loops"
                                + (f"; the last failed round: {last_failure}" if last_failure else ""))


def _hostname(page: Any) -> str:
    """The page's host alone: a path or query can carry a user's own data."""
    from urllib.parse import urlparse

    try:
        return (urlparse(page.url).hostname or "").lower()
    except Exception:
        return ""


def _bbox_center(bbox: Sequence[float]) -> Tuple[float, float]:
    x1, y1, x2, y2 = (float(v) for v in bbox)
    return (x1 + x2) / 2.0, (y1 + y2) / 2.0


def _round_pts(value: Any, places: int = 3) -> Any:
    # Float last-digit drift would make a repeated answer look new and cost a round.
    if isinstance(value, (int, float)):
        return round(float(value), places)
    if isinstance(value, (list, tuple)):
        return [_round_pts(v, places) for v in value]
    return value


def _as_dict(action: Any) -> Dict[str, Any]:
    if isinstance(action, dict):
        return action
    for method in ("model_dump", "dict"):
        if hasattr(action, method):
            try:
                return getattr(action, method)()
            except Exception:
                pass
    return {"action": getattr(action, "action", None)}


def _aggregate(usage: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not usage:
        return []
    total = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    for entry in usage:
        for key in total:
            total[key] += int(entry.get(key) or 0)
    return [{"rounds": len(usage), **total}]


def _read_png_dimensions(path: str) -> Optional[Tuple[int, int]]:
    """Width and height from the IHDR chunk, so no image-size dependency is needed."""
    try:
        with open(path, "rb") as handle:
            header = handle.read(24)
        if len(header) < 24 or header[1:4] != b"PNG":
            return None
        width, height = int.from_bytes(header[16:20], "big"), int.from_bytes(header[20:24], "big")
        return (width, height) if width and height else None
    except OSError:
        return None


def solve_captcha_on_page(page: Any, **kwargs: Any) -> SolveResult:
    return PageSolver(**kwargs).solve(page)
