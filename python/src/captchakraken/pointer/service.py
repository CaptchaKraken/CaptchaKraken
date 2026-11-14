"""Board in, answer out: one vLLM prefill of the bare board, then the decode.

    svc = PointerService("/models/pointer-0.8b")
    svc.solve(image=PIL.Image)                      # a still
    svc.solve(frames=[rgb arrays])                  # a video, `clipvideo`-cut

A still is resized to `layout.board_size` and sent as it is: nothing is detected
or drawn on it. The prompt text is the same for every board (`layout.chat`). The
answer is generation 3's shape, plus `checks`: how sure each decision was.

Needs the `serve` extra (vLLM, torch).
"""
from __future__ import annotations


from pathlib import Path
from typing import Dict, List, Optional, Sequence, Union

import numpy as np
from PIL import Image

from .. import clipvideo as CV
from . import elements as E
from . import layout as L
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


def _distinct_clicks(ans: Dict, els: Sequence[Optional[Dict]] = ()) -> Dict:
    """Drop a click that repeats an earlier one: in the same place, or anywhere in
    the same cell, where the second press deselects the first. Two clicks apart on
    any other element are two answers: a line has two ends to click."""
    pts = ans.get("points")
    if not pts:
        return ans
    ids = ans.get("ids") or [None] * len(pts)
    in_cell = [i is not None and els[i - 1]["class"] == "cell" for i in ids]
    keep = [k for k, p in enumerate(pts)
            if not any((abs(p[0] - q[0]) <= SAME_PLACE and abs(p[1] - q[1]) <= SAME_PLACE)
                       or (in_cell[k] and ids[j] == ids[k]) for j, q in enumerate(pts[:k]))]
    if len(keep) == len(pts):
        return ans
    out = {**ans, "points": [pts[k] for k in keep]}
    if "ids" in ans:
        out["ids"] = [ids[k] for k in keep]
    checks = ans.get("checks")
    if checks is not None:
        names = [f"click{k + 1}" for k in keep]
        out["checks"] = {**checks, "slots": [s for s in checks["slots"]
                                             if not s["slot"].startswith("click") or s["slot"] in names]}
    return out


#: Two points this close (0-1000) press the same place.
SAME_PLACE = 25


def _distinct_drags(ans: Dict) -> Dict:
    """Drop a drag that repeats an earlier one: the piece is already there, so the
    plan does nothing more than its shorter self and must not pass as a new answer."""
    drags = ans.get("drags")
    if not drags or len(drags) < 2:
        return ans

    def near(p, q):
        return abs(p[0] - q[0]) <= SAME_PLACE and abs(p[1] - q[1]) <= SAME_PLACE
    keep = [k for k, d in enumerate(drags)
            if not any(near(d["from"], e["from"]) and near(d["to"], e["to"]) for e in drags[:k])]
    if len(keep) == len(drags):
        return ans
    out = {**ans, "drags": [drags[k] for k in keep]}
    checks = ans.get("checks")
    if checks is not None:
        # The slots name a drag by its place in the list, so the ones that stay are renumbered.
        ends = {f"drag{k + 1} {end}": f"drag{n + 1} {end}" for n, k in enumerate(keep) for end in ("from", "to")}
        out["checks"] = {**checks, "slots": [{**s, "slot": ends.get(s["slot"], s["slot"])} for s in checks["slots"]
                                             if not s["slot"].startswith("drag") or s["slot"] in ends]}
    return out


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


def read_answers(d: Dict, size, els, detokenize, stop_id: Optional[int],
                 timestamps=None, avoid: Sequence[Dict] = (), top: int = 3) -> List[Dict]:
    """Unpacked decisions -> the likeliest distinct answers, best first.

    `avoid`: answers already performed on this board and refused. `top` answers are
    returned, each doing something none of `avoid` and none of the answers before it
    did, so a deterministic model still moves when an answer is refused and never
    goes back onto one already tried. With every variant refused, the heads' own
    answer is the one that comes back.

    `els`: numbered elements on the board, when the caller marked it (the client
    sends every board bare and passes none)."""
    if top < 1:
        raise ValueError("top must be at least 1")
    grid = L.token_grid(size)
    if timestamps is not None and els:
        els = E.on_frame(els, E.moment_frame(d["moment"], len(els[0]["frames"])))
    order = L.variants(d, stop_id)
    first = None
    answers: List[Dict] = []
    for v in order:
        ids = v["text_ids"]
        if stop_id is not None and stop_id in ids:
            ids = ids[:ids.index(stop_id)]
        ans = L.answer(v, grid, text=detokenize(ids), timestamps=timestamps)
        ans = cross_check(_distinct_drags(_distinct_clicks(E.ids_for(ans, size, els), els)), size, els)
        first = first or ans
        if any(same_effect(ans, r) for r in avoid):
            continue
        if any(same_effect(ans, r) for r in answers):
            continue
        answers.append(ans)
        if len(answers) >= top:
            break
    return answers or ([first] if first is not None else [])


def read_answer(d: Dict, size, els, detokenize, stop_id: Optional[int],
                timestamps=None, avoid: Sequence[Dict] = ()) -> Dict:
    """The single likeliest answer; `read_answers` with `top=1`."""
    return read_answers(d, size, els, detokenize, stop_id, timestamps, avoid, top=1)[0]


class PointerService:
    def __init__(self, checkpoint: Union[str, Path], gpu_memory_utilization: float = 0.45,
                 max_model_len: int = 8192, **llm_kwargs):
        vllm_plugin.register()
        from transformers import AutoProcessor
        from vllm import LLM
        self.processor = AutoProcessor.from_pretrained(str(checkpoint))
        tok = self.processor.tokenizer
        self.stop_id = tok.convert_tokens_to_ids("<|im_end|>")
        # The heads read a hidden state at every prompt token, and vLLM's prefix
        # cache returns only the uncached suffix. It is not an optimisation we
        # may take: a cached prompt is refused by the plugin.
        if llm_kwargs.pop("enable_prefix_caching", False):
            raise ValueError("the pointer heads need every prompt token; prefix caching is not supported")
        self.llm = LLM(model=str(checkpoint), runner="pooling", max_model_len=max_model_len,
                       gpu_memory_utilization=gpu_memory_utilization,
                       limit_mm_per_prompt={"image": 1 + L.MAX_HISTORY, "video": 1},
                       mm_processor_kwargs={"min_pixels": 64 * 64, "max_pixels": L.MAX_PIXELS},
                       enable_prefix_caching=False, **llm_kwargs)

    # ── one board ────────────────────────────────────────────────────────────
    def _shown(self, image: Image.Image) -> Image.Image:
        """The board at the size the model sees: the same for a screen sent now or again as history."""
        return image.convert("RGB").resize(L.board_size(*image.size), Image.LANCZOS)

    def prepare(self, image: Optional[Image.Image] = None, frames: Optional[Sequence[np.ndarray]] = None,
                history: Sequence[Image.Image] = ()) -> Dict:
        """The request vLLM gets, and what decoding its answer needs. `history`:
        the puzzle's earlier screens, oldest first, as they were sent, so the
        prompt up to them is the one already cached."""
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
            prompt = L.chat(self.processor, True).replace(L.VIDEO_PAD, L.VLLM_VIDEO)
            return {"request": {"prompt": prompt,
                                "multi_modal_data": {"video": (fr, meta)},
                                "mm_processor_kwargs": {"do_sample_frames": False}},
                    "size": (w, h), "shown": None, "timestamps": CV.pair_timestamps(n)}
        board = self._shown(image)
        earlier = [self._shown(h) for h in history]
        return {"request": {"prompt": L.chat(self.processor, False, history=len(earlier)),
                            "multi_modal_data": {"image": [*earlier, board] if earlier else board}},
                "size": board.size, "shown": board, "timestamps": None}

    def decode_answers(self, prep: Dict, vector: Sequence[float], avoid: Sequence[Dict] = (),
                       top: int = 3) -> List[Dict]:
        v = [float(x) for x in vector]
        per_moment, _moments = v[L.PACKED:L.PACKED + vllm_plugin.TRAILER]
        grid = L.token_grid(prep["size"])
        if int(per_moment) != grid[0] * grid[1]:
            raise ValueError(f"vLLM saw {int(per_moment)} tokens per moment, the board has {grid}: "
                             "the processor resized it, so points would be misplaced")
        d = L.unpack(v[:L.PACKED])
        return read_answers(d, prep["size"], [], self.processor.tokenizer.decode, self.stop_id,
                            prep["timestamps"], avoid, top)

    def decode(self, prep: Dict, vector: Sequence[float], avoid: Sequence[Dict] = ()) -> Dict:
        """The single likeliest answer; `decode_answers` with `top=1`."""
        return self.decode_answers(prep, vector, avoid, 1)[0]

    def solve(self, image: Optional[Image.Image] = None, frames: Optional[Sequence[np.ndarray]] = None,
              history: Sequence[Image.Image] = (), avoid: Sequence[Dict] = (), top: int = 3) -> Dict:
        """-> {"answer": the likeliest generation-3 dict, "answers": the `top` likeliest
        distinct ones, "shown": the image the model saw (None for a video), "size":
        board (W, H)}. `avoid`: see `read_answers`."""
        return self.solve_many([{"image": image, "frames": frames, "history": history, "avoid": avoid}],
                               top=top)[0]

    def solve_many(self, boards: List[Dict], top: int = 3) -> List[Dict]:
        preps = [self.prepare(b.get("image"), b.get("frames"), b.get("history", ()))
                 for b in boards]
        outs = self.llm.embed([p["request"] for p in preps], use_tqdm=False)
        results = []
        for b, p, o in zip(boards, preps, outs):
            answers = self.decode_answers(p, o.outputs.embedding, b.get("avoid", ()), top)
            results.append({"answer": answers[0], "answers": answers, "shown": p["shown"], "size": p["size"]})
        return results
