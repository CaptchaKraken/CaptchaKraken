import { Camoufox } from 'camoufox-js';
import { CaptchaKrakenSolver } from '../src/index';
import type { SolveResult } from '../src/types';

export interface DemoSpec {
  name: string;
  url: string;
}

export function specFromArgv(base: DemoSpec, argv: string[] = process.argv.slice(2)): DemoSpec {
  const spec = { ...base };
  const rest: string[] = [];
  for (let i = 0; i < argv.length; i++) {
    if (argv[i] === '--name' && argv[i + 1]) {
      spec.name = argv[++i];
    } else if (argv[i] === '--headed') {
      process.env.HEADLESS = '0';
    } else if (!argv[i].startsWith('-')) {
      rest.push(argv[i]);
    }
  }
  if (rest.length) {
    spec.url = rest[0];
    if (!spec.name || spec.name === base.name) spec.name = rest[0];
  }
  return spec;
}

function fmtMs(ms: number): string {
  return ms >= 1000 ? `${(ms / 1000).toFixed(1)}s` : `${ms}ms`;
}

function explain(result: SolveResult | void, err: unknown): string {
  const msg = err instanceof Error ? err.message : err ? String(err) : '';
  const low = msg.toLowerCase();

  if (low.includes('econnrefused') || low.includes('base_url') || low.includes('vllm') || low.includes('fetch failed')) {
    return 'Could not reach the vLLM server — is it running and is VLLM_BASE_URL correct? (It auto-starts locally only if captchakraken[serve] is installed.)';
  }
  if (low.includes('unsupported') || low.includes('cannot solve')) {
    return 'The model could not produce a usable action for this captcha — reload to try again.';
  }
  if (low.includes('timeout')) {
    return 'Timed out — the page or the challenge iframe never became interactable (slow network, or the widget was blocked).';
  }
  if (result && !result.isSolved) {
    return 'Tiles were selected but the provider did not accept the answer. Most often this is IP reputation / fingerprint flagging: providers reject even correct answers from a distrusted IP. Try a cleaner IP or a residential proxy.';
  }
  return msg || 'Unknown failure.';
}

function report(spec: DemoSpec, opts: {
  ok: boolean;
  totalMs: number;
  solveMs: number;
  result?: SolveResult | void;
  reason?: string;
}): void {
  const { ok, totalMs, solveMs, result, reason } = opts;
  const out = result ? result.tokenUsage.outputTokens : 0;
  const inp = result ? result.tokenUsage.inputTokens : 0;
  const tps = out > 0 && solveMs > 0 ? out / (solveMs / 1000) : 0;

  const line = '─'.repeat(52);
  console.log(`\n${line}`);
  console.log(`  CaptchaKraken demo — ${spec.name}`);
  console.log(`  ${spec.url}`);
  console.log(line);
  console.log(`  result        : ${ok ? '✓ SOLVED' : '✗ not solved'}`);
  console.log(`  total time    : ${fmtMs(totalMs)}   (solve: ${fmtMs(solveMs)})`);
  console.log(`  tokens        : ${inp} in / ${out} out`);
  console.log(`  gen speed     : ${tps > 0 ? `~${tps.toFixed(1)} tok/s (end-to-end approx)` : 'n/a'}`);
  if (!ok && reason) console.log(`  reason        : ${reason}`);
  console.log(`${line}\n`);
}

export async function runDemo(baseSpec: DemoSpec): Promise<void> {
  const spec = specFromArgv(baseSpec);
  const t0 = Date.now();
  const executablePath = process.env.CAMOUFOX_BINARY || process.env.CAMOUFOX_EXECUTABLE_PATH;
  const headless = process.env.HEADLESS !== '0';

  let browser: Awaited<ReturnType<typeof Camoufox>> | undefined;
  let context: any;
  try {
    browser = await Camoufox({
      headless,

      humanize: process.env.HUMANIZE === '1',
      geoip: false,

      ...(executablePath ? { executable_path: executablePath } : {}),
    });

    const videoDir = process.env.CAPTCHA_DEMO_VIDEO_DIR;
    const [vw, vh] = (process.env.CAPTCHA_DEMO_VIDEO_SIZE || '1280x800').split('x').map(Number);
    context = await (browser as any).newContext({
      viewport: null,
      ...(videoDir ? { recordVideo: { dir: videoDir, size: { width: vw, height: vh } } } : {}),
    });
    const page = await context.newPage();
    await page.goto(spec.url, { waitUntil: 'domcontentloaded', timeout: 60_000 });

    await page.waitForLoadState('networkidle', { timeout: 15_000 }).catch(() => {});
    await page.waitForTimeout(3000);

    const s0 = Date.now();
    let result: SolveResult | void;
    let reason: string | undefined;
    try {
      result = await new CaptchaKrakenSolver().solve(page);
    } catch (err) {
      const solveMs = Date.now() - s0;
      report(spec, { ok: false, totalMs: Date.now() - t0, solveMs, reason: explain(undefined, err) });
      process.exitCode = 1;
      return;
    }
    const solveMs = Date.now() - s0;

    const ok = !!result && result.isSolved;
    if (!ok) reason = explain(result, undefined);
    report(spec, { ok, totalMs: Date.now() - t0, solveMs, result, reason });
    process.exitCode = ok ? 0 : 1;
  } catch (err) {
    report(spec, { ok: false, totalMs: Date.now() - t0, solveMs: 0, reason: explain(undefined, err) });
    process.exitCode = 1;
  } finally {
    try { await context?.close(); } catch {  }
    try { await (browser as any)?.close(); } catch {  }
  }
}
