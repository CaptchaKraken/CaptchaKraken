import argparse
import json
import os
import sys
import time
from dataclasses import dataclass, replace

from camoufox.sync_api import Camoufox

from captchakraken.page_solver import CaptchaSolveError, PageSolver


@dataclass
class DemoSpec:
    name: str
    url: str
    vendor: str


def spec_from_argv(default: DemoSpec, argv=None) -> DemoSpec:
    ap = argparse.ArgumentParser(
        description=f"CaptchaKraken demo — {default.name}",
        epilog="With no URL, runs against the built-in demo page.")
    ap.add_argument("url", nargs="?", default=default.url,
                    help=f"page to solve (default: {default.url})")
    ap.add_argument("--vendor", default=default.vendor,
                    help="label recorded in the report; the solver auto-detects")
    ap.add_argument("--name", default=None, help="label for the report")
    ap.add_argument("--headed", action="store_true",
                    help="show the browser (same as HEADLESS=0)")
    args = ap.parse_args(argv)

    if args.headed:
        os.environ["HEADLESS"] = "0"
    name = args.name or (default.name if args.url == default.url else args.url)
    return replace(default, url=args.url, vendor=args.vendor, name=name)


def _launch_kwargs() -> dict:
    kw = dict(headless=os.getenv("HEADLESS", "1") != "0",
              humanize=os.getenv("HUMANIZE", "0") != "0", geoip=False)
    binary = os.getenv("CAMOUFOX_BINARY") or os.getenv("CAMOUFOX_EXECUTABLE_PATH")
    if binary:
        kw["executable_path"] = binary
    return kw


def _page_kwargs() -> dict:
    out = os.getenv("CAPTCHA_DEMO_VIDEO_DIR")
    if not out:
        return {}
    w, _, h = os.getenv("CAPTCHA_DEMO_VIDEO_SIZE", "1280x800").partition("x")
    return {"record_video_dir": out,
            "record_video_size": {"width": int(w), "height": int(h)}}


def _finish_video(page):
    video = getattr(page, "video", None)
    if video is None:
        return None
    try:
        page.context.close()
        return video.path()
    except Exception:
        return None


def _tokens(usage) -> tuple[int, int]:
    inp = out = 0
    for u in usage or []:
        inp += int(u.get("prompt_tokens", u.get("inputTokens", 0)) or 0)
        out += int(u.get("completion_tokens", u.get("outputTokens", 0)) or 0)
    return inp, out


def _explain(solved: bool, err) -> str:
    msg = str(err or "").lower()
    if "unsupported" in msg or "cannot solve" in msg:
        return "Not a supported challenge type — re-run to try again."
    if "no captcha" in msg or "nocaptchafound" in msg:
        return ("No captcha widget was found on that page. Check the URL, or "
                "the widget may load only after an interaction.")
    if "vllm" in msg or "connection" in msg or "refused" in msg or "max retries" in msg:
        return ("Could not reach the vLLM server — is it up and is VLLM_BASE_URL "
                "correct? (A local server auto-starts only with captchakraken[serve].)")
    if "timeout" in msg:
        return "Timed out — the page or challenge never became interactable."
    if err:
        return str(err)
    if not solved:
        return ("The answer was submitted but the vendor did not accept it. Most "
                "often IP reputation or fingerprint flagging rather than a wrong "
                "answer — try a cleaner IP or a residential proxy.")
    return "Unknown failure."


def run_demo(spec: DemoSpec) -> None:
    spec = spec_from_argv(spec)

    t0 = time.time()
    ok = False
    reason = None
    inp = out = 0
    solve_s = 0.0
    video_path = None
    err = None

    try:
        with Camoufox(**_launch_kwargs()) as browser:
            page = browser.new_page(**_page_kwargs())
            try:
                page.goto(spec.url, wait_until="domcontentloaded", timeout=60_000)
                try:
                    page.wait_for_load_state("networkidle", timeout=15_000)
                except Exception:
                    pass
                page.wait_for_timeout(3000)

                s0 = time.time()
                try:
                    result = PageSolver().solve(page)
                finally:
                    solve_s = time.time() - s0
                ok = bool(result.is_solved)
                inp, out = _tokens(result.token_usage)
                if not ok:
                    reason = _explain(ok, None)
            except CaptchaSolveError as e:
                err = e
                reason = _explain(False, e)
            finally:
                video_path = _finish_video(page)
    except Exception as e:
        err = e
        reason = _explain(False, e)

    tps = out / solve_s if out and solve_s > 0 else 0.0
    _report(spec, ok=ok, total_s=time.time() - t0, solve_s=solve_s,
            inp=inp, out=out, tps=tps, reason=reason, video=video_path)


def _fmt(s: float) -> str:
    return f"{s:.1f}s" if s >= 1 else f"{int(s * 1000)}ms"


def _report(spec, *, ok, total_s, solve_s, inp, out, tps, reason, video=None):
    line = "─" * 52
    print(f"\n{line}")
    print(f"  CaptchaKraken demo — {spec.name}")
    print(f"  {spec.url}")
    print(line)
    print(f"  result        : {'✓ SOLVED' if ok else '✗ not solved'}")
    print(f"  total time    : {_fmt(total_s)}   (solve: {_fmt(solve_s)})")
    print(f"  tokens        : {inp} in / {out} out")
    print(f"  gen speed     : {f'~{tps:.1f} tok/s' if tps > 0 else 'n/a'}")
    if video:
        print(f"  video         : {video}")
    if reason:
        print(f"  reason        : {reason}")
    print(f"{line}\n")

    record = os.getenv("CAPTCHA_DEMO_RECORD")
    if record:
        with open(record, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({
                "demo": spec.name, "url": spec.url, "vendor": spec.vendor,
                "ok": ok, "reason": reason,
                "total_s": round(total_s, 1), "solve_s": round(solve_s, 1),
                "input_tokens": inp, "output_tokens": out,
                "tokens_per_sec": round(tps, 1), "video": video,
            }) + "\n")

    sys.exit(0 if ok else 1)
