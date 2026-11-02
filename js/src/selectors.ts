/**
 * Every selector the driver knows, keyed by vendor, read from `captchakraken.config.json` at the repository root. The
 * Python port reads the same file. Detection takes the first visible match in table order, so the file's order is the
 * detection order.
 */
import fs from 'node:fs';
import path from 'node:path';

import { FrameRole, RecaptchaBanner, Vendor } from './kinds';
import { getBundledCliRoot } from './model-name';

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

/** A selector config file's shape: the repository's `captchakraken.config.json`, or any part of it. */
export interface SelectorConfigFile {
  readonly custom?: Record<string, unknown> | null;
  readonly vendors?: Record<string, Record<string, unknown>>;
  readonly generic?: Record<string, readonly string[]>;
  readonly [comment: `_${string}`]: unknown;
}

/** A selector config the solver cannot use; the message names the file and the key. */
export class SelectorConfigError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'SelectorConfigError';
  }
}

/** A loaded selector config: the caller's own entry, every vendor's in detection order, and the generic fallbacks. */
export interface SelectorConfig {
  readonly custom: CustomSelectors | null;
  readonly vendors: ReadonlyArray<readonly [Vendor, VendorSelectors]>;
  readonly generic: Readonly<Record<GenericKey, readonly string[]>>;
}

const GENERIC = ['submit_text', 'text_input', 'slider_handle', 'piece'] as const;
type GenericKey = (typeof GENERIC)[number];
// The file is spelled as the Python port's fields; these three are camelCase here.
const CAMEL: Record<string, string> = { text_input: 'textInput', slider_handle: 'sliderHandle', hold_completes: 'holdCompletes' };
const FIELDS = ['hosts', 'challenge', 'checkbox', 'enclave', 'widget', 'response', 'checked', 'box', 'accepted', 'fresh',
  'images', 'submit', 'banners', 'blocked', 'passive', 'text_input', 'slider_handle', 'piece', 'refresh', 'hold_completes'];
const ONE = new Set(['response', 'checked', 'accepted', 'fresh']);
const BANNERS = new Set<string>(Object.values(RecaptchaBanner));
const VENDOR_VALUES = new Set<string>(Object.values(Vendor));

const isObject = (v: unknown): v is Record<string, unknown> => typeof v === 'object' && v !== null && !Array.isArray(v);

function strings(where: string, value: unknown): readonly string[] {
  if (!Array.isArray(value) || !value.every((v) => typeof v === 'string')) {
    throw new SelectorConfigError(`${where}: must be a list of strings`);
  }
  return value;
}

function entry(where: string, raw: unknown, hostsRequired = true): VendorSelectors {
  if (!isObject(raw)) throw new SelectorConfigError(`${where}: must be an object`);
  const out: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(raw)) {
    const at = `${where}.${key}`;
    if (key === 'note' || key.startsWith('_')) continue;
    if (!FIELDS.includes(key)) throw new SelectorConfigError(`${at}: not a selector field (one of ${FIELDS.join(', ')})`);
    const name = CAMEL[key] ?? key;
    if (ONE.has(key)) {
      if (value !== null && typeof value !== 'string') throw new SelectorConfigError(`${at}: must be one selector string`);
      if (value !== null) out[name] = value;
    } else if (key === 'hold_completes') {
      if (typeof value !== 'boolean') throw new SelectorConfigError(`${at}: must be true or false`);
      if (value) out[name] = value;
    } else if (key === 'banners') {
      if (!Array.isArray(value)) throw new SelectorConfigError(`${at}: must be a list of [selector, verdict] pairs`);
      out[name] = value.map((pair, i) => {
        if (!Array.isArray(pair) || pair.length !== 2 || typeof pair[0] !== 'string') {
          throw new SelectorConfigError(`${at}[${i}]: must be a [selector, verdict] pair`);
        }
        if (!BANNERS.has(pair[1])) {
          throw new SelectorConfigError(`${at}[${i}]: verdict ${JSON.stringify(pair[1])} is not one of ${JSON.stringify([...BANNERS])}`);
        }
        return [pair[0], pair[1]] as const;
      });
    } else {
      const list = strings(at, value);
      if (list.length || key === 'hosts') out[name] = list;
    }
  }
  if (!('hosts' in out)) {
    if (hostsRequired) throw new SelectorConfigError(`${where}.hosts: missing (an empty list when the vendor has no host of its own)`);
    out.hosts = [];
  }
  return out as unknown as VendorSelectors;
}

function parse(name: string, doc: unknown, base: SelectorConfig | null): SelectorConfig {
  if (!isObject(doc)) throw new SelectorConfigError(`${name}: the top level must be an object`);
  for (const key of Object.keys(doc)) {
    if (!key.startsWith('_') && !['custom', 'vendors', 'generic'].includes(key)) {
      throw new SelectorConfigError(`${name}: ${key}: not a config key (custom, vendors, generic)`);
    }
  }
  let custom = base?.custom ?? null;
  if ('custom' in doc) custom = doc.custom === null ? null : entry(`${name}: custom`, doc.custom, false);
  const rawVendors = doc.vendors ?? {};
  if (!isObject(rawVendors)) throw new SelectorConfigError(`${name}: vendors: must be an object keyed by vendor`);
  const vendors = new Map<Vendor, VendorSelectors>(base?.vendors ?? []);
  for (const [key, raw] of Object.entries(rawVendors)) {
    if (key.startsWith('_')) continue;
    if (!VENDOR_VALUES.has(key)) {
      throw new SelectorConfigError(`${name}: vendors.${key}: not a vendor this solver knows; a captcha of your own goes under \`custom\``);
    }
    vendors.set(key as Vendor, entry(`${name}: vendors.${key}`, raw));
  }
  if (!base) {
    const missing = [...VENDOR_VALUES].filter((v) => !vendors.has(v as Vendor)).sort();
    if (missing.length) throw new SelectorConfigError(`${name}: vendors: every vendor must have an entry; missing ${JSON.stringify(missing)}`);
  }
  const rawGeneric = doc.generic ?? {};
  if (!isObject(rawGeneric)) throw new SelectorConfigError(`${name}: generic: must be an object`);
  const generic: Partial<Record<GenericKey, readonly string[]>> = { ...(base?.generic ?? {}) };
  for (const [key, value] of Object.entries(rawGeneric)) {
    if (key.startsWith('_')) continue;
    if (!(GENERIC as readonly string[]).includes(key)) {
      throw new SelectorConfigError(`${name}: generic.${key}: not a generic list (one of ${GENERIC.join(', ')})`);
    }
    generic[key as GenericKey] = strings(`${name}: generic.${key}`, value);
  }
  const absent = GENERIC.filter((k) => !generic[k]);
  if (absent.length) throw new SelectorConfigError(`${name}: generic: missing ${JSON.stringify(absent)}`);
  return { custom, vendors: [...vendors], generic: generic as Record<GenericKey, readonly string[]> };
}

function read(file: string): unknown {
  let text: string;
  try {
    text = fs.readFileSync(file, 'utf-8');
  } catch (e) {
    throw new SelectorConfigError(`${file}: cannot be read (${(e as Error).message})`);
  }
  try {
    return JSON.parse(text);
  } catch (e) {
    throw new SelectorConfigError(`${file}: cannot be read as JSON (${(e as Error).message})`);
  }
}

/**
 * The default config: the repository's own `captchakraken.config.json` when this package runs from a checkout, so an
 * edit there is what the solver reads, else the copy the bundled Python engine ships (an installed package has no
 * repository root). The Python port resolves the same file.
 */
export const DEFAULT_CONFIG_PATH: string = (() => {
  const checkout = path.resolve(__dirname, '..', '..', 'captchakraken.config.json');
  return fs.existsSync(checkout)
    ? checkout
    : path.join(getBundledCliRoot(), 'src', 'captchakraken', 'captchakraken.config.json');
})();

/**
 * The shipped default, or `source` (a path or a parsed object) laid over it: a key it gives replaces the default's
 * `custom`, one vendor's whole entry, or one generic list. Throws SelectorConfigError naming the bad key.
 */
export function loadConfig(source?: string | SelectorConfigFile): SelectorConfig {
  const base = parse(DEFAULT_CONFIG_PATH, read(DEFAULT_CONFIG_PATH), null);
  if (source === undefined || (typeof source === 'string' && path.resolve(source) === DEFAULT_CONFIG_PATH)) return base;
  return typeof source === 'string' ? parse(source, read(source), base) : parse('selectors', source, base);
}

export const DEFAULT_CONFIG: SelectorConfig = loadConfig();
/** Every vendor's entry, in detection order, as the default config gives it. */
export const SELECTORS: Readonly<Record<Vendor, VendorSelectors>> =
  Object.fromEntries(DEFAULT_CONFIG.vendors) as Record<Vendor, VendorSelectors>;

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
 * The table one solver detects and drives with: a selector config's vendors, plus its `custom` entry when it has one.
 * `config` is a path, a parsed object or a loaded SelectorConfig, laid over the shipped default (see `loadConfig`);
 * `custom` (the older `customSelectors`) replaces the config's own. A custom entry is reported as `Vendor.UNKNOWN` and
 * searched before the built-in vendors, because the caller wrote it for the page in front of them.
 */
export class SelectorTable {
  readonly config: SelectorConfig;
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
  /** `[draggable=true]` is absent from the generic handles: HTML5 DnD fires dragstart, not pointermove. */
  readonly sliderHandle: readonly string[];
  readonly refresh: readonly string[];
  readonly piece: readonly string[];

  constructor(custom?: CustomSelectors, config?: string | SelectorConfigFile | SelectorConfig) {
    const loaded = isLoaded(config) ? config : loadConfig(config);
    const own = custom ?? loaded.custom ?? undefined;
    if (own && !DETECTED_BY.some(([, key]) => own[key]?.length)) {
      throw new SelectorConfigError('custom selectors name nothing to detect: give the entry a `widget`, `challenge` or `checkbox`');
    }
    this.config = loaded;
    this.vendors = own
      ? [[Vendor.UNKNOWN, { hosts: [], ...own }], ...loaded.vendors.filter(([v]) => v !== Vendor.UNKNOWN)]
      : loaded.vendors;
    this.selectors = Object.fromEntries(this.vendors) as Record<Vendor, VendorSelectors>;
    const every = (key: ListKey): readonly string[] => this.vendors.flatMap(([, s]) => s[key] ?? []);
    this.widgetProbes = DETECTED_BY.flatMap(([role, key]) =>
      this.vendors.flatMap(([vendor, s]) => (s[key] ?? []).map((selector) => ({ vendor, role, selector }))));
    this.enclave = every('enclave');
    this.response = this.vendors.flatMap(([, s]) => s.response ?? []);
    this.accepted = this.vendors.flatMap(([, s]) => s.accepted ?? []);
    this.submit = [...loaded.generic.submit_text.map(submitByText), ...every('submit')];
    this.textInputVendor = every('textInput');
    this.textInput = [...this.textInputVendor, ...loaded.generic.text_input];
    this.sliderHandle = [...every('sliderHandle'), ...loaded.generic.slider_handle];
    this.refresh = every('refresh');
    this.piece = [...every('piece'), ...loaded.generic.piece];
  }
}

const isLoaded = (c: unknown): c is SelectorConfig =>
  isObject(c) && Array.isArray((c as any).vendors) && isObject((c as any).generic) && 'custom' in c;

export const DEFAULT_TABLE = new SelectorTable(undefined, DEFAULT_CONFIG);
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
