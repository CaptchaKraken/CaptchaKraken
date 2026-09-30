/**
 * Every selector the driver knows, keyed by vendor. Mirrored in python/src/captchakraken/selectors.py; keep both in the
 * same order, because detection takes the first visible match in table order.
 */
import { FrameRole, RecaptchaBanner, Vendor } from './kinds';

export interface VendorSelectors {
  /** URL substrings of the vendor's code on the wire. A tripwire, not a detector: the host stays on the wire when a vendor renames its markup (see TRIBAL_KNOWLEDGE.md). BotDetect is self-hosted, so it has none. */
  readonly hosts: readonly string[];
  /** On the host page: the open challenge. Detected first. */
  readonly challenge?: readonly string[];
  /** On the host page: the checkbox. Detected while `response` is empty and `checked` is not showing. */
  readonly checkbox?: readonly string[];
  /** On the host page: inline widget shapes, detected last. Iframe selectors go first; a class that lives inside the frame document (.CheckboxCaptcha, .mtcap) only ever matches an inline embed. */
  readonly widget?: readonly string[];
  /** On the host page: the field the vendor fills on success. Read first and unconditionally, because hCaptcha's overlay hides the anchor. */
  readonly response?: string;
  /** Inside the checkbox frame: the box shows accepted. Demo pages do not always fill `response`. */
  readonly checked?: string;
  /** On the host page: the vendor painted its success state. Visibility is part of the test (see TRIBAL_KNOWLEDGE.md). */
  readonly accepted?: string;
  /** Inside the challenge frame: a new round has painted, with text. */
  readonly fresh?: string;
  /** Inside the challenge frame: the pictures a board is made of; the driver waits for each to have painted. */
  readonly images?: readonly string[];
  /** Inside the widget: the vendor's own submit control, tried after the generic text probes. */
  readonly submit?: readonly string[];
  /** Inside the challenge frame: verdict banners and what each means. */
  readonly banners?: ReadonlyArray<readonly [string, RecaptchaBanner]>;
  /** Inside the challenge frame: the vendor refusing to serve this client at all. Nothing after it can succeed. */
  readonly blocked?: readonly string[];
  /** On the host page: the vendor's frames that are never interactive, so a page showing only these has no widget. */
  readonly passive?: readonly string[];
  /** Inside the widget, and its enclosing fieldset/form: the answer box of a typed captcha. */
  readonly textInput?: readonly string[];
  /** Inside the widget: the knob a slide must start on; a drag from the piece moves nothing. */
  readonly sliderHandle?: readonly string[];
  /** Inside the widget: the piece, measured to steer the slide and dragged directly when there is no track. */
  readonly piece?: readonly string[];
}

export const SELECTORS: Readonly<Record<Vendor, VendorSelectors>> = {
  [Vendor.RECAPTCHA]: {
    hosts: ['google.com/recaptcha', 'recaptcha.net'],
    challenge: ['iframe[src*="recaptcha/api2/bframe"]'],
    checkbox: ['iframe[src*="recaptcha/api2/anchor"]:not([src*="size=invisible"])'],
    response: '[name="g-recaptcha-response"]',
    checked: '.recaptcha-checkbox-checked',
    fresh: '.rc-imageselect-instructions, #rc-imageselect',
    submit: ['#recaptcha-verify-button'],
    banners: [
      ['.rc-imageselect-error-select-more', RecaptchaBanner.SELECT_MORE],
      ['.rc-imageselect-error-dynamic-more', RecaptchaBanner.DYNAMIC_MORE],
      ['.rc-imageselect-incorrect-response', RecaptchaBanner.REJECTED],
    ],
    blocked: ['.rc-doscaptcha-header-text'],
    passive: ['iframe[src*="size=invisible"]'],
  },
  // Keyed on the `hcaptcha` substring, not the apex host: challenges are served off newassets.hcaptcha.com.
  [Vendor.HCAPTCHA]: {
    hosts: ['hcaptcha.com'],
    challenge: ['iframe[src*="hcaptcha"][src*="frame=challenge"]'],
    checkbox: ['iframe[src*="hcaptcha"][src*="frame=checkbox"]'],
    response: '[name="h-captcha-response"]',
    checked: '#checkbox[aria-checked="true"]',
    fresh: '.prompt-text',
    images: ['.task-image .image', '.task .image', '.challenge-example img', '.image-wrapper img'],
    submit: ['.button-submit'],
  },
  [Vendor.TURNSTILE]: {
    hosts: ['challenges.cloudflare.com'],
    checkbox: ['iframe[src*="challenges.cloudflare.com"]', '.cf-turnstile'],
    response: '[name="cf-turnstile-response"]',
  },
  [Vendor.GEETEST]: {
    hosts: ['geetest.com'],
    widget: ['.geetest_box', '.geetest_panel_box', '.geetest_popup_window', '.geetest_widget'],
    accepted: '.geetest_result_tips.geetest_success, .geetest_captcha.geetest_success, .geetest_captcha.geetest_lock_success',
    submit: ['.geetest_submit'],
    sliderHandle: ['.geetest_slider_button', '.geetest_btn', '.geetest_slider .geetest_arrow'],
    piece: ['.geetest_slice'],
  },
  // Both in-page and iframe shapes stay (Tencent moved in-host on 2026-08-11; see TRIBAL_KNOWLEDGE.md), and the iframe id
  // is prefix-anchored: `[id*=tcaptcha]` also matched MTCaptcha's iframe and hid that `.mtcap` matched nothing.
  [Vendor.TENCENT]: {
    hosts: ['captcha.gtimg.com', 'captcha.qcloud.com'],
    widget: ['#tcaptcha_transform_dy', '#tCaptchaDyContent', '.tencent-captcha-dy__content', 'iframe#tcaptcha_iframe_dy', 'iframe[id^="tcaptcha"]', 'iframe[src*="captcha.gtimg.com"]', 'iframe[src*="captcha.qq.com"]'],
    sliderHandle: ['.tencent-captcha-dy__slider-block', '#tcaptcha_drag_thumb', '.tc-slider-normal', '[id*=slideBlock]'],
    piece: ['.tencent-captcha-dy__fg-item'],
  },
  [Vendor.YIDUN]: {
    hosts: ['dun.163.com', 'cstaticdun.126.net', 'necaptcha.nosdn.127.net'],
    widget: ['.yidun_panel', '.yidun'],
    sliderHandle: ['.yidun_slider', '.yidun_jigsaw'],
    piece: ['.yidun_jigsaw'],
  },
  [Vendor.YANDEX]: {
    hosts: ['smartcaptcha.yandexcloud.net'],
    widget: ['iframe[src*="smartcaptcha.yandexcloud.net/advanced"]', 'iframe[src*="smartcaptcha.yandexcloud.net"]', '.CheckboxCaptcha'],
    textInput: ['.AdvancedCaptcha-Input input', 'input.Textinput-Control', 'input[name="rep"]'],
  },
  [Vendor.LEMIN]: {
    hosts: ['leminnow.com'],
    widget: ['#lemin-cropped-captcha', '.lemin-captcha-popup'],
    sliderHandle: ['.lemin-slider-handle', '#lemin-cropped-captcha .slider'],
    piece: ['.lemin-cropped-puzzle-piece', '#lemin-cropped-captcha canvas + canvas'],
  },
  [Vendor.PROSOPO]: {
    hosts: ['prosopo.io'],
    widget: ['.prosopo-modalInner', '.procaptcha-checkbox'],
  },
  [Vendor.MTCAPTCHA]: {
    hosts: ['mtcaptcha.com'],
    widget: ['iframe[src*="service.mtcaptcha.com"]', 'iframe[id^="mtcaptcha-iframe"]', '.mtcaptcha', '.mtcap'],
    textInput: ['input.mtcap-inputtext', '.mtcap input[type=text]'],
  },
  [Vendor.BOTDETECT]: {
    hosts: [],
    widget: ['.BDC_CaptchaDiv'],
    textInput: ['input[id*=captchaCode]', 'input#captchaCode', 'input[id*=validateCaptcha]', '.BDC_CaptchaDiv input[type=text]'],
  },
  [Vendor.UNKNOWN]: { hosts: [] },
};

export const VENDORS = Object.entries(SELECTORS) as ReadonlyArray<readonly [Vendor, VendorSelectors]>;

type ListKey = { [K in keyof VendorSelectors]-?: VendorSelectors[K] extends readonly string[] | undefined ? K : never }[keyof VendorSelectors];
const ofEveryVendor = (key: ListKey): readonly string[] => VENDORS.flatMap(([, s]) => s[key] ?? []);

export interface WidgetProbe {
  readonly vendor: Vendor;
  readonly role: FrameRole;
  readonly selector: string;
}

/** Every host-page selector with what it names, in detection order: open challenges, then checkboxes, then inline widgets. */
export const WIDGET_PROBES: ReadonlyArray<WidgetProbe> = ([
  [FrameRole.CHALLENGE, 'challenge'], [FrameRole.CHECKBOX, 'checkbox'], [FrameRole.UNKNOWN, 'widget'],
] as const).flatMap(([role, key]) => VENDORS.flatMap(([vendor, s]) => (s[key] ?? []).map((selector) => ({ vendor, role, selector }))));

export const RESPONSE_SELECTORS: readonly string[] = VENDORS.flatMap(([, s]) => s.response ?? []);
export const ACCEPTED_SELECTORS: readonly string[] = VENDORS.flatMap(([, s]) => s.accepted ?? []);

const lower = "translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz')";
/** `.//` keeps the xpath relative so a host-page widget cannot reach the form's own submit. */
export const submitByText = (text: string): string =>
  `xpath=.//button[contains(${lower}, '${text}')] | .//div[@role="button" and contains(${lower}, '${text}')]`;
/** A real Verify/Next/Submit/Skip first; the vendor-named controls are fallbacks. */
export const SUBMIT_SELECTORS: readonly string[] = [...['verify', 'next', 'submit', 'skip'].map(submitByText), ...ofEveryVendor('submit')];

// Vendor-named first, generic last: the driver takes the first visible match, and a generic selector
// reached before the vendor's own is how a captcha's answer ends up in a login form's username box.
export const TEXT_INPUT_VENDOR_SELECTORS: readonly string[] = ofEveryVendor('textInput');
export const TEXT_INPUT_SELECTORS: readonly string[] = [...TEXT_INPUT_VENDOR_SELECTORS,
  'input[name*="captcha" i]', 'input[id*="captcha" i]', 'input[aria-label*="captcha" i]',
  'input[placeholder*="code" i]', 'input[autocomplete="off"][type=text]',
  'input[type=text]', 'input:not([type])', 'input[type=tel]', 'textarea',
];
// `[draggable=true]` is absent: HTML5 DnD fires dragstart, not pointermove.
export const SLIDER_HANDLE_SELECTORS: readonly string[] = [...ofEveryVendor('sliderHandle'),
  '[role="slider"]', '[aria-valuenow]',
  '[class*="slider"][class*="btn"]', '[class*="slider"][class*="button"]',
  '[class*="slide"][class*="handle"]', '[class*="drag"][class*="thumb"]',
];
export const PIECE_SELECTORS: readonly string[] = [...ofEveryVendor('piece'), '[class*="puzzle"][class*="piece"]', '[class*="jigsaw"]'];
