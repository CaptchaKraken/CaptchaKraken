from __future__ import annotations

import inspect
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
CONTRACT = REPO / "contract.json"
PKG = REPO / "python" / "src" / "captchakraken"

sys.path.insert(0, str(REPO / "python" / "src"))

import captchakraken
from captchakraken import config, errors, humanize, prompts
from captchakraken.page_solver import PageSolverConfig

assert Path(captchakraken.__file__).resolve().is_relative_to(REPO), (
    f"imported captchakraken from {captchakraken.__file__}, which is outside "
    f"{REPO}. This gate would be measuring a different checkout than the one "
    f"being tested. Run it with that tree on the path first — "
    f"`pip install -e python` inside this checkout, or "
    f"PYTHONPATH={REPO / 'python' / 'src'}.")

_ENV_RE = re.compile(
    r"""(?:os\.environ(?:\.get)?\(\s*|os\.getenv\(\s*|process\.env\.|process\.env\[\s*)"""
    r"""["']?([A-Z][A-Z0-9_]{2,})["']?""")
_ENV_CONST_RE = re.compile(
    r"""^\s*(?:export\s+)?(?:const\s+)?_?[A-Z][A-Za-z0-9_]*\s*(?::[^=]+)?=\s*"""
    r"""["']((?:CAPTCHA|VLLM|MIN_PIXELS|MAX_PIXELS)[A-Z0-9_]*)["']""", re.M)

_ENV_ROOTS = ("python/src", "js/src", "js/scripts", "mcp/src")


def _sig(fn) -> str:
    sig = inspect.signature(fn)
    return str(sig.replace(
        return_annotation=inspect.Signature.empty,
        parameters=[p.replace(annotation=inspect.Parameter.empty)
                    for p in sig.parameters.values()]))


def _env_vars() -> dict:
    found: dict[str, list[str]] = {}
    for root in _ENV_ROOTS:
        for path in sorted((REPO / root).rglob("*")):
            if path.suffix not in (".py", ".ts", ".js", ".mjs") or ".test." in path.name:
                continue
            src = path.read_text(errors="ignore")
            rel = path.relative_to(REPO).as_posix()
            for name in _ENV_RE.findall(src) + _ENV_CONST_RE.findall(src):
                if rel not in found.setdefault(name, []):
                    found[name].append(rel)
    return {k: sorted(v) for k, v in sorted(found.items())}


def _cli_subcommands() -> list:
    from captchakraken import cli

    return sorted(cli.COMMANDS)


def _error_codes() -> list:
    from captchakraken.kinds import ErrorCode

    src = (PKG / "errors.py").read_text()
    return sorted(c.value for c in ErrorCode if f"ErrorCode.{c.name}" in src)


def _solve_parser_flags() -> list:
    src = (PKG / "cli.py").read_text()
    tail = src[src.index('parser = argparse.ArgumentParser(description="CaptchaKraken v2'):]
    return sorted(set(re.findall(r'add_argument\(\s*\n?\s*"(--[a-z-]+|[a-z_]+)"', tail)))


def surface() -> dict:
    return {
        "python": {
            "version": captchakraken.__version__,
            "exports": sorted(captchakraken.__all__),
            "signatures": {
                "solve_captcha": _sig(captchakraken.solve_captcha),
                "CaptchaSolver.__init__": _sig(captchakraken.CaptchaSolver.__init__),
                "CaptchaSolver.solve": _sig(captchakraken.CaptchaSolver.solve),
                "CaptchaSolver.solve_keyframes": _sig(captchakraken.CaptchaSolver.solve_keyframes),
                "CaptchaSolver.solve_animated": _sig(captchakraken.CaptchaSolver.solve_animated),
                "PageSolver.__init__": _sig(captchakraken.PageSolver.__init__),
                "PageSolver.solve": _sig(captchakraken.PageSolver.solve),
                "PageSolver.watch": _sig(captchakraken.PageSolver.watch),
                "solve_captcha_on_page": _sig(captchakraken.solve_captcha_on_page),
                "CaptchaKrakenAPIError.__init__": _sig(errors.CaptchaKrakenAPIError.__init__),
                "add_overlays_to_image": _sig(captchakraken.add_overlays_to_image),
                "humanize.resolve": _sig(humanize.resolve),
            },
            "page_solver_config_fields": sorted(PageSolverConfig.__dataclass_fields__),
            "solve_result_fields": sorted(
                captchakraken.SolveResult.__dataclass_fields__),
            "config_functions": sorted(
                n for n, v in vars(config).items()
                if callable(v) and not n.startswith("_")
                and getattr(v, "__module__", "") == "captchakraken.config"),
            "error_codes": _error_codes(),
            "humanization_modes": sorted(humanize.MODES),
        },
        "cli": {
            "entry_point": "captchakraken = captchakraken.cli:main",
            "subcommands": _cli_subcommands(),
            "solve_parser": _solve_parser_flags(),
            "exit_codes": {"ok": 0, "failure": 1, "unsupported": 2, "api_error": 3},
        },
        "env": _env_vars(),
        "model_resolution": {
            "latest": prompts.latest_model(),
            "registered_models": sorted(prompts.registered_models()),
            "latest_prompt_version": prompts.LATEST_PROMPT_VERSION,
            "pinned_fallback_fields": sorted(config.pinned().keys() - {"_comment"}),
        },
    }


STORED = json.loads(CONTRACT.read_text())
LIVE = surface()

_FIX = ("\n\nIf this change is intended, run\n"
        "    python python/tests/test_public_contract.py --write\n"
        "in the same commit, bump the version the change deserves, and say in "
        "the commit message what callers have to do instead. If it is not "
        "intended, put the name back — an alias beside the new one costs "
        "nothing and keeps every published integration working.")


@pytest.mark.parametrize("section", ["python", "cli", "env", "model_resolution"])
def test_the_published_surface_has_not_moved(section):
    assert LIVE[section] == STORED[section], (
        f"the {section!r} half of the public contract changed." + _FIX)


def test_the_version_is_one_number_everywhere():
    pyproject = (REPO / "python" / "pyproject.toml").read_text()
    declared = re.search(r'^version = "([^"]+)"', pyproject, re.M).group(1)
    js = json.loads((REPO / "js" / "package.json").read_text())["version"]
    assert captchakraken.__version__ == declared == js, (
        f"captchakraken.__version__={captchakraken.__version__!r}, "
        f"pyproject={declared!r}, js/package.json={js!r}. The two ports ship "
        f"together (rule 1c) and the runtime attribute is the only one a "
        f"caller can read.")


def test_no_export_is_none_in_a_healthy_install():
    missing = [n for n in captchakraken.__all__ if getattr(captchakraken, n) is None]
    assert not missing, (
        f"{missing} imported as None — the ModuleNotFoundError guard in "
        f"__init__.py fired, so this environment is missing the client's own "
        f"dependencies. `pip install -e python`.")


def test_a_client_with_no_models_json_still_resolves_a_model(monkeypatch):
    monkeypatch.delenv("CAPTCHA_LORA_ADAPTER", raising=False)
    monkeypatch.delenv("CAPTCHA_LORA_NAME", raising=False)
    monkeypatch.delenv("CAPTCHA_LORA_REVISION", raising=False)
    monkeypatch.delenv("CAPTCHA_BASE_MODEL", raising=False)
    monkeypatch.setattr(prompts, "_load_registry", dict)
    prompts.clear_cache()
    config.pinned.cache_clear()
    try:
        assert prompts.registered_models() == {}, "premise: no registry"
        pinned = json.loads((PKG / "pinned_model.json").read_text())
        assert config.lora_adapter() == pinned["lora_adapter"]
        assert config.lora_name() == pinned["lora_name"]
        assert config.base_model() == pinned["base_model"]
        assert config.lora_revision() == pinned["lora_revision"]
        assert prompts.resolve(pinned["lora_adapter"]).version
    finally:
        prompts.clear_cache()
        config.pinned.cache_clear()


def test_an_unregistered_model_name_falls_back_loudly_not_silently(capsys):
    prompts.clear_cache()
    ps = prompts.resolve("candidate-20260805-002154")
    warning = capsys.readouterr().err
    assert "not in models.json" in warning and "register it" in warning, (
        f"resolving an unregistered adapter said nothing. It fell back to a "
        f"prompt generation nobody chose, which is the failure that reported "
        f"reCAPTCHA 3x3 at 0.300 against a pinned 0.953. stderr was: "
        f"{warning!r}")
    assert ps.version == prompts.registered_models()[
        prompts.latest_model()]["prompt_version"]
    prompts.clear_cache()


if __name__ == "__main__":
    if "--write" in sys.argv:
        doc = json.loads(CONTRACT.read_text()) if CONTRACT.exists() else {}
        doc.update(surface())
        CONTRACT.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n")
        print(f"wrote {CONTRACT}")
        subprocess.run(["git", "--no-pager", "diff", "--stat", str(CONTRACT)])
    else:
        print(json.dumps(surface(), indent=2, ensure_ascii=False))
