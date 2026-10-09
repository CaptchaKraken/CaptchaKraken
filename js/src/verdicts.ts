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

/**
 * Every verdict the page's network carries while a solve runs.
 *
 * A page-level listener sees the vendors' cross-origin frames too. It is optional: a page object with no `on`
 * records nothing, and the driver then judges every round by the DOM, as it always has.
 */
export class VerdictLog {
  readonly verdicts: RoundVerdict[] = [];
  private read = 0;
  private pending: Promise<void>[] = [];
  private readonly listener = (response: PlaywrightResponse): void => {
    const url = response.url();
    const status = response.status();
    if (!endpointFor(url)) return;
    const body = status === TOO_MANY_REQUESTS ? Promise.resolve('') : response.text();
    this.pending.push(body.then((text) => {
      const verdict = readVerdict(url, status, text);
      if (verdict) this.verdicts.push(verdict);
    }).catch(() => {}));
  };

  constructor(private readonly page: PlaywrightPage) {
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
