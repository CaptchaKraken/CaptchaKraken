"""What the pointer model is asked, and how its answer comes back.

The prompt is the SAME text for every captcha, with the board between its two
halves:

    <|im_start|>user
    Solve the captcha. ...                      PREFIX: identical on every request
    <|vision_start|>[image | video]<|vision_end|>
    action<|quad_end|> count<|quad_end|> click1<|quad_end|> ... moment<|quad_end|>

Everything up to the board is one cached prefix. The question markers have to
come AFTER the board: a causal model's state at a marker can only see what is
before it. They are fixed text too, so the board is the only thing a request
changes. Nothing about a board's elements is written in the prompt; a marked
board carries them as drawn outlines and numbers (`marks`), and the element a
point names is the one under it (`elements.ids_for`).

The heads read the hidden state at every `<|quad_end|>` (one per question), at
every vision token (the places a point can land) and at every `<|vision_end|>`
(one per moment of a video). All of those are found from the token ids alone, so
the same code reads them in training (transformers) and in serving (vLLM's
pooler).

The heads' decisions travel as one flat float vector (`pack` / `unpack`): a
pooling endpoint returns a tensor, not JSON. A point comes back as a vision
token index plus an offset inside it; `to_point` turns it into 0-1000 with the
board's token grid, which only the caller knows.
"""
from __future__ import annotations

from typing import Dict, List, Optional, Sequence, Tuple

from ..clipvideo import frame_size

ACTIONS = ("click", "drag", "slide", "hold", "type", "refresh")
MAX_CLICKS = 16
MAX_DRAGS = 4
MAX_TEXT = 16
MAX_ELEMENTS = 48
#: Earlier screens of the same puzzle a request may carry before the board
#: (`chat`'s `history`): FunCaptcha's pager shows 7 options and a solve may page
#: back, so this covers a solve that looks at each option once and returns.
MAX_HISTORY = 8
#: A still is resized to this many pixels at most, on the same 64 px lattice a
#: video frame is (`clipvideo.frame_size`), so neither processor resizes it again
#: and a token is always the same 32 px square of the board.
MAX_PIXELS = 720 * 720
#: Pixels per vision token: Qwen3.5's 16 px patch, merged 2x2.
TOKEN_PX = 32

Q_END = "<|quad_end|>"
IMAGE_PAD = "<|image_pad|>"
VIDEO_PAD = "<|video_pad|>"
VISION_END = "<|vision_end|>"

#: (question, kind). A kind has its own query projections: what a click names
#: differs from what a drag picks up (`pick`), where it lets go (`drop`), and what
#: a slider presses. A slide's `from` is picked up and its `to` dropped on; a
#: hold presses like a handle, and its fill runs from `from` to where it is let go.
SLOTS: List[Tuple[str, str]] = (
    [(f"click{k}", "click") for k in range(1, MAX_CLICKS + 1)]
    + [(f"drag{k} {end}", kind) for k in range(1, MAX_DRAGS + 1)
       for end, kind in (("from", "pick"), ("to", "drop"))]
    + [("slide handle", "handle"), ("slide from", "pick"), ("slide to", "drop")]
    + [("hold press", "handle"), ("hold from", "pick"), ("hold to", "drop")]
)
KINDS = ("click", "pick", "drop", "handle")
TEXT = [f"text{k}" for k in range(1, MAX_TEXT + 1)]
QUESTIONS: List[str] = ["action", "count"] + [s for s, _ in SLOTS] + TEXT + ["moment"]

INSTRUCTION = (
    "Solve the captcha. Read its instruction and decide what a person would do. "
    "Thin numbered outlines, where drawn, are ours and not part of the puzzle."
)
#: The fixed text after the board: one marker per question.
QUESTION_TEXT = " ".join(f"{q}{Q_END}" for q in QUESTIONS)

# ── the packed decision vector ──────────────────────────────────────────────
#: Per slot: vision token index (within the chosen moment), dx, dy (offset from
#: the token's centre, in tokens), p(token), the element number read off the
#: marks (0 for none), p(element).
SLOT_WIDTH = 6
N_COUNTS = MAX_CLICKS + 1          # clicks 0..16
N_DRAG_COUNTS = MAX_DRAGS          # drags 1..4
PACKED = (len(ACTIONS) + N_COUNTS + N_DRAG_COUNTS + SLOT_WIDTH * len(SLOTS)
          + MAX_TEXT + 2)


def board_size(width: int, height: int) -> Tuple[int, int]:
    """(W, H) a still is shown at."""
    h, w = frame_size(height, width, MAX_PIXELS)
    return w, h


def token_grid(size: Tuple[int, int]) -> Tuple[int, int]:
    """(columns, rows) of vision tokens on a board of `size` = board_size(...)."""
    return size[0] // TOKEN_PX, size[1] // TOKEN_PX


def to_norm(x: float, y: float, size: Tuple[int, int]) -> List[int]:
    return [int(round(x * 1000.0 / size[0])), int(round(y * 1000.0 / size[1]))]


def chat(processor, video: bool, history: int = 0) -> str:
    """The whole prompt string, as training builds it and serving sends it: the
    same for every board (see the module docstring).

    `history`: how many earlier screens of the same puzzle come before the board,
    oldest first, each an image exactly as it was sent then. A solve's next
    request is then this one up to its board plus one more screen, so the cached
    prefix covers every screen already seen; the questions after the last image
    see them all, and points land on the last only (`heads.Positions`). A video
    is one look and has none.

    vLLM replaces the chat template's whole `<|vision_start|><|video_pad|><|vision_end|>`
    with its per-pair placeholder, where transformers keeps the outer pair around it;
    the bare pad goes in so both expand a video alike (an image they already agree on)."""
    if video and history:
        raise ValueError("a video board carries no earlier screens")
    if not 0 <= history <= MAX_HISTORY:
        raise ValueError(f"{history} earlier screens; at most {MAX_HISTORY}")
    media = {"type": "video"} if video else {"type": "image"}
    msgs = [{"role": "user", "content": [{"type": "text", "text": INSTRUCTION},
                                         *({"type": "image"} for _ in range(history)), media,
                                         {"type": "text", "text": QUESTION_TEXT}]}]
    text = processor.apply_chat_template(msgs, tokenize=False, add_generation_prompt=False)
    return text.replace("<|vision_start|><|video_pad|><|vision_end|>", VIDEO_PAD)


def unpack(v: Sequence[float]) -> Dict:
    """The heads' flat vector -> {"action_p", "count_p", "drag_count_p", "slots":
    {name: {...}}, "text_ids", "moment", "moment_p"}."""
    v = [float(x) for x in v]
    if len(v) != PACKED:
        raise ValueError(f"decision vector has {len(v)} values, expected {PACKED}")
    i = 0

    def take(n):
        nonlocal i
        out = v[i:i + n]
        i += n
        return out
    out = {"action_p": take(len(ACTIONS)), "count_p": take(N_COUNTS),
           "drag_count_p": take(N_DRAG_COUNTS), "slots": {}}
    for name, _ in SLOTS:
        tok, dx, dy, pt, el, pe = take(SLOT_WIDTH)
        out["slots"][name] = {"token": int(tok), "dx": dx, "dy": dy, "p_point": pt,
                              "element": int(el), "p_element": pe}
    out["text_ids"] = [int(t) for t in take(MAX_TEXT)]
    out["moment"], out["moment_p"] = int(v[i]), v[i + 1]
    return out


def to_point(slot: Dict, grid: Tuple[int, int]) -> List[int]:
    """A slot's token + offset -> [x, y] on 0-1000, for a token grid (cols, rows)."""
    cols, rows = grid
    r, c = divmod(slot["token"], cols)
    x = (c + 0.5 + slot["dx"]) / cols * 1000
    y = (r + 0.5 + slot["dy"]) / rows * 1000
    return [int(round(min(max(x, 0), 1000))), int(round(min(max(y, 0), 1000)))]


def answer(decision: Dict, grid: Tuple[int, int], *, text: Optional[str] = None,
           timestamps: Optional[Sequence[float]] = None) -> Dict:
    """Unpacked decisions -> the generation-3 answer shape, points only
    (`elements.ids_for` adds the element numbers). `text` is the decoded typed
    string (the caller owns the tokenizer); `timestamps` are a video's pair times.

    `checks` says how sure each decision was: the action's, the count's and the
    moment's probability, and per slot used, in answer order, p(point) and the
    element number read off the marks with its probability (None: no number)."""
    def p(name):
        return to_point(decision["slots"][name], grid)
    a = max(range(len(ACTIONS)), key=lambda k: decision["action_p"][k])
    act = ACTIONS[a]
    out: Dict = {}
    checks: Dict = {"action_p": round(decision["action_p"][a], 4)}
    if timestamps:
        out["t"] = float(timestamps[min(decision["moment"], len(timestamps) - 1)])
        checks["moment_p"] = round(decision["moment_p"], 4)
    out["action"] = act
    names: List[str] = []
    if act in ("click", "refresh"):
        n = max(range(N_COUNTS), key=lambda k: decision["count_p"][k])
        checks["count_p"] = round(decision["count_p"][n], 4)
        if act == "refresh":
            n = min(n, 1)
        names = [f"click{k}" for k in range(1, n + 1)]
        out["points"] = [p(s) for s in names]
    elif act == "drag":
        k = max(range(N_DRAG_COUNTS), key=lambda k: decision["drag_count_p"][k])
        checks["count_p"] = round(decision["drag_count_p"][k], 4)
        drags = []
        for j in range(1, k + 2):
            drags.append({"from": p(f"drag{j} from"), "to": p(f"drag{j} to")})
            names += [f"drag{j} from", f"drag{j} to"]
        out["drags"] = drags
    elif act == "slide":
        names = ["slide handle", "slide from", "slide to"]
        out.update({"handle": p("slide handle"), "from": p("slide from"), "to": p("slide to")})
    elif act == "hold":
        names = ["hold press", "hold from", "hold to"]
        out.update({"press": p("hold press"), "from": p("hold from"), "to": p("hold to")})
    else:
        out["text"] = text or ""
    checks["slots"] = [{"slot": s, "p_point": round(decision["slots"][s]["p_point"], 4),
                        "element": decision["slots"][s]["element"] or None,
                        "p_element": round(decision["slots"][s]["p_element"], 4)} for s in names]
    out["checks"] = checks
    return out


def slot_point(ans: Dict, slot: str) -> Optional[List[int]]:
    """Where `answer`'s `slot` put its point (after any later move of it), or None."""
    if slot.startswith("click"):
        pts = ans.get("points") or []
        k = int(slot[5:]) - 1
        return pts[k] if k < len(pts) else None
    if slot.startswith("drag"):
        k, end = slot[4:].split()
        drags = ans.get("drags") or []
        return drags[int(k) - 1][end] if int(k) <= len(drags) else None
    return ans.get(slot.split()[1])
