"""Every selector the driver knows, keyed by vendor. Mirrored in js/src/selectors.ts; keep both in the same order,
because detection takes the first visible match in table order."""

from __future__ import annotations

from dataclasses import dataclass, fields
from typing import Mapping, NamedTuple, Optional, Sequence, Tuple

from .kinds import FrameRole, RecaptchaBanner, Vendor


@dataclass(frozen=True)
class VendorSelectors:
    # URL substrings of the vendor's code on the wire. A tripwire, not a detector: the host stays on the wire when a
    # vendor renames its markup (see TRIBAL_KNOWLEDGE.md). BotDetect is self-hosted, so it has none.
    hosts: Sequence[str]
    # On the host page: the open challenge. Detected first.
    challenge: Sequence[str] = ()
    # On the host page: the checkbox. Detected while `response` is empty and `checked` is not showing.
    checkbox: Sequence[str] = ()
    # On the host page: inline widget shapes, detected last. Iframe selectors go first; a class that lives inside the
    # frame document (.CheckboxCaptcha, .mtcap) only ever matches an inline embed.
    widget: Sequence[str] = ()
    # On the host page: the field the vendor fills on success. Read first and unconditionally, because hCaptcha's
    # overlay hides the anchor.
    response: Optional[str] = None
    # Inside the checkbox frame: the box shows accepted. Demo pages do not always fill `response`.
    checked: Optional[str] = None
    # On the host page: the vendor painted its success state. Visibility is part of the test (see TRIBAL_KNOWLEDGE.md).
    accepted: Optional[str] = None
    # Inside the challenge frame: a new round has painted, with text.
    fresh: Optional[str] = None
    # Inside the challenge frame: the pictures a board is made of; the driver waits for each to have painted.
    images: Sequence[str] = ()
    # Inside the widget: the vendor's own submit control, tried after the generic text probes.
    submit: Sequence[str] = ()
    # Inside the challenge frame: verdict banners and what each means.
    banners: Sequence[Tuple[str, RecaptchaBanner]] = ()
    # Inside the challenge frame: the vendor refusing to serve this client at all. Nothing after it can succeed.
    blocked: Sequence[str] = ()
    # On the host page: the vendor's frames that are never interactive, so a page showing only these has no widget.
    passive: Sequence[str] = ()
    # Inside the widget, and its enclosing fieldset/form: the answer box of a typed captcha.
    text_input: Sequence[str] = ()
    # Inside the widget: the knob a slide must start on; a drag from the piece moves nothing.
    slider_handle: Sequence[str] = ()
    # Inside the widget: the piece, measured to steer the slide and dragged directly when there is no track.
    piece: Sequence[str] = ()


SELECTORS: Mapping[Vendor, VendorSelectors] = {
    Vendor.RECAPTCHA: VendorSelectors(
        hosts=("google.com/recaptcha", "recaptcha.net"),
        challenge=('iframe[src*="recaptcha/api2/bframe"]',),
        checkbox=('iframe[src*="recaptcha/api2/anchor"]:not([src*="size=invisible"])',),
        response='[name="g-recaptcha-response"]',
        checked=".recaptcha-checkbox-checked",
        fresh=".rc-imageselect-instructions, #rc-imageselect",
        submit=("#recaptcha-verify-button",),
        banners=(
            (".rc-imageselect-error-select-more", RecaptchaBanner.SELECT_MORE),
            (".rc-imageselect-error-dynamic-more", RecaptchaBanner.DYNAMIC_MORE),
            (".rc-imageselect-incorrect-response", RecaptchaBanner.REJECTED),
        ),
        blocked=(".rc-doscaptcha-header-text",),
        passive=('iframe[src*="size=invisible"]',),
    ),
    # Keyed on the `hcaptcha` substring, not the apex host: challenges are served off newassets.hcaptcha.com.
    Vendor.HCAPTCHA: VendorSelectors(
        hosts=("hcaptcha.com",),
        challenge=('iframe[src*="hcaptcha"][src*="frame=challenge"]',),
        checkbox=('iframe[src*="hcaptcha"][src*="frame=checkbox"]',),
        response='[name="h-captcha-response"]',
        checked='#checkbox[aria-checked="true"]',
        fresh=".prompt-text",
        images=(".task-image .image", ".task .image", ".challenge-example img", ".image-wrapper img"),
        submit=(".button-submit",),
    ),
    Vendor.TURNSTILE: VendorSelectors(
        hosts=("challenges.cloudflare.com",),
        checkbox=('iframe[src*="challenges.cloudflare.com"]', ".cf-turnstile"),
        response='[name="cf-turnstile-response"]',
    ),
    Vendor.GEETEST: VendorSelectors(
        hosts=("geetest.com",),
        widget=(".geetest_box", ".geetest_panel_box", ".geetest_popup_window", ".geetest_widget"),
        accepted=(".geetest_result_tips.geetest_success, .geetest_captcha.geetest_success, "
                  ".geetest_captcha.geetest_lock_success"),
        submit=(".geetest_submit",),
        slider_handle=(".geetest_slider_button", ".geetest_btn", ".geetest_slider .geetest_arrow"),
        piece=(".geetest_slice",),
    ),
    # Both in-page and iframe shapes stay (Tencent moved in-host on 2026-08-11; see TRIBAL_KNOWLEDGE.md), and the iframe
    # id is prefix-anchored: `[id*=tcaptcha]` also matched MTCaptcha's iframe and hid that `.mtcap` matched nothing.
    Vendor.TENCENT: VendorSelectors(
        hosts=("captcha.gtimg.com", "captcha.qcloud.com"),
        widget=("#tcaptcha_transform_dy", "#tCaptchaDyContent", ".tencent-captcha-dy__content", "iframe#tcaptcha_iframe_dy",
                'iframe[id^="tcaptcha"]', 'iframe[src*="captcha.gtimg.com"]', 'iframe[src*="captcha.qq.com"]'),
        slider_handle=(".tencent-captcha-dy__slider-block", "#tcaptcha_drag_thumb", ".tc-slider-normal", "[id*=slideBlock]"),
        piece=(".tencent-captcha-dy__fg-item",),
    ),
    Vendor.YIDUN: VendorSelectors(
        hosts=("dun.163.com", "cstaticdun.126.net", "necaptcha.nosdn.127.net"),
        widget=(".yidun_panel", ".yidun"),
        slider_handle=(".yidun_slider", ".yidun_jigsaw"),
        piece=(".yidun_jigsaw",),
    ),
    Vendor.YANDEX: VendorSelectors(
        hosts=("smartcaptcha.yandexcloud.net",),
        widget=('iframe[src*="smartcaptcha.yandexcloud.net/advanced"]', 'iframe[src*="smartcaptcha.yandexcloud.net"]',
                ".CheckboxCaptcha"),
        text_input=(".AdvancedCaptcha-Input input", "input.Textinput-Control", 'input[name="rep"]'),
    ),
    Vendor.LEMIN: VendorSelectors(
        hosts=("leminnow.com",),
        widget=("#lemin-cropped-captcha", ".lemin-captcha-popup"),
        slider_handle=(".lemin-slider-handle", "#lemin-cropped-captcha .slider"),
        piece=(".lemin-cropped-puzzle-piece", "#lemin-cropped-captcha canvas + canvas"),
    ),
    Vendor.PROSOPO: VendorSelectors(
        hosts=("prosopo.io",),
        widget=(".prosopo-modalInner", ".procaptcha-checkbox"),
    ),
    Vendor.MTCAPTCHA: VendorSelectors(
        hosts=("mtcaptcha.com",),
        widget=('iframe[src*="service.mtcaptcha.com"]', 'iframe[id^="mtcaptcha-iframe"]', ".mtcaptcha", ".mtcap"),
        text_input=("input.mtcap-inputtext", ".mtcap input[type=text]"),
    ),
    Vendor.BOTDETECT: VendorSelectors(
        hosts=(),
        widget=(".BDC_CaptchaDiv",),
        text_input=("input[id*=captchaCode]", "input#captchaCode", "input[id*=validateCaptcha]",
                    ".BDC_CaptchaDiv input[type=text]"),
    ),
    Vendor.UNKNOWN: VendorSelectors(hosts=()),
}
assert set(SELECTORS) == set(Vendor), "every vendor names its selectors"

VENDORS: Sequence[Tuple[Vendor, VendorSelectors]] = tuple(SELECTORS.items())


def _of_every_vendor(key: str) -> Sequence[str]:
    assert key in {f.name for f in fields(VendorSelectors)}
    return tuple(s for _, v in VENDORS for s in getattr(v, key))


class WidgetProbe(NamedTuple):
    vendor: Vendor
    role: FrameRole
    selector: str


# Every host-page selector with what it names, in detection order: open challenges, then checkboxes, then inline widgets.
WIDGET_PROBES: Sequence[WidgetProbe] = tuple(
    WidgetProbe(vendor, role, selector)
    for role, key in ((FrameRole.CHALLENGE, "challenge"), (FrameRole.CHECKBOX, "checkbox"), (FrameRole.UNKNOWN, "widget"))
    for vendor, s in VENDORS
    for selector in getattr(s, key))

RESPONSE_SELECTORS: Sequence[str] = tuple(s.response for _, s in VENDORS if s.response)
ACCEPTED_SELECTORS: Sequence[str] = tuple(s.accepted for _, s in VENDORS if s.accepted)

_LOWER = "translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz')"


def submit_by_text(text: str) -> str:
    """`.//` keeps the xpath relative so a host-page widget cannot reach the form's own submit."""
    return f"xpath=.//button[contains({_LOWER}, '{text}')] | .//div[@role=\"button\" and contains({_LOWER}, '{text}')]"


# A real Verify/Next/Submit/Skip first; the vendor-named controls are fallbacks.
SUBMIT_SELECTORS: Sequence[str] = (*map(submit_by_text, ("verify", "next", "submit", "skip")), *_of_every_vendor("submit"))

# Vendor-named first, generic last: the driver takes the first visible match, and a generic selector
# reached before the vendor's own is how a captcha's answer ends up in a login form's username box.
TEXT_INPUT_VENDOR_SELECTORS: Sequence[str] = _of_every_vendor("text_input")
TEXT_INPUT_SELECTORS: Sequence[str] = (
    *TEXT_INPUT_VENDOR_SELECTORS,
    'input[name*="captcha" i]', 'input[id*="captcha" i]', 'input[aria-label*="captcha" i]',
    'input[placeholder*="code" i]', 'input[autocomplete="off"][type=text]',
    "input[type=text]", "input:not([type])", "input[type=tel]", "textarea",
)
# `[draggable=true]` is absent: HTML5 DnD fires dragstart, not pointermove.
SLIDER_HANDLE_SELECTORS: Sequence[str] = (
    *_of_every_vendor("slider_handle"),
    '[role="slider"]', "[aria-valuenow]",
    '[class*="slider"][class*="btn"]', '[class*="slider"][class*="button"]',
    '[class*="slide"][class*="handle"]', '[class*="drag"][class*="thumb"]',
)
PIECE_SELECTORS: Sequence[str] = (*_of_every_vendor("piece"), '[class*="puzzle"][class*="piece"]', '[class*="jigsaw"]')
