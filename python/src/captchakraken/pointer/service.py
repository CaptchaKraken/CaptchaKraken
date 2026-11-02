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

import collections
import math

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


#: Cyrillic capitals the Latin alphabet draws identically. The letter detector reads one
#: box at a time and cannot tell which script a box is in, so readings are compared folded.
HOMOGLYPHS_FROM, HOMOGLYPHS_TO = "АВЕКМНОРСТУХаеорсух", "ABEKMHOPCTYXaeopcyx"
HOMOGLYPHS = str.maketrans(HOMOGLYPHS_FROM, HOMOGLYPHS_TO)
_TO_CYRILLIC = str.maketrans(HOMOGLYPHS_TO, HOMOGLYPHS_FROM)


def fold(text: str) -> str:
    """`text` as the letter detector can be held to it: lookalike scripts and case merged."""
    return (text or "").translate(HOMOGLYPHS).casefold().translate(HOMOGLYPHS)


#: Two letter boxes overlapping this much are one letter read twice.
SAME_LETTER_IOU = 0.4


def _iou(a: Sequence[float], b: Sequence[float]) -> float:
    w = min(a[2], b[2]) - max(a[0], b[0])
    h = min(a[3], b[3]) - max(a[1], b[1])
    if w <= 0 or h <= 0:
        return 0.0
    inter = w * h
    return inter / ((a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter)


def letter_slots(dets: Sequence[Dict]) -> List[Dict]:
    """The letter detector's boxes -> its letters, left to right: {"box", "score", "chars":
    {folded character: score}}. The detector suppresses overlaps within a class only, so
    one glyph comes back as each lookalike it resembles (A and Cyrillic А, 0 and O): of
    boxes overlapping by SAME_LETTER_IOU, the surest stands for the letter and the rest
    are its other readings."""
    slots: List[Dict] = []
    for d in sorted(dets, key=lambda d: -d["score"]):
        home = next((s for s in slots if _iou(d["box"], s["box"]) >= SAME_LETTER_IOU), None)
        if home is None:
            slots.append({"box": d["box"], "score": d["score"], "char": d["class"], "chars": {}, "show": {}})
            home = slots[-1]
        c = fold(d["class"])
        home["chars"][c] = max(home["chars"].get(c, 0.0), d["score"])
        home["show"].setdefault(c, d["class"])
    return sorted(slots, key=lambda s: s["box"][0] + s["box"][2])


def _script(c: str) -> str:
    if "\u4e00" <= c <= "\u9fff":
        return "han"
    if "\u0400" <= c <= "\u04ff":
        return "cyrillic"
    return "latin" if c.isalpha() else "digit"


def in_board_script(slots: Sequence[Dict], like: str) -> List[Dict]:
    """`slots` with the readings no letter of the board's script could be: the board is
    in the script most of `like` (the model's text) is, and a 王 on a Latin board is the
    detector's guess at a stroke, not a letter of the code. Cyrillic boards keep Latin
    readings, which `fold` made of their lookalikes. A box left with no reading is still
    a box: `fuse` may count it, but the model names it."""
    seen = collections.Counter(_script(c) for c in like or "" if _script(c) != "digit")
    board = seen.most_common(1)[0][0] if seen else None
    if board is None:
        return list(slots)
    allowed = {board, "digit", *(("latin",) if board == "cyrillic" else ())}
    return [{**s, "chars": {c: p for c, p in s["chars"].items() if _script(c) in allowed}} for s in slots]


def letter_slots_counted(slots: Sequence[Dict]) -> List[Dict]:
    """The letters of `letter_slots` sure enough to count (LETTER_MIN_SCORE)."""
    return [s for s in slots if s["score"] >= LETTER_MIN_SCORE]


def typed_chars(d: Dict, detokenize, stop_id: int) -> List[Dict]:
    """The decision's typed characters as `fuse` takes them: each marker's top choice
    and runner-up, {"chars": {folded: p}, "show": {folded: as typed}}."""
    out = []
    for t, p, a, ap in zip(d["text_ids"], d["text_p"], d["text_alt_ids"], d["text_alt_p"]):
        if t == stop_id:
            break
        chars: Dict[str, float] = {}
        show: Dict[str, str] = {}
        for i, q in ((t, p), (a, ap)):
            if i == stop_id:
                continue
            c = detokenize([i])
            chars[fold(c)] = chars.get(fold(c), 0.0) + q
            show.setdefault(fold(c), c)
        out.append({"chars": chars, "show": show})
    return out


def read_letters(dets: Sequence[Dict]) -> str:
    """The letter detector's boxes -> the code they spell, left to right.

    The detector suppresses overlaps within a class only, so one glyph comes back as
    each lookalike it resembles (A and Cyrillic А, P and Р): of boxes overlapping by
    SAME_LETTER_IOU, the surest stands for the letter."""
    return "".join(s["char"] for s in letter_slots_counted(letter_slots(dets)))


#: A letter box this sure counts as a letter in `read_letters`; fainter ones are left to
#: `fuse`, which keeps one only when the model typed something there too.
LETTER_MIN_SCORE = 0.3
#: The faintest box `fuse` is shown (the detector's own default floor is 0.3).
FAINTEST_LETTER = 0.05
#: `fuse`'s odds. A character neither reader proposed is worth MODEL_FLOOR / CNN_FLOOR of
#: a proposal. A model character with no box under it is a letter the detector missed
#: (CNN_MISSED) or a marker that landed on a letter already read (MODEL_EXTRA, DOUBLED
#: when it repeats its neighbour: R99VK for R9VK, the model's usual slip); a box the
#: model typed nothing for is a letter the model skipped (MODEL_MISSED) or noise.
MODEL_FLOOR, CNN_FLOOR = 0.2, 0.2
CNN_MISSED, MODEL_EXTRA, DOUBLED = 0.05, 0.1, 0.3
MODEL_MISSED = 0.03
#: Joint readings tried before the model's own answers.
FUSED_TRIES = 2


def fuse(model: Sequence[Dict], slots: Sequence[Dict]) -> List[Dict]:
    """The code both readers support. `model`: the typed characters in order, each
    {"chars": {folded character: p}, "show": {folded: as typed}} (the head's top choice
    and runner-up); `slots`: `letter_slots`. The two are aligned in reading order, and
    every position picks the character with the most evidence from both, so the model
    fixes a box the detector misread and the boxes fix a doubled or wrong model letter.

    -> the chosen characters, each {"char", "margin"}: margin is the log odds of the
    choice over the runner-up character at that place (inf when there was none), the
    place a retry should change first."""
    lg = math.log
    n, m = len(model), len(slots)
    NEG = -1e18
    best = [[NEG] * (m + 1) for _ in range(n + 1)]
    back: List[List[Optional[tuple]]] = [[None] * (m + 1) for _ in range(n + 1)]
    best[0][0] = 0.0

    def pick(mc: Dict, cc: Dict):
        cands = sorted(((lg(mc.get(c, 0.0) + MODEL_FLOOR) + lg(cc.get(c, 0.0) + CNN_FLOOR), c)
                        for c in {*mc, *cc}), reverse=True)
        if len(cands) == 1:
            return cands[0][0], cands[0][1], None, math.inf
        return cands[0][0], cands[0][1], cands[1][1], cands[0][0] - cands[1][0]

    def top(chars: Dict):
        if not chars:
            return None, 0.0
        c = max(chars, key=chars.get)
        return c, chars[c]
    for i in range(n + 1):
        for j in range(m + 1):
            here = best[i][j]
            if here == NEG:
                continue
            if i < n and j < m:
                sc, c, alt, margin = pick(model[i]["chars"], slots[j]["chars"])
                step = (i, j, c, alt, margin)
                if here + sc > best[i + 1][j + 1]:
                    best[i + 1][j + 1], back[i + 1][j + 1] = here + sc, step
            if i < n:
                c, p = top(model[i]["chars"])
                doubled = any(top(model[k]["chars"])[0] == c for k in (i - 1, i + 1) if 0 <= k < n)
                keep, drop = lg(CNN_MISSED) + lg(p), lg(DOUBLED if doubled else MODEL_EXTRA)
                sc = max(keep, drop)
                if here + sc > best[i + 1][j]:
                    best[i + 1][j] = here + sc
                    back[i + 1][j] = (i, j, *((c, None) if keep >= drop else (None, c)), abs(keep - drop))
            if j < m:
                c, p = top(slots[j]["chars"])
                keep = lg(MODEL_MISSED) + lg(p) if c is not None else -math.inf
                drop = lg(1.0 - p + 1e-6)
                sc = max(keep, drop)
                if here + sc > best[i][j + 1]:
                    best[i][j + 1] = here + sc
                    back[i][j + 1] = (i, j, *((c, None) if keep >= drop else (None, c)), abs(keep - drop))
    out: List[Dict] = []
    i, j = n, m
    while (i, j) != (0, 0):
        pi, pj, c, alt, margin = back[i][j]

        def show(c):
            if c is None:
                return ""
            return (model[pi]["show"].get(c) if pi < i else None) or (slots[pj]["show"].get(c) if pj < j else None) or c
        out.append({"char": show(c), "alt": show(alt), "margin": margin})
        i, j = pi, pj
    return out[::-1]


def fused_texts(model: Sequence[Dict], slots: Sequence[Dict], tries: int = 2) -> List[str]:
    """`fuse`'s code, then the code with its least sure choice made the other way (the
    runner-up character, or a letter kept or dropped), and so on: `tries` distinct codes,
    written in the board's script (`_in_board_script`; a board whose script no letter
    tells is tried in Latin, then Cyrillic, before any letter changes). With no box
    found, the model's own text alone."""
    if not model:
        return []
    if not slots:
        return _in_board_script("".join(m["show"][max(m["chars"], key=m["chars"].get)] for m in model), slots)[:tries]
    steps = fuse(model, slots)
    out = _in_board_script("".join(s["char"] for s in steps), slots)
    for k in sorted(range(len(steps)), key=lambda k: steps[k]["margin"]):
        if len(out) >= tries or steps[k]["margin"] == math.inf:
            break
        text = _in_board_script("".join(s["alt"] if q == k else s["char"] for q, s in enumerate(steps)), slots)[0]
        if text and text not in out:
            out.append(text)
    return [t for t in out if t][:tries]


def _in_board_script(text: str, slots: Sequence[Dict]) -> List[str]:
    """`text` with each lookalike letter written in the board's script, a typed Cyrillic
    Р is not the P a Latin board asks for: the script its letters that have no lookalike
    are in, in `text` and in the detector's reading. With none to tell (ЕСКХ), or as
    many each way, Latin, the script nearly every live board is in, then Cyrillic: the
    detector's classes for a lookalike are no guide on real boards (it reads Х in a
    Latin 6X6XXT), and the model types Latin for both."""
    look = set(HOMOGLYPHS_FROM + HOMOGLYPHS_TO)
    seen = collections.Counter(_script(c) for c in text + "".join(s["char"] for s in slots)
                               if c not in look and _script(c) in ("latin", "cyrillic"))
    latin, cyrillic = text.translate(HOMOGLYPHS), text.translate(_TO_CYRILLIC)
    if seen["cyrillic"] > seen["latin"]:
        return [cyrillic]
    if seen["latin"] > seen["cyrillic"] or latin == cyrillic:
        return [latin]
    return [latin, cyrillic]


def read_answer(d: Dict, size, els, detokenize, stop_id: Optional[int],
                timestamps=None, avoid: Sequence[Dict] = (), letters: Optional[Sequence[Dict]] = None) -> Dict:
    """Unpacked decisions -> the answer, with element ids and `checks`.

    `avoid`: answers already performed on this board and refused. The answer is the
    likeliest of `layout.variants` that does something none of them did, so a
    deterministic model still moves when its first answer is refused, and never back
    onto one already tried. With every variant refused, the heads' own answer.

    `letters`: the letter detector's letters on a typed board (`letter_slots`). The
    code typed is the one the model and the detector read together (`fused_texts`):
    first their joint reading, then it with its least sure choice made the other way,
    then the model's own `variants`, then the detector's reading. `checks` carries the
    detector's reading and whether it spells what the model read on its own (`fold`ed):
    two readers that agree are almost always right (all 25 such real boards), and the
    fusion matters where they do not."""
    grid = L.token_grid(size)
    if timestamps is not None and els:
        els = E.on_frame(els, E.moment_frame(d["moment"], len(els[0]["frames"])))
    order = L.variants(d, stop_id)
    reading = model = slots = None
    if letters is not None and stop_id is not None and L._chosen(order[0])[0] == "type":
        chars = typed_chars(d, detokenize, stop_id)
        model = "".join(c["show"][max(c["chars"], key=c["chars"].get)] for c in chars)
        slots = in_board_script(letters, model)
        reading = "".join(s["char"] for s in letter_slots_counted(letters))
        joint = [{**order[0], "typed": t, **({"retry": "joint reading"} if k else {})}
                 for k, t in enumerate(fused_texts(chars, slots, FUSED_TRIES))]
        order = [*joint, *order, {**order[0], "typed": _in_board_script(reading, slots)[0],
                                  "retry": "letter detector's reading"}]
    first = None
    for v in order:
        ids = v["text_ids"]
        if stop_id is not None and stop_id in ids:
            ids = ids[:ids.index(stop_id)]
        text = v.get("typed")
        if text is None:
            text = detokenize(ids)
            if slots is not None and L._chosen(v)[0] == "type":
                text = _in_board_script(text, slots)[0]
        ans = L.answer(v, grid, text=text, timestamps=timestamps)
        ans = cross_check(_distinct_clicks(E.ids_for(ans, size, els)), size, els)
        if reading is not None and ans["action"] == "type":
            ans["checks"]["letters"] = reading
            ans["checks"]["letters_agree"] = fold(model) == fold(reading)
        first = first or ans
        if not any(same_effect(ans, r) for r in avoid):
            return ans
    return first


class PointerService:
    def __init__(self, checkpoint: Union[str, Path], detector: Union[str, Path, None] = None,
                 gpu_memory_utilization: float = 0.45, max_model_len: int = 8192,
                 letters: Union[str, Path, None] = None, **llm_kwargs):
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
        #: The letter detector (`scripts/build_glyph_dataset.py` in the Finetune repo): on a board the
        #: model types into, the characters it finds, left to right (`read_answer`'s `letters`).
        self.letters = None
        if letters is not None:
            from .detector import Detector
            self.letters = Detector(letters)

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
                "size": board.size, "elements": els, "shown": shown, "timestamps": None, "board": board}

    def decode(self, prep: Dict, vector: Sequence[float], avoid: Sequence[Dict] = ()) -> Dict:
        v = [float(x) for x in vector]
        per_moment, _moments = v[L.PACKED:L.PACKED + vllm_plugin.TRAILER]
        grid = L.token_grid(prep["size"])
        if int(per_moment) != grid[0] * grid[1]:
            raise ValueError(f"vLLM saw {int(per_moment)} tokens per moment, the board has {grid}: "
                             "the processor resized it, so points would be misplaced")
        d = L.unpack(v[:L.PACKED])
        return read_answer(d, prep["size"], prep["elements"], self.processor.tokenizer.decode, self.stop_id,
                           prep["timestamps"], avoid, self.count_letters(prep, d))

    def count_letters(self, prep: Dict, d: Dict) -> Optional[List[Dict]]:
        """The letter detector's `letter_slots` on a still the heads would type into; else None."""
        if self.letters is None or prep.get("board") is None:
            return None
        if L.ACTIONS[max(range(len(L.ACTIONS)), key=lambda k: d["action_p"][k])] != "type":
            return None
        return letter_slots(self.letters.detect(prep["board"], min_score=FAINTEST_LETTER))

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
