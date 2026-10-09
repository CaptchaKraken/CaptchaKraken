"""Every closed set of names the two ports agree on. Mirrored in js/src/kinds.ts; keep both in the same order."""
from enum import StrEnum


class Vendor(StrEnum):
    """`puzzle_source` everywhere. UNKNOWN must stay permissive: GeeTest and Prosopo report it, and so does the offline grader."""

    HCAPTCHA = "hcaptcha"
    RECAPTCHA = "recaptcha"
    TURNSTILE = "turnstile"
    GEETEST = "geetest"
    TENCENT = "tencent"
    YIDUN = "yidun"
    YANDEX = "yandex"
    LEMIN = "lemin"
    PROSOPO = "prosopo"
    MTCAPTCHA = "mtcaptcha"
    BOTDETECT = "botdetect"
    UNKNOWN = "unknown"


class ActionKind(StrEnum):
    CLICK = "click"
    DRAG = "drag"
    TYPE = "type"
    WAIT = "wait"
    DONE = "done"


class PixelAnswerKind(StrEnum):
    """What the pixel parser reads off the model's text before it becomes an action."""

    CLICK = "click"
    DRAG = "drag"
    SLIDE = "slide"
    TYPE = "type"


class RetryMode(StrEnum):
    MISSED_TILES = "missed-tiles"


class SettleVerdict(StrEnum):
    SETTLED = "settled"
    ANIMATED = "animated"
    TIMEOUT = "timeout"


class PaintVerdict(StrEnum):
    PAINTED = "painted"
    BLANK = "blank"
    UNKNOWN = "unknown"


class KeyframeMode(StrEnum):
    """EVEN means the slicer could not prove recurrence, not that the board is still."""

    STATIC = "static"
    CYCLE = "cycle"
    EVEN = "even"


class RecaptchaBanner(StrEnum):
    SELECT_MORE = "select-more"
    DYNAMIC_MORE = "dynamic-more"
    REJECTED = "rejected"


class PromptFamily(StrEnum):
    """One expert per family; `pixel` is spelled to match ckgate's prompt markers."""

    PIXEL = "pixel"
    GRID = "grid"
    VIDEO = "video"
    TEXT = "text"


class Availability(StrEnum):
    """PRIVATE is not a softer LICENSED: refusing a private model early would stop an authorised token from fetching weights."""

    PUBLIC = "public"
    PRIVATE = "private"
    LICENSED = "licensed"


class HumanizationMode(StrEnum):
    MOUSE = "mouse"
    MOBILE = "mobile"
    NONE = "none"


class PauseKind(StrEnum):
    TAP = "tap"
    BETWEEN = "between"
    GRAB = "grab"
    DROP = "drop"
    PROBE = "probe"
    SETTLE = "settle"
    KEY = "key"


class Outcome(StrEnum):
    SOLVED = "solved"
    FAILED = "failed"


class Verdict(StrEnum):
    """What the vendor's own server answered a round: BLOCKED is a refusal to serve at all, not a wrong answer."""

    ACCEPTED = "accepted"
    REJECTED = "rejected"
    NEW_CHALLENGE = "new-challenge"
    BLOCKED = "blocked"


class Phase(StrEnum):
    """Timing phases. Only INFERENCE and MOUSE are productive; everything else is waiting."""

    INFERENCE = "inference"
    MOUSE = "mouse"
    SCREENSHOT = "screenshot"
    DETECT = "detect"
    SETTLE = "settle"
    BURST = "burst"
    GRID = "grid"
    GRID_LOAD = "grid-load"
    FADE_WAIT = "fade-wait"
    BOARD_PAINT = "board-paint"
    HCAPTCHA_IMAGES = "hcaptcha-images"
    AWAIT_NEXT_ROUND = "await-next-round"
    AWAIT_VERDICT = "await-verdict"
    POST_SUBMIT_DELAY = "post-submit-delay"


class FrameRole(StrEnum):
    CHECKBOX = "checkbox"
    CHALLENGE = "challenge"
    UNKNOWN = "unknown"


class LabelPosition(StrEnum):
    TOP_LEFT = "top-left"
    CENTER = "center"
    TOP_RIGHT = "top-right"
    BOTTOM_LEFT = "bottom-left"
    BOTTOM_RIGHT = "bottom-right"


class ErrorCode(StrEnum):
    """The hosted API's machine-readable codes. Unknown codes still carry the server's message through; this is not a filter."""

    MISSING_API_KEY = "missing_api_key"
    INVALID_API_KEY = "invalid_api_key"
    ACCOUNT_SUSPENDED = "account_suspended"
    INSUFFICIENT_CREDITS = "insufficient_credits"
    RATE_LIMITED = "rate_limited"
    SOLVE_ABANDONED = "solve_abandoned"
    UNRECOGNIZED_PROMPT = "unrecognized_prompt"
    INVALID_REQUEST = "invalid_request"
    REQUEST_TOO_LARGE = "request_too_large"
    UPSTREAM_UNAVAILABLE = "upstream_unavailable"
