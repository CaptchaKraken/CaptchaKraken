"""The `captchakraken` CLI: one-shot solves, the OpenCV tool calls, the CV worker, and server management.

`captchakraken image.png [model] [api_provider] [api_key] [--puzzle-source ...]` solves one still.
Exit codes: 1 failure, 2 unsupported puzzle, 3 the hosted API refused.
"""

import argparse
import json
import os
import subprocess
import sys
import traceback
from typing import Any, Callable, Dict, List, Optional

from .errors import CaptchaKrakenAPIError
from .kinds import Outcome, PromptFamily, RetryMode, Vendor
from .solver import CaptchaSolver, UnsupportedCaptchaError


_SELF_PRINTED = object()


def _fail(message: str, code: int = 1) -> None:
    print(json.dumps({"error": message}), file=sys.stderr)
    sys.exit(code)


def _need(args: List[str], n: int, usage: str) -> None:
    if len(args) < n:
        _fail(f"Usage: captchakraken {usage}")


def _image(path: str) -> str:
    if not os.path.exists(path):
        _fail(f"Image not found: {path}")
    return path


def grid_cell_states(img_a: str, img_b: str, grid_boxes) -> dict:
    """{empty, changing, loaded, selected} (1-indexed) across two consecutive frames."""
    from .tool_calls.find_grid import detect_selected_cells, is_cell_opacity_changing, is_empty_cell

    empty, changing, loaded = [], [], []
    for c in range(1, len(grid_boxes) + 1):
        e = is_empty_cell(img_b, grid_boxes, c)
        ch = is_cell_opacity_changing(img_a, img_b, grid_boxes, c)
        if e:
            empty.append(c)
        if ch:
            changing.append(c)
        if not e and not ch:
            loaded.append(c)
    return {"empty": empty, "changing": changing, "loaded": loaded,
            "selected": detect_selected_cells(img_b, grid_boxes)[0]}


def match_region(ref: str, live: str, cx: float, cy: float, tolerance: Optional[float] = None) -> dict:
    """Does `live` look like `ref` around the 0-1 point? The wait gate behind an animated click.

    The neighbourhood only: a whole-frame match would need every unrelated sprite to align and would essentially never open.
    """
    import cv2

    from .keyframes import MATCH_REGION_TOLERANCE, region_box, region_diff_ratio

    tol = MATCH_REGION_TOLERANCE if tolerance is None else float(tolerance)
    a, b = cv2.imread(ref), cv2.imread(live)
    if a is None or b is None:
        return {"match": False, "diff": 1.0, "error": "unreadable image"}
    d = region_diff_ratio(a, b, region_box(a.shape[1::-1], (cx, cy)))
    return {"match": bool(d <= tol), "diff": float(d), "tolerance": tol}


def board_painted(image: str, floor=None, box=None) -> dict:
    from .tool_calls.board_painted import board_is_painted

    return board_is_painted(image, floor, box)


def track_piece(before: str, after: str, exclude=None, travel: float = 0.0) -> dict:
    from .tool_calls.track_piece import changed_bbox, locate_piece

    bbox = changed_bbox(before, after, exclude)
    piece = locate_piece(before, after, travel, exclude) if bbox is not None else None
    return {"bbox": bbox, "piece": piece, "moved": bbox is not None}


def _find_grid(args):
    from .tool_calls.find_grid import find_grid

    _need(args, 1, "find-grid image.png")
    return find_grid(_image(args[0]))


def _find_checkbox(args):
    from .tool_calls.find_checkbox import find_checkbox

    _need(args, 1, "find-checkbox image.png")
    return find_checkbox(_image(args[0]))


def _detect_selected(args):
    from .tool_calls.find_grid import detect_selected_cells, find_grid

    _need(args, 1, "detect-selected image.png")
    boxes = find_grid(_image(args[0]))
    if not boxes:
        return {"error": "No grid detected"}
    selected, loading = detect_selected_cells(args[0], boxes)
    return {"selected": selected, "loading": loading}


def _get_numbered_grid(args):
    from .tool_calls.find_grid import find_grid, get_numbered_grid_overlay

    _need(args, 1, "get-numbered-grid image.png")
    boxes = find_grid(_image(args[0]))
    return {"overlay_image": get_numbered_grid_overlay(args[0], boxes)} if boxes else {"error": "No grid detected"}


def _check_movement(args):
    from .image_processor import ImageProcessor

    _need(args, 2, "check-movement img1.png img2.png [threshold]")
    threshold = 0.005
    if len(args) > 2:
        try:
            threshold = float(args[2])
        except ValueError:
            pass
    return {"has_movement": ImageProcessor.detect_movement(args[0], args[1], threshold)}


def _grid_cell_states(args):
    from .tool_calls.find_grid import find_grid

    _need(args, 2, "grid-cell-states imgA.png imgB.png")
    a, b = _image(args[0]), _image(args[1])
    boxes = find_grid(b)
    return grid_cell_states(a, b, boxes) if boxes else {"grid": None}


def _grid_cell_states_fixed(args):
    """Boxes supplied by the caller: a blank mid-refresh frame has no lattice to detect."""
    _need(args, 3, "grid-cell-states-fixed imgA.png imgB.png '<json grid_boxes>'")
    a, b = _image(args[0]), _image(args[1])
    try:
        boxes = [tuple(int(v) for v in box) for box in json.loads(args[2])]
    except Exception as e:
        _fail(f"bad grid_boxes JSON: {e}")
    if not boxes:
        _fail("empty grid_boxes")
    return grid_cell_states(a, b, boxes)


def _match_region(args):
    _need(args, 4, "match-region ref.png live.png cx cy [tolerance]")
    return match_region(args[0], args[1], float(args[2]), float(args[3]),
                        float(args[4]) if len(args) > 4 else None)


def _board_painted(args):
    _need(args, 1, "board-painted image.png [floor]")
    return board_painted(args[0], float(args[1]) if len(args) > 1 else None)


def _track_piece(args):
    _need(args, 2, "track-piece before.png after.png [exclude_json] [travel]")
    return track_piece(args[0], args[1], json.loads(args[2]) if len(args) > 2 else None,
                       float(args[3]) if len(args) > 3 else 0.0)


def _report_outcome(args):
    """Tell the hosted API whether the widget accepted. Always exits 0: this runs after the solve is over."""
    if len(args) < 2 or args[1] not in list(Outcome):
        _fail("Usage: captchakraken report-outcome <session-id> solved|failed")
    try:
        from .planner import ActionPlanner

        planner = ActionPlanner()
        reported = planner.report_outcome(args[0], Outcome(args[1]) == Outcome.SOLVED)
        # `supported` false is the self-hosted 404, which tells the driver to stop spawning this.
        return {"reported": bool(reported), "supported": planner.outcome_supported}
    except Exception as exc:
        return {"reported": False, "error": str(exc)}


def _serve(args):
    """Persistent CV worker: one JSON request per stdin line, one JSON reply per stdout line."""
    from .image_processor import ImageProcessor
    from .tool_calls.find_grid import find_grid

    def handle(req):
        cmd = req.get("cmd")
        if cmd == "find-grid":
            return find_grid(req["image"])
        if cmd == "grid-cell-states":
            boxes = find_grid(req["b"])
            return grid_cell_states(req["a"], req["b"], boxes) if boxes else {"grid": None}
        if cmd == "grid-cell-states-fixed":
            boxes = [tuple(int(v) for v in box) for box in req["grid_boxes"]]
            if not boxes:
                raise ValueError("empty grid_boxes")
            return grid_cell_states(req["a"], req["b"], boxes)
        if cmd == "check-movement":
            ratio = ImageProcessor.movement_ratio(req["a"], req["b"])
            return {"has_movement": bool(ratio > float(req.get("threshold", 0.005))), "ratio": round(ratio, 5)}
        if cmd == "match-region":
            return match_region(req["ref"], req["live"], float(req["cx"]), float(req["cy"]), req.get("tolerance"))
        if cmd == "board-painted":
            return board_painted(req["image"], req.get("floor"), req.get("box"))
        if cmd == "track-piece":
            return track_piece(req["before"], req["after"], req.get("exclude"), req.get("travel") or 0.0)
        raise ValueError(f"unknown cmd: {cmd!r}")

    sys.stdout.write(json.dumps({"ready": True}) + "\n")
    sys.stdout.flush()
    for line in sys.stdin:
        if not line.strip():
            continue
        rid = None
        try:
            req = json.loads(line)
            rid = req.get("id")
            reply = {"id": rid, "ok": True, "result": handle(req)}
        except Exception as e:
            reply = {"id": rid, "ok": False, "error": str(e)}
        sys.stdout.write(json.dumps(reply) + "\n")
        sys.stdout.flush()
    return _SELF_PRINTED


def _run_solve(query: Callable[[], dict]) -> None:
    """Print the model's answer, mapping the two expected refusals onto their exit codes."""
    try:
        print(json.dumps(query()))
    except UnsupportedCaptchaError as e:
        print(json.dumps({"error": str(e), "unsupported": True}), file=sys.stderr)
        sys.exit(2)
    except CaptchaKrakenAPIError as e:
        print(json.dumps(e.to_payload()), file=sys.stderr)
        sys.exit(3)
    except Exception as e:
        traceback.print_exc()
        _fail(str(e))


def _solve_animated(args):
    """Slice a recorded burst (zero-padded PNGs in `--frames-dir`) into keyframes and solve them."""
    import glob

    parser = argparse.ArgumentParser(prog="captchakraken solve-animated")
    parser.add_argument("--frames-dir", required=True)
    parser.add_argument("--fps", type=float, default=10.0)
    parser.add_argument("--model", default=None)
    parser.add_argument("--api-key", default=None)
    parser.add_argument("--expert", default=None, type=PromptFamily, choices=list(PromptFamily))
    opts = parser.parse_args(args)
    frames = sorted(p for ext in ("png", "jpg", "jpeg") for p in glob.glob(os.path.join(opts.frames_dir, f"*.{ext}")))
    if not frames:
        _fail(f"no frames in {opts.frames_dir}")

    def query():
        import cv2

        from .keyframes import extract_keyframes, write_keyframes

        imgs = [im for im in (cv2.imread(p) for p in frames) if im is not None]
        if not imgs:
            _fail("no frame decoded")
        kfset = extract_keyframes(imgs, fps=float(opts.fps))
        paths = [os.path.abspath(p) for p in write_keyframes(kfset, os.path.join(opts.frames_dir, "keyframes"), stem="challenge")]
        solver = CaptchaSolver(model=opts.model, api_key=opts.api_key, expert=opts.expert)
        result = solver.solve_keyframes(paths)
        return {"actions": [a.model_dump() for a in result], "token_usage": solver.planner.token_usage,
                "keyframes": paths, "keyframe_mode": kfset.mode, "steady_screens": kfset.steady_screens,
                "source_frames": len(imgs)}

    _run_solve(query)
    return _SELF_PRINTED


def _server(args):
    from . import server_manager

    action = args[0] if args else "status"
    try:
        if action == "start":
            return server_manager.start(background=True)
        if action == "run":
            server_manager.run_foreground()
        if action == "stop":
            return server_manager.stop()
        if action == "status":
            return server_manager.status()
        _fail(f"unknown server action {action!r} (use start|stop|status|run)", 2)
    except SystemExit:
        raise
    except Exception as e:
        _fail(str(e))


def _fetch(args):
    from . import updater

    flags = set(args)
    unknown = flags - {"--weights-only", "--engine-only", "--no-restart", "--dry-run"}
    if unknown:
        _fail(f"unknown fetch flag(s): {sorted(unknown)} (use --weights-only|--engine-only|--no-restart|--dry-run)", 2)
    if {"--weights-only", "--engine-only"} <= flags:
        _fail("--weights-only and --engine-only are mutually exclusive", 2)
    try:
        return updater.fetch(weights="--engine-only" not in flags, engine="--weights-only" not in flags,
                             restart="--no-restart" not in flags, dry_run="--dry-run" in flags)
    except subprocess.CalledProcessError as e:
        cmd = " ".join(e.cmd) if isinstance(e.cmd, list) else e.cmd
        _fail(f"fetch step failed (exit {e.returncode}): {cmd}")
    except Exception as e:
        _fail(str(e))


COMMANDS: Dict[str, Callable[[List[str]], Any]] = {
    "find-grid": _find_grid,
    "find-checkbox": _find_checkbox,
    "detect-selected": _detect_selected,
    "get-numbered-grid": _get_numbered_grid,
    "check-movement": _check_movement,
    "grid-cell-states": _grid_cell_states,
    "grid-cell-states-fixed": _grid_cell_states_fixed,
    "match-region": _match_region,
    "board-painted": _board_painted,
    "track-piece": _track_piece,
    "report-outcome": _report_outcome,
    "serve": _serve,
    "solve-animated": _solve_animated,
    "server": _server,
    "fetch": _fetch,
    "update": _fetch,
}


def main():
    argv = sys.argv[1:]
    if argv and argv[0] in COMMANDS:
        try:
            result = COMMANDS[argv[0]](argv[1:])
        except SystemExit:
            raise
        except Exception as e:
            traceback.print_exc()
            _fail(str(e))
        if result is not _SELF_PRINTED:
            print(json.dumps(result))
        return

    parser = argparse.ArgumentParser(description="CaptchaKraken v2 (vLLM)")
    parser.add_argument("image_path", help="Path to the captcha image or video")
    parser.add_argument("model", nargs="?", default=None, help="Served LoRA name; defaults to models.json's latest.")
    parser.add_argument("api_provider", nargs="?", default="captchaKrakenApi", choices=["captchaKrakenApi"],
                        help="Kept for argv compatibility.")
    parser.add_argument("api_key", nargs="?", default=None, help="Bearer token (or CAPTCHA_KRAKEN_API_KEY).")
    parser.add_argument("--puzzle-source", default=Vendor.UNKNOWN, type=Vendor,
                        choices=list(Vendor),
                        help="Vendor hint; restricts which grid shapes a detection may be solved as.")
    parser.add_argument("--retry-mode", default=None, type=RetryMode, choices=list(RetryMode),
                        help="The vendor rejected the previous selection as incomplete.")
    parser.add_argument("--expert", default=None, type=PromptFamily, choices=list(PromptFamily),
                        help="Force one expert of a routed model. Also CAPTCHA_EXPERT.")
    parser.add_argument("--text-mode", action="store_true",
                        help="The widget has a text box, so the answer is typed rather than clicked.")
    args = parser.parse_args()
    _image(args.image_path)

    def query():
        solver = CaptchaSolver(model=args.model, api_key=args.api_key, expert=args.expert)
        result = solver.solve(args.image_path, puzzle_source=args.puzzle_source,
                              retry_mode=args.retry_mode, text_mode=args.text_mode)
        actions = [a.model_dump() for a in result] if isinstance(result, list) else result.model_dump()
        return {"actions": actions, "token_usage": solver.planner.token_usage}

    _run_solve(query)


if __name__ == "__main__":
    main()
