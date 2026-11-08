"""`captchakraken demo`: solve the vendors' own public demo pages through whatever this install points at.

The browser lives in its own small environment under the state directory, so it can never disturb the
versions the serving stack pins, and the first run needs no setup from anyone.
"""

import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Sequence

from . import __version__, config, server_manager

CAMOUFOX = "camoufox==0.5.9"


@dataclass(frozen=True)
class Site:
    id: str
    vendor: str
    what: str
    url: str
    settle_ms: int = 2500
    open: Sequence[str] = ()
    ready: Sequence[str] = ()


_GEETEST_OPEN = (".geetest_btn", ".geetest_btn_click", ".geetest_radar_btn", ".geetest_holder")
_GEETEST_READY = (".geetest_popup_box", ".geetest_popup_window", ".geetest_box", ".geetest_panel")

SITES = (
    Site("recaptcha", "reCAPTCHA", "tile grid, dealt until satisfied", "https://www.google.com/recaptcha/api2/demo",
         3000),
    Site("geetest-slide", "GeeTest v4", "slide a piece into its notch",
         "https://gt4.geetest.com/demov4/slide-popup-en.html", 2200, _GEETEST_OPEN, _GEETEST_READY),
    Site("geetest-icon", "GeeTest v4", "click named icons in order",
         "https://gt4.geetest.com/demov4/icon-popup-en.html", 2200, _GEETEST_OPEN, _GEETEST_READY),
)


def _env_dir() -> Path:
    return config.state_dir() / "demo"


def _python() -> Path:
    return _env_dir() / "bin" / "python"


def _ready(python: Path) -> bool:
    check = ("import captchakraken, camoufox.pkgman as p; "
             f"raise SystemExit(0 if p.installed_verstr() and captchakraken.__version__ == {__version__!r} else 1)")
    return python.exists() and subprocess.run([str(python), "-c", check], capture_output=True).returncode == 0


def prepare() -> None:
    """The environment and the browser, once. Downloads about 700 MB the first time."""
    from . import selfhost

    python = selfhost.make_venv(_env_dir())
    if _ready(python):
        return
    selfhost.install_client(python)
    subprocess.run([str(python), "-m", "pip", "install", "--quiet", CAMOUFOX], check=True)
    subprocess.run([str(python), "-m", "camoufox", "fetch"], check=True)


def _reveal(page, site: Site) -> None:
    for selector in site.open:
        try:
            page.wait_for_selector(selector, state="visible", timeout=8000).click(timeout=4000)
        except Exception:
            continue
        for panel in site.ready:
            try:
                page.wait_for_selector(panel, state="visible", timeout=12_000)
                return
            except Exception:
                continue
        return


def _solve_one(browser, site: Site) -> "tuple[bool, float, str]":
    from .page_solver import PageSolver

    context = browser.new_context(viewport=None)
    began = time.time()
    try:
        page = context.new_page()
        page.goto(site.url, wait_until="domcontentloaded", timeout=60_000)
        page.wait_for_timeout(site.settle_ms)
        _reveal(page, site)
        began = time.time()
        solved = bool(PageSolver().solve(page).is_solved)
        return solved, time.time() - began, "" if solved else "answered, the vendor did not accept"
    except Exception as e:
        return False, time.time() - began, str(e).splitlines()[0][:90]
    finally:
        try:
            context.close()
        except Exception:
            pass


def run(picked: List[str], headed: bool) -> int:
    from camoufox.sync_api import Camoufox

    sites = [s for s in SITES if s.id in picked] if picked else list(SITES)
    if not sites:
        print(f"No such site. Known: {', '.join(s.id for s in SITES)}", file=sys.stderr)
        return 2
    print(f"\n  Endpoint: {config.base_url()}\n  Model:    {config.selfhost().get('title') or config.lora_name()}\n",
          flush=True)
    if config.selfhost_active():
        try:
            server_manager.ensure_server()
        except RuntimeError as e:
            print(f"  {e}", file=sys.stderr)
            return 1
    solved = 0
    with Camoufox(headless=not headed, humanize=False, geoip=False, i_know_what_im_doing=True) as browser:
        for site in sites:
            print(f"  {site.vendor}: {site.what}\n    {site.url}", flush=True)
            ok, seconds, note = _solve_one(browser, site)
            solved += ok
            print(f"  \033[32m✓ solved\033[0m in {seconds:.1f}s\n" if ok
                  else f"  \033[31m✗ {note}\033[0m after {seconds:.1f}s\n", flush=True)
    print(f"  {solved}/{len(sites)} solved. Vendors grade each attempt, so an occasional miss is normal.\n")
    return 0 if solved else 1


def main(argv: Optional[List[str]] = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    headed = "--headed" in args
    picked = [a for a in args if not a.startswith("-")]
    if "--list" in args:
        for s in SITES:
            print(f"  {s.id:15} {s.vendor:11} {s.url}")
        return 0
    if Path(sys.prefix).resolve() != _env_dir().resolve():
        prepare()
        return subprocess.run([str(_python()), "-m", "captchakraken.demo", *args]).returncode
    return run(picked, headed)


if __name__ == "__main__":
    sys.exit(main())
