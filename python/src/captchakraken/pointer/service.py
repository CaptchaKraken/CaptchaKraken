"""Board in, answer out: the detector, the marks, one vLLM prefill, the decode.

    svc = PointerService("/models/pointer-0.8b", detector="/models/detector_r18.pt")
    svc.solve(image=PIL.Image)                      # a still
    svc.solve(frames=[rgb arrays])                  # a video, `clipvideo`-cut

A still is resized to `layout.board_size`; the detector runs on that, and the
elements it finds are drawn on it (`marks`). A video's frames are detected one
by one, linked across the clip (`elements.track`, so an element keeps one number)
and drawn on every frame. With no detector, or `marked=False`, the board goes
plain. The prompt text is the same for every board (`layout.chat`). The answer is
generation 3's shape, plus the 1-based number of the element under each point
(`elements.ids_for`) when the board was marked, and `checks`: how sure each
decision was, and whether each point's element is the one the model read off
the marks (`cross_check`).

Needs the `serve` extra (vLLM, torch, torchvision).
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional, Sequence, Union

import numpy as np
from PIL import Image

from .. import clipvideo as CV
from . import elements as E
from . import layout as L
from . import marks as M
from . import vllm_plugin


def cross_check(ans: Dict, size, els: Sequence[Optional[Dict]]) -> Dict:
    """Put the element under each point beside the one the model read off the marks.

    Each `checks` slot gains `under`: the 1-based element its (final) point lands on, or None. `checks["agree"]`
    is whether every slot's two answers name the same element, or None on a board with no elements, where there
    is nothing to read. Two answers decided apart that differ mean the board was misread."""
    checks = ans.get("checks")
    if checks is None:
        return ans
    has_elements = any(e is not None for e in els)
    for s in checks["slots"]:
        at = L.slot_point(ans, s["slot"])
        i = E.element_at(at, size, els) if has_elements and at is not None else None
        s["under"] = None if i is None else i + 1
    checks["agree"] = all(s["under"] == s["element"] for s in checks["slots"]) if has_elements else None
    return ans


def _distinct_clicks(ans: Dict) -> Dict:
    """Drop a click on an element an earlier click already took: on a tile board
    the second press deselects the first. Two slots can land on one element from
    different tokens, which no point-distance check sees."""
    ids, pts = ans.get("ids"), ans.get("points")
    if not ids or not pts or len(ids) != len(pts):
        return ans
    keep = [k for k, i in enumerate(ids) if i is None or i not in ids[:k]]
    if len(keep) == len(ids):
        return ans
    out = {**ans, "points": [pts[k] for k in keep], "ids": [ids[k] for k in keep]}
    checks = ans.get("checks")
    if checks is not None:
        names = [f"click{k + 1}" for k in keep]
        out["checks"] = {**checks, "slots": [s for s in checks["slots"]
                                             if not s["slot"].startswith("click") or s["slot"] in names]}
    return out


#: Two points this close (0-1000) press the same place.
SAME_PLACE = 25


def _places(ans: Dict) -> List:
    """Where performing `ans` presses, in order: an element number where the point
    has one, else the point."""
    out = []
    pts, ids = ans.get("points") or [], ans.get("ids") or []
    out += [ids[k] if k < len(ids) and ids[k] is not None else p for k, p in enumerate(pts)]
    for d in ans.get("drags") or []:
        out += [d.get("from_id") or d["from"], d.get("to_id") or d["to"]]
    for end in ("handle", "press", "from", "to"):
        if ans.get(end) is not None:
            out.append(ans.get(f"{end}_id") or ans[end])
    return out


def same_effect(a: Dict, b: Dict) -> bool:
    """Would performing `a` do what performing `b` did: the same action, text and
    places, clicks in any order. A point a hair from another, or on the same
    element, is the same place."""
    if a.get("action") != b.get("action") or (a.get("text") or "") != (b.get("text") or ""):
        return False
    pa, pb = _places(a), _places(b)
    if len(pa) != len(pb):
        return False

    def same(x, y):
        if isinstance(x, int) or isinstance(y, int):
            return x == y
        return abs(x[0] - y[0]) <= SAME_PLACE and abs(x[1] - y[1]) <= SAME_PLACE
    if a.get("action") == "click":
        left = list(pb)
        for x in pa:
            k = next((k for k, y in enumerate(left) if same(x, y)), None)
            if k is None:
                return False
            left.pop(k)
        return True
    return all(same(x, y) for x, y in zip(pa, pb))


def read_answer(d: Dict, size, els, detokenize, stop_id: Optional[int],
                timestamps=None, avoid: Sequence[Dict] = ()) -> Dict:
    """Unpacked decisions -> the answer, with element ids and `checks`.

    `avoid`: answers already performed on this board and refused. The answer is the
    likeliest of `layout.variants` that does something none of them did, so a
    deterministic model still moves when its first answer is refused, and never back
    onto one already tried. With every variant refused, the heads' own answer."""
    grid = L.token_grid(size)
    if timestamps is not None and els:
        els = E.on_frame(els, E.moment_frame(d["moment"], len(els[0]["frames"])))
    first = None
    for v in L.variants(d, stop_id):
        ids = v["text_ids"]
        if stop_id is not None and stop_id in ids:
            ids = ids[:ids.index(stop_id)]
        ans = L.answer(v, grid, text=detokenize(ids), timestamps=timestamps)
        ans = cross_check(_distinct_clicks(E.ids_for(ans, size, els)), size, els)
        first = first or ans
        if not any(same_effect(ans, r) for r in avoid):
            return ans
    return first


class PointerService:
    def __init__(self, checkpoint: Union[str, Path], detector: Union[str, Path, None] = None,
                 gpu_memory_utilization: float = 0.45, max_model_len: int = 8192, **llm_kwargs):
        vllm_plugin.register()
        from transformers import AutoProcessor
        from vllm import LLM
        self.processor = AutoProcessor.from_pretrained(str(checkpoint))
        tok = self.processor.tokenizer
        self.stop_id = tok.convert_tokens_to_ids("<|im_end|>")
        self.llm = LLM(model=str(checkpoint), runner="pooling", max_model_len=max_model_len,
                       gpu_memory_utilization=gpu_memory_utilization,
                       limit_mm_per_prompt={"image": 1 + L.MAX_HISTORY, "video": 1},
                       mm_processor_kwargs={"min_pixels": 64 * 64, "max_pixels": L.MAX_PIXELS}, **llm_kwargs)
        self.detector = None
        if detector is not None:
            from .detector import Detector
            self.detector = Detector(detector)

    # ── one board ────────────────────────────────────────────────────────────
    def _shown(self, image: Image.Image, marked: bool):
        """(the board at the size the model sees, its numbered elements, the
        picture sent): the same for a screen sent now or again as history."""
        board = image.convert("RGB").resize(L.board_size(*image.size), Image.LANCZOS)
        els = E.number(self.detector.detect(board)) if (marked and self.detector is not None) else []
        return board, els, (M.draw(board, els) if els else board)

    def prepare(self, image: Optional[Image.Image] = None, frames: Optional[Sequence[np.ndarray]] = None,
                marked: bool = True, history: Sequence[Image.Image] = ()) -> Dict:
        """The request vLLM gets, and what decoding its answer needs. `history`:
        the puzzle's earlier screens, oldest first, as they were sent (marked the
        same way), so the prompt up to them is the one already cached."""
        if (image is None) == (frames is None):
            raise ValueError("give exactly one of image or frames")
        if frames is not None and history:
            raise ValueError("a video board carries no earlier screens")
        if frames is not None:
            fr = np.stack([np.asarray(f) for f in frames])
            n, h, w = fr.shape[:3]
            if (h, w) != CV.frame_size(h, w, L.MAX_PIXELS):
                raise ValueError(f"frames are {w}x{h}; cut them with clipvideo.clip_video first")
            meta = {"fps": CV.FPS, "frames_indices": list(range(n)), "total_num_frames": n,
                    "duration": n / CV.FPS, "video_backend": "opencv", "do_sample_frames": False}
            tracks = []
            if marked and self.detector is not None:
                ims = [Image.fromarray(f) for f in fr]
                tracks = E.track([E.number(self.detector.detect(im)) for im in ims])
                if tracks:
                    fr = np.stack([np.asarray(M.draw(im, E.on_frame(tracks, k)))
                                   for k, im in enumerate(ims)])
            return {"request": {"prompt": L.chat(self.processor, True),
                                "multi_modal_data": {"video": (fr, meta)},
                                "mm_processor_kwargs": {"do_sample_frames": False}},
                    "size": (w, h), "elements": tracks, "shown": None,
                    "timestamps": CV.pair_timestamps(n)}
        board, els, shown = self._shown(image, marked)
        earlier = [self._shown(h, marked)[2] for h in history]
        return {"request": {"prompt": L.chat(self.processor, False, history=len(earlier)),
                            "multi_modal_data": {"image": [*earlier, shown] if earlier else shown}},
                "size": board.size, "elements": els, "shown": shown, "timestamps": None}

    def decode(self, prep: Dict, vector: Sequence[float], avoid: Sequence[Dict] = ()) -> Dict:
        v = [float(x) for x in vector]
        per_moment, _moments = v[L.PACKED:L.PACKED + vllm_plugin.TRAILER]
        grid = L.token_grid(prep["size"])
        if int(per_moment) != grid[0] * grid[1]:
            raise ValueError(f"vLLM saw {int(per_moment)} tokens per moment, the board has {grid}: "
                             "the processor resized it, so points would be misplaced")
        return read_answer(L.unpack(v[:L.PACKED]), prep["size"], prep["elements"],
                           self.processor.tokenizer.decode, self.stop_id, prep["timestamps"], avoid)

    def solve(self, image: Optional[Image.Image] = None, frames: Optional[Sequence[np.ndarray]] = None,
              marked: bool = True, history: Sequence[Image.Image] = (), avoid: Sequence[Dict] = ()) -> Dict:
        """-> {"answer": generation-3 dict, "elements": numbered elements (board px;
        a video's are `elements.track` tracks),
        "shown": the image the model saw (None for a video), "size": board (W, H)}. `avoid`: see `read_answer`."""
        return self.solve_many([{"image": image, "frames": frames, "marked": marked, "history": history,
                                 "avoid": avoid}])[0]

    def solve_many(self, boards: List[Dict]) -> List[Dict]:
        preps = [self.prepare(b.get("image"), b.get("frames"), b.get("marked", True), b.get("history", ()))
                 for b in boards]
        outs = self.llm.embed([p["request"] for p in preps], use_tqdm=False)
        return [{"answer": self.decode(p, o.outputs.embedding, b.get("avoid", ())), "elements": p["elements"],
                 "shown": p["shown"], "size": p["size"]} for b, p, o in zip(boards, preps, outs)]
