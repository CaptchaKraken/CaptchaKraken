"""Every selector the driver knows, keyed by vendor, read from `captchakraken.config.json` at the repository root.

The JS port reads the same file (js/src/selectors.ts). Detection takes the first visible match in table order, so the
file's order is the detection order."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any, Dict, Mapping, NamedTuple, Optional, Sequence, Tuple, Union

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
    # On the host page: a frame the vendor draws its other frames inside. Every host-page selector also reads the
    # inside of a visible one.
    enclave: Sequence[str] = ()
    # On the host page: inline widget shapes, detected last. Iframe selectors go first; a class that lives inside the
    # frame document (.CheckboxCaptcha, .mtcap) only ever matches an inline embed.
    widget: Sequence[str] = ()
    # On the host page: the field the vendor fills on success. Read first and unconditionally, because hCaptcha's
    # overlay hides the anchor.
    response: Optional[str] = None
    # Inside the checkbox frame: the box shows accepted. Demo pages do not always fill `response`.
    checked: Optional[str] = None
    # Inside the checkbox frame: the box itself, clicked from the DOM. A vendor without one is found on a photograph.
    # An in-page checkbox that names one is a button with no tick box to find, and is clicked where it is.
    box: Sequence[str] = ()
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
    # Inside the widget: the control that deals a new puzzle, pressed when the model answers `refresh`.
    refresh: Sequence[str] = ()
    # A press-and-hold that completes on its own once full, and resets when let go before it has: the fill reaching
    # the answer's `to` is not a release, and the hold lasts until the widget says it is done.
    hold_completes: bool = False


#: The default config: the repository's own `captchakraken.config.json` when this package runs from a checkout, so an
#: edit there is what the solver reads, else the copy shipped inside the package (a wheel has no repository root).
_SHIPPED_CONFIG = Path(__file__).with_name("captchakraken.config.json")
_CHECKOUT_CONFIG = Path(__file__).resolve().parents[3] / "captchakraken.config.json"
DEFAULT_CONFIG_PATH: Path = _CHECKOUT_CONFIG if _CHECKOUT_CONFIG.is_file() else _SHIPPED_CONFIG

ConfigSource = Union[str, "os.PathLike[str]", Mapping[str, Any]]

_FIELDS = {f.name: f for f in fields(VendorSelectors)}
_ONE = {"response", "checked", "accepted", "fresh"}
_GENERIC = ("submit_text", "text_input", "slider_handle", "piece")


class SelectorConfigError(ValueError):
    """A selector config the solver cannot use; the message names the file and the key."""


def _read(source: ConfigSource) -> Tuple[str, Mapping[str, Any]]:
    if isinstance(source, Mapping):
        return "selectors", source
    path = Path(source)
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise SelectorConfigError(f"{path}: cannot be read as JSON ({e})") from None
    if not isinstance(doc, Mapping):
        raise SelectorConfigError(f"{path}: the top level must be an object")
    return str(path), doc


def _strings(where: str, value: Any) -> Tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise SelectorConfigError(f"{where}: must be a list of strings")
    return tuple(value)


def _entry(where: str, raw: Any, hosts_required: bool = True) -> VendorSelectors:
    if not isinstance(raw, Mapping):
        raise SelectorConfigError(f"{where}: must be an object")
    kw: Dict[str, Any] = {}
    for key, value in raw.items():
        at = f"{where}.{key}"
        if key == "note" or key.startswith("_"):
            continue
        if key not in _FIELDS:
            raise SelectorConfigError(f"{at}: not a selector field (one of {', '.join(_FIELDS)})")
        if key in _ONE:
            if value is not None and not isinstance(value, str):
                raise SelectorConfigError(f"{at}: must be one selector string")
            kw[key] = value
        elif key == "hold_completes":
            if not isinstance(value, bool):
                raise SelectorConfigError(f"{at}: must be true or false")
            kw[key] = value
        elif key == "banners":
            if not isinstance(value, list):
                raise SelectorConfigError(f"{at}: must be a list of [selector, verdict] pairs")
            pairs = []
            for i, pair in enumerate(value):
                if not (isinstance(pair, list) and len(pair) == 2 and isinstance(pair[0], str)):
                    raise SelectorConfigError(f"{at}[{i}]: must be a [selector, verdict] pair")
                try:
                    pairs.append((pair[0], RecaptchaBanner(pair[1])))
                except ValueError:
                    raise SelectorConfigError(
                        f"{at}[{i}]: verdict {pair[1]!r} is not one of {[b.value for b in RecaptchaBanner]}") from None
            kw[key] = tuple(pairs)
        else:
            kw[key] = _strings(at, value)
    if "hosts" not in kw:
        if hosts_required:
            raise SelectorConfigError(f"{where}.hosts: missing (an empty list when the vendor has no host of its own)")
        kw["hosts"] = ()
    return VendorSelectors(**kw)


class SelectorConfig(NamedTuple):
    """A loaded selector config: the caller's own entry, every vendor's in detection order, and the generic fallbacks."""
    custom: Optional[VendorSelectors]
    vendors: Mapping[Vendor, VendorSelectors]
    generic: Mapping[str, Tuple[str, ...]]


def _parse(name: str, doc: Mapping[str, Any], base: Optional[SelectorConfig]) -> SelectorConfig:
    for key in doc:
        if not key.startswith("_") and key not in ("custom", "vendors", "generic"):
            raise SelectorConfigError(f"{name}: {key}: not a config key (custom, vendors, generic)")
    custom = base.custom if base else None
    if "custom" in doc:
        custom = None if doc["custom"] is None else _entry(f"{name}: custom", doc["custom"], hosts_required=False)
    raw_vendors = doc.get("vendors", {})
    if not isinstance(raw_vendors, Mapping):
        raise SelectorConfigError(f"{name}: vendors: must be an object keyed by vendor")
    vendors: Dict[Vendor, VendorSelectors] = dict(base.vendors) if base else {}
    for key, raw in raw_vendors.items():
        if key.startswith("_"):
            continue
        try:
            vendor = Vendor(key)
        except ValueError:
            raise SelectorConfigError(
                f"{name}: vendors.{key}: not a vendor this solver knows; a captcha of your own goes under `custom`") from None
        vendors[vendor] = _entry(f"{name}: vendors.{key}", raw)
    if base is None and set(vendors) != set(Vendor):
        missing = sorted(v.value for v in set(Vendor) - set(vendors))
        raise SelectorConfigError(f"{name}: vendors: every vendor must have an entry; missing {missing}")
    raw_generic = doc.get("generic", {})
    if not isinstance(raw_generic, Mapping):
        raise SelectorConfigError(f"{name}: generic: must be an object")
    generic: Dict[str, Tuple[str, ...]] = dict(base.generic) if base else {}
    for key, value in raw_generic.items():
        if key.startswith("_"):
            continue
        if key not in _GENERIC:
            raise SelectorConfigError(f"{name}: generic.{key}: not a generic list (one of {', '.join(_GENERIC)})")
        generic[key] = _strings(f"{name}: generic.{key}", value)
    if base is None and set(generic) != set(_GENERIC):
        raise SelectorConfigError(f"{name}: generic: missing {sorted(set(_GENERIC) - set(generic))}")
    return SelectorConfig(custom, vendors, generic)


def load_config(source: Optional[ConfigSource] = None) -> SelectorConfig:
    """The shipped default, or `source` (a path or a parsed object) laid over it: a key it gives replaces the default's
    `custom`, one vendor's whole entry, or one generic list. Raises SelectorConfigError naming the bad key."""
    default = _parse(*_read(DEFAULT_CONFIG_PATH), base=None)
    if source is None or (not isinstance(source, Mapping) and Path(source) == DEFAULT_CONFIG_PATH):
        return default
    return _parse(*_read(source), base=default)


DEFAULT_CONFIG: SelectorConfig = load_config()
#: Every vendor's entry, in detection order, as the default config gives it.
SELECTORS: Mapping[Vendor, VendorSelectors] = DEFAULT_CONFIG.vendors

_LOWER = "translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz')"


def submit_by_text(text: str) -> str:
    """`.//` keeps the xpath relative so a host-page widget cannot reach the form's own submit."""
    return f"xpath=.//button[contains({_LOWER}, '{text}')] | .//div[@role=\"button\" and contains({_LOWER}, '{text}')]"


class WidgetProbe(NamedTuple):
    vendor: Vendor
    role: FrameRole
    selector: str


_DETECTED_BY = ("challenge", "checkbox", "widget")


class SelectorTable:
    """The table one solver detects and drives with: a selector config's vendors, plus its `custom` entry when it has one.

    `config` is a path, a parsed object or a loaded SelectorConfig, laid over the shipped default (see `load_config`).
    `custom` (the older `custom_selectors=`) replaces the config's own `custom`. A custom entry is reported as
    `Vendor.UNKNOWN` and searched before the built-in vendors, because the caller wrote it for the page in front of them.
    """

    def __init__(self, custom: Optional[VendorSelectors] = None,
                 config: Union[ConfigSource, SelectorConfig, None] = None) -> None:
        loaded = config if isinstance(config, SelectorConfig) else load_config(config)
        custom = custom if custom is not None else loaded.custom
        if custom is not None and not any(getattr(custom, key) for key in _DETECTED_BY):
            raise SelectorConfigError(
                "custom selectors name nothing to detect: give the entry a `widget`, `challenge` or `checkbox`")
        self.config = loaded
        self.selectors: Mapping[Vendor, VendorSelectors] = (
            {Vendor.UNKNOWN: custom, **{v: s for v, s in loaded.vendors.items() if v != Vendor.UNKNOWN}}
            if custom is not None else loaded.vendors)
        self.vendors: Sequence[Tuple[Vendor, VendorSelectors]] = tuple(self.selectors.items())
        # Every host-page selector with what it names, in detection order: open challenges, then checkboxes, then
        # inline widgets.
        self.widget_probes: Sequence[WidgetProbe] = tuple(
            WidgetProbe(vendor, role, selector)
            for role, key in zip((FrameRole.CHALLENGE, FrameRole.CHECKBOX, FrameRole.UNKNOWN), _DETECTED_BY)
            for vendor, s in self.vendors
            for selector in getattr(s, key))
        self.enclave: Sequence[str] = self._of_every_vendor("enclave")
        self.response: Sequence[str] = tuple(s.response for _, s in self.vendors if s.response)
        self.accepted: Sequence[str] = tuple(s.accepted for _, s in self.vendors if s.accepted)
        # A real Verify/Next/Submit/Skip/Confirm first; the vendor-named controls are fallbacks.
        self.submit: Sequence[str] = (*map(submit_by_text, loaded.generic["submit_text"]),
                                      *self._of_every_vendor("submit"))
        # Vendor-named first, generic last: the driver takes the first visible match, and a generic selector
        # reached before the vendor's own is how a captcha's answer ends up in a login form's username box.
        self.text_input_vendor: Sequence[str] = self._of_every_vendor("text_input")
        self.text_input: Sequence[str] = (*self.text_input_vendor, *loaded.generic["text_input"])
        # `[draggable=true]` is absent from the generic handles: HTML5 DnD fires dragstart, not pointermove.
        self.slider_handle: Sequence[str] = (*self._of_every_vendor("slider_handle"), *loaded.generic["slider_handle"])
        self.refresh: Sequence[str] = self._of_every_vendor("refresh")
        self.piece: Sequence[str] = (*self._of_every_vendor("piece"), *loaded.generic["piece"])

    def _of_every_vendor(self, key: str) -> Sequence[str]:
        assert key in {f.name for f in fields(VendorSelectors)}
        return tuple(s for _, v in self.vendors for s in getattr(v, key))


DEFAULT_TABLE = SelectorTable(config=DEFAULT_CONFIG)
VENDORS = DEFAULT_TABLE.vendors
WIDGET_PROBES = DEFAULT_TABLE.widget_probes
ENCLAVE_SELECTORS = DEFAULT_TABLE.enclave
RESPONSE_SELECTORS = DEFAULT_TABLE.response
ACCEPTED_SELECTORS = DEFAULT_TABLE.accepted
SUBMIT_SELECTORS = DEFAULT_TABLE.submit
TEXT_INPUT_VENDOR_SELECTORS = DEFAULT_TABLE.text_input_vendor
TEXT_INPUT_SELECTORS = DEFAULT_TABLE.text_input
SLIDER_HANDLE_SELECTORS = DEFAULT_TABLE.slider_handle
REFRESH_SELECTORS = DEFAULT_TABLE.refresh
PIECE_SELECTORS = DEFAULT_TABLE.piece
