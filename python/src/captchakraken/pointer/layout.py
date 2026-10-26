"""What the pointer model is asked, and how its answer comes back.

The prompt is the board (an image, or a video's frame pairs), then each numbered
element in Qwen's own grounding format, then one marker per question:

    Solve the captcha. ...
    <|object_ref_start|>1 item<|object_ref_end|><|box_start|>(120,340),(260,480)<|box_end|>
    ...
    action<|quad_end|> count<|quad_end|> click1<|quad_end|> ... moment<|quad_end|>

The heads read the hidden state at every `<|box_end|>` (one per element), at
every `<|quad_end|>` (one per question), at every vision token (the places a
point can land) and at every `<|vision_end|>` (one per moment of a video). All
of those are found from the token ids alone, so the same code reads them in
training (transformers) and in serving (vLLM's pooler).

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
#: A still is resized to this many pixels at most, on the same 64 px lattice a
#: video frame is (`clipvideo.frame_size`), so neither processor resizes it again
#: and a token is always the same 32 px square of the board.
MAX_PIXELS = 720 * 720
#: Pixels per vision token: Qwen3.5's 16 px patch, merged 2x2.
TOKEN_PX = 32

EL_END = "<|box_end|>"
Q_END = "<|quad_end|>"
IMAGE_PAD = "<|image_pad|>"
VIDEO_PAD = "<|video_pad|>"
VISION_END = "<|vision_end|>"

#: (question, kind). A kind has its own query projections: what a click names
#: differs from what a drag picks up (`pick`), where it lets go (`drop`), and what
#: a slider presses. A slide's `from` is picked up and its `to` dropped on.
SLOTS: List[Tuple[str, str]] = (
    [(f"click{k}", "click") for k in range(1, MAX_CLICKS + 1)]
    + [(f"drag{k} {end}", kind) for k in range(1, MAX_DRAGS + 1)
       for end, kind in (("from", "pick"), ("to", "drop"))]
    + [("slide handle", "handle"), ("slide from", "pick"), ("slide to", "drop")]
)
KINDS = ("click", "pick", "drop", "handle")
TEXT = [f"text{k}" for k in range(1, MAX_TEXT + 1)]
QUESTIONS: List[str] = ["action", "count"] + [s for s, _ in SLOTS] + TEXT + ["moment"]

INSTRUCTION = (
    "Solve the captcha. Read its instruction and decide what a person would do. "
    "Thin numbered outlines, where drawn, are ours and not part of the puzzle."
)

# ── the packed decision vector ──────────────────────────────────────────────
#: Per slot: vision token index (within the chosen moment), dx, dy (offset from
#: the token's centre, in tokens), p(token), element index or -1, p(element).
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


def prompt_text(elements: Sequence[Dict], size: Tuple[int, int]) -> str:
    """The text after the board. `elements` are `elements.number(...)`'s, in pixels
    of a board of `size`; an empty list is a board shown with nothing marked."""
    lines = [INSTRUCTION]
    if elements:
        lines.append("Elements:")
    for n, e in enumerate(elements, 1):
        x0, y0 = to_norm(e["box"][0], e["box"][1], size)
        x1, y1 = to_norm(e["box"][2], e["box"][3], size)
        lines.append(f"<|object_ref_start|>{n} {e['class']}<|object_ref_end|>"
                     f"<|box_start|>({x0},{y0}),({x1},{y1}){EL_END}")
    lines.append(" ".join(f"{q}{Q_END}" for q in QUESTIONS))
    return "\n".join(lines)


def chat(processor, elements: Sequence[Dict], size: Tuple[int, int], video: bool) -> str:
    """The whole prompt string, as training builds it and serving sends it.

    vLLM replaces the chat template's whole `<|vision_start|><|video_pad|><|vision_end|>`
    with its per-pair placeholder, where transformers keeps the outer pair around it;
    the bare pad goes in so both expand a video alike (an image they already agree on)."""
    media = {"type": "video"} if video else {"type": "image"}
    msgs = [{"role": "user", "content": [media, {"type": "text", "text": prompt_text(elements, size)}]}]
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
                              "element": None if el < 0 else int(el), "p_element": pe}
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
    """Unpacked decisions -> the generation-3 answer shape, with 1-based element
    numbers beside each point that landed on one. `text` is the decoded typed
    string (the caller owns the tokenizer); `timestamps` are a video's pair times."""
    def p(name):
        return to_point(decision["slots"][name], grid)

    def el(name):
        e = decision["slots"][name]["element"]
        return None if e is None else e + 1
    act = ACTIONS[max(range(len(ACTIONS)), key=lambda k: decision["action_p"][k])]
    out: Dict = {}
    if timestamps:
        out["t"] = float(timestamps[min(decision["moment"], len(timestamps) - 1)])
    out["action"] = act
    if act in ("click", "hold", "refresh"):
        n = max(range(N_COUNTS), key=lambda k: decision["count_p"][k])
        if act == "hold":
            n = 1
        if act == "refresh":
            n = min(n, 1)
        names = [f"click{k}" for k in range(1, n + 1)]
        out["points"] = [p(s) for s in names]
        ids = [el(s) for s in names]
        if any(i is not None for i in ids):
            out["ids"] = ids
    elif act == "drag":
        n = 1 + max(range(N_DRAG_COUNTS), key=lambda k: decision["drag_count_p"][k])
        drags = []
        for k in range(1, n + 1):
            d = {"from": p(f"drag{k} from"), "to": p(f"drag{k} to")}
            if el(f"drag{k} from") is not None:
                d["from_id"] = el(f"drag{k} from")
            if el(f"drag{k} to") is not None:
                d["to_id"] = el(f"drag{k} to")
            drags.append(d)
        out["drags"] = drags
    elif act == "slide":
        out.update({"handle": p("slide handle"), "from": p("slide from"), "to": p("slide to")})
        if el("slide handle") is not None:
            out["handle_id"] = el("slide handle")
    else:
        out["text"] = text or ""
    return out
