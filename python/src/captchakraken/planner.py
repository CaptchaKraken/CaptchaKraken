import base64
import io
import json
import math
import os
import re
import sys
from mimetypes import guess_type
from typing import Any, Dict, List, Optional

import requests
from PIL import Image

from . import config, errors, prompts
from .kinds import ActionKind, PixelAnswerKind, PromptFamily, RetryMode
from .server_manager import ensure_server

DEBUG = os.getenv("CAPTCHA_DEBUG", "0") == "1"

# A floor, not a resize, and the AREA is clamped rather than the sides: predictions on a 277x285 GeeTest
# board landed 80-105px from the hand label at native size and 1-4px once upscaled, and squashing the
# aspect moves every tile centre.
MIN_PIXELS = 448 * 448


def _encode_image(path: str,
                  budget: "Optional[prompts.PixelBudget]" = None) -> tuple:
    budget = budget or prompts.pixel_budget(None)
    with open(path, "rb") as f:
        raw = f.read()
    mime = guess_type(path)[0] or "image/png"
    try:
        im = Image.open(io.BytesIO(raw))
        width, height = im.size
    except Exception:
        return mime, base64.b64encode(raw).decode()
    cap = budget.maximum
    if cap and width * height > cap:
        scale = math.sqrt(cap / (width * height))
        im = im.convert("RGB").resize(
            (max(1, int(width * scale)), max(1, int(height * scale))),
            Image.BICUBIC)
        buf = io.BytesIO()
        im.save(buf, "PNG")
        return "image/png", base64.b64encode(buf.getvalue()).decode()
    if width * height >= budget.minimum:
        return mime, base64.b64encode(raw).decode()
    scale = math.sqrt(budget.minimum / (width * height))
    im = im.convert("RGB").resize(
        (math.ceil(width * scale), math.ceil(height * scale)), Image.BICUBIC)
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return "image/png", base64.b64encode(buf.getvalue()).decode()

# A header, deliberately not vLLM's body `priority`: that field is lower-is-higher and already means
# captcha=0 / apply=100 / label=200 on the primary, so a 10 there would misorder. The gateway routes >5 to
# the backup GPUs; tier-2 CI sets it.
_PRIORITY_HEADER = "X-JH-Priority"
_PRIORITY_ENV = "CAPTCHA_REQUEST_PRIORITY"

_CLIENT_HEADER = "X-CK-Client"
_CLIENT_ENV = "CAPTCHA_KRAKEN_CLIENT"
# One id per solve lets the gateway cap an attempt's billable rounds.
_SESSION_HEADER = "X-CK-Session"
_SESSION_ENV = "CAPTCHA_KRAKEN_SESSION"
# Which vendor and which site a hosted solve was for, so the outcome ledger can say where solves fail. The site is
# a hostname only: a path or query can carry a user's own data.
_VENDOR_HEADER = "X-CK-Vendor"
_VENDOR_ENV = "CAPTCHA_KRAKEN_VENDOR"
_SITE_HEADER = "X-CK-Site"
_SITE_ENV = "CAPTCHA_KRAKEN_SITE"

# On by default; `captureOptOut` is the server half. Tier 3 sets it to 0 for ~100 solves a run.
_REPORT_OUTCOME_ENV = "CAPTCHA_REPORT_OUTCOME"

# Extra headers may not rewrite these: pinning one X-CK-Session forever would escape the per-attempt billing cap.
_EXTRA_HEADERS_ENV = "CAPTCHA_KRAKEN_EXTRA_HEADERS"
_PROTECTED_HEADERS = frozenset(
    h.lower() for h in ("authorization", "content-type", _CLIENT_HEADER, _SESSION_HEADER, _VENDOR_HEADER, _SITE_HEADER)
)

_HEADER_VALUE_MAX = 128


def _warn(message: str) -> None:
    print(f"[captchakraken] warning: {message}", file=sys.stderr, flush=True)


_VALID_HEADER_NAME = re.compile(r"^[!#$%&'*+\-.^_`|~0-9A-Za-z]+$")


def _clean_header_value(raw: str) -> str:
    # CR/LF would splice arbitrary headers into the request.
    return "".join(c for c in raw.strip() if 0x20 <= ord(c) < 0x7F)[:_HEADER_VALUE_MAX]


def _extra_headers(raw: str) -> Dict[str, str]:
    out: Dict[str, str] = {}
    if not raw.strip():
        return out

    for entry in raw.replace(",", "\n").splitlines():
        entry = entry.strip()
        if not entry or ":" not in entry:
            continue
        name, _, value = entry.partition(":")
        name = name.strip()
        value = _clean_header_value(value)
        if not name or not value:
            continue
        if not _VALID_HEADER_NAME.match(name):
            continue
        if name.lower() in _PROTECTED_HEADERS:
            continue
        out[name] = value
    return out


def routing_headers(env=None, hosted: bool = False) -> Dict[str, str]:
    """Each header is derived on its own: a malformed priority must not drop the attribution headers and understate a partner's revenue share.

    Vendor and site go to the hosted API only; a self-hosted endpoint has no ledger to read them.
    """
    env = os.environ if env is None else env
    headers: Dict[str, str] = {}

    raw = (env.get(_PRIORITY_ENV) or "").strip()
    if raw:
        try:
            headers[_PRIORITY_HEADER] = str(int(raw))
        except ValueError:
            pass

    attribution = ((_CLIENT_HEADER, _CLIENT_ENV), (_SESSION_HEADER, _SESSION_ENV))
    if hosted:
        attribution += ((_VENDOR_HEADER, _VENDOR_ENV), (_SITE_HEADER, _SITE_ENV))
    for header, var in attribution:
        value = _clean_header_value(env.get(var) or "")
        if value:
            headers[header] = value

    headers.update(_extra_headers(env.get(_EXTRA_HEADERS_ENV) or ""))

    return headers


_LATEST = prompts.builtin(prompts.LATEST_PROMPT_VERSION)

SELECT_GRID_PROMPT = _LATEST.grid_template


PIXEL_ACTION_PROMPT = _LATEST.action_prompt




# Greedy only, by measurement: (0.0, 0.35, 0.7) scored 0/5 against 4/5 and made the median failed attempt
# 24.0s against 13.9s, because a differing re-ask resets the no-progress counter. The level plumbing stays for
# a network-refusal trigger. Lives here once so the two ports cannot drift (TRIBAL_KNOWLEDGE.md).
RESAMPLE_TEMPERATURES = (0.0,)


def sampling_for_level(level: int) -> Dict[str, Any]:
    temps = RESAMPLE_TEMPERATURES or (0.0,)
    temp = temps[min(max(level, 0), len(temps) - 1)]
    if not temp:
        return {}
    return {"temperature": temp, "seed": 1000 + level}


def _sampling_from_env() -> Dict[str, Any]:
    raw = os.environ.get("CAPTCHA_RESAMPLE_LEVEL", "").strip()
    if not raw:
        return {}
    try:
        return sampling_for_level(int(raw))
    except ValueError:
        return {}


#: The ceiling on one ask, and the old hardcoded value. Measured why it matters: against the hosted
#: endpoint a single request hung and returned "the write operation timed out" after ~124s, inside a
#: solve whose whole budget was 45s + 29s of recording — the attempt ran 143s. A timeout longer than
#: the budget it sits inside cannot protect it, so callers with a deadline pass their own.
DEFAULT_REQUEST_TIMEOUT_S: float = 120.0
#: Never ask for less than this: a keyframe ask carries six images and a short timeout would turn a
#: busy endpoint into a guaranteed failure rather than a slow success.
MIN_REQUEST_TIMEOUT_S: float = 10.0


class ActionPlanner:

    def __init__(
        self,
        model: Optional[str] = None,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        expert: Optional[PromptFamily] = None,
        **_: Any,
    ):
        self.token_usage: List[Dict[str, Any]] = []

        self.model = model or config.lora_name()
        self.base_url = base_url or config.base_url()
        self.api_key = api_key or config.api_key()
        self.sampling: Dict[str, Any] = {}
        #: Seconds a single ask may take. The CALLER owns this: a solve has a budget, and a request
        #: that outlives it cannot be cancelled once it is in flight — the deadline is only read
        #: between steps. Left alone it is the old ceiling; `PageSolver` lowers it to what remains.
        self.request_timeout_s: float = DEFAULT_REQUEST_TIMEOUT_S
        _prompt_key = (self.model if prompts.canonical_model_id(self.model)
                       else config.lora_adapter())
        self.prompts = prompts.resolve(_prompt_key)
        self.pixel_budget = prompts.pixel_budget(_prompt_key)
        self.expert = (expert if expert is not None
                       else prompts.expert_pin())
        self.experts = prompts.experts(_prompt_key)
        if self.expert:
            prompts.route(_prompt_key, None, pin=self.expert)
        self._server_ensured = False
        self._http = requests.Session()
        self.outcome_supported = True

    def _model_for(self, family: Optional[PromptFamily]) -> str:
        if not self.experts:
            return self.model
        return prompts.route(self.model, family, pin=self.expert) or self.model

    _OUTCOME_PATH = "/solve-outcome"
    _OUTCOME_TIMEOUT_S = 3.0

    def report_outcome(self, session_id: Optional[str], solved: bool) -> bool:
        """A 404 from a self-hosted endpoint disables it for the planner's lifetime, since vLLM has no /solve-outcome.
        From the hosted API every failure is a fault and is warned about every time, never silently switched off."""
        if not session_id or not self.outcome_supported:
            return False
        if os.getenv(_REPORT_OUTCOME_ENV, "1") == "0":
            return False
        hosted = config.is_hosted_endpoint(self.base_url)
        url = f"{self.base_url}{self._OUTCOME_PATH}"
        try:
            resp = self._http.post(
                url,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                    **routing_headers(hosted=hosted),
                },
                json={"session": session_id, "solved": bool(solved)},
                timeout=self._OUTCOME_TIMEOUT_S,
            )
        except Exception as exc:
            (_warn if hosted else self._log)(f"outcome report failed: {exc}")
            return False
        if resp.status_code == 404 and not hosted:
            self.outcome_supported = False
            self._log("outcome reporting: endpoint has no /solve-outcome; disabled")
            return False
        ok = 200 <= resp.status_code < 300
        if not ok and hosted:
            _warn(f"outcome report for session {session_id} was refused: HTTP {resp.status_code} from {url}")
        self._log(f"outcome report {session_id} solved={solved} -> {resp.status_code}")
        return ok

    def _log(self, message: str) -> None:
        if DEBUG:
            print(f"[Planner] {message}", file=sys.stderr)

    def _chat_with_image(self, prompt: str, image_path: str, max_tokens: int = 512,
                         family: Optional[PromptFamily] = None) -> str:
        return self._chat_with_images(prompt, [image_path], max_tokens=max_tokens,
                                      family=family)

    def _chat_with_images(
        self, prompt: str, image_paths: List[str], max_tokens: int = 512,
        family: Optional[PromptFamily] = None,
    ) -> str:
        """One request per image set, images before the text in one message: the model reads frames positionally, and per-frame queries would cost N billable rounds."""
        if not image_paths:
            raise ValueError("no images to send")

        parts: List[Dict[str, Any]] = []
        for p in image_paths:
            mime, b64 = _encode_image(p, self.pixel_budget)
            parts.append({"type": "image_url",
                          "image_url": {"url": f"data:{mime};base64,{b64}"}})

        messages = [
            {
                "role": "system",
                "content": "You are an expert captcha solver. Respond ONLY with the JSON action.",
            },
            {
                "role": "user",
                "content": [*parts, {"type": "text", "text": prompt}],
            },
        ]

        model = self._model_for(family)
        payload = {
            "model": model,
            "messages": messages,
            "temperature": 0,
            "max_tokens": max_tokens,
            # Both spellings: Ollama ignores chat_template_kwargs and defaults thinking on; vLLM reads reasoning_effort only when the kwargs are unset.
            "chat_template_kwargs": {"enable_thinking": False},
            "reasoning_effort": "none",
        }
        sampling = self.sampling or _sampling_from_env()
        if sampling:
            payload.update(sampling)

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            **routing_headers(hosted=config.is_hosted_endpoint(self.base_url)),
        }

        if not self._server_ensured:
            try:
                ensure_server(self.base_url)
            except Exception as e:
                self._log(f"ensure_server: {e}")
            self._server_ensured = True

        url = f"{self.base_url}/chat/completions"
        self._log(f"POST {url} model={model} max_tokens={max_tokens} "
                  f"images={len(parts)}")

        resp = self._http.post(url, headers=headers, json=payload,
                               timeout=self.request_timeout_s or DEFAULT_REQUEST_TIMEOUT_S)

        if not resp.ok:
            raise errors.from_response(resp, url)

        try:
            data = resp.json()
        except ValueError:
            body = (resp.text or "")[:300]
            raise RuntimeError(
                f"vLLM returned a non-JSON body from {url} (is the server up and "
                f"is VLLM_BASE_URL correct?). Body: {body}"
            )

        if data.get("usage"):
            self.token_usage.append(data["usage"])

        content = data["choices"][0]["message"].get("content") or ""
        self._log(f"Raw content: {content[:300]}")
        return content

    @staticmethod
    def _parse_json(text: str) -> Any:
        text = (text or "").strip()
        if "```json" in text:
            text = text.split("```json", 1)[1].split("```", 1)[0]
        elif "```" in text:
            text = text.split("```", 1)[1].split("```", 1)[0]

        start_obj = text.find("{")
        start_list = text.find("[")
        if start_list != -1 and (start_obj == -1 or start_list < start_obj):
            start = start_list
            end = text.rfind("]") + 1
        elif start_obj != -1:
            start = start_obj
            end = text.rfind("}") + 1
        else:
            return None

        try:
            return json.loads(text[start:end], strict=False)
        except json.JSONDecodeError:
            repaired = ActionPlanner._balance_json(text[start:])
            if repaired is not None:
                try:
                    return json.loads(repaired, strict=False)
                except json.JSONDecodeError:
                    return None
            return None

    @staticmethod
    def _balance_json(text: str) -> Optional[str]:
        stack: List[str] = []
        in_str = False
        esc = False
        for ch in text:
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch in "{[":
                stack.append(ch)
            elif ch == "}":
                if stack and stack[-1] == "{":
                    stack.pop()
            elif ch == "]":
                if stack and stack[-1] == "[":
                    stack.pop()
        if not stack and not in_str:
            return None
        out = text
        if in_str:
            out += '"'
        out = out.rstrip().rstrip(",")
        for opener in reversed(stack):
            out += "}" if opener == "{" else "]"
        return out

    def get_grid_selection(
        self,
        image_path: str,
        rows: int,
        cols: int,
        retry_mode: Optional[RetryMode] = None,
    ) -> List[int]:
        total = rows * cols
        if rows == 4 and cols == 4:
            grid_hint = "Hint: Single large image split into tiles. Select ALL parts."
        else:
            grid_hint = "Hint: Separate images. Select only clear matches."

        prompt = self.prompts.grid_prompt(
            rows=rows, cols=cols, grid_hint=grid_hint
        )
        if retry_mode == RetryMode.MISSED_TILES:
            prompt = (
                prompt
                + "\n\nIMPORTANT: A previous submission was rejected because not all "
                  "matching tiles were selected. Re-examine EVERY cell in the grid "
                  "carefully. There is at least one more matching tile you missed. "
                  "Return the complete list of cell numbers that match the description, "
                  "including any matches you may have overlooked."
            )
        raw = self._chat_with_image(prompt, image_path, max_tokens=128,
                                    family=PromptFamily.GRID)
        out = self._normalize_grid(self._parse_json(raw), total)
        self._log(f"grid selection -> {out}")
        return out

    @staticmethod
    def _normalize_grid(data: Any, total: int) -> List[int]:
        if isinstance(data, list):
            ids = data
        elif isinstance(data, dict):
            nested = data.get("action")
            nested_ids = nested.get("target_ids") if isinstance(nested, dict) else None
            ids = data.get("target_ids") or nested_ids or []
        else:
            ids = []

        out: List[int] = []
        for v in ids:
            try:
                iv = int(v)
            except (TypeError, ValueError):
                continue
            if 1 <= iv <= total:
                out.append(iv)
        return out

    def get_pixel_actions(self, image_path: str, text_mode: bool = False) -> List[Dict[str, Any]]:
        prompt = self.prompts.text_prompt() if text_mode else self.prompts.action_prompt
        raw = self._chat_with_image(prompt, image_path, max_tokens=512,
                                    family=PromptFamily.TEXT if text_mode else PromptFamily.PIXEL)
        data = self._parse_json(raw)
        actions = self._normalize_pixel(data)
        self._log(f"pixel actions -> {actions}")
        return actions

    def get_keyframe_actions(self, keyframe_paths: List[str]) -> List[Dict[str, Any]]:
        if not keyframe_paths:
            return []
        prompt = self.prompts.video_prompt(len(keyframe_paths))
        raw = self._chat_with_images(prompt, list(keyframe_paths), max_tokens=512,
                                     family=PromptFamily.VIDEO)
        data = self._parse_json(raw)
        actions = self._normalize_pixel(data)
        frame = self._normalize_frame(data, len(keyframe_paths))
        for a in actions:
            a["frame"] = frame
        self._log(f"keyframe actions (frame={frame}) -> {actions}")
        return actions

    @staticmethod
    def _normalize_frame(data: Any, n_keyframes: int) -> Optional[int]:
        """Out of range is None, not clamped: clamping a 7 to 6 would invent an intent."""
        if not isinstance(data, dict):
            return None
        raw = data.get("frame")
        if raw is None and isinstance(data.get("action"), dict):
            raw = data["action"].get("frame")
        try:
            n = int(raw)
        except (TypeError, ValueError):
            return None
        return n if 1 <= n <= n_keyframes else None

    @staticmethod
    def _normalize_pixel(data: Any) -> List[Dict[str, Any]]:
        """Every answer shape the model has been seen to produce, oldest last; `kind` is a PixelAnswerKind."""
        def norm_xy(x: Any, y: Any) -> Optional[tuple]:
            try:
                fx, fy = float(x) / 1000.0, float(y) / 1000.0
            except (TypeError, ValueError):
                return None
            if not (0.0 <= fx <= 1.0 and 0.0 <= fy <= 1.0):
                if 0.0 <= float(x) <= 1.0 and 0.0 <= float(y) <= 1.0:
                    fx, fy = float(x), float(y)
                else:
                    fx, fy = min(max(fx, 0.0), 1.0), min(max(fy, 0.0), 1.0)
            return (fx, fy)

        def flat_numbers(v: Any) -> List[float]:
            nums: List[float] = []
            if isinstance(v, bool):
                return nums
            if isinstance(v, (list, tuple)):
                for e in v:
                    nums.extend(flat_numbers(e))
            elif isinstance(v, dict):
                for k in ("x", "y", "X", "Y"):
                    if k in v:
                        nums.extend(flat_numbers(v[k]))
            elif isinstance(v, (int, float)):
                nums.append(float(v))
            elif isinstance(v, str):
                nums.extend(float(m) for m in re.findall(r"-?\d+(?:\.\d+)?", v))
            return nums

        def coordish(v: Any) -> bool:
            if not isinstance(v, (list, tuple)) or not v:
                return False
            for e in v:
                if isinstance(e, bool):
                    return False
                if isinstance(e, (int, float, list, tuple, dict)):
                    continue
                if isinstance(e, str) and re.search(r"\d", e):
                    continue
                return False
            return True

        out: List[Dict[str, Any]] = []
        if not isinstance(data, dict):
            return out

        act = data.get("action")
        if isinstance(act, dict) and act.get("action") == ActionKind.TYPE:
            act = act.get("action")
        if act == ActionKind.TYPE or (isinstance(data.get("text"), str) and "drags" not in data):
            container = data if isinstance(data.get("text"), str) else data.get("action")
            text = container.get("text") if isinstance(container, dict) else None
            if isinstance(text, str) and text:
                return [{"kind": PixelAnswerKind.TYPE, "text": text}]

        content_drags = data.get("drags")
        if content_drags is None and isinstance(data.get("action"), dict):
            content_drags = data["action"].get("drags")
        if isinstance(content_drags, dict):
            content_drags = [content_drags]
        if isinstance(content_drags, list) and content_drags:
            for d in content_drags:
                if not isinstance(d, dict):
                    continue
                snums = flat_numbers(d.get("from"))
                dnums = flat_numbers(d.get("to"))
                if len(dnums) < 2:
                    continue
                dst = norm_xy(dnums[0], dnums[1])
                if not dst:
                    continue
                if len(snums) >= 2:
                    src = norm_xy(snums[0], snums[1])
                    if src:
                        out.append({"kind": PixelAnswerKind.DRAG, "src": src, "dst": dst})
                else:
                    out.append({"kind": PixelAnswerKind.SLIDE, "dst": dst})
            if out:
                return out

        drags = data.get("output")
        if isinstance(drags, list) and drags:
            for d in drags:
                if not isinstance(d, dict):
                    continue
                sp = d.get("SourcePosition") or {}
                ep = d.get("EstimatedPosition") or d.get("DestinationPosition") or {}
                src = norm_xy(sp.get("x"), sp.get("y")) if isinstance(sp, dict) else None
                dst = norm_xy(ep.get("x"), ep.get("y")) if isinstance(ep, dict) else None
                if src and dst:
                    out.append({"kind": PixelAnswerKind.DRAG, "src": src, "dst": dst})
            if out:
                return out

        sd = data.get("simulate_drag")
        if sd is None and isinstance(action := data.get("action"), dict):
            sd = action.get("simulate_drag")
        if isinstance(sd, dict):
            sd = [sd]
        if isinstance(sd, list) and sd:
            def _drag_coords(obj: Any, *roles: str) -> List[float]:
                if not isinstance(obj, dict):
                    return []
                for k, v in obj.items():
                    kn = str(k).lower().replace("_", "").replace("-", "")
                    if "pos" not in kn:
                        continue
                    if any(r in kn for r in roles):
                        nums = flat_numbers(v)
                        if len(nums) >= 2:
                            return nums
                return []
            for d in sd:
                if not isinstance(d, dict):
                    continue
                snums = _drag_coords(d, "source", "src")
                dnums = _drag_coords(d, "destination", "dest", "estimated", "target")
                if len(snums) >= 2 and len(dnums) >= 2:
                    src = norm_xy(snums[0], snums[1])
                    dst = norm_xy(dnums[0], dnums[1])
                    if src and dst:
                        out.append({"kind": PixelAnswerKind.DRAG, "src": src, "dst": dst})
            if out:
                return out

        action = data.get("action")
        for _ in range(4):
            if (
                isinstance(action, dict)
                and action.get("points") is None
                and action.get("source") is None
                and isinstance(action.get("action"), dict)
            ):
                action = action["action"]
            else:
                break
        points = None
        if isinstance(action, dict):
            points = action.get("points")
            if points is None and action.get("action") == ActionKind.DRAG:
                src = norm_xy(*(action.get("source") or (None, None)))
                dst = norm_xy(*(action.get("target") or (None, None)))
                if src and dst:
                    return [{"kind": PixelAnswerKind.DRAG, "src": src, "dst": dst}]
        if points is None:
            points = data.get("points")
        if not (isinstance(points, list) and points):
            for container in (action if isinstance(action, dict) else None, data):
                if not isinstance(container, dict):
                    continue
                cand = container.get("click")
                if cand is None:
                    cand = container.get("coordinates")
                if coordish(cand):
                    nums = flat_numbers(cand)
                    if len(nums) >= 2:
                        points = [
                            [nums[i], nums[i + 1]] for i in range(0, len(nums) - 1, 2)
                        ]
                        break
        if isinstance(points, list) and points:
            pts = []
            for p in points:
                if isinstance(p, (list, tuple)) and len(p) >= 2:
                    xy = norm_xy(p[0], p[1])
                elif isinstance(p, dict):
                    xy = norm_xy(p.get("x"), p.get("y"))
                else:
                    xy = None
                if xy:
                    pts.append(xy)
            if pts:
                out.append({"kind": PixelAnswerKind.CLICK, "points": pts})
        return out
