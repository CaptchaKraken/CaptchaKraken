/**
 * The vendor's own answer to each submitted round, read off the wire. Mirrors python/src/captchakraken/verdicts.py.
 *
 * Every shape below was recorded against the vendor's public demo page, never inferred: a DOM done-signal can only
 * say "something changed", while the answer-check response says whether the round was taken. A vendor with no
 * readable answer (Turnstile, and the rest of the table) is judged by the DOM signals in the driver instead.
 */
import { Verdict, Vendor } from './kinds';
import type { PlaywrightPage, PlaywrightResponse } from './playwright-types';

// The vendors' own HTTP refusal: hCaptcha's frame words a 429 as "Your computer or network has sent too many requests".
const TOO_MANY_REQUESTS = 429;

export interface RoundVerdict {
  vendor: Vendor;
  verdict: Verdict;
}

const parse = (body: string): unknown => {
  try {
    return JSON.parse(body);
  } catch {
    return null;
  }
};

/** A JSON object whose boolean `pass` is the verdict. */
const passField = (body: string): Verdict | null => {
  const passed = (parse(body) as { pass?: unknown } | null)?.pass;
  return typeof passed !== 'boolean' ? null : passed ? Verdict.ACCEPTED : Verdict.REJECTED;
};

/** A JSON array behind the `)]}'` anti-hijacking line. */
const xssiArray = (body: string): unknown[] | null => {
  const data = parse(body.startsWith(")]}'") && body.includes('\n') ? body.slice(body.indexOf('\n') + 1) : body);
  return Array.isArray(data) && data.length ? data : null;
};

/** `["uvresp", token, 1, lifetime, ...]` when taken; `["uvresp", context, 0, ..., ["rresp", ...next board]]` when refused. */
const userVerify = (body: string): Verdict | null => {
  const data = xssiArray(body);
  if (!data || data[0] !== 'uvresp' || data.length < 3) return null;
  return data[2] === 1 ? Verdict.ACCEPTED : data[2] === 0 ? Verdict.REJECTED : null;
};

const newBoard = (body: string): Verdict | null => (xssiArray(body)?.[0] === 'rresp' ? Verdict.NEW_CHALLENGE : null);

/** `callback({...})` whose `data.result` is the verdict. */
const jsonpResult = (body: string): Verdict | null => {
  const start = body.indexOf('(');
  const end = body.lastIndexOf(')');
  const data = (start >= 0 && start < end ? parse(body.slice(start + 1, end)) : null) as
    { status?: unknown; data?: { result?: unknown } } | null;
  const result = data?.status === 'success' ? data.data?.result : undefined;
  return result === 'success' ? Verdict.ACCEPTED : result === 'fail' ? Verdict.REJECTED : null;
};

/**
 * `{"errorCode": "0", "ticket": ...}` when taken; `{"errorCode": "50", "ticket": ""}` when a wrong slide is refused.
 * Any other code (rate limits, expired sessions) has not been recorded, so the DOM judges it.
 */
const tencentTicket = (body: string): Verdict | null => {
  const data = parse(body) as { errorCode?: unknown; ticket?: unknown } | null;
  if (!data || typeof data !== 'object') return null;
  const code = String(data.errorCode);
  if (code === '0' && data.ticket) return Verdict.ACCEPTED;
  return code === '50' && !data.ticket ? Verdict.REJECTED : null;
};

/** `callback({"data": {"result": true, ...}, "error": 0})` when taken, `"result": false` with `"error": 0` when refused. */
const yidunCheck = (body: string): Verdict | null => {
  const start = body.indexOf('(');
  const end = body.lastIndexOf(')');
  const data = (start >= 0 && start < end ? parse(body.slice(start + 1, end)) : null) as
    { data?: { result?: unknown } | null; error?: unknown } | null;
  if (!data || data.error !== 0) return null;
  const result = data.data?.result;
  return result === true ? Verdict.ACCEPTED : result === false ? Verdict.REJECTED : null;
};

/** `solved: true` when taken; `solved: false` with `time_end` set when the session ended refused. */
const arkoseAnswer = (body: string): Verdict | null => {
  const data = parse(body) as { solved?: unknown; time_end?: unknown } | null;
  if (data?.solved === true) return Verdict.ACCEPTED;
  return data?.solved === false && data.time_end != null ? Verdict.REJECTED : null;
};

const urlOnly = (): Verdict | null => Verdict.NEW_CHALLENGE;

export interface VerdictEndpoint {
  /** A URL substring naming the vendor's own endpoint. */
  marker: string;
  read: (body: string) => Verdict | null;
}

/** Only a vendor listed here has a readable answer; the rest are judged by the DOM done-signals. */
export const VERDICT_ENDPOINTS: Partial<Record<Vendor, readonly VerdictEndpoint[]>> = {
  // The deal endpoint's body is encrypted, so its URL is the whole signal.
  [Vendor.HCAPTCHA]: [
    { marker: 'hcaptcha.com/checkcaptcha/', read: passField },
    { marker: 'hcaptcha.com/getcaptcha/', read: urlOnly },
  ],
  [Vendor.RECAPTCHA]: [
    { marker: '/recaptcha/api2/userverify', read: userVerify },
    { marker: '/recaptcha/api2/reload', read: newBoard },
  ],
  [Vendor.GEETEST]: [
    { marker: 'geetest.com/verify', read: jsonpResult },
    { marker: 'geetest.com/load', read: urlOnly },
  ],
  [Vendor.TENCENT]: [{ marker: '/cap_union_new_verify', read: tencentTicket }],
  [Vendor.YIDUN]: [{ marker: 'dun.163.com/api/v3/check', read: yidunCheck }],
  // Sites serve this from their own hostnames, so the path is what identifies it.
  [Vendor.FUNCAPTCHA]: [{ marker: '/fc/ca/', read: arkoseAnswer }],
};

/** The vendor and endpoint whose marker the URL carries, so a listener reads only the bodies it can judge. */
export function endpointFor(url: string): { vendor: Vendor; endpoint: VerdictEndpoint } | null {
  return (Object.entries(VERDICT_ENDPOINTS) as [Vendor, readonly VerdictEndpoint[]][])
    .flatMap(([vendor, endpoints]) => endpoints.map((endpoint) => ({ vendor, endpoint })))
    .find(({ endpoint }) => url.includes(endpoint.marker)) ?? null;
}

export function readVerdict(url: string, status: number, body: string): RoundVerdict | null {
  const found = endpointFor(url);
  if (!found) return null;
  if (status === TOO_MANY_REQUESTS) return { vendor: found.vendor, verdict: Verdict.BLOCKED };
  const verdict = status >= 200 && status < 300 ? found.endpoint.read(body) : null;
  return verdict ? { vendor: found.vendor, verdict } : null;
}

// ── whether a board moves, read off the file it is dealt as ──────────────────
// Measured 2026-11-14 on the live demos. hCaptcha (46 deals over three sitekeys) loads each board from
// imgs*.hcaptcha.com/tip/: image/jpeg for every still deal, video/webm for every animated one. GeeTest v4's /load names
// its challenge in plain JSONP, and only the two svg types moved (22 deals over seven demo pages). A vendor, file or
// type not listed here gives no hint, and the driver films the board to find out, as it always has.
const GEETEST_MOVING = new Set(['svg_icon', 'svg_seed']);
const GEETEST_STILL = new Set(['slide', 'icon', 'nine', 'match', 'winlinze']);

const mediaMoves = (contentType: string): boolean | null => {
  const kind = contentType.split('/', 1)[0].trim().toLowerCase();
  return kind === 'video' ? true : kind === 'image' ? false : null;
};

const geetestTypeMoves = (_contentType: string, body: string): boolean | null => {
  const start = body.indexOf('(');
  const end = body.lastIndexOf(')');
  const data = (start >= 0 && start < end ? parse(body.slice(start + 1, end)) : null) as
    { data?: { captcha_type?: unknown } } | null;
  const kind = data?.data?.captcha_type;
  if (typeof kind !== 'string') return null;
  return GEETEST_MOVING.has(kind) ? true : GEETEST_STILL.has(kind) ? false : null;
};

export interface MotionSignal {
  /** A URL substring naming the response that carries the board, or names its kind. */
  marker: string;
  read: (contentType: string, body: string) => boolean | null;
  needsBody: boolean;
}

export const MOTION_SIGNALS: Partial<Record<Vendor, readonly MotionSignal[]>> = {
  [Vendor.HCAPTCHA]: [{ marker: 'hcaptcha.com/tip/', read: mediaMoves, needsBody: false }],
  [Vendor.GEETEST]: [{ marker: 'geetest.com/load', read: geetestTypeMoves, needsBody: true }],
};

export function motionSignalFor(url: string): { vendor: Vendor; signal: MotionSignal } | null {
  return (Object.entries(MOTION_SIGNALS) as [Vendor, readonly MotionSignal[]][])
    .flatMap(([vendor, signals]) => signals.map((signal) => ({ vendor, signal })))
    .find(({ signal }) => url.includes(signal.marker)) ?? null;
}

/** The vendor whose deal endpoint this is: what it said about the last board no longer holds. */
function dealsABoard(url: string): Vendor | null {
  const found = endpointFor(url);
  return found && found.endpoint.read === urlOnly ? found.vendor : null;
}

const SCRIPTED_REQUESTS = new Set(['xhr', 'fetch', 'script']);

/**
 * Every verdict the page's network carries while a solve runs.
 *
 * A page-level listener sees the vendors' cross-origin frames too. It is optional: a page object with no `on`
 * records nothing, and the driver then judges every round by the DOM, as it always has.
 */
export class VerdictLog {
  readonly verdicts: RoundVerdict[] = [];
  /** Requests the page's scripts have made. A board that answers a press with none has refused nothing. */
  exchanges = 0;
  readonly listening: boolean;
  private read = 0;
  private pending: Promise<void>[] = [];
  private readonly listener = (response: PlaywrightResponse): void => {
    const url = response.url();
    const status = response.status();
    if (SCRIPTED_REQUESTS.has(response.request?.().resourceType?.() ?? '')) this.exchanges++;
    const dealt = dealsABoard(url);
    // At once, not when the body lands: the new board's own file can arrive first.
    if (dealt) {
      this.motion.delete(dealt);
      this.deals.set(dealt, (this.deals.get(dealt) ?? 0) + 1);
    }
    const found = motionSignalFor(url);
    const judged = endpointFor(url) !== null;
    if (!judged && !found) return;
    if (found && status >= 200 && status < 300 && !found.signal.needsBody) {
      let contentType = '';
      try { contentType = response.headers?.()['content-type'] ?? ''; } catch { /* no header, no hint */ }
      this.noteMotion(found.vendor, found.signal.read(contentType, ''));
    }
    const needsBody = judged || (found?.signal.needsBody ?? false);
    // A body read for an earlier deal must not describe a board that has since been replaced.
    const deal = found ? this.deals.get(found.vendor) ?? 0 : 0;
    if (!needsBody) return;
    const body = status === TOO_MANY_REQUESTS ? Promise.resolve('') : response.text();
    this.pending.push(body.then((text) => {
      if (found?.signal.needsBody && status >= 200 && status < 300 && (this.deals.get(found.vendor) ?? 0) === deal) {
        this.noteMotion(found.vendor, found.signal.read('', text));
      }
      const verdict = readVerdict(url, status, text);
      if (verdict) this.verdicts.push(verdict);
    }).catch(() => {}));
  };
  /** What each vendor's network said about its current board: true moves, false is still. */
  private readonly motion = new Map<Vendor, boolean>();
  private readonly deals = new Map<Vendor, number>();

  private noteMotion(vendor: Vendor, moves: boolean | null): void {
    // One moving file makes the board a moving one: a board may also load a still example.
    if (moves !== null && !this.motion.get(vendor)) this.motion.set(vendor, moves);
  }

  /** Whether the vendor dealt its current board as a moving one; null when its network has not said. */
  async boardMotion(vendor: Vendor): Promise<boolean | null> {
    await Promise.all([...this.pending]);
    return this.motion.get(vendor) ?? null;
  }

  constructor(private readonly page: PlaywrightPage) {
    this.listening = typeof page.on === 'function';
    page.on?.('response', this.listener);
  }

  /** The verdicts that arrived since the last call, once every body already on the wire has been read. */
  async fresh(): Promise<RoundVerdict[]> {
    await Promise.all(this.pending.splice(0));
    const fresh = this.verdicts.slice(this.read);
    this.read = this.verdicts.length;
    return fresh;
  }

  /** The last accept or reject, which is what the round came to. */
  decisive(): Verdict | null {
    return [...this.verdicts].reverse().map((v) => v.verdict)
      .find((v) => v === Verdict.ACCEPTED || v === Verdict.REJECTED) ?? null;
  }

  async close(): Promise<void> {
    this.page.off?.('response', this.listener);
    await Promise.all(this.pending.splice(0));
  }
}
