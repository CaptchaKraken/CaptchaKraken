"""The published surface: what a caller constructs, configures, receives or implements. Everything else is internal
and can change in any release; add a name here only when a caller needs to write it."""

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
from .errors import CaptchaKrakenAPIError
from .humanize import (
    Humanizer,
    MobileHumanizer,
    MouseHumanizer,
    NullHumanizer,
    TouchBackend,
)
from .kinds import (
    ActionKind,
    ErrorCode,
    HumanizationMode,
    Outcome,
    PauseKind,
    PromptFamily,
    RetryMode,
    Vendor,
    Verdict,
)
from .verdicts import RoundVerdict

try:
    from .solver import CaptchaSolver, solve_captcha

    from .page_solver import CaptchaSolveError, PageSolver, PageSolverConfig, SolveResult, solve_captcha_on_page
    from .selectors import DEFAULT_CONFIG_PATH, SelectorConfigError, VendorSelectors, load_config
    from .watcher import CaptchaWatcher
except ModuleNotFoundError:
    CaptchaSolver = None
    solve_captcha = None
    CaptchaSolveError = None
    PageSolver = None
    PageSolverConfig = None
    SolveResult = None
    solve_captcha_on_page = None
    VendorSelectors = None
    DEFAULT_CONFIG_PATH = None
    SelectorConfigError = None
    load_config = None
    CaptchaWatcher = None

__all__ = [
    # Solving a page
    "PageSolver",
    "PageSolverConfig",
    "SolveResult",
    "CaptchaSolveError",
    "solve_captcha_on_page",
    "CaptchaWatcher",
    # Solving an image
    "CaptchaSolver",
    "solve_captcha",
    "CaptchaAction",
    "ClickAction",
    "DragAction",
    "TypeAction",
    "WaitAction",
    "ActionKind",
    "RetryMode",
    "PromptFamily",
    # Configuration
    "DEFAULT_CONFIG_PATH",
    "SelectorConfigError",
    "VendorSelectors",
    "load_config",
    "Vendor",
    "HumanizationMode",
    # Results and errors
    "RoundVerdict",
    "Outcome",
    "Verdict",
    "ErrorCode",
    "CaptchaKrakenAPIError",
    # Humanizers: the built-in three, and what one of your own implements
    "Humanizer",
    "MouseHumanizer",
    "MobileHumanizer",
    "NullHumanizer",
    "TouchBackend",
    "PauseKind",
]

__version__ = "4.0.0"
