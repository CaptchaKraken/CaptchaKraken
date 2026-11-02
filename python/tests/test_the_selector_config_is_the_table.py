"""Every URL pattern and selector the solver uses comes from `captchakraken.config.json` at the repository root, and a
file of the caller's own is laid over it. Mirrors js/src/the-selector-config-is-the-table.test.ts: both ports are held
to the same file, so they read it identically.
"""

from __future__ import annotations

import json
from dataclasses import fields
from pathlib import Path

import pytest

from captchakraken import selectors as S
from captchakraken.kinds import FrameRole, RecaptchaBanner, Vendor
from captchakraken.page_solver import PageSolver, PageSolverConfig
from captchakraken.selectors import (DEFAULT_CONFIG_PATH, DEFAULT_TABLE, SELECTORS, SelectorConfigError, SelectorTable,
                                     load_config, submit_by_text)
from fake_dom import FakeNode, fake_scope

ROOT = Path(__file__).resolve().parents[2]
ROOT_CONFIG = ROOT / "captchakraken.config.json"
SHIPPED = ROOT / "python" / "src" / "captchakraken" / "captchakraken.config.json"
RAW = json.loads(ROOT_CONFIG.read_text())


def _expected(raw: dict) -> dict:
    """One vendor's entry as the file spells it, with every field the file leaves out at its empty default."""
    out = {}
    for f in fields(S.VendorSelectors):
        v = raw.get(f.name)
        if f.name == "banners":
            out[f.name] = tuple((a, RecaptchaBanner(b)) for a, b in (v or ()))
        elif f.name == "hold_completes":
            out[f.name] = bool(v)
        elif f.name in ("response", "checked", "accepted", "fresh"):
            out[f.name] = v
        else:
            out[f.name] = tuple(v or ())
    return out


def test_a_checkout_reads_the_file_at_the_repository_root():
    assert DEFAULT_CONFIG_PATH == ROOT_CONFIG


def test_the_package_ships_the_root_file_unchanged():
    """A wheel has no repository root, so the package carries a copy; it must be the file, not a fork of it."""
    assert SHIPPED.read_bytes() == ROOT_CONFIG.read_bytes(), (
        "python/src/captchakraken/captchakraken.config.json differs from the root captchakraken.config.json. "
        "Edit the root file, then: cp captchakraken.config.json python/src/captchakraken/")


def test_every_vendor_is_the_files_entry_in_the_files_order():
    assert [v.value for v in SELECTORS] == [k for k in RAW["vendors"] if not k.startswith("_")]
    for vendor, entry in SELECTORS.items():
        got = {f.name: getattr(entry, f.name) for f in fields(entry)}
        assert got == _expected(RAW["vendors"][vendor.value]), f"vendors.{vendor.value} is not what the file says"


def test_the_generic_fallbacks_come_last_in_the_files_order():
    g = RAW["generic"]
    assert DEFAULT_TABLE.text_input[-len(g["text_input"]):] == tuple(g["text_input"])
    assert DEFAULT_TABLE.slider_handle[-len(g["slider_handle"]):] == tuple(g["slider_handle"])
    assert DEFAULT_TABLE.piece[-len(g["piece"]):] == tuple(g["piece"])
    assert DEFAULT_TABLE.submit[:len(g["submit_text"])] == tuple(map(submit_by_text, g["submit_text"]))


def test_the_default_config_has_no_entry_of_its_own():
    assert RAW["custom"] is None and load_config().custom is None


# ── a config of the caller's own ─────────────────────────────────────────

SIGNUP = {"widget": ["#signup-captcha"], "text_input": ["#signup-code"], "submit": ["#signup-check"]}


def _solver(selectors) -> PageSolver:
    return PageSolver(config=PageSolverConfig(selectors=selectors), solver=object())


def test_a_file_with_only_your_entry_finds_your_captcha_first(tmp_path):
    """Your entry is searched before every built-in vendor, reported as unknown, and every built-in vendor stays."""
    mine = tmp_path / "mine.json"
    mine.write_text(json.dumps({"custom": SIGNUP}))
    s = _solver(str(mine))
    both = fake_scope([FakeNode(["#signup-captcha", ".geetest_box"])])
    widget = s.detect_captcha(both)
    assert widget is not None and (widget.vendor, widget.role) == (Vendor.UNKNOWN, FrameRole.UNKNOWN)
    assert s._sel.text_input[0] == "#signup-code"
    assert len(s._sel.vendors) == len(SELECTORS), "a built-in vendor was dropped"
    assert _solver(DEFAULT_CONFIG_PATH).detect_captcha(fake_scope([FakeNode(["#signup-captcha"])])) is None


def test_a_parsed_object_works_like_a_file():
    assert _solver({"custom": SIGNUP})._sel.vendors[0][0] == Vendor.UNKNOWN


def test_a_vendor_you_give_replaces_that_vendor_and_keeps_its_place():
    table = SelectorTable(config={"vendors": {"geetest": {"hosts": ["geetest.example"], "widget": [".my-geetest"]}}})
    assert [v for v, _ in table.vendors] == list(SELECTORS)
    assert table.selectors[Vendor.GEETEST].widget == (".my-geetest",)
    assert table.selectors[Vendor.GEETEST].checkbox == (), "the whole entry is replaced, not merged"
    assert table.selectors[Vendor.RECAPTCHA] == SELECTORS[Vendor.RECAPTCHA]


def test_a_generic_list_you_give_replaces_that_list():
    table = SelectorTable(config={"generic": {"submit_text": ["weiter"]}})
    assert table.submit[0] == submit_by_text("weiter") and submit_by_text("verify") not in table.submit
    assert table.text_input == DEFAULT_TABLE.text_input


def test_custom_selectors_still_wins_over_the_files_entry():
    old = S.VendorSelectors(hosts=(), widget=("#old-way",))
    table = SelectorTable(old, config={"custom": SIGNUP})
    assert table.selectors[Vendor.UNKNOWN].widget == ("#old-way",)


# ── a config the solver cannot use ───────────────────────────────────────


@pytest.mark.parametrize("doc,names", [
    ({"vendor": {}}, "vendor: not a config key"),
    ({"vendors": {"geetest": {"hosts": [], "widgets": [".x"]}}}, "vendors.geetest.widgets: not a selector field"),
    ({"vendors": {"mysite": {"hosts": []}}}, "vendors.mysite: not a vendor"),
    ({"vendors": {"geetest": {"widget": [".x"]}}}, "vendors.geetest.hosts: missing"),
    ({"vendors": {"recaptcha": {"hosts": [], "banners": [[".b", "maybe"]]}}}, "vendors.recaptcha.banners[0]: verdict"),
    ({"vendors": {"human": {"hosts": [], "hold_completes": "yes"}}}, "vendors.human.hold_completes: must be true"),
    ({"custom": {"widget": ".one-string"}}, "custom.widget: must be a list of strings"),
    ({"custom": {"text_input": ["#code"]}}, "nothing to detect"),
    ({"generic": {"buttons": []}}, "generic.buttons: not a generic list"),
    ({"detector": "heavy"}, "detector: 'heavy' is not one of auto, standard, lite"),
])
def test_a_bad_key_is_named(doc, names):
    with pytest.raises(SelectorConfigError, match=names.replace("[", r"\[").replace("]", r"\]")):
        SelectorTable(config=doc)


def test_the_detector_is_auto_unless_the_config_names_one():
    assert DEFAULT_TABLE.config.detector == "auto"
    assert SelectorTable(config={"custom": {"widget": ["#c"]}}).config.detector == "auto"
    assert SelectorTable(config={"detector": "lite"}).config.detector == "lite"


def test_the_configs_detector_choices_are_the_detectors_models():
    from captchakraken.pointer import detector
    assert S.DETECTOR_CHOICES == detector.MODELS


def test_a_page_solver_runs_its_configs_detector(monkeypatch):
    from captchakraken.pointer import detector
    monkeypatch.setattr(detector, "_CHOICE", None)
    PageSolver(PageSolverConfig(selectors={"detector": "standard"}), solver=object())
    assert detector._CHOICE == "standard"
    detector.configure(None)


def test_a_file_that_is_not_json_names_the_file(tmp_path):
    bad = tmp_path / "broken.json"
    bad.write_text('{"custom": ')
    with pytest.raises(SelectorConfigError, match="broken.json: cannot be read as JSON"):
        _solver(str(bad))
