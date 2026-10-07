from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

from .kinds import Availability, PromptFamily

_MODELS_PATH = Path(__file__).with_name("models.json")
_PROMPTS_FILE_ENV = "CAPTCHA_PROMPTS_FILE"
_DISABLE_FETCH_ENV = "CAPTCHA_PROMPTS_NO_FETCH"

LATEST_PROMPT_VERSION = "2"


# Pure literals only, no f-strings, joins or constant references: the training repo's release parity gate reads
# this dict by AST without importing the package, and the gate going quiet is how prompt drift shipped once.
BUILTIN_PROMPTS = {
    "1": {
        "action_pixel": (
            "Your task is to solve the captcha. Read the instruction at the top of the image carefully.\n\n"
            "Look at the puzzle and decide what action solves it. All coordinates you return must be on a "
            "normalized 0–1000 image scale (top-left = (0, 0), bottom-right = (1000, 1000)).\n\n"
            "Name WHAT each object is with a short 1–2 word label, then give its position. "
            "Choose ONE response:\n\n"
            "FOR CLICK PUZZLES:\n"
            "  Label each thing you click and give its point — subjects[i] names points[i]:\n"
            "  → \"action\": \"click\", \"subjects\": [\"<label>\", ...], "
            "\"points\": [[x1, y1], [x2, y2], ...]\n\n"
            "FOR DRAG PUZZLES:\n"
            "  Drag ONE item at a time. Label the source (the piece you pick up) and the destination "
            "(where it belongs), each with a short 1–2 word label, and give both points:\n"
            "  → \"action\": \"drag\", \"drags\": [{ \"source\": \"<label>\", \"from\": [x, y], "
            "\"destination\": \"<label>\", \"to\": [x, y] }, ...]\n\n"
            "Respond ONLY with JSON:\n"
            "{\n"
            "  \"action\": \"click\", \"subjects\": [ ... ], \"points\": [ ... ]\n"
            "  // OR \"action\": \"drag\", \"drags\": [ ... ]\n"
            "}"
        ),
        "grid": (
            "Solve the captcha grid by choosing the cell numbers that match the description "
            "from the captcha image prompt.\n\nGrid: {rows}x{cols} ({total} cells)\n{grid_hint}\n\n"
            "If no tiles match the description (e.g., they have all been cleared or none were "
            "present), return an empty list for target_ids: [].\n\n"
            "Return JSON Array: [list of cell numbers (1-{total})]"
        ),
        "video": None,
        "text": None,
    },
    "2": {
        "action_pixel": (
            "Your task is to solve the captcha. Read the instruction at the top of the image carefully.\n\n"
            "Look at the puzzle and decide what action solves it. All coordinates you return must be on a "
            "normalized 0–1000 image scale (top-left = (0, 0), bottom-right = (1000, 1000)).\n\n"
            "Name WHAT each object is with a short 1–2 word label, then give its position. "
            "Choose ONE response:\n\n"
            "FOR CLICK PUZZLES:\n"
            "  Label each thing you click and give its point — subjects[i] names points[i]:\n"
            "  → \"action\": \"click\", \"subjects\": [\"<label>\", ...], "
            "\"points\": [[x1, y1], [x2, y2], ...]\n\n"
            "FOR DRAG PUZZLES:\n"
            "  Drag ONE item at a time. Label the source (the piece you pick up) and the destination "
            "(where it belongs), each with a short 1–2 word label, and give both points:\n"
            "  → \"action\": \"drag\", \"drags\": [{ \"source\": \"<label>\", \"from\": [x, y], "
            "\"destination\": \"<label>\", \"to\": [x, y] }, ...]\n\n"
            "FOR PUZZLE PIECE SLIDER PUZZLES:\n"
            "  A single jigsaw piece has to end up in the piece-shaped slot cut into the picture. "
            "Do not pick up the piece or the slider handle — leave the source EMPTY and give only "
            "the destination, the CENTER OF THE SLOT the piece belongs in:\n"
            "  → \"action\": \"drag\", \"drags\": [{ \"source\": \"\", \"from\": [], "
            "\"destination\": \"<label>\", \"to\": [x, y] }]\n\n"
            "Respond ONLY with JSON:\n"
            "{\n"
            "  \"action\": \"click\", \"subjects\": [ ... ], \"points\": [ ... ]\n"
            "  // OR \"action\": \"drag\", \"drags\": [ ... ]\n"
            "}"
        ),
        "grid": (
            "Solve the captcha grid by choosing the cell numbers that match the description "
            "from the captcha image prompt.\n\nGrid: {rows}x{cols} ({total} cells)\n{grid_hint}\n\n"
            "A cell that is already selected — small checkmark badge, border or highlight — "
            "still counts. Include it if it matches.\n\n"
            "A cell being REPLACED does not: a large checkmark over the middle of the picture, "
            "a picture fading to white, or a new picture fading in. That cell is on its way to "
            "showing something else, so leave it out however well it matches.\n\n"
            "If no cells match the description, return an empty list for target_ids: [].\n\n"
            "Return JSON Array: [list of cell numbers (1-{total})]"
        ),
        "video": (
            "Your task is to solve the captcha. This challenge is animated, so instead of one "
            "picture you are given {n} still keyframes cut from a short recording of it, in "
            "order: {listing}.\n\n"
            "Every keyframe shows the SAME puzzle at a different moment. Read the instruction at "
            "the top of the keyframes carefully. What you need to act on may be visible in only "
            "some of the frames — sprites fade in and out, boards cycle their contents — so pick "
            "the ONE frame in which your target is clearest and report its number as \"frame\".\n\n"
            "The frame number is there so the solver knows WHEN to press the mouse: it waits for the "
            "widget to look like that frame before clicking. If your answer does not depend on the "
            "frame — the target is in the same place in every one of them — then there is nothing to "
            "wait for, and you may leave \"frame\" out entirely.\n\n"
            "Read your coordinates off THAT frame. All coordinates must be on a normalized 0–1000 "
            "image scale (top-left = (0, 0), bottom-right = (1000, 1000)).\n\n"
            "Name WHAT each object is with a short 1–2 word label, then give its position. "
            "Choose ONE response:\n\n"
            "FOR CLICK PUZZLES:\n"
            "  Label each thing you click and give its point — subjects[i] names points[i]:\n"
            "  → \"frame\": <1-{n}>, \"action\": \"click\", \"subjects\": [\"<label>\", ...], "
            "\"points\": [[x1, y1], [x2, y2], ...]\n\n"
            "FOR DRAG PUZZLES:\n"
            "  Drag ONE item at a time. Label the source (the piece you pick up) and the "
            "destination (where it belongs), each with a short 1–2 word label, and give both "
            "points:\n"
            "  → \"frame\": <1-{n}>, \"action\": \"drag\", \"drags\": [{{ \"source\": \"<label>\", "
            "\"from\": [x, y], \"destination\": \"<label>\", \"to\": [x, y] }}, ...]\n\n"
            "Respond ONLY with JSON:\n"
            "{{\n"
            "  \"frame\": <1-{n}>,   // omit if your answer holds in every frame\n"
            "  \"action\": \"click\", \"subjects\": [ ... ], \"points\": [ ... ]\n"
            "  // OR \"action\": \"drag\", \"drags\": [ ... ]\n"
            "}}"
        ),
        "text": (
            "Your task is to solve the captcha. The image shows a short code drawn in distorted, "
            "overlapping or warped characters, sometimes over a busy background.\n\n"
            "Read the code exactly as printed. Preserve letter case when the characters clearly "
            "show it, and do not add spaces the image does not show. Decoration — strike-through "
            "lines, dots, blobs, background texture — is not part of the code.\n\n"
            "Respond ONLY with JSON:\n"
            "{\n"
            "  \"action\": \"type\", \"text\": \"<the code>\"\n"
            "}"
        ),
    },
}


def _load_registry() -> Dict[str, Any]:
    try:
        with _MODELS_PATH.open(encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


_REGISTRY: Optional[Dict[str, Any]] = None


def registry() -> Dict[str, Any]:
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = _load_registry()
    return _REGISTRY


def registered_models() -> Dict[str, Dict[str, Any]]:
    return {k: v for k, v in (registry().get("models") or {}).items()
            if isinstance(v, dict)}


def latest_model() -> Optional[str]:
    return registry().get("latest")


def served_aliases() -> Dict[str, str]:
    return dict(registry().get("served_aliases") or {})


def hosted_default_model() -> Optional[str]:
    return registry().get("hosted_default")


def canonical_model_id(model: Optional[str]) -> Optional[str]:
    if not model:
        return None
    if model in registered_models():
        return model
    alias = (registry().get("served_aliases") or {}).get(model)
    return alias if isinstance(alias, str) else None


PUBLIC = Availability.PUBLIC
PRIVATE = Availability.PRIVATE
LICENSED = Availability.LICENSED
# String literals, like BUILTIN_PROMPTS: the parity gate reads this tuple by AST, and enum references are not literals to it.
AVAILABILITIES = ("public", "private", "licensed")


def availability(model: Optional[str]) -> Availability:
    """Unset reads as public; an unrecognised value fails closed as licensed, never as a softer licence."""
    entry = registered_models().get(canonical_model_id(model) or "") or {}
    value = entry.get("availability")
    if not (isinstance(value, str) and value):
        return Availability.PUBLIC
    try:
        return Availability(value)
    except ValueError:
        return Availability.LICENSED


def is_licensed(model: Optional[str]) -> bool:
    # PRIVATE is not a softer LICENSED: refusing a licensed model early replaces a RepositoryNotFoundError that
    # reads as "not logged in" with the truth, but refusing a private one would stop our own token pulling weights.
    return availability(model) == Availability.LICENSED


def requires_auth(model: Optional[str]) -> bool:
    return availability(model) == Availability.PRIVATE


@dataclass
class PromptSet:

    version: str
    action_prompt: str
    grid_template: str
    video_template: Optional[str]
    text_template: Optional[str]
    grid_by_type: Dict[str, str]
    source: str

    def grid_prompt(self, *, rows: int, cols: int, grid_hint: str = "",
                    puzzle_type: Optional[str] = None) -> str:
        if puzzle_type and puzzle_type in self.grid_by_type:
            return self.grid_by_type[puzzle_type]
        return self.grid_template.format(rows=rows, cols=cols,
                                         total=rows * cols, grid_hint=grid_hint)

    def video_prompt(self, n_keyframes: int) -> str:
        n = int(n_keyframes)
        if n < 1:
            raise ValueError(f"a keyframe request needs at least one frame, got {n_keyframes}")
        if self.video_template is None:
            raise ValueError(
                f"prompt generation {self.version} has no animated-puzzle prompt — "
                f"model was trained before the video family existed. Use a model on "
                f"generation 2 or later for animated captchas."
            )
        listing = ", ".join(f"frame {i}" for i in range(1, n + 1))
        return self.video_template.format(n=n, listing=listing)

    def text_prompt(self) -> str:
        if self.text_template is None:
            raise ValueError(
                f"prompt generation {self.version} has no distorted-text prompt — "
                f"model was trained before the text family existed. Use a model on "
                f"generation 2 or later for BotDetect/MTCaptcha/Yandex text captchas."
            )
        return self.text_template


def builtin(version: str) -> Optional[PromptSet]:
    spec = BUILTIN_PROMPTS.get(str(version))
    if spec is None:
        return None
    return PromptSet(
        version=str(version),
        action_prompt=spec["action_pixel"],
        grid_template=spec["grid"],
        video_template=spec["video"],
        text_template=spec["text"],
        grid_by_type={},
        source=f"built-in v{version}",
    )


def _from_doc(doc: Dict[str, Any], source: str) -> PromptSet:
    version = str(doc.get("prompt_version", LATEST_PROMPT_VERSION))
    base = builtin(version) or builtin(LATEST_PROMPT_VERSION)
    templates = doc.get("templates") or {}
    grid_by_type = {k.split("grid::", 1)[1]: v for k, v in templates.items()
                    if k.startswith("grid::") and isinstance(v, str)}
    return PromptSet(
        version=version,
        action_prompt=templates.get("action_pixel") or base.action_prompt,
        grid_template=templates.get("grid") or base.grid_template,
        video_template=templates.get("video") or base.video_template,
        text_template=templates.get("text") or base.text_template,
        grid_by_type=grid_by_type,
        source=source,
    )


_cache: Dict[str, PromptSet] = {}


def _warn(msg: str) -> None:
    print(f"[captchakraken] {msg}", file=sys.stderr)


def resolve(model: Optional[str]) -> PromptSet:
    """File, then registry, then the Hub: the registry is the only source that works for a private model (the production adapter is gated and 401s)."""
    key = model or ""
    if key in _cache:
        return _cache[key]

    ps: Optional[PromptSet] = None

    explicit = os.getenv(_PROMPTS_FILE_ENV)
    if explicit:
        try:
            with open(explicit, encoding="utf-8") as fh:
                ps = _from_doc(json.load(fh), f"file:{explicit}")
        except Exception as exc:
            _warn(f"could not read {_PROMPTS_FILE_ENV}={explicit}: {exc}; "
                  "falling back to the registry")

    repo_id = canonical_model_id(model)
    if ps is None and repo_id:
        entry = registered_models().get(repo_id) or {}
        version = str(entry.get("prompt_version", "")) or None
        if version:
            ps = builtin(version)
            if ps is None:
                _warn(f"{repo_id} is registered as prompt_version {version}, which this "
                      f"client ships no prompts for — using v{LATEST_PROMPT_VERSION}. "
                      "Upgrade captchakraken.")
            else:
                ps = PromptSet(**{**ps.__dict__, "source": f"registry:{repo_id}"})

    if ps is None and model and "/" in model and os.getenv(_DISABLE_FETCH_ENV, "0") != "1":
        try:
            from huggingface_hub import hf_hub_download

            path = hf_hub_download(repo_id=model, filename="prompts.json")
            with open(path, encoding="utf-8") as fh:
                ps = _from_doc(json.load(fh), f"hub:{model}")
        except Exception:
            ps = None

    if ps is None:
        default_version = str(
            (registered_models().get(latest_model() or "") or {})
            .get("prompt_version", LATEST_PROMPT_VERSION))
        ps = builtin(default_version) or builtin(LATEST_PROMPT_VERSION)
        if model:
            _warn(f"model {model!r} is not in models.json and published no prompts.json; "
                  f"using generation {ps.version}. If it was trained on different prompts, "
                  "its answers will be quietly worse — register it.")

    _cache[key] = ps
    return ps


MIN_PIXELS_ENV = "CAPTCHA_MIN_PIXELS"
MAX_PIXELS_ENV = "CAPTCHA_MAX_PIXELS"


@dataclass(frozen=True)
class PixelBudget:
    minimum: int
    maximum: Optional[int]
    source: str


DEFAULT_PIXEL_BUDGET = PixelBudget(minimum=448 * 448, maximum=None,
                                   source="client-default")


def _env_int(name: str) -> Optional[int]:
    try:
        value = int(os.environ.get(name) or 0)
    except ValueError:
        return None
    return value if value > 0 else None


def pixel_budget(model: Optional[str]) -> PixelBudget:
    # Deliberately no Hub fetch here: a wrong budget degrades quality silently.
    env_min, env_max = _env_int(MIN_PIXELS_ENV), _env_int(MAX_PIXELS_ENV)
    if env_min or env_max:
        return PixelBudget(
            minimum=env_min or DEFAULT_PIXEL_BUDGET.minimum,
            maximum=env_max if env_max else DEFAULT_PIXEL_BUDGET.maximum,
            source="env")

    repo_id = canonical_model_id(model)
    entry = (registered_models().get(repo_id) or {}) if repo_id else {}
    budget = entry.get("pixel_budget") or {}
    if budget:
        return PixelBudget(
            minimum=int(budget.get("min") or DEFAULT_PIXEL_BUDGET.minimum),
            maximum=int(budget["max"]) if budget.get("max") else None,
            source=f"registry:{repo_id}")
    return DEFAULT_PIXEL_BUDGET


EXPERT_ENV = "CAPTCHA_EXPERT"

# String literals: the parity gate reads this tuple by AST. The enum is PromptFamily.
PROMPT_FAMILIES = ("pixel", "grid", "video", "text")


def experts(model: Optional[str]) -> Dict[PromptFamily, str]:
    """Unknown family keys are dropped with a warning, never raised: the day the `text` family reached ckgate without a marker, refusing it cost every distorted-text solve for a day."""
    repo_id = canonical_model_id(model)
    entry = (registered_models().get(repo_id) or {}) if repo_id else {}
    mapping = entry.get("experts")
    if not isinstance(mapping, dict):
        return {}
    out: Dict[PromptFamily, str] = {}
    for family in PromptFamily:
        name = mapping.get(family)
        if isinstance(name, str) and name:
            out[family] = name
    for key in mapping:
        if key not in PROMPT_FAMILIES and not str(key).startswith("_"):
            _warn(f"model {repo_id!r} declares an expert for unknown prompt "
                  f"family {key!r}; have {', '.join(PROMPT_FAMILIES)}. It will "
                  "never be selected.")
    return out


#: Printed once when a hosted request names a model the endpoint no longer routes. The JS port prints the same
#: text (`model-name.ts`, pinned by test_the_legacy_model_warning_is_one_text.py).
LEGACY_MODEL_WARNING = ("The hosted API answers the model name '{model}' with an older model. Remove the model "
                        "pin (CAPTCHA_LORA_NAME or the model option) to use the current one.")


def routed_names() -> set:
    """Every name a current client puts on the wire to the hosted API: each routing alias and its expert arms."""
    out = set()
    for alias in served_aliases():
        if alias.startswith("_"):
            continue
        arms = experts(alias)
        if arms:
            out.add(alias)
            out.update(arms.values())
    return out


def is_legacy_hosted_name(model: Optional[str]) -> bool:
    """A name the hosted API serves with an older model: neither a routing alias nor one of its arms."""
    return bool(model) and model not in routed_names()


def route(model: Optional[str], family: Optional[PromptFamily], *,
          pin: Optional[str] = None) -> str:
    """An unknown pin raises (a benchmark that silently measured the generalist is a number nobody can catch); an unknown family degrades to the generalist."""
    if pin is not None:
        pin = pin.strip()
    if pin:
        if pin not in PROMPT_FAMILIES:
            raise ValueError(
                f"unknown expert {pin!r}; have {', '.join(PROMPT_FAMILIES)}")
        family = PromptFamily(pin)
    mapping = experts(model)
    if not mapping:
        if pin:
            raise ValueError(
                f"expert {pin!r} was requested but model {model!r} declares no "
                "experts — it serves one adapter under one name. Drop the "
                "expert, or point the client at a routed model.")
        return model or ""
    return mapping.get(family or "") or model or ""


def _env_str(name: str) -> Optional[str]:
    # The indirection matters: test_public_contract greps environ reads by name, and reading EXPERT_ENV inline would record the constant as a variable.
    return (os.environ.get(name) or "").strip() or None


def expert_pin() -> Optional[PromptFamily]:
    raw = _env_str(EXPERT_ENV)
    return PromptFamily(raw) if raw else None


def clear_cache() -> None:
    _cache.clear()
    global _REGISTRY
    _REGISTRY = None
