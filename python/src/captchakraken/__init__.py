from pathlib import Path

try:
    from dotenv import load_dotenv

    project_root = Path(__file__).resolve().parent.parent
    load_dotenv(project_root / ".env")
except Exception:
    pass

from .action_types import (
    CaptchaAction,
    ClickAction,
    DragAction,
    TypeAction,
    WaitAction,
)
from .image_processor import ImageProcessor
from .overlay import add_overlays_to_image

from .errors import CaptchaKrakenAPIError
from .kinds import (
    ActionKind,
    Availability,
    ErrorCode,
    HumanizationMode,
    KeyframeMode,
    Outcome,
    PauseKind,
    PromptFamily,
    RetryMode,
    Vendor,
    Verdict,
)
from .verdicts import RoundVerdict

from .humanize import (
    AppiumTouchBackend,
    CdpTouchBackend,
    Humanizer,
    MobileHumanizer,
    MouseHumanizer,
    NullHumanizer,
    TouchBackend,
    TouchscreenTouchBackend,
)

try:
    from .planner import ActionPlanner
    from .solver import CaptchaSolver, solve_captcha

    from .page_solver import PageSolver, SolveResult, solve_captcha_on_page
    from .selectors import DEFAULT_CONFIG_PATH, SELECTORS, SelectorConfigError, VendorSelectors, load_config
    from .watcher import CaptchaWatcher
except ModuleNotFoundError:
    ActionPlanner = None
    CaptchaSolver = None
    solve_captcha = None
    PageSolver = None
    SELECTORS = None
    VendorSelectors = None
    DEFAULT_CONFIG_PATH = None
    SelectorConfigError = None
    load_config = None
    CaptchaWatcher = None
    SolveResult = None
    solve_captcha_on_page = None

__all__ = [
    "CaptchaSolver",
    "solve_captcha",
    "PageSolver",
    "SELECTORS",
    "VendorSelectors",
    "DEFAULT_CONFIG_PATH",
    "SelectorConfigError",
    "load_config",
    "CaptchaWatcher",
    "SolveResult",
    "solve_captcha_on_page",
    "ActionPlanner",
    "ImageProcessor",
    "CaptchaAction",
    "ClickAction",
    "DragAction",
    "TypeAction",
    "WaitAction",
    "add_overlays_to_image",
    "CaptchaKrakenAPIError",
    "Humanizer",
    "MouseHumanizer",
    "MobileHumanizer",
    "NullHumanizer",
    "TouchBackend",
    "CdpTouchBackend",
    "AppiumTouchBackend",
    "TouchscreenTouchBackend",
    "ActionKind",
    "Availability",
    "ErrorCode",
    "HumanizationMode",
    "KeyframeMode",
    "Outcome",
    "PauseKind",
    "PromptFamily",
    "RetryMode",
    "RoundVerdict",
    "Vendor",
    "Verdict",
]

__version__ = "3.3.0"
