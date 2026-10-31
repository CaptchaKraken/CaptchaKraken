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
  /** On the host page: a frame the vendor draws its other frames inside. Every host-page selector also reads the inside of a visible one. */
  readonly enclave?: readonly string[];
  /** On the host page: inline widget shapes, detected last. Iframe selectors go first; a class that lives inside the frame document (.CheckboxCaptcha, .mtcap) only ever matches an inline embed. */
  readonly widget?: readonly string[];
  /** On the host page: the field the vendor fills on success. Read first and unconditionally, because hCaptcha's overlay hides the anchor. */
  readonly response?: string;
  /** Inside the checkbox frame: the box shows accepted. Demo pages do not always fill `response`. */
  readonly checked?: string;
  /**
   * Inside the checkbox frame: the box itself, clicked from the DOM. A vendor without one is found on a photograph.
   * An in-page checkbox that names one is a button with no tick box to find, and is clicked where it is.
   */
  readonly box?: readonly string[];
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
  /** Inside the widget: the control that deals a new puzzle, pressed when the model answers `refresh`. */
  readonly refresh?: readonly string[];
  /**
   * A press-and-hold that completes on its own once full, and resets when let go before it has: the fill reaching the
   * answer's `to` is not a release, and the hold lasts until the widget says it is done.
   */
  readonly holdCompletes?: boolean;
}

export const SELECTORS: Readonly<Record<Vendor, VendorSelectors>> = {
  // An Enterprise sitekey serves the same widget from /recaptcha/enterprise/ instead of /recaptcha/api2/.
  [Vendor.RECAPTCHA]: {
    hosts: ['google.com/recaptcha', 'recaptcha.net'],
    challenge: ['iframe[src*="recaptcha/api2/bframe"]', 'iframe[src*="recaptcha/enterprise/bframe"]'],
    checkbox: [
      'iframe[src*="recaptcha/api2/anchor"]:not([src*="size=invisible"])',
      'iframe[src*="recaptcha/enterprise/anchor"]:not([src*="size=invisible"])',
    ],
    response: '[name="g-recaptcha-response"]',
    checked: '.recaptcha-checkbox-checked',
    box: ['#recaptcha-anchor'],
    fresh: '.rc-imageselect-instructions, #rc-imageselect',
    submit: ['#recaptcha-verify-button'],
    refresh: ['#recaptcha-reload-button'],
    banners: [
      ['.rc-imageselect-error-select-more', RecaptchaBanner.SELECT_MORE],
      ['.rc-imageselect-error-dynamic-more', RecaptchaBanner.DYNAMIC_MORE],
      ['.rc-imageselect-incorrect-response', RecaptchaBanner.REJECTED],
    ],
    blocked: ['.rc-doscaptcha-header-text'],
    passive: ['iframe[src*="size=invisible"]'],
  },
  // Keyed on the `hcaptcha` substring, not the apex host: challenges are served off newassets.hcaptcha.com. secure-api.js
  // draws every frame inside a full-viewport enclave, one per render, and only a visible one holds an open challenge.
  [Vendor.HCAPTCHA]: {
    hosts: ['hcaptcha.com'],
    challenge: ['iframe[src*="hcaptcha"][src*="frame=challenge"]'],
    checkbox: ['iframe[src*="hcaptcha"][src*="frame=checkbox"]:not([src*="frame=checkbox-invisible"])'],
    enclave: ['iframe[src*="hcaptcha"][src*="frame=enclave"]'],
    response: '[name="h-captcha-response"]',
    checked: '#checkbox[aria-checked="true"]',
    box: ['#checkbox'],
    fresh: '.prompt-text',
    images: ['.task-image .image', '.task .image', '.challenge-example img', '.image-wrapper img'],
    submit: ['.button-submit'],
    refresh: ['.refresh.button'],
    passive: ['iframe[src*="hcaptcha"][src*="frame=enclave"]', 'iframe[src*="hcaptcha"][src*="frame=checkbox-invisible"]'],
  },
  [Vendor.TURNSTILE]: {
    hosts: ['challenges.cloudflare.com'],
    checkbox: ['iframe[src*="challenges.cloudflare.com"]', '.cf-turnstile'],
    response: '[name="cf-turnstile-response"]',
  },
  // v4's "Click to verify" bar opens the puzzle. Its container wears `geetest_freeze_wait` while the puzzle is open
  // (`geetest_boxShow` only until a first wrong answer, after which the box stays up dealing a new one) and
  // `geetest_success` once passed, so the checkbox matches only a bar that has not been clicked yet.
  [Vendor.GEETEST]: {
    hosts: ['geetest.com'],
    checkbox: ['.geetest_captcha:not(.geetest_boxShow):not(.geetest_freeze_wait):not(.geetest_success):not(.geetest_lock_success) .geetest_btn_click'],
    box: ['.geetest_btn_click'],
    widget: ['.geetest_box', '.geetest_panel_box', '.geetest_popup_window', '.geetest_widget'],
    accepted: '.geetest_result_tips.geetest_success, .geetest_captcha.geetest_success, .geetest_captcha.geetest_lock_success',
    submit: ['.geetest_submit'],
    refresh: ['.geetest_refresh', '.geetest_refresh_1'],
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
    refresh: ['.tencent-captcha-dy__footer-icon--refresh'],
  },
  [Vendor.YIDUN]: {
    hosts: ['dun.163.com', 'cstaticdun.126.net', 'necaptcha.nosdn.127.net'],
    widget: ['.yidun_panel', '.yidun'],
    sliderHandle: ['.yidun_slider', '.yidun_jigsaw'],
    piece: ['.yidun_jigsaw'],
    refresh: ['.yidun_refresh'],
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
    refresh: ['.mtcap-refresh'],
  },
  [Vendor.BOTDETECT]: {
    hosts: [],
    widget: ['.BDC_CaptchaDiv'],
    textInput: ['input[id*=captchaCode]', 'input#captchaCode', 'input[id*=validateCaptcha]', '.BDC_CaptchaDiv input[type=text]'],
    refresh: ['a[id*="ReloadLink"]', '.BDC_ReloadIcon'],
  },
  // The press-and-hold widget. Found by its host-page container whether the button is drawn inline or in the vendor's
  // iframe inside it: the hold is performed on a photograph of the container, so it never needs the frame's DOM.
  [Vendor.HUMAN]: {
    hosts: [],
    widget: ['#px-captcha'],
    holdCompletes: true,
  },
  // The card is drawn in an open shadow root, which the locator engine pierces; its Confirm is found by the text probe.
  [Vendor.AWSWAF]: {
    hosts: ['awswaf.com'],
    widget: ['.amzn-captcha-modal'],
  },
  // The puzzle opens in a modal over the "I am human" box, which stays on screen, so the modal is a challenge: a
  // widget would be outranked by the box and the box clicked again.
  [Vendor.CAPTCHAFOX]: {
    hosts: ['captchafox.com'],
    challenge: ['.cf-modal__challenge'],
    checkbox: ['div[id^="cf-widget-"]'],
    response: '[name="cf-captcha-response"]',
    sliderHandle: ['.cf-slider__button'],
  },
  // Every mode opens the same popup card. The trigger bar under it has no box to tick and is not a widget.
  [Vendor.DINGXIANG]: {
    hosts: ['cdn.dingxiang-inc.com/ctu-group/captcha', 'cap.dingxiang-inc.com'],
    widget: ['.dx_captcha_oneclick_one-step'],
    sliderHandle: ['.dx_captcha_basic_slider', '.dx_captcha_rotate_slider'],
  },
  // The host page carries the outer frame (iframe.arkoselabs.com/<key>/index.html) and the game is two frames inside
  // it; the game frame's own path is listed so a page that frames the game directly is found too.
  [Vendor.FUNCAPTCHA]: {
    hosts: ['arkoselabs.com'],
    widget: ['iframe[src*="arkoselabs.com"]', 'iframe[src*="ec-game-core/game-core"]'],
    holdCompletes: true,
  },
  // Proton frames its own captcha at /core/v4/captcha, on account-api.proton.me or under the app's own /api/.
  [Vendor.PROTON]: {
    hosts: ['/core/v4/captcha'],
    widget: ['iframe[src*="/core/v4/captcha"]'],
  },
  [Vendor.UNKNOWN]: { hosts: [] },
};

export interface WidgetProbe {
  readonly vendor: Vendor;
  readonly role: FrameRole;
  readonly selector: string;
}

const lower = "translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz')";
/** `.//` keeps the xpath relative so a host-page widget cannot reach the form's own submit. */
export const submitByText = (text: string): string =>
  `xpath=.//button[contains(${lower}, '${text}')] | .//div[@role="button" and contains(${lower}, '${text}')]`;

/** Your own vendor entry: the built-in schema, with `hosts` optional. */
export type CustomSelectors = Omit<VendorSelectors, 'hosts'> & { readonly hosts?: readonly string[] };

type ListKey = { [K in keyof VendorSelectors]-?: VendorSelectors[K] extends readonly string[] | undefined ? K : never }[keyof VendorSelectors];
const DETECTED_BY = [[FrameRole.CHALLENGE, 'challenge'], [FrameRole.CHECKBOX, 'checkbox'], [FrameRole.UNKNOWN, 'widget']] as const;

/**
 * The table one solver detects and drives with: the built-in vendors, plus the caller's own entry when given. A custom
 * entry is reported as `Vendor.UNKNOWN` and searched before the built-in vendors, because the caller wrote it for the
 * page in front of them.
 */
export class SelectorTable {
  readonly selectors: Readonly<Record<Vendor, VendorSelectors>>;
  readonly vendors: ReadonlyArray<readonly [Vendor, VendorSelectors]>;
  /** Every host-page selector with what it names, in detection order: open challenges, then checkboxes, then inline widgets. */
  readonly widgetProbes: ReadonlyArray<WidgetProbe>;
  readonly enclave: readonly string[];
  readonly response: readonly string[];
  readonly accepted: readonly string[];
  /** A real Verify/Next/Submit/Skip/Confirm first; the vendor-named controls are fallbacks. */
  readonly submit: readonly string[];
  readonly textInputVendor: readonly string[];
  /**
   * Vendor-named first, generic last: the driver takes the first visible match, and a generic selector reached before
   * the vendor's own is how a captcha's answer ends up in a login form's username box.
   */
  readonly textInput: readonly string[];
  /** `[draggable=true]` is absent: HTML5 DnD fires dragstart, not pointermove. */
  readonly sliderHandle: readonly string[];
  readonly refresh: readonly string[];
  readonly piece: readonly string[];

  constructor(custom?: CustomSelectors) {
    if (custom && !DETECTED_BY.some(([, key]) => custom[key]?.length)) {
      throw new Error('customSelectors names nothing to detect: give it a `widget`, `challenge` or `checkbox`');
    }
    const builtIn = Object.entries(SELECTORS) as Array<[Vendor, VendorSelectors]>;
    this.vendors = custom
      ? [[Vendor.UNKNOWN, { hosts: [], ...custom }], ...builtIn.filter(([v]) => v !== Vendor.UNKNOWN)]
      : builtIn;
    this.selectors = Object.fromEntries(this.vendors) as Record<Vendor, VendorSelectors>;
    const every = (key: ListKey): readonly string[] => this.vendors.flatMap(([, s]) => s[key] ?? []);
    this.widgetProbes = DETECTED_BY.flatMap(([role, key]) =>
      this.vendors.flatMap(([vendor, s]) => (s[key] ?? []).map((selector) => ({ vendor, role, selector }))));
    this.enclave = every('enclave');
    this.response = this.vendors.flatMap(([, s]) => s.response ?? []);
    this.accepted = this.vendors.flatMap(([, s]) => s.accepted ?? []);
    this.submit = [...['verify', 'next', 'submit', 'skip', 'confirm'].map(submitByText), ...every('submit')];
    this.textInputVendor = every('textInput');
    this.textInput = [...this.textInputVendor,
      'input[name*="captcha" i]', 'input[id*="captcha" i]', 'input[aria-label*="captcha" i]',
      'input[placeholder*="code" i]', 'input[autocomplete="off"][type=text]',
      'input[type=text]', 'input:not([type])', 'input[type=tel]', 'textarea',
    ];
    this.sliderHandle = [...every('sliderHandle'),
      '[role="slider"]', '[aria-valuenow]',
      '[class*="slider"][class*="btn"]', '[class*="slider"][class*="button"]',
      '[class*="slide"][class*="handle"]', '[class*="drag"][class*="thumb"]',
    ];
    this.refresh = every('refresh');
    this.piece = [...every('piece'), '[class*="puzzle"][class*="piece"]', '[class*="jigsaw"]'];
  }
}

export const DEFAULT_TABLE = new SelectorTable();
export const VENDORS = DEFAULT_TABLE.vendors;
export const WIDGET_PROBES = DEFAULT_TABLE.widgetProbes;
export const ENCLAVE_SELECTORS = DEFAULT_TABLE.enclave;
export const RESPONSE_SELECTORS = DEFAULT_TABLE.response;
export const ACCEPTED_SELECTORS = DEFAULT_TABLE.accepted;
export const SUBMIT_SELECTORS = DEFAULT_TABLE.submit;
export const TEXT_INPUT_VENDOR_SELECTORS = DEFAULT_TABLE.textInputVendor;
export const TEXT_INPUT_SELECTORS = DEFAULT_TABLE.textInput;
export const SLIDER_HANDLE_SELECTORS = DEFAULT_TABLE.sliderHandle;
export const REFRESH_SELECTORS = DEFAULT_TABLE.refresh;
export const PIECE_SELECTORS = DEFAULT_TABLE.piece;
