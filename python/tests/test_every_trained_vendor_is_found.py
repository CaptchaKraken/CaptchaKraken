"""Each vendor's widget as its own page ships it, measured on its demo or a live page, is found and named by its own row.
Frames are matched off their real `src`; inline widgets off their real id and class tokens. Mirrors
js/src/every-trained-vendor-is-found.test.ts."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional, Sequence, Tuple

from captchakraken.kinds import FrameRole, Vendor
from captchakraken.page_solver import PageSolver, PageSolverConfig
from captchakraken.selectors import SUBMIT_SELECTORS, WIDGET_PROBES, submit_by_text
from fake_dom import FakeNode, fake_scope


@dataclass(frozen=True)
class Measured:
    tag: str
    id: str = ""
    classes: Sequence[str] = ()
    visible: bool = True


_SRC = re.compile(r'\[src\*="([^"]+)"\]')
_INLINE = re.compile(r'^([a-z]*)((?:\.[\w-]+)*)(?:\[id\^="([^"]+)"\])?$')


def _frame(src: str) -> FakeNode:
    """The host-page iframe probes an element with this `src` answers to, the way a CSS engine reads them."""
    def hit(sel: str) -> bool:
        positive, _, negative = sel.partition(":not(")
        return (sel.startswith("iframe[src") and all(s in src for s in _SRC.findall(positive))
                and not any(s in src for s in _SRC.findall(negative)))
    return FakeNode([p.selector for p in WIDGET_PROBES if hit(p.selector)], src=src)


def _inline(el: Measured) -> FakeNode:
    """The inline probes an element answers to. Only the shapes the inline rows use: `.a.b`, `tag.a`, `tag[id^="x"]`."""
    def hit(sel: str) -> bool:
        m = _INLINE.match(sel)
        if not m:
            return False
        tag, classes, id_prefix = m.groups()
        names = [c for c in classes.split(".") if c]
        return ((not tag or tag == el.tag) and all(c in el.classes for c in names)
                and (not id_prefix or el.id.startswith(id_prefix)) and bool(names or id_prefix))
    return FakeNode([p.selector for p in WIDGET_PROBES if hit(p.selector)], visible=el.visible)


def _detect(nodes) -> Optional[Tuple[Vendor, FrameRole]]:
    widget = PageSolver(config=PageSolverConfig()).detect_captcha(fake_scope(nodes))
    return (widget.vendor, widget.role) if widget is not None else None


def test_recaptcha_enterprise_is_recaptcha_in_both_frame_roles():
    assert _detect([_frame("https://www.google.com/recaptcha/enterprise/bframe?hl=en&v=abc&k=6Lf")]) == (
        Vendor.RECAPTCHA, FrameRole.CHALLENGE)
    assert _detect([_frame("https://www.google.com/recaptcha/enterprise/anchor?ar=1&k=6Lf&co=aHR0&hl=en&size=normal")]) == (
        Vendor.RECAPTCHA, FrameRole.CHECKBOX)
    assert _detect([_frame("https://www.google.com/recaptcha/enterprise/anchor?ar=1&k=6Lf&size=invisible")]) is None


def test_funcaptcha_is_found_by_the_outer_arkose_frame_the_host_page_carries():
    outer = "https://iframe.arkoselabs.com/B7D8911C-5CC8-A9A3-35B0-554ACEE604DA/index.html?mkt=en"
    game = "https://client-api.arkoselabs.com/fc/assets/ec-game-core/game-core/1.40.0/standard/index.html?session=1"
    assert _detect([_frame(outer)]) == (Vendor.FUNCAPTCHA, FrameRole.UNKNOWN)
    assert _detect([_frame(game)]) == (Vendor.FUNCAPTCHA, FrameRole.UNKNOWN)


def test_proton_is_found_on_the_api_host_and_under_the_apps_own_api():
    for src in ("https://account-api.proton.me/core/v4/captcha?Token=abc&ForceWebMessaging=1",
                "https://verify.proton.me/api/core/v4/captcha?Token=abc&ForceWebMessaging=1"):
        assert _detect([_frame(src)]) == (Vendor.PROTON, FrameRole.UNKNOWN), src


def test_the_aws_waf_card_is_found():
    assert _detect([_inline(Measured("div", classes=("amzn-captcha-modal",)))]) == (Vendor.AWSWAF, FrameRole.UNKNOWN)


# Measured on captchafox.com: `<div id="cf-widget-<hex>">` holds `.cf-button`, and the puzzle opens in
# `div.cf-modal > div.cf-modal__wrap > div.cf-modal__challenge` with that box still showing.
CAPTCHAFOX_BOX = Measured("div", id="cf-widget-2d5fe02ef9734")
CAPTCHAFOX_MODAL = (Measured("div", id="cf-modal-1a2b", classes=("cf-modal",)),
                    Measured("div", classes=("cf-modal__wrap",)),
                    Measured("div", classes=("cf-modal__challenge",)))


def test_the_captchafox_box_is_a_checkbox_and_its_open_puzzle_outranks_it():
    assert _detect([_inline(CAPTCHAFOX_BOX)]) == (Vendor.CAPTCHAFOX, FrameRole.CHECKBOX)
    assert _detect([_inline(CAPTCHAFOX_BOX), *map(_inline, CAPTCHAFOX_MODAL)]) == (Vendor.CAPTCHAFOX, FrameRole.CHALLENGE)


# Measured on dingxiang-inc.com/business/captcha: the trigger bar sits in `div.captcha-trigger.dx_captcha`, a hidden
# loading card is `div.dx_captcha.dx_captcha_loading-style-popup`, and the open card is the one-step popup.
DINGXIANG_TRIGGER = Measured("div", classes=("captcha-trigger", "dx_captcha"))
DINGXIANG_LOADING = Measured("div", id="get-price-captcha", classes=("dx_captcha", "dx_captcha_loading-style-popup"),
                             visible=False)
DINGXIANG_POPUP = Measured("div", id="dx_captcha_oneclick_one-step_1", classes=(
    "dx_captcha_oneclick_one-step", "dx_captcha", "dx_captcha_clickword", "dx_captcha-type-clickword",
    "dx_captcha_clickword-style-popup"))


def test_the_dingxiang_popup_is_found_and_its_trigger_bar_is_not_a_widget():
    assert _detect([_inline(DINGXIANG_TRIGGER), _inline(DINGXIANG_LOADING)]) is None
    assert _detect([_inline(DINGXIANG_TRIGGER), _inline(DINGXIANG_LOADING), _inline(DINGXIANG_POPUP)]) == (
        Vendor.DINGXIANG, FrameRole.UNKNOWN)


def test_the_new_rows_claim_no_other_vendors_frame():
    assert _detect([_frame("https://service.mtcaptcha.com/mtcv1/client/iframe.html?v=2")]) == (
        Vendor.MTCAPTCHA, FrameRole.UNKNOWN)
    assert _detect([_frame("https://newassets.hcaptcha.com/captcha/v1/abc/static/hcaptcha.html#frame=challenge&id=0x1")]) == (
        Vendor.HCAPTCHA, FrameRole.CHALLENGE)


def test_a_card_whose_submit_says_confirm_is_submitted():
    confirm = FakeNode([s for s in SUBMIT_SELECTORS if s == submit_by_text("confirm")], text="Confirm")
    found = PageSolver.__new__(PageSolver)._get_verify_button(fake_scope([confirm]))
    assert found is not None and found.node is confirm, "the AWS WAF card answers with Confirm, and nothing pressed it"
